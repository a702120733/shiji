"""Read the current macOS Chrome profile's local bookmarks after user consent."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from local_content import safe_link


PROFILE_NAME = re.compile(r'(?:Default|Profile [1-9][0-9]*)\Z')
MAX_FILE_BYTES = 20_000_000
MAX_BOOKMARKS = 50_000
ROOT_LABELS = {'bookmark_bar': '书签栏', 'other': '其他书签', 'synced': '移动设备书签'}


def chrome_root():
    override = os.environ.get('SHIJI_CHROME_USER_DATA_DIR')
    return Path(override) if override else Path.home() / 'Library/Application Support/Google/Chrome'


def _read_json(path: Path, max_bytes: int):
    if not path.is_file() or path.stat().st_size > max_bytes:
        raise ValueError('Chrome 书签文件不存在或过大')
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Chrome 书签文件暂时无法读取，请稍后重试') from exc


def _profile_path(root: Path, profile: str):
    if not isinstance(profile, str) or not PROFILE_NAME.fullmatch(profile):
        raise ValueError('Chrome 配置名称无效')
    root = root.resolve()
    directory = root / profile
    if directory.resolve().parent != root or not directory.is_dir():
        raise ValueError('未找到当前 Chrome 配置')
    path = directory / 'Bookmarks'
    if path.resolve().parent != directory.resolve() or not path.is_file():
        raise ValueError('未找到当前 Chrome 配置的书签')
    return path


def current_profile(root: Path | None = None):
    root = chrome_root() if root is None else root
    state = _read_json(root / 'Local State', 2_000_000)
    details = state.get('profile', {}) if isinstance(state, dict) else {}
    if not isinstance(details, dict):
        raise ValueError('Chrome 当前配置无法确认')
    profile = details.get('last_used')
    info_cache = details.get('info_cache', {})
    if not isinstance(info_cache, dict) or profile not in info_cache:
        raise ValueError('Chrome 当前配置无法确认')
    _profile_path(root, profile)
    return profile


def _added(value):
    try:
        micros = int(value)
        seconds = micros / 1_000_000 - 11644473600
        datetime.fromtimestamp(seconds, timezone.utc)
        return str(int(seconds))
    except (TypeError, ValueError, OverflowError, OSError):
        return ''


def read_bookmarks(profile: str, root: Path | None = None):
    root = chrome_root() if root is None else root
    path = _profile_path(root, profile)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('Chrome 书签文件超过 20 MB')
    source = path.read_bytes()
    if len(source) > MAX_FILE_BYTES:
        raise ValueError('Chrome 书签文件超过 20 MB')
    try:
        data = json.loads(source)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Chrome 书签文件暂时无法读取，请稍后重试') from exc
    roots = data.get('roots') if isinstance(data, dict) else None
    if not isinstance(roots, dict):
        raise ValueError('Chrome 书签结构无效')
    rows = []
    skipped = 0

    def visit(node, folders, depth):
        nonlocal skipped
        if depth > 64 or not isinstance(node, dict):
            raise ValueError('Chrome 书签层级无效')
        kind = node.get('type')
        if kind == 'url':
            url = safe_link(node.get('url'))
            if not url:
                skipped += 1
                return
            node_id = str(node.get('id') or f'{len(rows)}:{url}')
            stable_id = hashlib.sha256(f'{profile}:{node_id}'.encode()).hexdigest()[:32]
            rows.append({'id': stable_id, 'title': str(node.get('name') or url).strip()[:300] or url,
                         'url': url, 'folders': folders, 'added': _added(node.get('date_added'))})
            if len(rows) > MAX_BOOKMARKS:
                raise ValueError('单次最多导入 50000 条书签')
        elif kind == 'folder':
            name = str(node.get('name') or '').strip()[:120] or '未命名文件夹'
            children = node.get('children', [])
            if not isinstance(children, list):
                raise ValueError('Chrome 书签层级无效')
            for child in children:
                visit(child, [*folders, name], depth + 1)

    for key, label in ROOT_LABELS.items():
        node = roots.get(key)
        if isinstance(node, dict):
            children = node.get('children', [])
            if not isinstance(children, list):
                raise ValueError('Chrome 书签层级无效')
            for child in children:
                visit(child, [label], 1)
    if not rows:
        raise ValueError('Chrome 当前配置没有可导入的网页书签')
    return {'rows': rows, 'skipped': skipped, 'fingerprint': hashlib.sha256(source).hexdigest()}
