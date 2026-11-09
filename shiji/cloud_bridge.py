"""Short-lived, explicit pairing for a cloud UI talking to the loopback server."""

from __future__ import annotations

import hashlib
import hmac
from html import escape
import json
import secrets
import threading
import time
from urllib.parse import urlsplit


TOKEN_LIFETIME = 12 * 60 * 60


def normalize_origin(value: str) -> str:
    """Accept one exact HTTPS origin (or an explicit loopback development origin)."""
    value = value.strip()
    if not value:
        return ''
    if any(ord(char) <= 32 or char == '\\' for char in value):
        raise ValueError('SHIJI_CLOUD_ORIGIN must be one exact HTTPS origin')
    parsed = urlsplit(value)
    loopback = parsed.hostname in ('127.0.0.1', 'localhost')
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError('SHIJI_CLOUD_ORIGIN must be one exact HTTPS origin') from exc
    if ((parsed.scheme != 'https' and not (loopback and parsed.scheme == 'http'))
            or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment
            or port == 0
            or value.rstrip('/') != f'{parsed.scheme}://{parsed.netloc}'):
        raise ValueError('SHIJI_CLOUD_ORIGIN must be one exact HTTPS origin')
    return value.rstrip('/')


class CloudBridge:
    def __init__(self, origin: str):
        self.origin = normalize_origin(origin)
        self._tokens: dict[bytes, float] = {}
        self._lock = threading.RLock()

    def issue(self) -> str:
        if not self.origin:
            raise ValueError('Cloud bridge is disabled')
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode('ascii')).digest()
        with self._lock:
            now = time.monotonic()
            self._tokens = {key: expiry for key, expiry in self._tokens.items() if expiry > now}
            if len(self._tokens) >= 8:
                oldest = min(self._tokens, key=self._tokens.get)
                del self._tokens[oldest]
            self._tokens[digest] = now + TOKEN_LIFETIME
        return token

    def accepts(self, origin: str | None, token: str | None) -> bool:
        if not self.origin or origin != self.origin or not token or len(token) > 128:
            return False
        digest = hashlib.sha256(token.encode('utf-8')).digest()
        with self._lock:
            now = time.monotonic()
            for candidate, expiry in list(self._tokens.items()):
                if expiry <= now:
                    del self._tokens[candidate]
                elif hmac.compare_digest(candidate, digest):
                    return True
        return False

    def pairing_page(self) -> bytes:
        """The user explicitly approves the exact configured origin in a local tab."""
        label = escape(self.origin)
        target = json.dumps(self.origin).replace('<', '\\u003c')
        page = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer">
<title>连接本机资料库 · 拾集</title><style>
body{{font:16px/1.6 -apple-system,BlinkMacSystemFont,sans-serif;background:#f8f7f4;color:#252522;margin:0;display:grid;min-height:100vh;place-items:center}}
main{{max-width:440px;margin:24px;padding:32px;background:#fff;border:1px solid #e8e5df;border-radius:18px}}
h1{{font-size:23px;margin:0 0 12px}}.origin{{overflow-wrap:anywhere;background:#f4f3f0;padding:10px;border-radius:8px}}
button{{border:0;background:#292925;color:#fff;padding:12px 20px;border-radius:9px;cursor:pointer;font-size:16px}}
small{{display:block;color:#777;margin-top:14px}}
</style></head><body><main><h1>连接本机资料库</h1>
<p>允许 <strong class="origin">{label}</strong> 在本次配对有效期内读取和整理这台电脑上的拾集资料。资料由浏览器直接连接本机，不会经由网站服务器传输。</p>
<button id="allow" type="button">允许连接</button><small id="result">只在你信任此网站时继续；关闭此窗口即可取消。</small>
</main><script>
const target={target};
document.getElementById('allow').addEventListener('click', async () => {{
 const button=document.getElementById('allow'); button.disabled=true;
 try {{
  if (!window.opener) throw new Error('请从网站的连接按钮打开此页面');
  const response=await fetch('/api/cloud-pair',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:'{{}}',cache:'no-store'}});
  if (!response.ok) throw new Error('本机服务拒绝配对');
  const value=await response.json();
  window.opener.postMessage({{type:'shiji-cloud-paired',token:value.token}},target);
  document.getElementById('result').textContent='已授权，可返回原窗口。';
  setTimeout(() => window.close(), 200);
 }} catch(error) {{ document.getElementById('result').textContent=error.message; button.disabled=false; }}
}});
</script></body></html>'''
        return page.encode('utf-8')
