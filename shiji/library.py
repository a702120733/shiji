#!/usr/bin/env python3
"""Capture, preprocess, and render a Xiaohongshu library; Codex supplies analysis."""
import argparse
import csv
import hashlib
import html
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import wave
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse, quote
from shiji_shell import wrap_shell

IMAGES = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic', '.avif'}
VIDEOS = {'.mp4', '.mov', '.mkv', '.webm', '.m4v'}
STOP = re.compile(r'AUTH_REQUIRED|SECURITY_BLOCK|CAPTCHA|RATE_LIMIT|Navigation\s+(?:rejected|denied)|ACCESS_DENIED|访问被拒绝|访问受限|验证码|安全验证|请先登录|requires login', re.I)
MODEL = None


def emit(event, **kwargs):
    print(json.dumps({'event': event, **kwargs}, ensure_ascii=False), flush=True)


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def load(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(temp, path)


def binary(name):
    found = shutil.which(name)
    if found:
        return found
    for base in ('/opt/homebrew/bin', '/usr/local/bin', str(Path.home() / '.local/bin')):
        p = Path(base) / name
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


def run(args, timeout=180, env=None):
    try:
        result = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f'Command timed out after {timeout}s; progress saved') from None
    if result.returncode:
        message = (result.stderr or result.stdout or f'exit {result.returncode}')[-3000:]
        message = re.sub(r'xsec_token=[^\s"&]+', 'xsec_token=[redacted]', message)
        raise RuntimeError(message.strip())
    return result.stdout


def parse_json(output):
    decoder = json.JSONDecoder()
    for match in re.finditer(r'(?m)^\s*([\[{])', output):
        start = match.start() + len(match.group(0)) - 1
        try:
            value, _ = decoder.raw_decode(output[start:])
            if isinstance(value, (list, dict)):
                return value
        except json.JSONDecodeError:
            pass
    raise RuntimeError('OpenCLI returned no structured JSON')


def cli(*args):
    executable = binary('opencli')
    if not executable:
        raise RuntimeError('OpenCLI missing; install @jackwener/opencli and connect its browser extension')
    return parse_json(run([executable, 'xiaohongshu', *args, '--site-session', 'persistent', '-f', 'json'], timeout=600,
                          env={**os.environ, 'OPENCLI_BROWSER_COMMAND_TIMEOUT': '300', 'OPENCLI_WINDOW': 'background'}))


def rows(value):
    if isinstance(value, dict):
        for key in ('data', 'rows', 'notes', 'items'):
            if isinstance(value.get(key), list):
                return value[key]
    if isinstance(value, list):
        return value
    raise ValueError('Expected OpenCLI record array')


def public_url(url):
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path, '', '', ''))


def author_url(value):
    p = urlparse(str(value or ''))
    if p.scheme == 'https' and p.hostname in ('www.xiaohongshu.com', 'xiaohongshu.com') and re.fullmatch(r'/user/profile/[0-9a-f]{24}/?', p.path, re.I):
        return public_url(value).rstrip('/')
    return ''


def install_adapter(name):
    source = Path(__file__).with_name(name + '.js')
    dest = Path.home() / '.opencli' / 'clis' / 'xiaohongshu' / source.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)


def collection(args):
    install_adapter('shiji-list')
    cmd = ['shiji-list', '--source', args.source, '--limit', str(args.limit)]
    if args.profile:
        cmd += ['--id', args.profile]
    return rows(cli(*cmd))


def update_authors(root, listing):
    authors = load(root / 'authors.json', {})
    for item in listing:
        url = author_url(item.get('author_url'))
        if url:
            authors[item['id']] = {'name': item.get('author', ''), 'url': url}
    save(root / 'authors.json', authors)


def authors(args):
    listing = collection(args)
    update_authors(args.root.resolve(), listing)
    emit('authors_updated', profiles=sum(bool(author_url(row.get('author_url'))) for row in listing), returned=len(listing))
    return 0


def validate_url(url):
    p = urlparse(url)
    if p.scheme not in ('https', 'http') or p.hostname not in ('www.xiaohongshu.com', 'xiaohongshu.com'):
        raise ValueError('Use a full Xiaohongshu signed note URL; expand xhslink first')
    if not re.search(r'(?:^|&)xsec_token=[^&]+', p.query):
        raise ValueError('Note URL needs xsec_token from the visible list')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def media(directory):
    return sorted(p for p in (directory / 'media').rglob('*') if p.is_file() and p.suffix.lower() in IMAGES | VIDEOS)


def hashes(paths, root):
    return {str(p.relative_to(root)): sha(p) for p in paths}


def intact(mapping, root):
    return all((root / p).is_file() and sha(root / p) == h for p, h in mapping.items())


