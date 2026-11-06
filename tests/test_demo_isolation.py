"""The local UI test mode cannot read either personal account source."""
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'shiji'))
from app import ImportManager


class DemoIsolationTest(unittest.TestCase):
    def test_demo_uses_only_its_own_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            personal = root / 'personal'
            personal.mkdir()
            marker = personal / 'bookmarks.json'
            marker.write_text('[{"title":"personal"}]', encoding='utf-8')
            demo = ImportManager(root / 'demo', demo_mode=True)
            self.assertEqual(demo.status()['bookmarks_count'], 0)
            self.assertTrue(demo.status()['demo_mode'])
            with patch('app.current_profile', side_effect=AssertionError('real Chrome accessed')):
                with self.assertRaisesRegex(ValueError, '测试环境'):
                    demo.sync_chrome_bookmarks(authorize=True)
            with self.assertRaisesRegex(ValueError, '测试环境'):
                demo.import_bookmarks('<!doctype html>')
            demo.save_settings({'sources': ['liked', 'following'], 'limit': 2, 'auto_analyze': True})
            with patch('app.shutil.which', side_effect=AssertionError('real CLI accessed')):
                self.assertEqual(demo.connect()['profile_id'], '0' * 24)
                demo.start()
            for _ in range(30):
                if demo.status()['job']['state'] != 'running':
                    break
                time.sleep(0.05)
            self.assertEqual(demo.status()['job']['state'], 'complete')
            self.assertEqual(demo.status()['libraries']['liked']['visible'], 0)
            self.assertEqual(marker.read_text(encoding='utf-8'), '[{"title":"personal"}]')


if __name__ == '__main__':
    unittest.main()
