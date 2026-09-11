import unittest
from export import validate
from install import IMAGE, HOST, nginx, spec


class PreviewTests(unittest.TestCase):
    def test_only_expected_passed_image_can_be_exported(self):
        valid = {'status': 'passed', 'image_id': IMAGE, 'checks': [
            'production_release_image', 'release_migrations', 'http_health']}
        validate(valid)
        for key, value in [('status', 'failed'), ('image_id', 'other'), ('checks', [])]:
            with self.assertRaises(ValueError):
                validate({**valid, key: value})

    def test_spec_keeps_app_and_data_separate_from_existing_projects(self):
        config = spec('sha256:database')
        self.assertTrue(config['networks']['private']['internal'])
        app = config['services']['app']
        self.assertEqual(app['image'], IMAGE)
        self.assertEqual(app['ports'], ['127.0.0.1:4187:4000'])
        self.assertTrue(app['read_only'])
        self.assertEqual(config['services']['db']['volumes'], ['data:/var/lib/postgresql/data'])
        self.assertNotIn('ports', config['services']['db'])
        for service in config['services'].values():
            self.assertNotIn('build', service)
            self.assertNotIn('privileged', service)
            self.assertNotIn('container_name', service)
            self.assertNotIn('network_mode', service)

    def test_migrations_are_explicit_and_have_no_public_port(self):
        service = spec('db')['services']['migrate']
        self.assertEqual(service['profiles'], ['migration'])
        self.assertEqual(service['command'], ['bin/du_chat', 'eval', 'DuChat.Release.migrate()'])
        self.assertNotIn('ports', service)
        self.assertEqual(service['restart'], 'no')

    def test_http_never_proxies_app_and_https_requires_auth(self):
        bootstrap = nginx(False)
        self.assertNotIn('proxy_pass', bootstrap)
        self.assertIn('return 503', bootstrap)
        final = nginx(True)
        http, tls = final.split('listen 443 ssl;')
        self.assertNotIn('proxy_pass', http)
        self.assertIn('auth_basic_user_file /etc/nginx/picoclaw-preview.htpasswd;', tls)
        self.assertIn('server_name ' + HOST, tls)
        self.assertIn('proxy_pass http://127.0.0.1:4187;', tls)


if __name__ == '__main__':
    unittest.main()
