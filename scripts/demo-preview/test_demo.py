import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from frontend import checked, install_frontend, export, unpack
from install import spec, nginx, IMAGE


class DemoTests(unittest.TestCase):
    def test_network_fix_keeps_db_private(self):
        config = spec('dbimage')
        self.assertEqual(config['services']['app']['networks'], ['private', 'web'])
        self.assertEqual(config['services']['db']['networks'], ['private'])
        self.assertEqual(config['services']['migrate']['networks'], ['private'])
        self.assertEqual(config['services']['app']['ports'], ['127.0.0.1:4188:4000'])
        self.assertEqual(config['services']['app']['image'], IMAGE)
        self.assertTrue(config['networks']['private']['internal'])
        self.assertFalse(config['networks']['web'].get('internal', False))
        self.assertNotIn('ports', config['services']['db'])

    def test_frontend_and_api_share_protection(self):
        text = nginx(True, 'a' * 64)
        self.assertIn('auth_basic_user_file', text)
        self.assertIn('location /api/', text)
        self.assertIn('try_files $uri $uri/ /index.html', text)
        self.assertNotIn('auth_basic off', text)
        self.assertNotIn('proxy_pass', nginx(False, 'a' * 64))

    def test_rejects_traversal_and_conflicting_paths(self):
        for name in ['../escape', '/etc/file', '.', 'a/../file', '.env']:
            with self.assertRaises(ValueError):
                checked({'index.html': 'eA==', name: 'eA=='})
        with self.assertRaises(ValueError):
            checked({'index.html': 'eA==', 'a': 'eA==', 'a/b': 'eA=='})

    def test_export_verifies_passed_artifact_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'dist').mkdir()
            (root / 'dist/index.html').write_bytes(b'hello')
            digest, _ = checked({'index.html': base64.b64encode(b'hello').decode()})
            report = root / 'report.json'
            report.write_text(json.dumps({'status': 'passed', 'checks': [['npm', 'run', 'build']], 'artifact_sha256': digest}))
            export(report, root / 'frontend.json')
            self.assertEqual(unpack(root / 'frontend.json'), (digest, {'index.html': b'hello'}))
            (root / 'dist/index.html').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                export(report, root / 'bad.json')

    def test_install_is_readable_and_refuses_modified_existing_files(self):
        with tempfile.TemporaryDirectory() as temp, patch('frontend.WEBROOT', Path(temp) / 'web'):
            digest = 'a' * 64
            files = {'index.html': b'x', 'assets/app.js': b'y'}
            install_frontend(digest, files)
            target = Path(temp) / 'web' / digest
            self.assertEqual(target.stat().st_mode & 0o777, 0o755)
            self.assertEqual((target / 'assets').stat().st_mode & 0o777, 0o755)
            install_frontend(digest, files)
            with self.assertRaises(ValueError):
                install_frontend(digest, {'index.html': b'changed'})


if __name__ == '__main__':
    unittest.main()
