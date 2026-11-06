"""Render the shared library shell before the page reaches the browser."""
from pathlib import Path
import re
from typing import Optional


def wrap_shell(page: str, scope: str, liked_count: Optional[int], following_count: Optional[int], bookmarks_count: Optional[int] = None, products_count: Optional[int] = None) -> str:
    if scope not in ('liked', 'saved', 'following', 'bookmarks', 'products'):
        raise ValueError(f'Unknown library scope: {scope}')
    marker = f'<body data-library="{"liked" if scope == "saved" else scope}">'
    start = page.index('<main>', page.index(marker))
    end = page.index('</main>', start) + len('</main>')
    main = page[start:end]
    search = re.search(r'<input\b[^>]*\bid="search"[^>]*>', main)
    if not search:
        raise ValueError(f'Search input missing from {scope} page')
    main = main[:search.start()] + main[search.end():]
    shell = (Path(__file__).with_name('shiji-shell.html')).read_text(encoding='utf-8')
    if scope in ('bookmarks', 'products'):
        bookmark_current = 'aria-current="page"' if scope == 'bookmarks' else ''
        product_current = 'aria-current="page"' if scope == 'products' else ''
        function_nav = (
            f'<a href="bookmarks.html" {bookmark_current}><img src="shiji-assets/bookmark.svg" alt="" aria-hidden="true"><span>收藏夹</span><small class="shiji-bookmarks-count">{bookmarks_count or 0}</small></a>'
            f'<a href="products.html" {product_current}><img src="shiji-assets/sparkles.svg" alt="" aria-hidden="true"><span>个人产品</span><small class="shiji-products-count">{products_count or 0}</small></a>'
        )
    else:
        liked_current = 'aria-current="page"' if scope == 'liked' else ''
        saved_current = 'aria-current="page"' if scope == 'saved' else ''
        following_current = 'aria-current="page"' if scope == 'following' else ''
        function_nav = (
            '<a href="/import"><img src="shiji-assets/download.svg" alt="" aria-hidden="true"><span>导入中心</span></a>'
            f'<a href="/index.html" {liked_current}><img src="shiji-assets/heart.svg" alt="" aria-hidden="true"><span>点赞</span></a>'
            f'<a href="/saved.html" {saved_current}><img src="shiji-assets/bookmark.svg" alt="" aria-hidden="true"><span>收藏</span></a>'
            f'<a href="/following.html" {following_current}><img src="shiji-assets/users.svg" alt="" aria-hidden="true"><span>关注</span></a>'
        )
    replacements = {
        '__LIKED_CURRENT__': 'aria-current="page"' if scope == 'liked' else '',
        '__FOLLOWING_CURRENT__': 'aria-current="page"' if scope == 'following' else '',
        '__LIKED_COUNT__': str(liked_count) if liked_count is not None else '',
        '__FOLLOWING_COUNT__': str(following_count) if following_count is not None else '',
        '__PAGE_LABEL__': {'liked':'点赞资料库','saved':'收藏资料库','following':'关注资料库','bookmarks':'收藏夹','products':'个人产品'}[scope],
        '__XHS_CURRENT__': 'aria-current="page"' if scope in ('liked', 'saved', 'following') else '',
        '__CHROME_CURRENT__': 'aria-current="page"' if scope in ('bookmarks', 'products') else '',
        '__FUNCTION_NAV__': function_nav,
        '__GROUP_HEADING__': '分类' if scope == 'bookmarks' else '我的分组',
        '__GROUP_ACTION__': '<button class="shiji-folder-add" type="button" aria-label="新建文件夹" title="新建文件夹">＋</button>' if scope == 'liked' else '<small>按内容整理</small>' if scope == 'bookmarks' else '<small>可自定义</small>',
        '__GROUPS_LABEL__': '分组文件夹' if scope == 'liked' else '常用分组',
        '__GROUP_ALL__': '查看全部分类' if scope == 'bookmarks' else '查看全部分组',
        '__SEARCH_INPUT__': search.group(0),
        '__MAIN__': main,
    }
    for token, value in replacements.items():
        shell = shell.replace(token, value)
    return page[:start] + shell + page[end:]
