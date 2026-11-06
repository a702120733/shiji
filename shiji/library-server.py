#!/usr/bin/env python3
"""Loopback-only static library with atomic, separate user grouping preferences."""
import argparse
import copy
import json
import os
import re
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


NOTE_ID = re.compile(r'[0-9a-f]{24}')


def signed_note_url(root, note_id):
    """Find the most recent saved source link without publishing its token in HTML."""
    latest = Path(root) / 'latest-list.json'
    candidates = []
    if latest.is_file():
        try:
            listing = json.loads(latest.read_text(encoding='utf-8'))
            if isinstance(listing, list):
                candidates.extend(item.get('url') for item in listing if isinstance(item, dict) and item.get('id') == note_id)
        except (ValueError, OSError):
            pass
    raw = Path(root) / 'notes' / note_id / 'raw.json'
    if raw.is_file():
        try:
            item = json.loads(raw.read_text(encoding='utf-8')).get('list_item', {})
            if isinstance(item, dict) and item.get('id') == note_id:
                candidates.append(item.get('url'))
        except (ValueError, OSError, AttributeError):
            pass
    for value in candidates:
        if not isinstance(value, str):
            continue
        url = urlsplit(value)
        path = url.path.rstrip('/')
        valid_path = re.fullmatch(r'/user/profile/[0-9a-f]{24}/' + note_id, path, re.I) or path == '/explore/' + note_id
        if url.scheme == 'https' and url.hostname in ('www.xiaohongshu.com', 'xiaohongshu.com') and valid_path and parse_qs(url.query).get('xsec_token'):
            return value
    return None


def empty_scope():
    return {'groups': {}, 'order': [], 'assignments': {}}


DEFAULT_LIKED_FOLDERS = [
    {'id': 'design', 'name': '设计'},
    {'id': 'ai', 'name': 'AI'},
    {'id': 'life', 'name': '生活'},
]
DESIGN_SOURCES = {'App设计', '视觉', '动效', '影视与创作', '动画', '产品设计', '设计方法'}
AI_SOURCES = {'AI与工具', 'AI工具', '独立开发', '效率工具'}


def default_liked_folder(group):
    source = group.get('source') or ''
    name = group.get('name') or ''
    if source == '待分析' or name == '待分析':
        return None
    if source in DESIGN_SOURCES or name in ('视觉灵感', '想法灵感'):
        return 'design'
    if source in AI_SOURCES:
        return 'ai'
    if re.search(r'设计|视觉|动效|动画|创作|灵感|作品|交互|UI|UX', name, re.I):
        return 'design'
    if re.search(r'AI|智能|模型|编程|开发|工具|Agent', name, re.I):
        return 'ai'
    return 'life'