def capture(args):
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest = load(root / 'manifest.json', {'version': 1, 'notes': {}, 'runs': []})
    previous_listing = load(root / 'latest-list.json', [])
    try:
        if args.urls_file:
            listing = []
            for url in args.urls_file.read_text().splitlines():
                if not url.strip() or url.startswith('#'):
                    continue
                url = url.strip()
                validate_url(url)
                note_id = urlparse(url).path.rstrip('/').split('/')[-1].lower()
                if not re.fullmatch(r'[0-9a-f]{24}', note_id):
                    raise ValueError('Note ID missing from signed URL')
                listing.append({'id': note_id, 'url': url})
        else:
            listing = collection(args)
        listing_short = bool(getattr(args, 'incremental', False) and previous_listing
                             and len(listing) < min(args.limit, len(previous_listing)))
        if not listing_short:
            save(root / 'latest-list.json', listing)
        else:
            emit('list_window_short', requested=args.limit, returned=len(listing),
                 previous_returned=len(previous_listing),
                 message='来源列表短于上次完整窗口；保留上次列表和同步基线。')
        update_authors(root, listing)
    except Exception as exc:
        emit('capture_blocked', error=str(exc))
        return 2
    targets, boundary_missing, historical_boundary_missing = listing, False, False
    if getattr(args, 'incremental', False) and manifest['notes']:
        recent_ids = {item['id'] for item in previous_listing if item.get('id')}
        legacy_anchor_ids = manifest.get('sync_anchor_ids', list(manifest['notes']))
        recent_anchor = next((i for i, item in enumerate(listing) if item['id'] in recent_ids), len(listing)) if recent_ids else len(listing)
        legacy_anchor = next((i for i, item in enumerate(listing) if item['id'] in legacy_anchor_ids), len(listing))
        targets = listing[:recent_anchor] + [item for item in listing[recent_anchor:] if manifest['notes'].get(item['id'], {}).get('capture_status') not in ('complete', None)]
        boundary_missing = (recent_anchor if recent_ids else legacy_anchor) == len(listing)
        historical_boundary_missing = legacy_anchor == len(listing)
        manifest['sync_anchor_ids'] = legacy_anchor_ids
        if recent_anchor < len(listing):
            emit('observed_new_prefix', count=recent_anchor, basis='previous_latest_list')
    seen, processed, skipped, blocked = set(), 0, 0, False
    for item in targets:
        note_id = str(item.get('id', '')).lower()
        if not re.fullmatch(r'[0-9a-f]{24}', note_id):
            emit('invalid_note', error='Invalid note ID')
            continue
        if note_id in seen:
            continue
        seen.add(note_id)
        directory = root / 'notes' / note_id
        record = manifest['notes'].get(note_id, {})
        metadata = load(directory / 'metadata.json', {})
        expected = record.get('media_hashes', {})
        if record.get('capture_status') == 'complete' and metadata and expected and intact(expected, root) and not args.refresh:
            skipped += 1
            emit('capture_skipped', note_id=note_id)
            continue
        errors, details_ok, downloads_ok = [], False, False
        try:
            source_url = str(item.get('url', ''))
            validate_url(source_url)
            install_adapter('shiji-note')
            detail_rows = rows(cli('shiji-note', source_url))
            details = {r['field']: r.get('value', '') for r in detail_rows if 'field' in r}
            if not details.get('title') and not details.get('author'):
                raise RuntimeError('No title/author extracted')
            metadata = {'note_id': note_id, 'title': details.get('title') or item.get('title', ''),
                        'author': details.get('author') or item.get('author', ''), 'content': details.get('content', ''),
                        'tags': details.get('tags', ''), 'type': item.get('type', ''), 'url': public_url(source_url), 'captured_at': now()}
            save(directory / 'metadata.json', metadata)
            update_authors(root, [{**item, 'author': metadata['author'], 'author_url': details.get('author_url') or item.get('author_url')}])
            save(directory / 'raw.json', {'list_item': item, 'detail_rows': detail_rows})
            details_ok = True
            time.sleep(args.interval)
            downloads = rows(cli('download', source_url, '--output', str(directory / 'media')))
            save(directory / 'downloads.json', downloads)
            downloads_ok = bool(downloads) and all(r.get('status') == 'success' for r in downloads) and len(media(directory)) >= len(downloads)
            if not downloads_ok:
                failures = '; '.join(str(r.get('size', '')) for r in downloads if r.get('status') != 'success')
                errors.append('素材下载不完整，查看 downloads.json')
                blocked = bool(STOP.search(failures))
        except Exception as exc:
            errors.append(str(exc))
            blocked = bool(STOP.search(str(exc)))
        files = media(directory)
        status = 'complete' if details_ok and downloads_ok and files else 'partial' if details_ok or files else 'failed'
        manifest['notes'][note_id] = {'note_id': note_id, 'title': metadata.get('title') or item.get('title', ''),
                                      'capture_status': status, 'errors': errors, 'updated_at': now(), 'media_hashes': hashes(files, root)}
        save(root / 'manifest.json', manifest)
        processed += 1
        emit('captured', note_id=note_id, status=status, files=len(files), errors=errors)
        if blocked:
            break
        time.sleep(args.interval)
    manifest['runs'].append({'at': now(), 'source': 'links' if args.urls_file else args.source,
                             'requested': len(listing) if args.urls_file else args.limit, 'returned': len(listing),
                             'processed': processed, 'skipped': skipped, 'blocked': blocked})
    if getattr(args, 'incremental', False) and not historical_boundary_missing and not listing_short and not blocked and all(manifest['notes'].get(item['id'], {}).get('capture_status') == 'complete' for item in targets):
        manifest.pop('sync_anchor_ids', None)
    save(root / 'manifest.json', manifest)
    previous = load(root / 'display-order.json', list(manifest['notes']))
    included = set(previous) | {item['id'] for item in targets if item['id'] in manifest['notes']}
    order = list(dict.fromkeys([item['id'] for item in listing if item['id'] in included] + previous))
    save(root / 'display-order.json', order)
    if boundary_missing:
        emit('incremental_boundary_missing', message='本次窗口内未遇到上次列表中的笔记；不能据此确定新增点赞数量。')
    if historical_boundary_missing:
        emit('historical_backfill_boundary_missing', message='更早的完整同步基线尚未接上；这不影响根据上次列表判断本次新增数量。')
    emit('capture_finished', returned=len(listing), processed=processed, skipped=skipped, blocked=blocked)
    return 2 if blocked or boundary_missing or listing_short else 0


