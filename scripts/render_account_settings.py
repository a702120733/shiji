#!/usr/bin/env python3
"""Render a local account settings page from a verified, private profile record."""
import argparse
from html import escape
import json
from pathlib import Path
import re
from urllib.parse import urlsplit


def render(root: Path, new_account_url: str):
    root = root.resolve()
    profile = json.loads((root / 'account-profile.json').read_text(encoding='utf-8'))
    profile_id = str(profile.get('profile_id', ''))
    if not re.fullmatch(r'[0-9a-f]{24}', profile_id, re.I):
        raise ValueError('账号主页 ID 无效')
    profile_url = f'https://www.xiaohongshu.com/user/profile/{profile_id}'
    avatar = profile.get('avatar', '')
    if avatar not in ('account-avatar.webp', 'account-avatar.jpg') or not (root / avatar).is_file():
        raise ValueError('本机头像尚未保存')
    target = urlsplit(new_account_url)
    if target.scheme != 'http' or target.hostname not in ('127.0.0.1', 'localhost') or target.path != '/import':
        raise ValueError('新账号流程必须是本机 /import 页面')
    name = escape(str(profile.get('name') or '昵称待核实'))
    verified = escape(str(profile.get('verified_at') or '待核实'))
    new_url = escape(new_account_url, quote=True)
    html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><title>账号设置 · 拾集</title><link rel="stylesheet" href="shiji-theme.css"><link rel="stylesheet" href="account-settings.css"></head>
<body data-library="accounts"><div class="shiji-shell"><aside class="shiji-sidebar" aria-label="资料库导航"><a class="shiji-brand" href="index.html"><span class="shiji-mark"><img src="shiji-assets/bookmark.svg" alt=""></span><strong>拾集</strong><small>SHIJI</small></a><nav class="shiji-platforms" aria-label="内容平台"><a href="bookmarks.html"><span class="shiji-platform-icon chrome">C</span>Chrome</a><a href="index.html" aria-current="page"><span class="shiji-platform-icon xhs">小</span>小红书</a></nav><nav class="shiji-nav" aria-label="平台功能"><a href="index.html"><img src="shiji-assets/heart.svg" alt=""><span>点赞</span></a><a href="following.html"><img src="shiji-assets/users.svg" alt=""><span>关注</span></a><a href="index.html?view=trash"><img src="shiji-assets/trash.svg" alt=""><span>回收站</span></a></nav><div class="shiji-sidebar-spacer"></div><a class="shiji-account-link" href="accounts.html" aria-current="page" aria-label="{name} · 账号设置"><img class="shiji-account-avatar" src="{escape(avatar, quote=True)}" alt=""><span class="shiji-account-copy"><strong class="shiji-account-name">{name}</strong><small>账号设置</small></span><span class="shiji-account-arrow" aria-hidden="true">›</span></a></aside>
<div class="shiji-workspace"><div class="shiji-topbar"><div class="shiji-breadcrumb"><span>我的空间</span><img src="shiji-assets/chevron.svg" alt=""><strong>账号设置</strong></div></div><main class="account-page"><header class="account-heading"><h1>账号设置</h1><p>查看当前资料库对应的小红书账号，或为另一个账号开始独立导入。</p></header>
<section class="account-panel" aria-label="当前账号"><div class="account-row"><img class="account-avatar" src="{escape(avatar, quote=True)}" alt="{name}的头像"><div class="account-name"><span class="account-status">已核实主页</span><h2>{name}</h2><p>小红书账号 · {escape(profile_id)}</p></div></div><dl class="account-meta"><div><dt>主页来源</dt><dd>小红书本人主页 · {verified}</dd></div><div><dt>资料库</dt><dd>当前本机资料库</dd></div></dl><div class="account-actions"><a class="account-action" href="{profile_url}" target="_blank" rel="noreferrer">打开小红书主页 ↗</a></div></section>
<section class="account-panel" aria-label="添加账号"><h2 class="section-title">添加账号</h2><p class="note">在 Chrome 中切换到另一个小红书账号后，进入新的授权导入流程。新账号的数据保存在单独的测试目录；若仍登录当前账号，验证会拒绝继续。</p><div class="account-actions"><a class="account-action primary" href="{new_url}">＋ 添加账号并开始授权 →</a></div></section></main></div></div></body></html>'''
    (root / 'accounts.html').write_text(html, encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--new-account-url', default='http://127.0.0.1:8880/import')
    args = parser.parse_args()
    render(args.root, args.new_account_url)