class GroupStore:
    def __init__(self, root):
        self.path = Path(root) / 'group-settings.json'
        self.lock = threading.RLock()

    def read(self):
        with self.lock:
            if not self.path.exists():
                state = {'version': 1, 'liked': empty_scope(), 'following': empty_scope()}
            else:
                state = json.loads(self.path.read_text(encoding='utf-8'))
            liked = state['liked']
            liked.setdefault('folders', copy.deepcopy(DEFAULT_LIKED_FOLDERS))
            assignments = liked.setdefault('folderAssignments', {})
            folder_ids = {folder['id'] for folder in liked['folders']}
            for group_id, group in liked['groups'].items():
                if group_id not in assignments:
                    folder_id = default_liked_folder(group)
                    if folder_id and folder_ids:
                        assignments[group_id] = folder_id if folder_id in folder_ids else liked['folders'][0]['id']
            return state

    @staticmethod
    def folder(value):
        if not isinstance(value, dict):
            raise ValueError('缺少文件夹')
        identity, name = value.get('id'), value.get('name')
        if not isinstance(identity, str) or not re.fullmatch(r'(?:design|ai|life|custom:[A-Za-z0-9-]{1,80})', identity):
            raise ValueError('无效文件夹编号')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40 or any(ord(c) < 32 for c in name):
            raise ValueError('文件夹名称需为1–40个字符')
        return {'id': identity, 'name': name.strip()}

    @staticmethod
    def group(value):
        if not isinstance(value, dict):
            raise ValueError('缺少分组')
        identity, name, source = value.get('id'), value.get('name'), value.get('source')
        if not isinstance(identity, str) or len(identity) > 160:
            raise ValueError('无效分组编号')
        if identity.startswith('source:'):
            if not isinstance(source, str) or identity != 'source:' + source or not source:
                raise ValueError('无效原始分组')
        elif not re.fullmatch(r'custom:[A-Za-z0-9-]{1,80}', identity) or source is not None:
            raise ValueError('无效自定义分组')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40 or any(ord(c) < 32 for c in name):
            raise ValueError('分组名称需为1–40个字符')
        return {'id': identity, 'name': name.strip(), 'source': source}

    def apply(self, payload):
        if not isinstance(payload, dict) or payload.get('scope') not in ('liked', 'following'):
            raise ValueError('无效列表')
        with self.lock:
            state = copy.deepcopy(self.read())
            scope = state[payload['scope']]
            action = payload.get('action')

            def register(value, overwrite=False):
                group = self.group(value)
                old = scope['groups'].get(group['id'])
                if old and old['source'] != group['source']:
                    raise ValueError('原始分组不可改变')
                if overwrite or not old:
                    scope['groups'][group['id']] = group
                if group['id'] not in scope['order']:
                    scope['order'].append(group['id'])
                if payload['scope'] == 'liked' and group['id'] not in scope['folderAssignments']:
                    folder_id = default_liked_folder(group)
                    folder_ids = {folder['id'] for folder in scope['folders']}
                    if folder_id and folder_ids:
                        scope['folderAssignments'][group['id']] = folder_id if folder_id in folder_ids else scope['folders'][0]['id']
                return group['id']

            context = payload.get('groups', [])
            if not isinstance(context, list) or len(context) > 300:
                raise ValueError('无效分组列表')
            for group in context:
                register(group)

            if action in ('rename', 'create'):
                group = self.group(payload.get('group'))
                if any(g['name'] == group['name'] and key != group['id'] for key, g in scope['groups'].items()):
                    raise ValueError('已有同名分组')
                if action == 'create' and group['id'] in scope['groups']:
                    raise ValueError('分组已存在')
                register(group, overwrite=True)
                if action == 'create' and payload['scope'] == 'liked' and payload.get('folder_id'):
                    if payload['folder_id'] not in {folder['id'] for folder in scope['folders']}:
                        raise ValueError('目标文件夹不存在')
                    scope['folderAssignments'][group['id']] = payload['folder_id']
            elif action in ('move', 'move_many'):
                items = [payload.get('item_id')] if action == 'move' else payload.get('ids')
                if not isinstance(items, list) or not 1 <= len(items) <= 500 or any(not isinstance(item, str) or not NOTE_ID.fullmatch(item) for item in items):
                    raise ValueError('无效内容编号')
                target_id = register(payload.get('group'))
                for item in items:
                    scope['assignments'][item] = target_id
            elif action == 'reorder':
                groups, ids = payload.get('groups'), payload.get('ids')
                if not isinstance(groups, list) or not isinstance(ids, list) or len(groups) > 300 or len(ids) != len(set(ids)):
                    raise ValueError('无效分组顺序')
                for group in groups:
                    register(group)
                if any(identity not in scope['groups'] for identity in ids):
                    raise ValueError('分组不存在')
                scope['order'] = ids + [identity for identity in scope['order'] if identity not in ids]
            elif action in ('folder_create', 'folder_rename', 'folder_delete', 'folder_assign') and payload['scope'] == 'liked':
                folders = scope['folders']
                folder_ids = {folder['id'] for folder in folders}
                if action in ('folder_create', 'folder_rename'):
                    folder = self.folder(payload.get('folder'))
                    if any(item['name'] == folder['name'] and item['id'] != folder['id'] for item in folders):
                        raise ValueError('已有同名文件夹')
                    if action == 'folder_create':
                        if folder['id'] in folder_ids or len(folders) >= 30:
                            raise ValueError('文件夹已存在或已达到30个')
                        folders.append(folder)
                    else:
                        if folder['id'] not in folder_ids:
                            raise ValueError('文件夹不存在')
                        folders[:] = [folder if item['id'] == folder['id'] else item for item in folders]
                elif action == 'folder_assign':
                    group_id, folder_id = payload.get('group_id'), payload.get('folder_id')
                    if group_id not in scope['groups'] or folder_id not in folder_ids:
                        raise ValueError('分组或目标文件夹不存在')
                    scope['folderAssignments'][group_id] = folder_id
                else:
                    folder_id, target_id = payload.get('folder_id'), payload.get('target_id')
                    if folder_id not in folder_ids or len(folders) <= 1:
                        raise ValueError('文件夹不存在或不能删除最后一个文件夹')
                    owned = [group_id for group_id, assigned in scope['folderAssignments'].items() if assigned == folder_id]
                    if owned and (target_id not in folder_ids or target_id == folder_id):
                        raise ValueError('请选择另一个文件夹接收二级分类')
                    for group_id in owned:
                        scope['folderAssignments'][group_id] = target_id
                    folders[:] = [folder for folder in folders if folder['id'] != folder_id]
            else:
                raise ValueError('不支持的分组操作')
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, filename = tempfile.mkstemp(prefix='.groups-', dir=self.path.parent)
            try:
                with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                    json.dump(state, output, ensure_ascii=False, indent=2)
                    output.write('\n')
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(filename, self.path)
            finally:
                if os.path.exists(filename):
                    os.unlink(filename)
            return state


