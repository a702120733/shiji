"""Explicit, local-only selection of an existing Shiji library or ZIP package."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import stat
import subprocess
import sys
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.parse import unquote, urlsplit
import zipfile

from cloud_bridge import normalize_origin


MAX_ARCHIVE_FILES = 100_000
MAX_ARCHIVE_BYTES = 30 * 1024 ** 3
ALLOWED_EXTENSIONS = {'.html', '.css', '.js', '.svg', '.png', '.jpg', '.jpeg',
                      '.webp', '.gif', '.avif', '.ico', '.mp4', '.mov', '.m4v',
                      '.webm', '.woff', '.woff2', '.ttf', '.md', '.csv', '.txt'}
PAGE_NAMES = {'index.html': '点赞列表', 'following.html': '关注列表',
              'bookmarks.html': 'Chrome 收藏夹', 'products.html': '个人产品',
              'accounts.html': '账号设置'}
NOTE_ID = re.compile(r'[0-9a-f]{24}', re.I)


def _read_count(path: Path) -> int:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return max(0, int(value.get('visible', 0)))
    except (OSError, ValueError, TypeError, AttributeError):
        return 0


def inspect_folder(folder: Path) -> dict:
    """Recognize both the earlier flat library and current liked/saved layout."""
    folder = folder.expanduser().resolve(strict=True)
    if not folder.is_dir():
        raise ValueError('请选择资料文件夹')
    def note_directory(parent):
        return parent.is_dir() and any(NOTE_ID.fullmatch(item.name) for item in parent.iterdir() if item.is_dir())

    flat = ((folder / 'render-status.json').is_file() or
            ((folder / 'manifest.json').is_file() and note_directory(folder / 'notes')) or
            note_directory(folder / 'notes'))
    pages = []
    companion = {
        'index.html': flat,
        'following.html': flat or (folder / 'following.json').is_file() or (folder / 'following-list.json').is_file(),
        'bookmarks.html': flat or (folder / 'chrome-bookmarks.json').is_file() or (folder / 'bookmarks.json').is_file(),
        'products.html': flat or (folder / 'personal-products.json').is_file() or (folder / 'products.json').is_file(),
        'accounts.html': flat or (folder / 'account-profile.json').is_file(),
    }
    for name, label in PAGE_NAMES.items():
        page = folder / name
        if companion[name] and page.is_file() and page.resolve().is_relative_to(folder):
            pages.append({'label': label, 'path': '/' + name})
    for name, label in (('liked', '点赞列表'), ('saved', '收藏列表')):
        page = folder / name / 'index.html'
        source = folder / name
        valid = (source / 'render-status.json').is_file() or note_directory(source / 'notes')
        if valid and page.is_file() and page.resolve().is_relative_to(folder):
            pages.append({'label': label, 'path': f'/{name}/index.html'})
    if not pages:
        raise ValueError('所选文件夹没有可识别的拾集资料页面与数据标记')
    counts = [_read_count(folder / 'render-status.json'),
              _read_count(folder / 'liked' / 'render-status.json'),
              _read_count(folder / 'saved' / 'render-status.json')]
    items = sum(counts)
    if not items:
        notes = folder / 'notes'
        if notes.is_dir():
            items = sum(bool(re.fullmatch(r'[0-9a-f]{24}', item.name, re.I)) for item in notes.iterdir() if item.is_dir())
    return {'path': str(folder), 'kind': 'folder', 'pages': pages, 'items': items}


def _archive_members(package: Path) -> tuple[list[zipfile.ZipInfo], int]:
    if package.suffix.lower() != '.zip' or not zipfile.is_zipfile(package):
        raise ValueError('请选择有效的 ZIP 资料包')
    members = []
    total = 0
    seen = set()
    with zipfile.ZipFile(package) as archive:
        for info in archive.infolist():
            name = info.filename
            parts = PurePosixPath(name).parts
            mode = (info.external_attr >> 16) & 0xFFFF
            if (not name or name.startswith('/') or '\\' in name or '\x00' in name
                    or any(part in ('', '.', '..') for part in parts)
                    or any(':' in part for part in parts)
                    or (mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))
                    or info.flag_bits & 0x1):
                raise ValueError('资料包包含不安全的文件路径或链接')
            key = '/'.join(parts).casefold()
            if key in seen:
                raise ValueError('资料包包含重复文件路径')
            seen.add(key)
            if info.is_dir():
                continue
            members.append(info)
            total += info.file_size
            if len(members) > MAX_ARCHIVE_FILES or total > MAX_ARCHIVE_BYTES:
                raise ValueError('资料包超过本机导入上限')
    if not _package_preview(members):
        raise ValueError('资料包没有可识别的拾集资料页面与数据标记')
    return members, total


def _package_preview(members):
    files = {PurePosixPath(item.filename).as_posix() for item in members}
    prefixes = [''] + sorted({name.split('/', 1)[0] + '/' for name in files if '/' in name})
    best = None
    for prefix in prefixes:
        relative = {name[len(prefix):] for name in files if name.startswith(prefix)}
        if not relative:
            continue
        note_roots = set()
        for name in relative:
            parts = PurePosixPath(name).parts
            if len(parts) >= 3 and parts[0] == 'notes' and NOTE_ID.fullmatch(parts[1]):
                note_roots.add(('flat', parts[1]))
            elif (len(parts) >= 4 and parts[0] in ('liked', 'saved')
                  and parts[1] == 'notes' and NOTE_ID.fullmatch(parts[2])):
                note_roots.add((parts[0], parts[2]))
        flat = 'render-status.json' in relative or any(source == 'flat' for source, _ in note_roots)
        pages = []
        companions = {
            'index.html': flat,
            'following.html': flat or 'following.json' in relative or 'following-list.json' in relative,
            'bookmarks.html': flat or 'chrome-bookmarks.json' in relative or 'bookmarks.json' in relative,
            'products.html': flat or 'personal-products.json' in relative or 'products.json' in relative,
            'accounts.html': flat or 'account-profile.json' in relative,
        }
        for name, label in PAGE_NAMES.items():
            if name in relative and companions[name]:
                pages.append({'label': label, 'path': '/' + name})
        for name, label in (('liked', '点赞列表'), ('saved', '收藏列表')):
            note_files = any(source == name for source, _ in note_roots)
            if f'{name}/index.html' in relative and (f'{name}/render-status.json' in relative or note_files):
                pages.append({'label': label, 'path': f'/{name}/index.html'})
        if pages and (best is None or len(pages) > len(best['pages'])):
            best = {'prefix': prefix, 'pages': pages, 'items': len(note_roots)}
    return best


def inspect_package(package: Path) -> dict:
    package = package.expanduser().resolve(strict=True)
    if not package.is_file():
        raise ValueError('请选择 ZIP 资料包')
    members, total = _archive_members(package)
    preview = _package_preview(members)
    return {'path': str(package), 'kind': 'package', 'pages': preview['pages'],
            'items': preview['items'], 'total_bytes': total}


def _viewer_handler(base_handler, folder: Path, first_page: str, import_url: str):
    root = folder.resolve(strict=True)

    class ReadOnlyViewer(base_handler):
        def _allowed(self):
            parsed = urlsplit(self.path)
            path = unquote(parsed.path)
            if path in ('/api/groups', '/api/trash') or re.fullmatch(r'/open-note/[0-9a-f]{24}', path, re.I):
                return True
            parts = PurePosixPath(path).parts
            return (path.startswith('/') and '\\' not in path and '\x00' not in path
                    and not any(part == '..' or part.startswith('.') for part in parts)
                    and Path(path).suffix.lower() in ALLOWED_EXTENSIONS)

        def translate_path(self, path):
            raw = unquote(urlsplit(path).path)
            if '\\' in raw or '\x00' in raw or any(part == '..' for part in PurePosixPath(raw).parts):
                return str(root / '__not_found__')
            target = (root / raw.lstrip('/')).resolve(strict=False)
            if not target.is_relative_to(root):
                return str(root / '__not_found__')
            return str(target)

        def _valid_host(self):
            return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}',
                                                f'localhost:{self.server.server_port}')

        def do_GET(self):
            if not self._valid_host():
                return self.send_error(403, 'Local access only')
            if urlsplit(self.path).path == '/import' and import_url:
                self.send_response(302)
                self.send_header('Location', import_url)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            if urlsplit(self.path).path == '/':
                self.send_response(302)
                self.send_header('Location', first_page)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            if not self._allowed():
                return self.send_error(404, 'Not found')
            if urlsplit(self.path).path in ('/api/groups', '/api/trash'):
                store = self.server.group_store if urlsplit(self.path).path == '/api/groups' else self.server.trash_store
                if not store.path.resolve(strict=False).is_relative_to(root):
                    return self.send_error(404, 'Not found')
            return super().do_GET()

        def do_HEAD(self):
            if not self._valid_host() or not self._allowed():
                return self.send_error(404, 'Not found')
            return super().do_HEAD()

        def do_POST(self):
            return self.send_error(405, 'Read only')

        do_PUT = do_DELETE = do_PATCH = do_POST

        def end_headers(self):
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'no-store')
            super().end_headers()

    return ReadOnlyViewer


class LocalLibraryManager:
    def __init__(self, data_root: Path, base_handler, group_store, trash_store, demo_mode=False):
        self.root = data_root.resolve()
        self.base_handler = base_handler
        self.group_store = group_store
        self.trash_store = trash_store
        self.demo_mode = demo_mode
        self.lock = threading.RLock()
        self.selection = None
        self.attached = None
        self.viewer = None
        self.viewer_thread = None
        self.import_url = ''
        self.job = {'state': 'idle', 'phase': '', 'processed': 0, 'total': 0, 'error': '', 'url': ''}

    def set_import_entry(self, cloud_origin: str, main_port: int):
        """Only the local server supplies these trusted values, never the browser."""
        if not isinstance(main_port, int) or not 1 <= main_port <= 65535:
            raise ValueError('本机端口无效')
        if cloud_origin:
            cloud_origin = normalize_origin(cloud_origin)
        with self.lock:
            self.import_url = (cloud_origin if cloud_origin else f'http://127.0.0.1:{main_port}') + '/import'

    def status(self):
        try:
            configured = inspect_folder(self.root)
        except (OSError, ValueError):
            configured = {'path': str(self.root), 'kind': 'folder', 'pages': [], 'items': 0}
        with self.lock:
            return {'data_root': str(self.root), 'demo_mode': self.demo_mode,
                    'configured': configured, 'attached': dict(self.attached) if self.attached else None,
                    'job': dict(self.job)}

    @staticmethod
    def _pick(kind):
        if sys.platform != 'darwin' or not Path('/usr/bin/osascript').is_file():
            raise ValueError('当前系统不支持原生选择器，请在 macOS 上使用')
        expression = ('POSIX path of (choose folder with prompt "选择拾集资料文件夹")'
                      if kind == 'folder' else
                      'POSIX path of (choose file with prompt "选择拾集 ZIP 资料包")')
        try:
            result = subprocess.run(['/usr/bin/osascript', '-e', expression],
                                    capture_output=True, text=True, timeout=180, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError('本机文件选择器未能打开') from exc
        if result.returncode:
            if 'User canceled' in result.stderr or '用户已取消' in result.stderr or '-128' in result.stderr:
                raise ValueError('已取消选择')
            raise ValueError('本机文件选择器未能打开')
        return Path(result.stdout.strip())

    def choose(self, kind):
        if kind not in ('folder', 'package'):
            raise ValueError('请选择资料文件夹或 ZIP 资料包')
        path = self._pick(kind)
        try:
            details = inspect_folder(path) if kind == 'folder' else inspect_package(path)
        except OSError as exc:
            raise ValueError('所选资料无法读取') from exc
        with self.lock:
            token = secrets.token_urlsafe(32)
            self.selection = {'token': token, **details}
        return {'selection': token, **details}

    def _mount(self, details):
        path = Path(details['path'])
        first_page = details['pages'][0]['path']
        handler = _viewer_handler(self.base_handler, path, first_page, self.import_url)
        try:
            server = ThreadingHTTPServer(('127.0.0.1', 0), partial(handler, directory=str(path)))
        except OSError as exc:
            raise RuntimeError('本机资料页无法启动') from exc
        group_root = path / 'liked' if (path / 'liked' / 'index.html').is_file() else path
        server.group_store = self.group_store(group_root)
        server.trash_store = self.trash_store(group_root)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}{first_page}'
        old = None
        with self.lock:
            old = self.viewer
            self.viewer, self.viewer_thread = server, thread
            self.attached = {**details, 'url': url}
            self.job = {'state': 'ready', 'phase': '资料已就绪', 'processed': details.get('items', 0),
                        'total': details.get('items', 0), 'error': '', 'url': url}
        if old:
            threading.Thread(target=lambda: (old.shutdown(), old.server_close()), daemon=True).start()
        return {'state': 'ready', 'url': url}

    def open(self, payload):
        if payload.get('source') == 'configured':
            details = inspect_folder(self.root)
            return self._mount(details)
        token = payload.get('selection')
        with self.lock:
            selected = dict(self.selection) if self.selection and self.selection['token'] == token else None
        if not selected:
            raise ValueError('选择已失效，请重新选择资料')
        selected.pop('token')
        if selected['kind'] == 'folder':
            details = inspect_folder(Path(selected['path']))
            return self._mount(details)
        package = Path(selected['path'])
        members, total = _archive_members(package)
        with self.lock:
            if self.job['state'] == 'extracting':
                raise ValueError('已有资料包正在读取')
            self.job = {'state': 'extracting', 'phase': '正在读取资料包', 'processed': 0,
                        'total': total, 'error': '', 'url': ''}
        threading.Thread(target=self._extract, args=(package, members, total), daemon=True).start()
        return {'state': 'extracting'}

    def _extract(self, package, members, total):
        target_base = self.root / 'reader-packages'
        identifier = secrets.token_hex(12)
        staging = target_base / ('.tmp-' + identifier)
        final = target_base / identifier
        try:
            target_base.mkdir(parents=True, exist_ok=True, mode=0o700)
            if shutil.disk_usage(target_base).free < total + 256 * 1024 ** 2:
                raise ValueError('本机可用空间不足，建议改为选择原资料文件夹')
            staging.mkdir(mode=0o700)
            with zipfile.ZipFile(package) as archive:
                for member in members:
                    dest = staging.joinpath(*PurePosixPath(member.filename).parts)
                    if not dest.resolve(strict=False).is_relative_to(staging):
                        raise ValueError('资料包包含不安全的文件路径')
                    dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    with archive.open(member) as source, dest.open('xb') as output:
                        while chunk := source.read(1024 * 1024):
                            output.write(chunk)
                            with self.lock:
                                self.job['processed'] += len(chunk)
                    dest.chmod(0o600)
            preview = _package_preview(members)
            if not preview:
                raise ValueError('解包后没有找到拾集资料页面')
            relative = Path(preview['prefix'])
            os.replace(staging, final)
            details = inspect_folder(final / relative)
            details['kind'] = 'package'
            self._mount(details)
        except Exception as exc:
            with self.lock:
                self.job.update(state='failed', phase='读取资料包失败', error=str(exc), url='')
            if final.exists():
                shutil.rmtree(final, ignore_errors=True)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    def close(self):
        with self.lock:
            server, thread = self.viewer, self.viewer_thread
            self.viewer, self.viewer_thread = None, None
        if server:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
