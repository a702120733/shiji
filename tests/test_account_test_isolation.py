"""A second-account import cannot silently reuse the existing account."""
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'shiji'))
from app import ImportManager


EXISTING = 'aaaaaaaaaaaaaaaaaaaaaaaa'
NEW = '1234567890abcdef12345678'


class AccountTestIsolation(unittest.TestCase):
    def test_existing_account_is_rejected_before_saving(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = ImportManager(Path(temp) / 'account-test', excluded_profile_id=EXISTING,
                                    previous_account_url='http://127.0.0.1:8765/accounts.html')
            with patch('app.shutil.which', return_value='/bin/opencli'), patch('app.install_adapter'), \
                    patch('app.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=f'[{{"profile_id":"{EXISTING}"}}]', stderr='')):
                with self.assertRaisesRegex(ValueError, '已有账号'):
                    manager.connect()
            self.assertEqual(manager.config()['profile_id'], '')
            self.assertFalse((Path(temp) / 'account-test/config.json').exists())
            self.assertTrue(manager.status()['account_test'])
            self.assertEqual(manager.status()['previous_account_url'], 'http://127.0.0.1:8765/accounts.html')

    def test_different_account_can_continue_in_separate_root(self):
        with tempfile.TemporaryDirectory() as temp:
            existing = Path(temp) / 'personal'
            existing.mkdir()
            marker = existing / 'manifest.json'
            marker.write_text('{"unchanged":true}')
            manager = ImportManager(Path(temp) / 'account-test', excluded_profile_id=EXISTING)
            with patch('app.shutil.which', return_value='/bin/opencli'), patch('app.install_adapter'), \
                    patch('app.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=f'[{{"profile_id":"{NEW}"}}]', stderr='')):
                self.assertEqual(manager.connect()['profile_id'], NEW)
            self.assertEqual(manager.config()['profile_id'], NEW)
            self.assertEqual(marker.read_text(), '{"unchanged":true}')
            (manager.root / 'liked').mkdir()
            (manager.root / 'liked/manifest.json').write_text('{"notes":{}}')
            OTHER = 'abcdef1234567890abcdef12'
            with patch('app.shutil.which', return_value='/bin/opencli'), patch('app.install_adapter'), \
                    patch('app.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=f'[{{"profile_id":"{OTHER}"}}]', stderr='')):
                with self.assertRaisesRegex(ValueError, '不能混合导入'):
                    manager.connect()
            self.assertEqual(manager.config()['profile_id'], NEW)


if __name__ == '__main__':
    unittest.main()
