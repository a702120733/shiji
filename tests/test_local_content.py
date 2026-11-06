"""Checks for private local imports and link validation."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'shiji'))
from app import ImportManager
from local_content import parse_chrome_export, safe_link


EXPORT = '''<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p><DT><H3>收藏夹栏</H3><DL><p>
<DT><H3>设计</H3><DL><p><DT><H3>灵感</H3><DL><p>
<DT><A HREF="https://example.com/design" ADD_DATE="1700000000">示例作品</A>
<DT><A HREF="javascript:alert(1)">不安全链接</A>
</DL><p></DL><p></DL><p></DL><p>'''


class LocalContentTest(unittest.TestCase):
    def test_bookmark_hierarchy_and_unsafe_link(self):
        rows = parse_chrome_export(EXPORT)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['folders'], ['收藏夹栏', '设计', '灵感'])
        self.assertEqual(rows[0]['title'], '示例作品')
        self.assertEqual(safe_link('https://[broken'), '')
        with self.assertRaises(ValueError):
            parse_chrome_export('<html><a href="https://example.com">x</a></html>')

    def test_import_and_personal_products_stay_private(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = ImportManager(Path(temp))
            self.assertEqual(manager.import_bookmarks(EXPORT)['imported'], 1)
            self.assertEqual((Path(temp) / 'bookmarks.json').stat().st_mode & 0o777, 0o600)
            product = manager.save_product({'title': '测试产品', 'url': 'https://example.com', 'description': '本地示例'})
            self.assertEqual(manager.status()['products_count'], 1)
            with self.assertRaises(ValueError):
                manager.save_product({'title': '无效', 'url': 'javascript:alert(1)'})
            manager.remove_product(product['id'])
            self.assertEqual(manager.status()['products_count'], 0)


if __name__ == '__main__':
    unittest.main()