class TrashStore:
    """Reversible, note-id-only trash state; source media is never changed."""
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / 'trash.json'
        self.lock = threading.RLock()

    def read(self):
        with self.lock:
            if not self.path.exists():
                return {'version': 1, 'liked': {}}
            state = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(state, dict) or not isinstance(state.get('liked'), dict):
                raise ValueError('回收站记录格式无效')
            return state

    def apply(self, payload):
        if not isinstance(payload, dict) or payload.get('action') not in ('trash', 'restore'):
            raise ValueError('无效回收站操作')
        ids = payload.get('ids')
        if not isinstance(ids, list) or not 1 <= len(ids) <= 500 or any(not isinstance(note_id, str) or not NOTE_ID.fullmatch(note_id) for note_id in ids):
            raise ValueError('无效笔记编号')
        with self.lock:
            state = self.read()
            for note_id in set(ids):
                if payload['action'] == 'trash':
                    if not (self.root / 'notes' / note_id / 'analysis.json').is_file():
                        raise ValueError('笔记不存在')
                    state['liked'].setdefault(note_id, {'deleted_at': datetime.now(timezone.utc).isoformat()})
                else:
                    state['liked'].pop(note_id, None)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, filename = tempfile.mkstemp(prefix='.trash-', dir=self.path.parent)
            try:
                with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                    json.dump(state, output, ensure_ascii=False, indent=2)
                    output.write('\n')
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(filename, self.path)
            finally:
                if os.path.exists(filename):
                    os.unlink(filename)
            return state


