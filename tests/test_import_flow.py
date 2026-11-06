"""End-to-end import with a fake local OpenCLI, no user account access."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'shiji'))
from app import ImportManager


FAKE_OPENCLI = r'''#!/usr/bin/env python3
import base64, json, pathlib, sys
args = sys.argv[1:]
command = args[1] if len(args) > 1 else ''
profile = '1234567890abcdef12345678'
note = 'abcdefabcdefabcdefabcdef'
url = f'https://www.xiaohongshu.com/user/profile/{profile}/{note}?xsec_token=TEST_ONLY'
if command == 'shiji-connect':
    result = [{'profile_id': profile}]
elif command == 'shiji-list':
    result = [{'id': note, 'url': url, 'title': '测试笔记', 'author': '测试作者', 'likes': '12', 'type': '图文'}]
elif command == 'shiji-note':
    result = [{'field': 'title', 'value': '测试笔记'}, {'field': 'author', 'value': '测试作者'},
              {'field': 'content', 'value': '这是可读的测试正文'},
              {'field': 'author_url', 'value': f'https://www.xiaohongshu.com/user/profile/{profile}'}]
elif command == 'download':
    destination = pathlib.Path(args[args.index('--output') + 1]); destination.mkdir(parents=True, exist_ok=True)
    destination.joinpath('image.png').write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEklEQVR4nGM8ZOrMwMDAxAAGAA9hAT5m//PTAAAAAElFTkSuQmCC'))
    result = [{'status':'success','size':'image.png'}]
elif command == 'shiji-following':
    result = [{'sort': label, 'position': 1, 'name':'测试作者', 'description':'视觉设计',
               'avatar':'https://example.com/avatar.png', 'starred':False, 'source_count':1,
               'profile_url':f'https://www.xiaohongshu.com/user/profile/{profile}'}
              for label in ('综合排序','最新关注','最早关注')]
else:
    sys.exit('unknown command: ' + command)
print(json.dumps(result, ensure_ascii=False))
'''

FAKE_CODEX = r'''#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
context = json.loads(sys.stdin.read().split('EVIDENCE_INPUT_JSON=', 1)[1])
result = {'category':'视觉设计','subcategory':'界面','tags':['示例'],'summary':'界面示例 · 视觉结构 · 素材归档',
          'key_points':['正文提到可读的测试内容'],'takeaways':[],'limitations':[],
          'text_evidence':'正文包含可读的测试内容',
          'image_evidence':[{'path':path,'observation':'可见示例图片'} for path in context['images']],
          'frame_evidence':[{'path':path,'observation':'可见视频采样画面'} for path in context['video_frame_sheets']],
          'transcript_evidence':[{'path':item['path'],'observation':'转写包含语音内容'} for item in context['transcripts']]}
pathlib.Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(result, ensure_ascii=False))
'''


class ImportFlowTest(unittest.TestCase):
    def test_login_capture_prepare_render_preserve_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            executable = bin_dir / 'opencli'
            executable.write_text(FAKE_OPENCLI, encoding='utf-8')
            executable.chmod(0o755)
            env = {'HOME': str(root), 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'],
                   'PYTHONPYCACHEPREFIX': str(root / 'pycache')}
            with patch.dict(os.environ, env):
                manager = ImportManager(root / 'data')
                manager.save_settings({'sources': ['liked', 'saved', 'following'], 'limit': 1, 'auto_analyze': False})
                account = manager.connect()
                self.assertEqual(account['profile_id'], '1234567890abcdef12345678')
                manager.start()
                for _ in range(300):
                    if manager.status()['job']['state'] != 'running':
                        break
                    time.sleep(.1)
                status = manager.status()
                self.assertEqual(status['job']['state'], 'complete', status['job']['error'])
                self.assertEqual(status['libraries']['liked']['visible'], 1, status['job']['events'])
                self.assertEqual(status['libraries']['liked']['pending'], 1)
                self.assertEqual(status['libraries']['saved']['visible'], 1)
                self.assertEqual(status['following_count'], 1)
                self.assertEqual(status['job']['counts']['following_visible'], 1)
                self.assertTrue((root / 'data/liked/index.html').is_file())
                self.assertIn('小红书收藏资料库', (root / 'data/saved/index.html').read_text(encoding='utf-8'))
                self.assertTrue((root / 'data/liked/notes/abcdefabcdefabcdefabcdef/media/image.png').is_file())
                self.assertNotIn('TEST_ONLY', (root / 'data/liked/index.html').read_text(encoding='utf-8'))
                self.assertEqual((root / 'data/config.json').stat().st_mode & 0o777, 0o600)

    def test_auto_classification_uses_prepared_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            for name, source in (('opencli', FAKE_OPENCLI), ('codex', FAKE_CODEX)):
                executable = bin_dir / name
                executable.write_text(source, encoding='utf-8')
                executable.chmod(0o755)
            env = {'HOME': str(root), 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'],
                   'PYTHONPYCACHEPREFIX': str(root / 'pycache')}
            with patch.dict(os.environ, env):
                manager = ImportManager(root / 'data')
                manager.save_settings({'sources': ['liked'], 'limit': 1, 'auto_analyze': True})
                manager.connect()
                manager.start()
                for _ in range(300):
                    if manager.status()['job']['state'] != 'running':
                        break
                    time.sleep(.1)
                status = manager.status()
                self.assertEqual(status['job']['state'], 'complete', status['job']['error'])
                self.assertEqual(status['libraries']['liked']['pending'], 0)
                self.assertEqual(status['libraries']['liked']['categories'], {'视觉设计': 1})
                analysis = json.loads((root / 'data/liked/notes/abcdefabcdefabcdefabcdef/analysis.json').read_text())
                self.assertEqual(analysis['coverage']['status'], 'complete')
                self.assertEqual(len(analysis['coverage']['reviewed_images']), 1)

    def test_reject_empty_and_invalid_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = ImportManager(Path(temp))
            for value in ({'sources': [], 'limit': 1}, {'sources': ['liked', 'liked'], 'limit': 1},
                          {'sources': ['liked'], 'limit': 1001}, {'sources': ['secret'], 'limit': 1}):
                with self.assertRaises(ValueError):
                    manager.save_settings(value)


if __name__ == '__main__':
    unittest.main()
