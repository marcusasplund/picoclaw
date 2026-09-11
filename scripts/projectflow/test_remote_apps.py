import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import ExitStack

import remote_apps as app
from jobs import digest


def request():
    ident = '123456abcdef'
    manifest = {'image': 'sha256:' + 'a' * 64, 'frontend': 'b' * 64,
                'image_archive': 'c' * 64, 'frontend_file': 'd' * 64, 'previous': None,
                'target': 'app-' + ident + '.marcusasplund.com',
                'sources': {'frontend': 'e' * 64, 'backend': 'f' * 64}}
    return {'mode': 'deploy', 'app': ident, 'job': ident, 'manifest': manifest, 'approval': digest(manifest)}


def static_request():
    ident = '654321fedcba'
    manifest = {'profile': 'static', 'frontend': 'b' * 64,
                'frontend_file': 'd' * 64, 'previous': None,
                'target': 'app-' + ident + '.marcusasplund.com',
                'sources': {'frontend': 'e' * 64}}
    return {'mode': 'deploy', 'app': ident, 'job': ident,
            'manifest': manifest, 'approval': digest(manifest)}


class AppDeployTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        for name in ['STATE', 'CONFIG', 'WEB', 'AVAILABLE', 'ENABLED']:
            path = self.root / name; path.mkdir()
            self.stack.enter_context(patch.object(app, name, path))
        auth = self.root / 'auth'; auth.touch()
        self.stack.enter_context(patch.object(app.demo, 'AUTH', str(auth)))
        self.stack.enter_context(patch.object(app.time, 'sleep'))
        self.stack.enter_context(patch.object(app.socket, 'socket'))
        demo = self.root / 'demo'; demo.mkdir()
        (demo / 'compose.json').write_text(json.dumps({'services': {'db': {'image': 'sha256:' + '9' * 64}}}))
        self.stack.enter_context(patch.object(app.demo, 'ROOT', demo))
        self.stack.enter_context(patch.object(app.remote, 'copy_incoming'))
        self.stack.enter_context(patch.object(app.remote, 'validate_image_archive'))
        self.stack.enter_context(patch.object(app.frontend, 'unpack', return_value=('b' * 64, {'index.html': b'app'})))
        self.calls = []

    def run_command(self, *args, **kw):
        self.calls.append(args)
        if args[:3] == ('docker', 'image', 'inspect'): return b'linux/amd64'
        if args[:2] == ('docker', 'inspect'): return ('sha256:' + 'a' * 64).encode()
        if args[0] == 'curl':
            return b'401' if 'https://' in args[-1] else b'{"status":"ok"}'
        if 'ps' in args: return b'own-app'
        return b'' if kw.get('capture') else None

    def test_new_app_has_own_resources_and_idempotent_receipt(self):
        req = request()
        receipt = app.handle(req, self.run_command)
        self.assertEqual(receipt['approval'], req['approval'])
        spec = json.loads((app.CONFIG / req['app'] / 'compose.json').read_text())
        self.assertEqual(spec['name'], 'picoclaw-app-' + req['app'])
        self.assertEqual(spec['services']['app']['ports'], ['127.0.0.1:4200:4000'])
        self.assertNotIn('ports', spec['services']['db'])
        self.assertEqual(spec['networks']['private'], {'internal': True})
        self.assertFalse((app.STATE / req['app'] / 'pending.json').exists())
        self.assertTrue(any(c[0] == 'certbot' for c in self.calls))
        before = len(self.calls)
        self.assertEqual(app.handle(req, self.run_command), receipt)
        self.assertEqual(before, len(self.calls))
        self.assertFalse(any('duchat' in str(c) for c in self.calls))

    def test_static_app_has_no_compose_database_or_backend_image(self):
        req = static_request()
        receipt = app.handle(req, self.run_command)
        self.assertEqual(receipt['profile'], 'static')
        self.assertEqual(receipt['version'], {'frontend': 'b' * 64})
        self.assertFalse((app.CONFIG / req['app']).exists())
        self.assertFalse((app.STATE / req['app'] / 'reservation.json').exists())
        self.assertFalse(any(call[0] == 'docker' for call in self.calls))
        site = (app.AVAILABLE / ('picoclaw-app-' + req['app'])).read_text()
        self.assertNotIn('proxy_pass', site)
        self.assertIn('try_files $uri $uri/ /index.html', site)
        release = {'mode': 'release', 'app': req['app'], 'slug': 'static-test',
                   'approval': req['approval']}
        def public_run(*args, **kw):
            if args[0] == 'curl':
                return b'200'
            return self.run_command(*args, **kw)
        released = app.handle(release, public_run)
        self.assertEqual(released['url'], 'https://static-test.marcusasplund.com/')
        public_site = (app.AVAILABLE / 'picoclaw-public-static-test').read_text()
        self.assertNotIn('auth_basic', public_site)
        self.assertNotIn('proxy_pass', public_site)

    def test_no_adoption_of_existing_resources(self):
        req = request(); (app.CONFIG / req['app']).mkdir()
        with self.assertRaises(ValueError): app.handle(req, self.run_command)
        self.assertEqual(self.calls, [])

    def test_rejects_other_domain_and_host_commands(self):
        for mutation in [{'target': 'duchat.se'}, {'command': 'sh'}, {'previous': {'image': 'existing'}}]:
            req = request(); req['manifest'].update(mutation); req['approval'] = digest(req['manifest'])
            with self.assertRaises(ValueError): app.handle(req, self.run_command)
        self.assertEqual(self.calls, [])

    def test_failure_removes_only_new_route_and_keeps_data_journal(self):
        req = request()
        def fail(*args, **kw):
            if args[0] == 'certbot': raise ValueError('certificate failed')
            return self.run_command(*args, **kw)
        with self.assertRaises(ValueError): app.handle(req, fail)
        self.assertTrue((app.STATE / req['app'] / 'pending.json').exists())
        self.assertTrue((app.CONFIG / req['app'] / 'db.env').exists())
        self.assertEqual(list(app.ENABLED.iterdir()), [])
        self.assertTrue(any(c[-2:] == ('stop', 'app') for c in self.calls))
        count = len(self.calls)
        with self.assertRaises(ValueError): app.handle(req, self.run_command)
        self.assertEqual(len(self.calls), count)

    def test_second_app_uses_different_port_and_database_project(self):
        first = request(); app.handle(first, self.run_command)
        second = request(); second['app'] = second['job'] = 'abcdef123456'
        second['manifest']['target'] = 'app-abcdef123456.marcusasplund.com'
        second['approval'] = digest(second['manifest'])
        app.handle(second, self.run_command)
        spec = json.loads((app.CONFIG / second['app'] / 'compose.json').read_text())
        self.assertEqual(spec['services']['app']['ports'], ['127.0.0.1:4201:4000'])
        self.assertNotEqual(spec['name'], 'picoclaw-app-' + first['app'])


if __name__ == '__main__':
    unittest.main()