class LibraryHandler(SimpleHTTPRequestHandler):
    def send_head(self):
        """Serve local videos with byte ranges so playback can seek before download ends."""
        self._range_remaining = None
        path = urlsplit(self.path).path
        requested = self.headers.get('Range')
        if not requested or not path.lower().endswith(('.mp4', '.mov', '.m4v', '.webm')):
            return super().send_head()
        filename = self.translate_path(path)
        if not os.path.isfile(filename):
            return super().send_head()
        size = os.path.getsize(filename)
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested.strip())
        if not match or not size or (not match.group(1) and not match.group(2)):
            self.send_error(416, 'Invalid byte range')
            return None
        if match.group(1):
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else size - 1
        else:
            suffix = int(match.group(2))
            start, end = max(0, size - suffix), size - 1
        if start >= size or start > end:
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{size}')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return None
        end = min(end, size - 1)
        try:
            source = open(filename, 'rb')
        except OSError:
            self.send_error(404, 'File not found')
            return None
        source.seek(start)
        self._range_remaining = end - start + 1
        self.send_response(206)
        self.send_header('Content-Type', self.guess_type(filename))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length', str(self._range_remaining))
        self.send_header('Last-Modified', self.date_time_string(os.path.getmtime(filename)))
        self.end_headers()
        return source

    def copyfile(self, source, outputfile):
        remaining = getattr(self, '_range_remaining', None)
        if remaining is None:
            return super().copyfile(source, outputfile)
        while remaining > 0:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)

    def end_headers(self):
        path = urlsplit(self.path).path
        if path == '/' or path.endswith(('.html', '.js', '.css')):
            self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def json_response(self, value, status=200):
        data = json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/api/groups':
            try:
                return self.json_response(self.server.group_store.read())
            except (ValueError, OSError):
                return self.json_response({'error': '分组配置无法读取，请保留文件并检查格式'}, 500)
        if path == '/api/trash':
            try:
                return self.json_response(self.server.trash_store.read())
            except (ValueError, OSError):
                return self.json_response({'error': '回收站记录无法读取，请保留文件并检查格式'}, 500)
        if path in ('/latest-list.json', '/trash.json', '/group-settings.json', '/account-profile.json') or re.fullmatch(r'/notes/[0-9a-f]{24}/raw\.json', path):
            return self.json_response({'error': '私有采集记录不在网页中公开'}, 404)
        match = re.fullmatch(r'/open-note/([0-9a-f]{24})', path)
        if match:
            url = signed_note_url(self.server.group_store.path.parent, match.group(1))
            if not url:
                return self.json_response({'error': '未找到该笔记的原始访问链接'}, 404)
            self.send_response(302)
            self.send_header('Location', url)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        return super().do_GET()

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ('/api/groups', '/api/open-note', '/api/trash'):
            return self.json_response({'error': '不存在的接口'}, 404)
        expected = 'http://' + self.headers.get('Host', '')
        allowed = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
        if expected not in allowed or self.headers.get('Origin') != expected:
            return self.json_response({'error': '仅允许本机资料页保存分组'}, 403)
        if self.headers.get_content_type() != 'application/json':
            return self.json_response({'error': '需要JSON格式'}, 415)
        try:
            size = int(self.headers.get('Content-Length', 0))
            if not 0 < size <= (256 if path == '/api/open-note' else 262144):
                raise ValueError('保存内容大小无效')
            payload = json.loads(self.rfile.read(size).decode('utf-8'))
            if path == '/api/trash':
                return self.json_response(self.server.trash_store.apply(payload))
            if path == '/api/open-note':
                note_id = payload.get('note_id') if isinstance(payload, dict) else None
                if not isinstance(note_id, str) or not NOTE_ID.fullmatch(note_id):
                    raise ValueError('无效笔记编号')
                url = signed_note_url(self.server.group_store.path.parent, note_id)
                if not url:
                    return self.json_response({'error': '未找到该笔记的原始访问链接'}, 404)
                try:
                    subprocess.run(['/usr/bin/open', '-a', 'Google Chrome', url],
                                   stdin=subprocess.DEVNULL, capture_output=True,
                                   timeout=10, check=True)
                except (OSError, subprocess.SubprocessError):
                    return self.json_response({'error': 'Chrome 无法打开，请使用原笔记链接'}, 500)
                return self.json_response({'opened': True})
            return self.json_response(self.server.group_store.apply(payload))
        except (ValueError, TypeError, KeyError, UnicodeError) as error:
            return self.json_response({'error': str(error)}, 400)
        except OSError:
            return self.json_response({'error': '本机保存失败，原分组配置已保留'}, 500)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    root = args.root.resolve()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), partial(LibraryHandler, directory=str(root)))
    server.group_store = GroupStore(root)
    server.trash_store = TrashStore(root)
    print(f'Library: http://127.0.0.1:{args.port}/index.html', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