def probe(path):
    executable = binary('ffprobe')
    if not executable:
        raise RuntimeError('ffprobe not found')
    return json.loads(run([executable, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', path]))


def sheets(items, dest, prefix, root):
    from PIL import Image, ImageDraw, ImageOps
    result = []
    for start in range(0, len(items), 6):
        batch = items[start:start + 6]
        sheet = Image.new('RGB', (1440, 600 * math.ceil(len(batch) / 3)), '#eeeeee')
        draw = ImageDraw.Draw(sheet)
        for i, (path, label) in enumerate(batch):
            with Image.open(path) as image:
                thumbnail = ImageOps.contain(ImageOps.exif_transpose(image).convert('RGB'), (468, 556))
            x = i % 3 * 480 + (480 - thumbnail.width) // 2
            y = i // 3 * 600 + 34 + (556 - thumbnail.height) // 2
            sheet.paste(thumbnail, (x, y))
            draw.text((i % 3 * 480 + 12, i // 3 * 600 + 10), label, fill='#111111')
        path = dest / f'{prefix}-sheet-{start // 6 + 1}.jpg'
        sheet.save(path, quality=90)
        result.append(str(path.relative_to(root)))
    return result


def transcribe(wav, dest, model_name):
    global MODEL
    import numpy as np
    from faster_whisper import WhisperModel
    if MODEL is None:
        emit('loading_transcription_model', model=model_name)
        MODEL = WhisperModel(model_name, device='cpu', compute_type='int8')
    # ffmpeg has already decoded the input; use standard PCM instead of another
    # decoder pass (PyAV releases differ in accepted av.open keyword arguments).
    with wave.open(str(wav), 'rb') as audio:
        if audio.getnchannels() != 1 or audio.getframerate() != 16000 or audio.getsampwidth() != 2:
            raise ValueError('Transcription expects mono 16kHz signed 16-bit PCM WAV')
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype='<i2').astype(np.float32) / 32768.0
    segments, info = MODEL.transcribe(samples, beam_size=5, vad_filter=True, condition_on_previous_text=False)
    value = {'model': model_name, 'language': info.language, 'language_probability': info.language_probability,
             'segments': [{'start': round(s.start, 2), 'end': round(s.end, 2), 'text': s.text.strip(),
                           'avg_logprob': s.avg_logprob, 'no_speech_prob': s.no_speech_prob} for s in segments]}
    save(dest, value)
    dest.with_suffix('.txt').write_text('\n'.join(f"[{s['start']:.2f}-{s['end']:.2f}] {s['text']}" for s in value['segments']), encoding='utf-8')


def prepare(args):
    from PIL import Image
    root = args.root.resolve()
    manifest = load(root / 'manifest.json')
    if not manifest:
        raise ValueError('Run capture first')
    for note_id, record in manifest['notes'].items():
        directory = root / 'notes' / note_id
        metadata = load(directory / 'metadata.json')
        if not metadata:
            continue
        files = media(directory)
        metadata_signature = {k: v for k, v in metadata.items() if k != 'captured_at'}
        input_signature = signature({'metadata': metadata_signature, 'files': hashes(files, root), 'frames': args.frames, 'model': args.model,
                                     'capture_status': record['capture_status'], 'capture_errors': record.get('errors', [])})
        old = load(directory / 'review.json', {})
        if old.get('input_signature') == input_signature and old.get('prepare_status') == 'complete' and intact(old.get('derived_hashes', {}), root) and not args.refresh:
            emit('prepare_skipped', note_id=note_id)
            continue
        dest = directory / 'derived'
        dest.mkdir(parents=True, exist_ok=True)
        errors, images, videos = [], [], []
        for path in files:
            try:
                if path.suffix.lower() in IMAGES:
                    with Image.open(path) as im:
                        im.verify()
                    images.append(str(path.relative_to(root)))
                else:
                    info = probe(path)
                    if not any(s.get('codec_type') == 'video' for s in info.get('streams', [])):
                        raise ValueError('No video stream')
                    videos.append((path, info))
            except Exception as exc:
                errors.append(f'{path.name}: {str(exc)[:400]}')
        image_sheets = sheets([(root / p, f'Image {i + 1}') for i, p in enumerate(images)], dest, 'images', root) if images else []
        prepared = []
        # Retain all downloaded encodings; analyze the largest encoding of the note's video.
        if videos:
            path, info = max(videos, key=lambda entry: entry[0].stat().st_size)
            video = {'file': str(path.relative_to(root)), 'frames': [], 'frame_sheets': [], 'transcript': None, 'audio_status': 'unknown'}
            try:
                ffmpeg = binary('ffmpeg')
                if not ffmpeg:
                    raise RuntimeError('ffmpeg not found')
                stream = next(s for s in info['streams'] if s.get('codec_type') == 'video')
                duration = float(stream.get('duration') or info.get('format', {}).get('duration') or 0)
                rate_parts = str(stream.get('avg_frame_rate', '30/1')).split('/')
                fps = float(rate_parts[0]) / float(rate_parts[1]) if len(rate_parts) == 2 and float(rate_parts[1]) else 30
                last_sample = max(0, duration - max(0.05, 1 / (fps or 30)))
                if duration <= 0 or not math.isfinite(duration):
                    raise ValueError('Unknown video duration')
                video['duration_seconds'] = round(duration, 3)
                labeled = []
                count = min(args.frames, max(1, math.ceil(duration)))
                for i in range(count):
                    timestamp = min(duration * (i + 0.5) / count, last_sample)
                    frame = dest / f'video-1-frame-{i + 1:03d}.jpg'
                    run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-ss', str(timestamp), '-i', path,
                         '-frames:v', '1', '-vf', 'scale=1600:1600:force_original_aspect_ratio=decrease,format=yuvj420p', frame])
                    if not frame.is_file() or frame.stat().st_size == 0:
                        raise ValueError(f'No frame at {timestamp:.2f}s')
                    video['frames'].append({'at_seconds': round(timestamp, 3), 'file': str(frame.relative_to(root))})
                    labeled.append((frame, f'{timestamp:.2f}s / {duration:.2f}s'))
                video['frame_sheets'] = sheets(labeled, dest, 'video-1', root)
                if any(s.get('codec_type') == 'audio' for s in info['streams']):
                    wav = dest / 'video-1-audio.wav'
                    run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-i', path, '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', wav], timeout=600)
                    transcript = dest / 'video-1-transcript.json'
                    transcribe(wav, transcript, args.model)
                    video['transcript'] = str(transcript.relative_to(root))
                    video['audio_status'] = 'transcribed' if load(transcript)['segments'] else 'no_speech_detected'
                else:
                    video['audio_status'] = 'no_audio_stream'
            except Exception as exc:
                errors.append(f'视频预处理: {str(exc)[:600]}')
            prepared.append(video)
        if not images and not videos:
            errors.append('没有有效媒体素材')
        if metadata.get('type') == 'video' and not videos:
            errors.append('列表标记为视频，但视频素材缺失')
        review = {'note_id': note_id, 'metadata': metadata, 'images': images, 'image_sheets': image_sheets, 'videos': prepared,
                  'input_signature': input_signature, 'prepare_status': 'partial' if errors else 'complete',
                  'capture_status': record['capture_status'], 'capture_errors': record.get('errors', []),
                  'source_media_hashes': hashes(files, root), 'limitations': record.get('errors', []) + errors}
        derived = image_sheets + [p for v in prepared for p in v['frame_sheets']] + [f['file'] for v in prepared for f in v['frames']]
        derived += [v['transcript'] for v in prepared if v['transcript']]
        review['derived_hashes'] = {p: sha(root / p) for p in derived}
        # Capture timestamps alone should not invalidate analysis.
        fingerprint_payload = {**review, 'metadata': metadata_signature}
        review['fingerprint'] = signature(fingerprint_payload)
        save(directory / 'review.json', review)
        emit('prepared', note_id=note_id, images=len(images), videos=len(prepared), status=review['prepare_status'], errors=errors)
    return 0


def check(analysis, review, root):
    if not isinstance(analysis, dict) or analysis.get('note_id') != review['note_id']:
        raise ValueError('缺少分析或 note_id 不匹配')
    if analysis.get('fingerprint') != review['fingerprint']:
        raise ValueError('素材或预处理变化，需要重新分析')
    for key in ('category', 'summary'):
        if not isinstance(analysis.get(key), str) or not analysis[key].strip():
            raise ValueError(f'{key} must be nonempty text')
    if not isinstance(analysis.get('subcategory', ''), str):
        raise ValueError('subcategory must be text')
    for key in ('tags', 'key_points', 'takeaways', 'limitations'):
        if not isinstance(analysis.get(key), list) or any(not isinstance(s, str) for s in analysis[key]):
            raise ValueError(f'{key} must be string array')
    coverage = analysis.get('coverage', {})
    if not isinstance(coverage, dict) or coverage.get('status') not in ('complete', 'partial'):
        raise ValueError('coverage.status must be complete or partial')
    if not isinstance(coverage.get('read_text'), bool):
        raise ValueError('read_text must be boolean')
    required = {'reviewed_images': review['images'], 'reviewed_frame_sheets': [p for v in review['videos'] for p in v['frame_sheets']],
                'read_transcripts': [v['transcript'] for v in review['videos'] if v['transcript']]}
    missing = []
    for key, expected in required.items():
        actual = coverage.get(key)
        if not isinstance(actual, list) or any(not isinstance(p, str) or p not in expected or not (root / p).is_file() for p in actual):
            raise ValueError(f'{key} contains unknown paths')
        missing.extend(set(expected) - set(actual))
    if review['metadata'].get('content') and not coverage['read_text']:
        missing.append('正文')
    if coverage['status'] == 'complete' and (review['capture_status'] != 'complete' or review['prepare_status'] != 'complete' or missing):
        raise ValueError('素材缺失或未阅读，不能标为 complete')
    if coverage['status'] == 'partial' and not any(s.strip() for s in analysis['limitations']):
        raise ValueError('partial requires limitations')


def pending(args):
    root = args.root.resolve()
    manifest = load(root / 'manifest.json', {'notes': {}})
    for path in sorted((root / 'notes').glob('*/review.json')):
        review = load(path)
        try:
            check_current(review, manifest['notes'].get(review['note_id'], {}), root)
            check(load(path.with_name('analysis.json')), review, root)
        except (ValueError, TypeError, KeyError) as exc:
            emit('needs_analysis', note_id=review['note_id'], review=str(path), reason=str(exc))
    return 0


def check_current(review, record, root):
    directory = root / 'notes' / review['note_id']
    current = load(directory / 'metadata.json', {})
    strip_time = lambda value: {k: v for k, v in value.items() if k != 'captured_at'}
    payload = {k: v for k, v in review.items() if k != 'fingerprint'}
    payload['metadata'] = strip_time(review['metadata'])
    if signature(payload) != review['fingerprint']:
        raise ValueError('review.json 已变化，请重新预处理')
    if strip_time(current) != strip_time(review['metadata']) or hashes(media(directory), root) != review['source_media_hashes']:
        raise ValueError('正文或原始素材变化，请重新预处理')
    if record.get('capture_status') != review['capture_status'] or record.get('errors', []) != review['capture_errors']:
        raise ValueError('采集状态变化，请重新预处理')
    if not intact(review['derived_hashes'], root):
        raise ValueError('预处理素材变化或缺失，请重新预处理')


def md(value):
    return re.sub(r'([\\`*_{}\[\]<>|])', r'\\\1', str(value)).replace('\r', '')


def cell(value):
    text = str(value)
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')) else text


def render(args):
    root = args.root.resolve()
    manifest = load(root / 'manifest.json', {'notes': {}, 'runs': []})
    root.mkdir(parents=True, exist_ok=True)
    entries, failures = [], []
    selected = manifest['notes']
    if (root / 'display-order.json').exists():
        selected = {note_id: manifest['notes'].get(note_id, {}) for note_id in load(root / 'display-order.json', [])}
    if getattr(args, 'scope_latest', False):
        selected = {row['id']: manifest['notes'].get(row['id'], {}) for row in load(root / 'latest-list.json', [])}
    for note_id, record in selected.items():
        directory = root / 'notes' / note_id
        review, analysis = load(directory / 'review.json'), load(directory / 'analysis.json')
        try:
            if not review:
                if record.get('capture_status') == 'failed':
                    raise ValueError('采集失败：原笔记访问被拒或不可用')
                raise ValueError('尚未预处理')
            check_current(review, record, root)
            check(analysis, review, root)
            if not intact(record.get('media_hashes', {}), root) or not intact(review.get('derived_hashes', {}), root):
                raise ValueError('素材变化或缺失，请重新预处理')
        except (ValueError, TypeError, KeyError) as exc:
            failures.append({'note_id': note_id, 'title': record.get('title', ''), 'reason': str(exc)})
            # Keep captured notes visible while their content review is pending.
            # Never present a guessed category or summary as a finished analysis.
            if review and review.get('metadata') and review.get('prepare_status') == 'complete' and \
                    intact(record.get('media_hashes', {}), root) and intact(review.get('derived_hashes', {}), root):
                metadata = review['metadata']
                raw = load(directory / 'raw.json', {})
                rows = raw.get('detail_rows', []) if isinstance(raw, dict) else []
                list_item = raw.get('list_item', {}) if isinstance(raw, dict) else {}
                likes = next((str(row.get('value')).strip() for row in rows
                              if isinstance(row, dict) and row.get('field') == 'likes' and row.get('value') is not None and str(row['value']).strip()), '')
                if not likes and isinstance(list_item, dict):
                    likes = str(list_item.get('likes') or '').strip()
                profile = author_url(load(root / 'authors.json', {}).get(note_id, {}).get('url'))
                entries.append({'note_id': note_id, 'title': metadata.get('title') or record.get('title') or note_id,
                                'author': metadata.get('author', ''), 'author_url': profile,
                                'type': '视频' if review.get('videos') else '图文', 'likes': likes,
                                'category': '待分析', 'subcategory': '', 'tags': [],
                                'summary': '素材已保存 · 内容待分析', 'status': '待分析',
                                'url': metadata.get('url', ''), 'review': review})
            continue
        metadata, coverage = review['metadata'], analysis['coverage']
        title = metadata.get('title') or note_id
        status = '完整' if coverage['status'] == 'complete' else '部分'
        profile = author_url(load(root / 'authors.json', {}).get(note_id, {}).get('url'))
        author_label = f"[{md(metadata.get('author', ''))}]({profile})" if profile else md(metadata.get('author', ''))
        open_route = 'open-saved-note' if getattr(args, 'source', 'liked') == 'saved' else 'open-note'
        body = [f'# {md(title)}', '', f"作者：{author_label}", '',
                f"[原笔记](../../{open_route}/{note_id}) · [公开链接]({metadata['url']}) · {' · '.join(md(t) for t in dict.fromkeys([analysis['category'], *analysis['tags']]))} · {status}", '',
                '## 摘要', '', md(analysis['summary']), '', '## 关键要点', '']
        body += ['- ' + md(p) for p in analysis['key_points']] or ['暂无。']
        body += ['', '## 可复用信息', '']
        body += ['- ' + md(p) for p in analysis['takeaways']] or ['暂无。']
        body += ['', '## 识别依据', '', f"正文：{'已读取' if coverage['read_text'] else '未读取或无正文'}；图片 {len(coverage['reviewed_images'])} 张；抽帧拼图 {len(coverage['reviewed_frame_sheets'])} 张；转写 {len(coverage['read_transcripts'])} 份。"]
        for video in review['videos']:
            times = ', '.join(str(f['at_seconds']) for f in video['frames'])
            body += ['', f"视频时长 {video.get('duration_seconds', '未知')} 秒；采样时间：{times or '无'}。画面结论仅覆盖采样帧。"]
        limitations = list(dict.fromkeys(review['limitations'] + analysis['limitations']))
        if limitations:
            body += ['', '## 缺失与不确定性', ''] + ['- ' + md(p) for p in limitations]
        body += ['', '## 本地素材', '']
        for path in media(directory):
            body.append(f'- [{md(path.name)}]({quote(str(path.relative_to(directory)))})')
        (directory / 'summary.md').write_text('\n'.join(body) + '\n', encoding='utf-8')
        raw = load(directory / 'raw.json', {})
        rows = raw.get('detail_rows', []) if isinstance(raw, dict) else []
        list_item = raw.get('list_item', {}) if isinstance(raw, dict) else {}
        likes = next((str(row.get('value')).strip() for row in rows
                      if isinstance(row, dict) and row.get('field') == 'likes' and row.get('value') is not None and str(row['value']).strip()), '')
        if not likes and isinstance(list_item, dict):
            likes = str(list_item.get('likes') or '').strip()
        entries.append({'note_id': note_id, 'title': title, 'author': metadata.get('author', ''), 'author_url': profile, 'type': '视频' if review['videos'] else '图文',
                        'likes': likes,
                        'category': analysis['category'], 'subcategory': analysis.get('subcategory', ''), 'tags': analysis['tags'],
                        'summary': analysis['summary'], 'status': status, 'url': metadata['url'], 'review': review})
    summarized = [e for e in entries if e['status'] != '待分析']
    analysis_pending = sum(e['status'] == '待分析' for e in entries)
    capture_pending = len(failures) - analysis_pending
    counts = Counter(e['category'] for e in entries)
    with (root / 'catalog.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['ID', '标题', '作者', '形式', '分类', '子分类', '标签', '摘要', '识别状态', '原链接', '本地总结'])
        for e in entries:
            writer.writerow([cell(e[k]) for k in ('note_id', 'title', 'author', 'type', 'category', 'subcategory')] +
                            [cell('、'.join(e['tags'])), cell(e['summary']), e['status'], e['url'],
                             f"notes/{e['note_id']}/summary.md" if e['status'] != '待分析' else ''])
    overview = ['# 小红书资料库', '', f"本次范围 {len(selected)} 条；已总结 {len(summarized)} 条（完整 {sum(e['status'] == '完整' for e in summarized)} 条）；待分析 {analysis_pending} 条；采集或预处理失败 {capture_pending} 条。", '',
                '完整视频包含全文、语音及采样画面，不表示每一帧均已识别。', '']
    if manifest['runs']:
        last = manifest['runs'][-1]
        overview += [f"最近一批请求 {last['requested']} 条，实际返回 {last['returned']} 条；时间 {last['at']}。", '']
    for category, count in Counter(e['category'] for e in summarized).most_common():
        overview += [f'## {md(category)}（{count}）', '']
        overview += [f"- [{md(e['title'])}](notes/{e['note_id']}/summary.md)：{md(e['summary'])}" for e in summarized if e['category'] == category]
        overview.append('')
    if failures:
        overview += ['## 待处理', ''] + [f"- {md(f['title'] or f['note_id'])}：{md(f['reason'])}" for f in failures]
    (root / 'overview.md').write_text('\n'.join(overview) + '\n', encoding='utf-8')
    build_html(root, entries, counts, failures, getattr(args, 'source', 'liked'))
    save(root / 'render-status.json', {'at': now(), 'summarized': len(summarized), 'visible': len(entries), 'categories': dict(counts), 'analysis_pending': analysis_pending, 'capture_pending': capture_pending, 'pending': failures})
    emit('rendered', summarized=len(summarized), visible=len(entries), pending=len(failures), index=str(root / 'index.html'))
    return 0


def build_html(root, entries, counts, failures, source='liked'):
    esc = lambda value: html.escape(str(value), quote=True)
    dimensions_path = root / 'media-dimensions.json'
    dimensions_cache = load(dimensions_path, {})

    def dimensions(relative, video=False):
        """Reserve each media's display ratio without loading every video in the browser."""
        path = root / relative
        stat = path.stat()
        stamp = [stat.st_size, stat.st_mtime_ns]
        cached = dimensions_cache.get(relative, {})
        if cached.get('stamp') == stamp:
            return cached['ratio']
        if video:
            stream = next(s for s in probe(path)['streams'] if s.get('codec_type') == 'video')
            width, height = int(stream['width']), int(stream['height'])
            display = stream.get('display_aspect_ratio', '').split(':')
            if len(display) == 2 and all(p.isdigit() and int(p) > 0 for p in display):
                width, height = map(int, display)
            rotations = [s.get('rotation', 0) for s in stream.get('side_data_list', [])]
            rotation = float(next((r for r in rotations if r), stream.get('tags', {}).get('rotate', 0)))
            if abs(rotation) % 180 == 90:
                width, height = height, width
        else:
            from PIL import Image
            with Image.open(path) as image:
                width, height = image.size
                if image.getexif().get(274) in (5, 6, 7, 8):
                    width, height = height, width
        if width <= 0 or height <= 0:
            raise ValueError(f'Unknown media dimensions: {relative}')
        ratio = f'{width} / {height}'
        dimensions_cache[relative] = {'stamp': stamp, 'ratio': ratio}
        return ratio

    cards = []
    for e in entries:
        review, note_id = e['review'], e['note_id']
        labels = list(dict.fromkeys([e['category'], *e['tags']]))
        slides = []
        image_paths = [] if review['videos'] else sorted(review['images'], key=lambda value: [int(part) if part.isdigit() else part.casefold() for part in re.split(r'(\d+)', Path(value).name)])
        poster = review['images'][0] if review['images'] else ''
        for video in review['videos']:
            poster = video['frames'][0]['file'] if video.get('frames') else poster
            poster_attr = f' poster="{quote(poster)}"' if poster else ''
            mime = {'.webm': 'video/webm', '.mov': 'video/quicktime', '.mkv': 'video/x-matroska'}.get(Path(video['file']).suffix.lower(), 'video/mp4')
            slides.append(f'<div class="slide" data-kind="视频" data-aspect="{dimensions(video["file"], video=True)}"><video controls playsinline preload="none"{poster_attr} aria-label="{esc(e["title"])}的视频"><source src="{quote(video["file"])}" type="{mime}"></video></div>')
        # A video's downloaded cover remains available under Downloads, not as a second slide.
        for i, path in enumerate(image_paths):
            slides.append(f'<div class="slide" data-kind="图片" data-aspect="{dimensions(path)}"><img loading="lazy" src="{quote(path)}" alt="{esc(e["title"])} · 图片{i + 1}"></div>')
        for i in range(1, len(slides)):
            slides[i] = slides[i].replace('class="slide"', 'class="slide" hidden', 1)
        navigation = ''
        if len(slides) > 1:
            navigation = '<button class="arrow prev" data-step="-1" aria-label="上一张素材">‹</button><button class="arrow next" data-step="1" aria-label="下一张素材">›</button>'
        kind = '视频' if review['videos'] else '图片'
        first_ratio = dimensions(review['videos'][0]['file'], video=True) if review['videos'] else dimensions(image_paths[0]) if image_paths else '1 / 1'
        position = '视频' if len(slides) == 1 and review['videos'] else f'{kind} 1 / {len(slides)}'
        gallery = f'<div class="gallery" data-index="0" style="aspect-ratio:{first_ratio}">{"".join(slides)}{navigation}<span class="position" aria-live="polite">{position}</span></div>'
        profile = author_url(e.get('author_url'))
        author = f'<a class="author" href="{esc(profile)}" target="_blank" rel="noreferrer">{esc(e["author"])}</a>' if profile else f'<span class="author">{esc(e["author"])}</span>'
        original_author = f'<a class="original-author" href="{esc(profile)}" target="_blank" rel="noreferrer">{esc(e["author"])}</a>' if profile else f'<span class="original-author">{esc(e["author"])}</span>'
        likes_label = e.get('likes') or '—'
        likes_title = '采集时点赞数' if e.get('likes') else '点赞数未记录'
        original_meta = (f'<div class="original-meta"><p class="original-title">{esc(e["title"])}</p>'
                         f'<div class="original-byline">{original_author}'
                         f'<span class="original-likes" title="{likes_title}" aria-label="{likes_title} {esc(likes_label)}">'
                         f'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/></svg>{esc(likes_label)}</span></div></div>')
        tags = ''.join(f'<button class="tag" data-filter="{esc(t)}" aria-pressed="false">{esc(t)}</button>' for t in labels)
        search = ' '.join([e['title'], e['author'], e['subcategory'], e['summary'], *labels])
        analysis = load(root / 'notes' / note_id / 'analysis.json') or {}
        points = ''.join(f'<li>{esc(p)}</li>' for p in analysis.get('key_points', []))
        limits = ''.join(f'<li>{esc(p)}</li>' for p in dict.fromkeys(review['limitations'] + analysis.get('limitations', [])))
        evidence = f'<details class="evidence"><summary>要点与依据</summary><ul>{points}</ul>'
        if limits:
            evidence += f'<p class="muted">备注</p><ul>{limits}</ul>'
        evidence += f'<p class="muted">正文 · {len(review["images"])}张原图 · {sum(len(v["frames"]) for v in review["videos"])}帧采样</p>'
        if e['status'] != '待分析':
            evidence += f'<a href="notes/{note_id}/summary.md">完整记录</a>'
        evidence += '</details>'
        downloads = ' '.join(f'<a href="{quote(str(p.relative_to(root)))}" download>{esc(p.name)}</a>' for p in media(root / 'notes' / note_id))
        split_attr = ' data-clean-split="true"' if len(image_paths) > 1 else ''
        cards.append(f'<article data-note-id="{note_id}" data-item-id="{note_id}"{split_attr} data-default-group="{esc(e["category"])}" data-tags="{esc(json.dumps(labels, ensure_ascii=False))}" data-search="{esc(search.lower())}">{gallery}{original_meta}<div class="body"><div class="byline">{author}<span class="status">{esc(e["type"])} · {esc(e["status"])}</span></div><h2>{esc(e["title"])}</h2><p class="phrase">{esc(e["summary"])}</p><div class="tags">{tags}</div>{evidence}<div class="links"><button type="button" class="open-chrome" data-open-note="{note_id}" title="在已登录的 Chrome 中打开">原笔记 ↗</button><a href="/open-note/{note_id}" target="_blank" rel="noreferrer">当前浏览器</a><details class="downloads"><summary>下载素材</summary>{downloads}</details></div></div></article>')
        for i, path in enumerate(image_paths if split_attr else []):
            ratio = dimensions(path)
            cards.append(f'<div class="clean-tile" data-clean-note-id="{esc(note_id)}" data-slide-index="{i}"><div class="gallery" data-index="0" style="aspect-ratio:{ratio}"><div class="slide" data-kind="图片" data-aspect="{ratio}"><img loading="lazy" src="{quote(path)}" alt="{esc(e["title"])} · 图片{i + 1}"></div></div></div>')
    filters = '<button class="tag active" data-filter="" aria-pressed="true">全部</button>' + ''.join(f'<button class="tag" data-filter="{esc(c)}" aria-pressed="false">{esc(c)} <span>{n}</span></button>' for c, n in counts.most_common())
    for asset in ('library-groups.js', 'library-groups.css', 'shiji-shell.js', 'shiji-theme.css', 'library-selection.js', 'library-selection.css'):
        asset_source = Path(__file__).with_name(asset)
        if asset_source.is_file():
            (root / asset).write_bytes(asset_source.read_bytes())
    icon_source = Path(__file__).with_name('shiji-assets')
    if icon_source.is_dir():
        shutil.copytree(icon_source, root / 'shiji-assets', dirs_exist_ok=True)
    template = Path(__file__).with_name('library-template.html').read_text(encoding='utf-8')
    template = template.replace('__FOLLOWING_LINK__', '<a href="following.html">关注账号</a>' if (root / 'following.html').is_file() else '')
    liked_current = 'aria-current="page"' if source == 'liked' else ''
    saved_current = 'aria-current="page"' if source == 'saved' else ''
    template = template.replace('__LIST_TABS__',
        f'<a class="list-tab" href="/index.html" {liked_current}>点赞列表</a>'
        f'<a class="list-tab" href="/saved.html" {saved_current}>收藏列表</a>'
        '<a class="list-tab" href="/following.html">关注列表</a>')
    save(dimensions_path, dimensions_cache)
    following_count = len(load(root / 'following.json', []))
    save(root / 'shiji-counts.json', {'liked': len(entries), 'following': following_count})
    analysis_pending = sum(e['status'] == '待分析' for e in entries)
    stats = f'{len(entries)} 条笔记 · {len(counts)} 个分类标签 · {analysis_pending} 条待分析 · {len(failures) - analysis_pending} 条采集失败'
    output = template.replace('__STATS__', stats).replace('__FILTERS__', filters).replace('__CARDS__', ''.join(cards)).replace('__UPDATED__', esc(datetime.now().astimezone().strftime('%Y-%m-%d %H:%M')))
    for asset in ('library-groups.js', 'library-groups.css', 'shiji-shell.js', 'shiji-theme.css', 'library-selection.js', 'library-selection.css'):
        version = hashlib.sha256((root / asset).read_bytes()).hexdigest()[:12]
        output = output.replace(f'"{asset}"', f'"{asset}?v={version}"')
    if not (root / 'digest.md').is_file():
        output = output.replace('<a href="digest.md">综合总结</a>', '')
    if source == 'saved':
        output = output.replace('小红书点赞资料库', '小红书收藏资料库')
        output = output.replace('/open-note/', '/open-saved-note/')
    output = wrap_shell(output, source, len(entries), following_count)
    (root / 'index.html').write_text(output, encoding='utf-8')


def doctor(args):
    emit('doctor', python=sys.executable, opencli=binary('opencli'), ffmpeg=binary('ffmpeg'), ffprobe=binary('ffprobe'),
         pillow=bool(importlib.util.find_spec('PIL')), faster_whisper=bool(importlib.util.find_spec('faster_whisper')))
    return 0


def serve(args):
    return subprocess.call([sys.executable, str(Path(__file__).with_name('library-server.py')), '--root', str(args.root.resolve()), '--port', str(args.port)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('doctor')
    for name in ('capture', 'prepare', 'pending', 'render', 'authors', 'serve'):
        sub = commands.add_parser(name)
        sub.add_argument('--root', type=Path, required=True)
        if name == 'serve':
            sub.add_argument('--port', type=int, default=8765)
        if name == 'render':
            sub.add_argument('--scope-latest', action='store_true', help='Only render the latest captured list, in list order')
            sub.add_argument('--source', choices=('liked', 'saved'), default='liked')
        if name in ('capture', 'authors'):
            sub.add_argument('--source', choices=('liked', 'saved'), default='liked')
            sub.add_argument('--limit', type=int, default=20)
            sub.add_argument('--profile')
        if name == 'capture':
            sub.add_argument('--urls-file', type=Path)
            sub.add_argument('--interval', type=float, default=3)
            sub.add_argument('--refresh', action='store_true')
            sub.add_argument('--incremental', action='store_true', help='Only capture new prefix and retry visible incomplete notes')
        if name == 'prepare':
            sub.add_argument('--frames', type=int, default=12)
            sub.add_argument('--model', default='base')
            sub.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    if args.command in ('capture', 'authors') and not 1 <= args.limit <= 1000:
        parser.error('collection limit must be 1–1000')
    if args.command == 'capture' and args.interval < 2:
        parser.error('interval must be at least 2 seconds')
    if args.command == 'prepare' and not 1 <= args.frames <= 120:
        parser.error('frames must be 1–120')
    try:
        return globals()[args.command](args)
    except Exception as exc:
        emit('error', error=str(exc))
        return 1


if __name__ == '__main__':
    sys.exit(main())
