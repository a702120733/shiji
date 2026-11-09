"""The public UI must never read a local library before explicit local pairing."""

import http.client
import json
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'shiji'))
from app import AppHandler, ImportManager, library_server
from cloud_bridge import CloudBridge, normalize_origin


CLOUD = 'https://example.vercel.app'


class CloudBridgeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name) / 'data'
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(AppHandler, directory=str(root)))
        self.server.import_manager = ImportManager(root)
        self.server.group_store = library_server.GroupStore(root / 'liked')
        self.server.trash_store = library_server.TrashStore(root / 'liked')
        self.server.cloud_bridge = CloudBridge(CLOUD)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, method, path, headers=None, body=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_exact_origin_and_pairing_token_required(self):
        cloud = {'Origin': CLOUD}
        status, headers, data = self.request('GET', '/api/cloud-health', cloud)
        self.assertEqual(status, 200)
        self.assertEqual(headers['Access-Control-Allow-Origin'], CLOUD)
        self.assertEqual(json.loads(data), {'ready': True})

        self.assertEqual(self.request('GET', '/api/status', cloud)[0], 403)
        self.assertEqual(self.request('GET', '/api/status', {'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.request('POST', '/api/settings', {'Origin': CLOUD, 'Content-Type': 'application/json'}, b'{}')[0], 403)
        self.assertEqual(self.request('GET', '/cloud-pair?origin=https%3A%2F%2Fevil.example')[0], 404)

        local_origin = f'http://127.0.0.1:{self.server.server_port}'
        status, _, data = self.request('POST', '/api/cloud-pair', {'Origin': local_origin, 'Content-Type': 'application/json'}, b'{}')
        self.assertEqual(status, 200)
        token = json.loads(data)['token']
        self.assertGreaterEqual(len(token), 40)
        self.assertEqual(self.request('GET', '/api/status', {**cloud, 'X-Shiji-Token': token})[0], 200)
        self.assertEqual(self.request('GET', '/api/status', {**cloud, 'X-Shiji-Token': 'wrong'})[0], 403)

    def test_preflight_is_restricted(self):
        headers = {'Origin': CLOUD, 'Access-Control-Request-Method': 'POST',
                   'Access-Control-Request-Headers': 'content-type,x-shiji-token'}
        status, response, _ = self.request('OPTIONS', '/api/settings', headers)
        self.assertEqual(status, 204)
        self.assertEqual(response['Access-Control-Allow-Origin'], CLOUD)
        self.assertEqual(self.request('OPTIONS', '/api/settings', {**headers, 'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.request('OPTIONS', '/api/settings', {**headers, 'Access-Control-Request-Headers': 'authorization'})[0], 403)

    def test_local_only_default_and_origin_validation(self):
        self.server.cloud_bridge = CloudBridge('')
        self.assertEqual(self.request('GET', '/api/cloud-health', {'Origin': CLOUD})[0], 403)
        self.assertEqual(self.request('GET', '/api/status')[0], 200)
        for value in ('http://example.com', 'https://example.com/path', 'https://user@example.com', 'https://example.com/?x=1'):
            with self.assertRaises(ValueError):
                normalize_origin(value)


if __name__ == '__main__':
    unittest.main()
