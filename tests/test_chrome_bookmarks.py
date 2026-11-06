"""Chrome's native bookmark JSON can be imported without a manual export."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'shiji'))
from app import ImportManager
from chrome_bookmarks import current_profile, read_bookmarks


class ChromeNativeBookmarksTest(unittest.TestCase):
    def test_authorize_sync_and_preserve_on_invalid_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            chrome = root / 'Chrome'
            profile = chrome / 'Profile 1'
            profile.mkdir(parents=True)
            (chrome / 'Local State').write_text(json.dumps({'profile': {'last_used': 'Profile 1',
                                                             'info_cache': {'Profile 1': {}}}}))
            source = {'roots': {'bookmark_bar': {'children': [
                {'type': 'folder', 'name': '设计', 'children': [
                    {'type': 'url', 'id': '42', 'name': '作品', 'url': 'https://example.com/design',
                     'date_added': '13344473600000000'},
                    {'type': 'url', 'id': '43', 'name': '脚本', 'url': 'javascript:alert(1)'}]}]},
                'other': {'children': []}}}
            path = profile / 'Bookmarks'
            path.write_text(json.dumps(source))
            with patch.dict(os.environ, {'SHIJI_CHROME_USER_DATA_DIR': str(chrome)}):
                self.assertEqual(current_profile(), 'Profile 1')
                parsed = read_bookmarks('Profile 1')
                self.assertEqual(len(parsed['rows']), 1)
                self.assertEqual(parsed['skipped'], 1)
                self.assertEqual(parsed['rows'][0]['folders'], ['书签栏', '设计'])
                manager = ImportManager(root / 'data')
                self.assertFalse(manager.bookmarks_access()['authorized'])
                self.assertEqual(manager.sync_chrome_bookmarks(authorize=True)['imported'], 1)
                self.assertTrue(manager.bookmarks_access()['authorized'])
                self.assertTrue(manager.sync_chrome_bookmarks()['unchanged'])
                self.assertEqual((root / 'data/bookmarks-access.json').stat().st_mode & 0o777, 0o600)
                saved = (root / 'data/bookmarks.json').read_bytes()
                path.write_text('{bad json')
                with self.assertRaises(ValueError):
                    manager.sync_chrome_bookmarks()
                self.assertEqual((root / 'data/bookmarks.json').read_bytes(), saved)
                with self.assertRaises(ValueError):
                    read_bookmarks('../Default')


if __name__ == '__main__':
    unittest.main()
