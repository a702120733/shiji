"""Selected local archives stay on-device and are served read-only."""

import http.client
import json
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'shiji'))
from app import AppHandler, ImportManager, library_server
from cloud_bridge import CloudBridge
from local_library import LocalLibraryManager, inspect_package


CLOUD = 'https://example.vercel.app'


class LocalLibraryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.manager = LocalLibraryManager(self.data, library_server.LibraryHandler,
                                           library_server.GroupStore, library_server.TrashStore)

    def tearDown(self):
        self.manager.close()
        self.temp.cleanup()

    def test_configured_folder_read_only_and_video_seek(self):
        liked = self.data / 'liked'
        liked.mkdir()
        (liked / 'index.html').write_text('<title>My library</title>')
        (liked / 'render-status.json').write_text('{"visible": 3}')
        (liked / 'sample.mp4').write_bytes(b'0123456789')
        secret = self.root / 'secret.txt'
        secret.write_text('outside')
        (liked / 'escape.txt').symlink_to(secret)
        status = self.manager.status()
        self.assertEqual(status['configured']['items'], 3)
        self.assertEqual(status['configured']['pages'][0]['path'], '/liked/index.html')
        self.manager.set_import_entry(CLOUD, 8879)
        result = self.manager.open({'source': 'configured'})
        self.assertEqual(result['state'], 'ready')
        self.assertIn('My library', urlopen(result['url']).read().decode())
        base = result['url'].split('/liked/', 1)[0]
        video = urlopen(Request(base + '/liked/sample.mp4', headers={'Range': 'bytes=2-5'}))
        self.assertEqual(video.status, 206)
        self.assertEqual(video.read(), b'2345')
        for path in ('/liked/render-status.json', '/liked/escape.txt', '/liked/../secret.txt'):
            with self.assertRaises(HTTPError) as caught:
                urlopen(base + path)
            self.assertEqual(caught.exception.code, 404)
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(base + '/api/groups', data=b'{}', method='POST'))
        self.assertEqual(caught.exception.code, 405)
        conn = http.client.HTTPConnection('127.0.0.1', self.manager.viewer.server_port, timeout=5)
        conn.request('GET', '/import')
        redirect = conn.getresponse()
        self.assertEqual(redirect.status, 302)
        self.assertEqual(redirect.getheader('Location'), CLOUD + '/import')
        redirect.read()
        conn.close()
        self.manager.set_import_entry('', 8879)
        self.manager.open({'source': 'configured'})
        conn = http.client.HTTPConnection('127.0.0.1', self.manager.viewer.server_port, timeout=5)
        conn.request('GET', '/import')
        redirect = conn.getresponse()
        self.assertEqual(redirect.getheader('Location'), 'http://127.0.0.1:8879/import')
        redirect.read()
        conn.close()
        with self.assertRaises(ValueError):
            self.manager.set_import_entry('https://evil.example/path', 8879)

    def test_selection_token_and_zip_validation(self):
        legacy = self.root / 'legacy'
        legacy.mkdir()
        (legacy / 'index.html').write_text('<title>Legacy</title>')
        (legacy / 'render-status.json').write_text('{"visible": 1}')
        with patch.object(LocalLibraryManager, '_pick', return_value=legacy):
            chosen = self.manager.choose('folder')
        self.assertEqual(chosen['path'], str(legacy.resolve()))
        self.assertGreater(len(chosen['selection']), 30)
        with self.assertRaisesRegex(ValueError, '失效'):
            self.manager.open({'selection': str(legacy)})
        result = self.manager.open({'selection': chosen['selection']})
        self.assertIn('Legacy', urlopen(result['url']).read().decode())
        unsafe = self.root / 'unsafe.zip'
        with zipfile.ZipFile(unsafe, 'w') as archive:
            archive.writestr('index.html', '<title>Bad</title>')
            archive.writestr('../outside.txt', 'escape')
        with self.assertRaisesRegex(ValueError, '不安全'):
            inspect_package(unsafe)
        with patch.object(LocalLibraryManager, '_pick', return_value=unsafe):
            with self.assertRaisesRegex(ValueError, '不安全'):
                self.manager.choose('package')
        unrelated = self.root / 'unrelated.zip'
        with zipfile.ZipFile(unrelated, 'w') as archive:
            archive.writestr('site/blog/index.html', '<title>Blog</title>')
        with self.assertRaisesRegex(ValueError, '数据标记'):
            inspect_package(unrelated)

    def test_zip_extract_reports_progress_and_opens(self):
        package = self.root / 'library.zip'
        with zipfile.ZipFile(package, 'w') as archive:
            archive.writestr('export/index.html', '<title>Package</title>')
            archive.writestr('export/render-status.json', '{"visible": 1}')
            archive.writestr('export/notes/abc.txt', 'saved on this device')
        with patch.object(LocalLibraryManager, '_pick', return_value=package):
            chosen = self.manager.choose('package')
        self.assertEqual(chosen['pages'], [{'label': '点赞列表', 'path': '/index.html'}])
        self.assertEqual(self.manager.open({'selection': chosen['selection']})['state'], 'extracting')
        for _ in range(100):
            job = self.manager.status()['job']
            if job['state'] != 'extracting':
                break
            time.sleep(.03)
        self.assertEqual(job['state'], 'ready', job['error'])
        self.assertIn('Package', urlopen(job['url']).read().decode())
        self.assertTrue((self.data / 'reader-packages').exists())

    def test_demo_only_reads_personal_folder_after_explicit_selection(self):
        personal = self.root / 'personal'
        personal.mkdir()
        (personal / 'index.html').write_text('<title>Personal</title>')
        (personal / 'render-status.json').write_text('{"visible": 5}')
        demo = LocalLibraryManager(self.data, library_server.LibraryHandler,
                                   library_server.GroupStore, library_server.TrashStore, demo_mode=True)
        self.assertEqual(demo.status()['configured']['pages'], [])
        self.assertIsNone(demo.status()['attached'])
        with patch.object(LocalLibraryManager, '_pick', return_value=personal):
            chosen = demo.choose('folder')
        opened = demo.open({'selection': chosen['selection']})
        self.assertIn('Personal', urlopen(opened['url']).read().decode())
        self.assertEqual(demo.root, self.data.resolve())
        self.assertEqual(demo.status()['configured']['pages'], [])
        demo.close()


class LocalLibraryApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'data'
        self.manager = ImportManager(self.root)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(AppHandler, directory=str(self.root)))
        self.server.import_manager = self.manager
        self.server.group_store = library_server.GroupStore(self.root / 'liked')
        self.server.trash_store = library_server.TrashStore(self.root / 'liked')
        self.server.cloud_bridge = CloudBridge(CLOUD)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.manager.local_library.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, method, path, headers=None, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        result = response.status, json.loads(response.read())
        conn.close()
        return result

    def test_cloud_auth_and_folder_picker_endpoint(self):
        self.assertEqual(self.request('GET', '/api/local-library/status', {'Origin': CLOUD})[0], 403)
        payload = json.dumps({'kind': 'folder'}).encode()
        self.assertEqual(self.request('POST', '/api/local-library/choose',
                                      {'Origin': CLOUD, 'Content-Type': 'application/json'}, payload)[0], 403)
        local_origin = f'http://127.0.0.1:{self.server.server_port}'
        _, paired = self.request('POST', '/api/cloud-pair',
                                 {'Origin': local_origin, 'Content-Type': 'application/json'}, b'{}')
        headers = {'Origin': CLOUD, 'X-Shiji-Token': paired['token'], 'Content-Type': 'application/json'}
        code, value = self.request('GET', '/api/local-library/status', headers)
        self.assertEqual(code, 200)
        self.assertEqual(value['configured']['pages'], [])
        with patch.object(LocalLibraryManager, '_pick', return_value=self.root):
            self.assertEqual(self.request('POST', '/api/local-library/choose', headers, payload)[0], 400)
        (self.root / 'index.html').write_text('<title>Local</title>')
        (self.root / 'render-status.json').write_text('{"visible": 1}')
        with patch.object(LocalLibraryManager, '_pick', return_value=self.root):
            code, chosen = self.request('POST', '/api/local-library/choose', headers, payload)
        self.assertEqual(code, 200)
        code, opened = self.request('POST', '/api/local-library/open', headers,
                                    json.dumps({'selection': chosen['selection']}).encode())
        self.assertEqual(code, 200)
        self.assertEqual(opened['state'], 'ready')
        self.assertIn('Local', urlopen(opened['url']).read().decode())


if __name__ == '__main__':
    unittest.main()
