#!/usr/bin/env python3
"""Local Shiji onboarding and import server. No remote account credentials are stored."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone, timedelta
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote, parse_qs

from library import parse_json
import library as library_module
from analysis_engine import analyze_note, codex_binary
from chrome_bookmarks import current_profile, read_bookmarks
from local_content import parse_chrome_export, validate_product

# library-server.py is kept under its historical name for the existing viewer.
import importlib.util

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('library_server', HERE / 'library-server.py')
library_server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(library_server)

PROFILE_ID = re.compile(r'^[0-9a-f]{24}$', re.I)
SOURCES = ('liked', 'saved', 'following')
PRIVATE_FILES = {'manifest.json', 'authors.json', 'display-order.json', 'media-dimensions.json',
                 'downloads.json', 'metadata.json', 'analysis.json', 'review.json', 'config.json',
                 'following-list.json', 'following-orders.json', 'bookmarks.json', 'bookmarks-access.json', 'products.json'}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def write_private(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix(path.suffix + '.tmp')
    with os.fdopen(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write('\n')
    os.replace(temp, path)


def read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return fallback


def redact(value):
    return re.sub(r'xsec_token=[^\s"&]+', 'xsec_token=[redacted]', str(value))


def install_adapter(name):
    source = HERE / (name + '.js')
    target = Path.home() / '.opencli' / 'clis' / 'xiaohongshu' / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(0o600)


def cli_env():
    return {**os.environ, 'OPENCLI_WINDOW': 'background', 'OPENCLI_BROWSER_COMMAND_TIMEOUT': '300'}


class ImportManager:
    def __init__(self, data_dir: Path):
        self.root = data_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.config_path = self.root / 'config.json'
        self.bookmarks_access_path = self.root / 'bookmarks-access.json'
        self.lock = threading.RLock()
        self.process = None
        self.cancel_requested = False
        self.job = {'state': 'idle', 'phase': '', 'events': [], 'counts': {}, 'error': '', 'started_at': None}

    def config(self):
        return read_json(self.config_path, {'sources': ['liked'], 'limit': 100, 'auto_analyze': True,
                                            'profile_id': '', 'verified_at': None})

    def status(self):
        with self.lock:
            config = self.config()
            return {'config': config, 'job': json.loads(json.dumps(self.job)),
                    'libraries': {source: {'visible': read_json(self.root / source / 'render-status.json', {}).get('visible', 0),
                                           'pending': read_json(self.root / source / 'render-status.json', {}).get('analysis_pending', 0),
                                           'categories': read_json(self.root / source / 'render-status.json', {}).get('categories', {})}
                                  for source in ('liked', 'saved')},
                    'following_count': sum(row.get('sort') == '综合排序' for row in read_json(self.root / 'following-list.json', [])),
                    'bookmarks_count': len(read_json(self.root / 'bookmarks.json', [])),
                    'products_count': len(read_json(self.root / 'products.json', []))}

    def import_bookmarks(self, content):
        rows = parse_chrome_export(content)
        with self.lock:
            write_private(self.root / 'bookmarks.json', rows)
            self.bookmarks_access_path.unlink(missing_ok=True)
        return {'imported': len(rows)}

    def bookmarks_access(self):
        access = read_json(self.bookmarks_access_path, {})
        return {'authorized': bool(access.get('profile')), 'profile': access.get('profile', ''),
                'last_sync_at': access.get('last_sync_at')}

    def sync_chrome_bookmarks(self, authorize=False):
        access = read_json(self.bookmarks_access_path, {})
        profile = current_profile() if authorize else access.get('profile')
        if not profile:
            raise ValueError('请先授权读取当前 Chrome 配置的书签')
        result = read_bookmarks(profile)
        with self.lock:
            unchanged = (access.get('profile') == profile and access.get('fingerprint') == result['fingerprint']
                         and (self.root / 'bookmarks.json').is_file())
            if not unchanged:
                write_private(self.root / 'bookmarks.json', result['rows'])
            write_private(self.bookmarks_access_path, {'profile': profile, 'fingerprint': result['fingerprint'],
                                                       'authorized_at': access.get('authorized_at') if access.get('profile') == profile else utc_now(),
                                                       'last_sync_at': utc_now()})
        return {'imported': len(result['rows']), 'skipped': result['skipped'], 'profile': profile,
                'unchanged': unchanged}

    def save_product(self, payload):
        product = validate_product(payload)
        with self.lock:
            rows = read_json(self.root / 'products.json', [])
            rows.append(product)
            write_private(self.root / 'products.json', rows)
        return product

    def remove_product(self, product_id):
        if not isinstance(product_id, str) or not re.fullmatch(r'[0-9a-f]{32}', product_id):
            raise ValueError('产品编号无效')
        with self.lock:
            rows = read_json(self.root / 'products.json', [])
            kept = [row for row in rows if row.get('id') != product_id]
            if len(kept) == len(rows):
                raise ValueError('未找到该产品')
            write_private(self.root / 'products.json', kept)
        return {'removed': product_id}

    def save_settings(self, payload):
        sources = payload.get('sources')
        limit = payload.get('limit', 100)
        auto_analyze = payload.get('auto_analyze', True)
        if not isinstance(sources, list) or not sources or len(sources) != len(set(sources)) or any(x not in SOURCES for x in sources):
            raise ValueError('请选择至少一种可导入内容')
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('每类最多导入 1–1000 条')
        if type(auto_analyze) is not bool:
            raise ValueError('自动归类设置无效')
        with self.lock:
            if self.job['state'] == 'running':
                raise ValueError('导入正在运行，无法修改范围')
            config = self.config()
            config.update(sources=sources, limit=limit, auto_analyze=auto_analyze)
            write_private(self.config_path, config)
            return config

    def connect(self):
        with self.lock:
            if self.job['state'] == 'running':
                raise ValueError('请等待当前导入完成')
        executable = shutil.which('opencli')
        if not executable:
            raise RuntimeError('未安装 OpenCLI；请先完成 README 中的 Chrome 扩展连接')
        install_adapter('shiji-connect')
        result = subprocess.run([executable, 'xiaohongshu', 'shiji-connect', '--site-session', 'persistent', '-f', 'json'],
                                env=cli_env(), text=True, capture_output=True, timeout=120)
        if result.returncode:
            raise RuntimeError(redact((result.stderr or result.stdout or '登录会话不可用')[-800:]))
        rows = parse_json(result.stdout)
        if isinstance(rows, dict):
            rows = rows.get('data', rows.get('rows', []))
        profile_id = rows[0].get('profile_id') if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None
        if not isinstance(profile_id, str) or not PROFILE_ID.fullmatch(profile_id):
            raise RuntimeError('未能确认当前登录账号，请在 Chrome 中登录小红书后重试')
        with self.lock:
            config = self.config()
            config.update(profile_id=profile_id.lower(), verified_at=utc_now())
            write_private(self.config_path, config)
        return {'profile_id': profile_id.lower(), 'verified_at': config['verified_at']}

    def start(self):
        with self.lock:
            config = self.config()
            if not PROFILE_ID.fullmatch(config.get('profile_id', '')):
                raise ValueError('请先验证已登录的小红书账号')
            try:
                verified = datetime.fromisoformat(config.get('verified_at') or '')
            except ValueError:
                verified = None
            if not verified or verified.tzinfo is None or datetime.now(timezone.utc) - verified > timedelta(minutes=10):
                raise ValueError('登录验证已过期，请重新验证当前账号')
            if self.job['state'] == 'running':
                raise ValueError('已有导入任务正在运行')
            if not shutil.which('opencli'):
                raise RuntimeError('OpenCLI 不可用')
            if config.get('auto_analyze', True) and any(source in ('liked', 'saved') for source in config['sources']) and not codex_binary():
                raise RuntimeError('自动归类需要已登录的 Codex CLI；安装后重试，或在导入设置中关闭自动归类')
            self.cancel_requested = False
            self.job = {'state': 'running', 'phase': '准备导入', 'events': [], 'counts': {},
                        'error': '', 'started_at': utc_now(), 'finished_at': None}
            thread = threading.Thread(target=self._run, args=(config,), daemon=True)
            thread.start()
            return self.job

    def cancel(self):
        with self.lock:
            self.cancel_requested = True
            if self.process and self.process.poll() is None:
                self.process.terminate()
            return {'cancel_requested': True}

    def _event(self, source, stage, detail):
        with self.lock:
            safe = json.loads(redact(json.dumps(detail, ensure_ascii=False))) if isinstance(detail, (dict, list)) else redact(detail)
            self.job['phase'] = stage
            self.job['events'].append({'at': utc_now(), 'source': source, 'stage': stage, 'detail': safe})
            self.job['events'] = self.job['events'][-100:]
            if isinstance(detail, dict):
                event = detail.get('event')
                if event in ('captured', 'capture_skipped'):
                    key = f'{source}_{event}'
                    self.job['counts'][key] = self.job['counts'].get(key, 0) + 1
                if event == 'rendered':
                    self.job['counts'][f'{source}_visible'] = detail.get('visible', 0)
                    self.job['counts'][f'{source}_pending'] = detail.get('pending', 0)
                if event == 'following_saved':
                    self.job['counts']['following_visible'] = detail.get('count', 0)
                if event in ('analyzed', 'analysis_partial', 'analysis_failed'):
                    key = f'{source}_{event}'
                    self.job['counts'][key] = self.job['counts'].get(key, 0) + 1

    def _command(self, source, stage, args):
        if self.cancel_requested:
            raise InterruptedError('用户取消了导入，已保存已完成的内容')
        self._event(source, stage, {'command': stage})
        events = []
        with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, bufsize=1, env=cli_env()) as process:
            with self.lock:
                self.process = process
            for line in process.stdout:
                try:
                    detail = json.loads(line)
                except json.JSONDecodeError:
                    detail = {'message': line.strip()[:300]}
                events.append(detail)
                self._event(source, stage, detail)
            error = process.stderr.read()[-1200:]
            code = process.wait()
            with self.lock:
                self.process = None
            if self.cancel_requested:
                raise InterruptedError('用户取消了导入，已保存已完成的内容')
            if code:
                boundary = any(isinstance(item, dict) and item.get('event') == 'incremental_boundary_missing' for item in events)
                blocked = any(isinstance(item, dict) and (item.get('event') in ('capture_blocked', 'list_window_short') or item.get('blocked') is True) for item in events)
                if code == 2 and boundary and not blocked:
                    return {'boundary_missing': True}
                issue = next((item.get('error') or item.get('message') for item in reversed(events)
                              if isinstance(item, dict) and item.get('event') in ('capture_blocked', 'error', 'list_window_short')), '')
                raise RuntimeError(redact(issue or error or f'{stage} 退出码 {code}；请查看进度记录'))
        return {'boundary_missing': False}

    def _run_following(self, config):
        install_adapter('shiji-following')
        executable = shutil.which('opencli')
        args = [executable, 'xiaohongshu', 'shiji-following', '--site-session', 'persistent', '-f', 'json',
                '--id', config['profile_id'], '--limit', str(config['limit']), '--sort', 'all']
        self._event('following', '读取关注名单', {'message': '正在读取综合、最新、最早三种顺序'})
        with subprocess.Popen(args, env=cli_env(), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
            with self.lock:
                self.process = process
            try:
                output, error = process.communicate(timeout=1800)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                raise RuntimeError('关注名单读取超时；已保留旧名单，请检查登录状态与访问限制')
            finally:
                with self.lock:
                    self.process = None
            if self.cancel_requested:
                raise InterruptedError('用户取消了导入，已保存已完成的内容')
            if process.returncode:
                raise RuntimeError(redact((error or output or '关注名单读取失败')[-1200:]))
        rows = parse_json(output)
        if isinstance(rows, dict):
            rows = rows.get('data', rows.get('rows', []))
        if not isinstance(rows, list) or not rows:
            raise RuntimeError('关注名单没有返回数据')
        buckets = {name: [row for row in rows if row.get('sort') == name] for name in ('综合排序', '最新关注', '最早关注')}
        counts = {len(value) for value in buckets.values()}
        if len(counts) != 1 or 0 in counts:
            raise RuntimeError('三种关注顺序数量不同，已保留旧名单')
        identity = lambda row: urlsplit(row.get('profile_url', '')).path or (row.get('name'), row.get('avatar'), row.get('description'))
        members = [Counter(identity(row) for row in bucket) for bucket in buckets.values()]
        if members[0] != members[1] or members[1] != members[2]:
            raise RuntimeError('三种关注顺序的成员集合不同，已保留旧名单')
        # Names may repeat; keep source rows and order instead of inventing an identity.
        write_private(self.root / 'following-list.json', rows)
        count = counts.pop()
        self._event('following', '读取关注名单', {'event': 'following_saved', 'count': count,
                                            'message': f'三种顺序各 {count} 项；主页身份未核验的项保留待核实'})

    def _analyze_source(self, root, source):
        executable = codex_binary()
        if not executable:
            self._event(source, '自动归类', {'event': 'analysis_failed', 'message': 'Codex CLI 不可用，内容保留待分析'})
            return
        manifest = library_module.load(root / 'manifest.json', {'notes': {}})
        latest = library_module.load(root / 'latest-list.json', [])
        ordered = list(dict.fromkeys([row.get('id') for row in latest if isinstance(row, dict)] + list(manifest['notes'])))
        existing = [name for name in library_module.load(root / 'render-status.json', {}).get('categories', {}) if name != '待分析']
        streak = 0
        for note_id in ordered:
            if self.cancel_requested:
                raise InterruptedError('用户取消了导入，已保存已完成的内容')
            if not isinstance(note_id, str) or not PROFILE_ID.fullmatch(note_id):
                continue
            directory = root / 'notes' / note_id
            review = library_module.load(directory / 'review.json')
            if not review:
                continue
            current = library_module.load(directory / 'analysis.json')
            try:
                library_module.check_current(review, manifest['notes'].get(note_id, {}), root)
                if current:
                    try:
                        library_module.check(current, review, root)
                        continue
                    except ValueError:
                        pass
                self._event(source, '自动归类', {'message': f'正在分析笔记 {note_id}'})
                def set_process(process):
                    with self.lock:
                        self.process = process
                analysis = analyze_note(root, review, existing, executable, on_process=set_process,
                                        cancelled=lambda: self.cancel_requested)
                library_module.save(directory / 'analysis.json', analysis)
                if analysis['category'] not in existing:
                    existing.append(analysis['category'])
                event = 'analyzed' if analysis['coverage']['status'] == 'complete' else 'analysis_partial'
                self._event(source, '自动归类', {'event': event, 'note_id': note_id,
                                            'category': analysis['category'],
                                            'message': f'{analysis["category"]} · {analysis["coverage"]["status"]}'})
                streak = 0
            except InterruptedError:
                raise
            except Exception as exc:
                streak += 1
                self._event(source, '自动归类', {'event': 'analysis_failed', 'note_id': note_id,
                                            'message': redact(str(exc))[:300]})
                if streak >= 3 or any(term in str(exc).lower() for term in ('not logged in', '401 unauthorized', 'quota exceeded')):
                    self._event(source, '自动归类', {'message': '连续分析失败，后续内容保留待分析'})
                    break

    def _run(self, config):
        try:
            for source in config['sources']:
                if self.cancel_requested:
                    raise InterruptedError('用户取消了导入，已保存已完成的内容')
                if source == 'following':
                    self._run_following(config)
                    continue
                root = self.root / source
                command = [sys.executable, str(HERE / 'library.py')]
                incremental = (root / 'manifest.json').exists()
                capture = command + ['capture', '--root', str(root), '--source', source,
                                     '--profile', config['profile_id'], '--limit', str(config['limit'])]
                if incremental:
                    capture.append('--incremental')
                result = self._command(source, '采集与下载', capture)
                if incremental and result['boundary_missing']:
                    for limit in (200, 400, 1000):
                        if limit <= config['limit']:
                            continue
                        self._event(source, '扩大读取窗口', {'message': f'上次列表边界未出现，扩大到 {limit} 条'})
                        wider = [str(limit) if item == str(config['limit']) else item for item in capture]
                        result = self._command(source, '采集与下载', wider)
                        if not result['boundary_missing']:
                            break
                    if result['boundary_missing']:
                        raise RuntimeError('读取到 1000 条仍未遇到上次列表边界；已保留旧同步基线')
                self._command(source, '图像与视频预处理', command + ['prepare', '--root', str(root)])
                if config.get('auto_analyze', True):
                    self._analyze_source(root, source)
                self._command(source, '生成资料库', command + ['render', '--root', str(root), '--source', source])
            with self.lock:
                incomplete = any(key.endswith(('_analysis_failed', '_analysis_partial')) and value
                                 for key, value in self.job['counts'].items())
                self.job.update(state='partial' if incomplete else 'complete',
                                phase='导入完成，部分内容待核实' if incomplete else '导入完成',
                                finished_at=utc_now())
        except (Exception, InterruptedError) as exc:
            with self.lock:
                self.job.update(state='cancelled' if isinstance(exc, InterruptedError) else 'failed',
                                phase='已停止', error=redact(exc), finished_at=utc_now())
            self._event('', '已停止', {'message': str(exc)})


class AppHandler(library_server.LibraryHandler):
    def _host_allowed(self):
        host = self.headers.get('Host', '')
        return host in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

    def _origin_allowed(self):
        origin = self.headers.get('Origin')
        return origin in (f'http://127.0.0.1:{self.server.server_port}',
                          f'http://localhost:{self.server.server_port}')

    def do_GET(self):
        if not self._host_allowed():
            return self.send_error(403, 'Local access only')
        path = unquote(urlsplit(self.path).path)
        if path in ('/', '/import', '/import.html'):
            return self._asset('import.html', 'text/html; charset=utf-8')
        if path == '/import.css':
            return self._asset('import.css', 'text/css; charset=utf-8')
        if path == '/import.js':
            return self._asset('import.js', 'text/javascript; charset=utf-8')
        if path in ('/bookmarks.html', '/products.html'):
            return self._asset(path.lstrip('/'), 'text/html; charset=utf-8')
        if path == '/local.css':
            return self._asset('local.css', 'text/css; charset=utf-8')
        if path == '/local.js':
            return self._asset('local.js', 'text/javascript; charset=utf-8')
        if path == '/api/status':
            return self.json_response(self.server.import_manager.status())
        if path == '/api/bookmarks':
            return self.json_response(read_json(self.server.import_manager.root / 'bookmarks.json', []))
        if path == '/api/bookmarks/access':
            return self.json_response(self.server.import_manager.bookmarks_access())
        if path == '/api/products':
            return self.json_response(read_json(self.server.import_manager.root / 'products.json', []))
        if path in ('/api/groups', '/api/trash') and parse_qs(urlsplit(self.path).query).get('source') == ['saved']:
            store = (library_server.GroupStore if path == '/api/groups' else library_server.TrashStore)(self.server.import_manager.root / 'saved')
            return self.json_response(store.read())
        if path in ('/api/groups', '/api/trash') or re.fullmatch(r'/open-note/[0-9a-f]{24}', path):
            return super().do_GET()
        if path == '/following.html':
            return self._following_page()
        match = re.fullmatch(r'/open-saved-note/([0-9a-f]{24})', path)
        if match:
            url = library_server.signed_note_url(self.server.import_manager.root / 'saved', match.group(1))
            if not url:
                return self.json_response({'error': '未找到原笔记链接'}, 404)
            self.send_response(302)
            self.send_header('Location', url)
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            return
        if path == '/index.html':
            self.send_response(302)
            self.send_header('Location', '/liked/index.html')
            self.end_headers()
            return
        if path == '/saved.html':
            self.send_response(302)
            self.send_header('Location', '/saved/index.html')
            self.end_headers()
            return
        parts = Path(path).parts
        if any(part.startswith('.') or part in PRIVATE_FILES or part == '..' for part in parts) or path.endswith(('.json', '.py', '.sh')):
            return self.send_error(404, 'Not found')
        if '%' in path or not path.lower().endswith(('.html', '.css', '.js', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.mp4', '.mov', '.m4v', '.webm', '.md', '.csv', '.txt')):
            return self.send_error(404, 'Not found')
        return super().do_GET()

    def _asset(self, name, content_type):
        data = (HERE / name).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _following_page(self):
        from html import escape
        rows = read_json(self.server.import_manager.root / 'following-list.json', [])
        current = [row for row in rows if row.get('sort') == '综合排序']
        cards = []
        for row in current:
            url = row.get('profile_url', '')
            parsed = urlsplit(url)
            valid = parsed.scheme == 'https' and parsed.hostname in ('www.xiaohongshu.com', 'xiaohongshu.com') and re.fullmatch(r'/user/profile/[0-9a-f]{24}/?', parsed.path, re.I)
            name = escape(row.get('name', ''))
            name = f'<a href="{escape(url, quote=True)}" target="_blank" rel="noreferrer">{name} ↗</a>' if valid else name
            avatar = row.get('avatar', '')
            avatar_url = urlsplit(avatar)
            if avatar_url.scheme != 'https' or not (avatar_url.hostname or '').endswith('.xhscdn.com'):
                avatar = ''
            cards.append('<article class="person"><img src="{}" alt=""><div><b>{}</b><p>{}</p><small>{}</small></div></article>'.format(
                escape(avatar, quote=True), name, escape(row.get('description', '')),
                '已记录主页' if valid else '主页待核实'))
        html = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>我的关注 · 拾集</title><link rel="stylesheet" href="/import.css"><body><div class="simple-page"><a href="/import">← 导入中心</a><h1>我的关注</h1><p>共 {} 位。缺少真实主页链接时保留待核实，不凭昵称猜测身份。</p><div class="people">{}</div></div></body></html>'.format(len(current), ''.join(cards))
        data = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if not self._host_allowed() or not self._origin_allowed():
            return self.json_response({'error': '仅接受本机页面请求'}, 403)
        path = urlsplit(self.path).path
        if path in ('/api/groups', '/api/trash') and parse_qs(urlsplit(self.path).query).get('source') == ['saved']:
            if self.headers.get_content_type() != 'application/json':
                return self.json_response({'error': '需要JSON格式'}, 415)
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 262144:
                return self.json_response({'error': '请求大小无效'}, 400)
            try:
                payload = json.loads(self.rfile.read(size))
                store = (library_server.GroupStore if path == '/api/groups' else library_server.TrashStore)(self.server.import_manager.root / 'saved')
                return self.json_response(store.apply(payload))
            except (ValueError, TypeError, KeyError) as exc:
                return self.json_response({'error': str(exc)}, 400)
        if path == '/api/open-note' and parse_qs(urlsplit(self.path).query).get('source') == ['saved']:
            if self.headers.get_content_type() != 'application/json':
                return self.json_response({'error': '需要JSON格式'}, 415)
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 256:
                return self.json_response({'error': '请求大小无效'}, 400)
            try:
                note_id = json.loads(self.rfile.read(size)).get('note_id')
            except (ValueError, AttributeError):
                note_id = None
            if not isinstance(note_id, str) or not PROFILE_ID.fullmatch(note_id):
                return self.json_response({'error': '无效笔记编号'}, 400)
            url = library_server.signed_note_url(self.server.import_manager.root / 'saved', note_id)
            if not url:
                return self.json_response({'error': '未找到原笔记链接'}, 404)
            try:
                subprocess.run(['/usr/bin/open', '-a', 'Google Chrome', url],
                               stdin=subprocess.DEVNULL, capture_output=True, timeout=10, check=True)
            except (OSError, subprocess.SubprocessError):
                return self.json_response({'error': 'Chrome 无法打开'}, 500)
            return self.json_response({'opened': True})
        if path not in ('/api/settings', '/api/connect', '/api/import/start', '/api/import/cancel',
                        '/api/bookmarks/import', '/api/bookmarks/connect', '/api/bookmarks/sync',
                        '/api/products/save', '/api/products/remove'):
            return super().do_POST()
        if self.headers.get_content_type() != 'application/json':
            return self.json_response({'error': '需要JSON格式'}, 415)
        size = int(self.headers.get('Content-Length', '0'))
        max_size = 12_000_000 if path == '/api/bookmarks/import' else 4096
        if not 0 <= size <= max_size:
            return self.json_response({'error': '请求过大'}, 413)
        try:
            payload = json.loads(self.rfile.read(size) or b'{}')
            if not isinstance(payload, dict):
                raise ValueError('请求内容格式无效')
            if path == '/api/settings':
                result = self.server.import_manager.save_settings(payload)
            elif path == '/api/connect':
                result = self.server.import_manager.connect()
            elif path == '/api/import/start':
                result = self.server.import_manager.start()
            elif path == '/api/import/cancel':
                result = self.server.import_manager.cancel()
            elif path == '/api/bookmarks/import':
                result = self.server.import_manager.import_bookmarks(payload.get('content'))
            elif path == '/api/bookmarks/connect':
                result = self.server.import_manager.sync_chrome_bookmarks(authorize=True)
            elif path == '/api/bookmarks/sync':
                result = self.server.import_manager.sync_chrome_bookmarks()
            elif path == '/api/products/save':
                result = self.server.import_manager.save_product(payload)
            else:
                result = self.server.import_manager.remove_product(payload.get('id'))
            return self.json_response(result)
        except (ValueError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            return self.json_response({'error': redact(exc)}, 400)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path.cwd() / 'data')
    parser.add_argument('--port', type=int, default=8879)
    args = parser.parse_args()
    manager = ImportManager(args.data_dir)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), partial(AppHandler, directory=str(manager.root)))
    server.import_manager = manager
    server.group_store = library_server.GroupStore(manager.root / 'liked')
    server.trash_store = library_server.TrashStore(manager.root / 'liked')
    print(f'Shiji: http://127.0.0.1:{args.port}/import', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
