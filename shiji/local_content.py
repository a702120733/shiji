"""Parse a user-selected Chrome bookmark export and validate local product links."""
from html.parser import HTMLParser
from urllib.parse import urlsplit
from uuid import uuid4


def safe_link(value):
    if not isinstance(value, str) or len(value) > 2048:
        return ''
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return ''
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return ''
    return value.strip()


class ChromeBookmarks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.folders = []
        self.entered = []
        self.pending_folder = None
        self.field = None
        self.buffer = []
        self.href = ''
        self.added = ''
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'h3':
            self.field, self.buffer = 'folder', []
        elif tag == 'a':
            self.field, self.buffer = 'link', []
            self.href = safe_link(attrs.get('href', ''))
            self.added = str(attrs.get('add_date', ''))[:24]
        elif tag == 'dl':
            entered = self.pending_folder is not None
            if entered:
                self.folders.append(self.pending_folder)
                self.pending_folder = None
            self.entered.append(entered)

    def handle_data(self, data):
        if self.field:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag == 'h3' and self.field == 'folder':
            self.pending_folder = ''.join(self.buffer).strip()[:120] or '未命名文件夹'
            self.field = None
        elif tag == 'a' and self.field == 'link':
            if self.href:
                path = list(self.folders)
                self.rows.append({'id': uuid4().hex, 'title': ''.join(self.buffer).strip()[:300] or self.href,
                                  'url': self.href, 'folders': path, 'added': self.added})
            self.field = None
        elif tag == 'dl' and self.entered:
            if self.entered.pop() and self.folders:
                self.folders.pop()


def parse_chrome_export(content):
    if not isinstance(content, str) or len(content.encode('utf-8')) > 10_000_000:
        raise ValueError('书签文件不能超过 10 MB')
    if 'NETSCAPE-Bookmark-file-1' not in content[:1000]:
        raise ValueError('请选择 Chrome 导出的书签 HTML 文件')
    parser = ChromeBookmarks()
    parser.feed(content)
    if not parser.rows:
        raise ValueError('文件中没有可导入的网页书签')
    if len(parser.rows) > 50_000:
        raise ValueError('单次最多导入 50000 条书签')
    return parser.rows


def validate_product(payload):
    if not isinstance(payload, dict):
        raise ValueError('产品信息格式无效')
    title = str(payload.get('title') or '').strip()[:120]
    url = safe_link(payload.get('url'))
    description = str(payload.get('description') or '').strip()[:500]
    if not title or not url:
        raise ValueError('请填写产品名称和有效的 http(s) 链接')
    return {'id': uuid4().hex, 'title': title, 'url': url, 'description': description}
