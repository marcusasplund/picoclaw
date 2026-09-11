import hashlib
import io
import json
from pathlib import Path
import tempfile
import tarfile
import unittest
from unittest.mock import patch

from jobs import digest
import remote


def request():
    manifest = {'image': 'sha256:' + 'a' * 64, 'frontend': 'b' * 64,
                'image_archive': 'c' * 64, 'frontend_file': 'd' * 64,
                'previous': {'image': 'sha256:' + 'e' * 64, 'frontend': 'f' * 64},
                'target': 'preview-demo.marcusasplund.com', 'sources': {'frontend': 'x', 'backend': 'y'}}
    return {'mode': 'deploy', 'job': '123456abcdef', 'manifest': manifest, 'approval': digest(manifest)}


class RemoteTests(unittest.TestCase):
    def test_request_is_single_fixed_target(self):
        remote.validate(request())
        for key, value in [('job', '../escape'), ('mode', 'shell'), ('approval', 'bad')]:
            with self.assertRaises(ValueError):
                remote.validate({**request(), key: value})
        req = request()
        req['manifest']['target'] = 'duchat.se'
        req['approval'] = digest(req['manifest'])
        with self.assertRaises(ValueError):
            remote.validate(req)

    def test_copy_rejects_symlink_and_changed_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            incoming = root / 'incoming'
            (incoming / '123456abcdef').mkdir(parents=True)
            (incoming / '123456abcdef/frontend.json').symlink_to('/etc/passwd')
            with patch.object(remote, 'INCOMING', incoming):
                with self.assertRaises(OSError):
                    remote.copy_incoming('123456abcdef', 'frontend.json', root / 'out', 'x', 1000)
                (incoming / '123456abcdef/frontend.json').unlink()
                (incoming / '123456abcdef/frontend.json').write_bytes(b'changed')
                with self.assertRaises(ValueError):
                    remote.copy_incoming('123456abcdef', 'frontend.json', root / 'out2', 'x', 1000)

    def test_tagged_image_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'image.tar.gz'
            config = b'{"architecture":"amd64"}'
            def write(tags):
                with tarfile.open(path, 'w:gz') as tar:
                    for name, data in [('config.json', config), ('manifest.json', json.dumps([
                        {'Config': 'config.json', 'RepoTags': tags, 'Layers': []}]).encode())]:
                        info = tarfile.TarInfo(name); info.size = len(data)
                        tar.addfile(info, io.BytesIO(data))
            expected = 'sha256:' + hashlib.sha256(config).hexdigest()
            write(None)
            remote.validate_image_archive(path, expected)
            write(['duchat-backend:latest'])
            with self.assertRaises(ValueError):
                remote.validate_image_archive(path, expected)

    def test_stale_version_cannot_change_server(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'compose.json').write_text(json.dumps({'services': {'app': {'image': 'different'}}}))
            (root / 'frontend-hash').write_text('f' * 64)
            with patch.object(remote.demo, 'ROOT', root), patch.object(remote, 'STATE', root):
                with self.assertRaisesRegex(ValueError, 'stale'):
                    remote.handle(request(), lambda *a, **kw: self.fail('No command should run'))

    def test_pending_journal_blocks_new_deployment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'compose.json').write_text(json.dumps({'services': {'app': {'image': 'sha256:' + 'e' * 64}}}))
            (root / 'frontend-hash').write_text('f' * 64)
            (root / 'pending.json').write_text('{}')
            with patch.object(remote.demo, 'ROOT', root), patch.object(remote, 'STATE', root):
                with self.assertRaisesRegex(ValueError, 'review'):
                    remote.handle(request(), lambda *a, **kw: self.fail('No command should run'))


if __name__ == '__main__':
    unittest.main()

class RemoteDeployTests(unittest.TestCase):
    def exercise(self, fail_migration=False):
        from contextlib import ExitStack
        import subprocess
        req = request()
        with tempfile.TemporaryDirectory() as temp, ExitStack() as patches:
            root = Path(temp) / 'config'; root.mkdir()
            state = Path(temp) / 'state'; state.mkdir()
            nginx = Path(temp) / 'nginx'; nginx.write_text(remote.demo.MARKER + 'old config')
            link = Path(temp) / 'enabled'; link.symlink_to(nginx)
            old = {'services': {'app': {'image': req['manifest']['previous']['image']}, 'db': {'image': 'dbimage'}}}
            (root / 'compose.json').write_text(json.dumps(old))
            (root / 'frontend-hash').write_text(req['manifest']['previous']['frontend'])
            (root / 'image-id').write_text(req['manifest']['previous']['image'])
            for obj, name, value in [(remote, 'STATE', state), (remote.demo, 'ROOT', root),
                                     (remote.demo, 'AVAILABLE', nginx), (remote.demo, 'ENABLED', link)]:
                patches.enter_context(patch.object(obj, name, value))
            patches.enter_context(patch.object(remote, 'copy_incoming', side_effect=lambda j,n,p,*a: p.write_bytes(b'data')))
            patches.enter_context(patch.object(remote, 'validate_image_archive'))
            patches.enter_context(patch.object(remote, 'unpack', return_value=(req['manifest']['frontend'], {'index.html': b'ok'})))
            patches.enter_context(patch.object(remote, 'install_frontend'))
            calls = []
            def run(*args, **kw):
                calls.append(args)
                if 'pg_dump' in args:
                    kw['output'].write(b'database backup')
                if fail_migration and 'run' in args and 'migrate' in args:
                    raise subprocess.CalledProcessError(1, args)
                if '{{.Os}}/{{.Architecture}}' in args:
                    return b'linux/amd64\n'
                if '{{.Image}}' in args:
                    return req['manifest']['image'].encode()
                if 'ps' in args:
                    return b'app-container'
                if 'curl' in args:
                    return b'401' if '--resolve' in args else b'{"value": 1}'
                return None
            if fail_migration:
                with self.assertRaises(subprocess.CalledProcessError):
                    remote.handle(req, run)
                self.assertEqual(json.loads((root / 'compose.json').read_text()), old)
                self.assertEqual(nginx.read_text(), remote.demo.MARKER + 'old config')
                self.assertTrue((state / 'pending.json').exists())
            else:
                receipt = remote.handle(req, run)
                self.assertEqual(receipt['approval'], req['approval'])
                self.assertFalse((state / 'pending.json').exists())
                self.assertEqual(remote.handle(req, lambda *a, **kw: self.fail('Duplicate deploy repeated action')), receipt)
            self.assertEqual((state / req['job'] / 'database.dump').read_bytes(), b'database backup')
            return calls

    def test_backup_and_receipt_make_success_repeatable_without_redeploy(self):
        calls = self.exercise()
        backup = next(i for i,a in enumerate(calls) if 'pg_dump' in a)
        migration = next(i for i,a in enumerate(calls) if 'migrate' in a)
        self.assertLess(backup, migration)

    def test_migration_failure_restores_config_and_requires_review(self):
        self.exercise(fail_migration=True)

class OCIIdentityTests(unittest.TestCase):
    def archive(self, path, nested=False, corrupt=False, wrong_config=False, tag=None):
        blobs = {}
        def blob(value):
            raw = json.dumps(value, separators=(',', ':')).encode()
            digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
            blobs['blobs/sha256/' + digest.split(':')[1]] = raw
            return {'digest': digest, 'size': len(raw)}
        config = {'architecture': 'amd64', 'os': 'linux'}
        desc = blob(config)
        exported = desc
        if wrong_config:
            exported = blob({'architecture': 'arm64', 'os': 'linux'})
        manifest = blob({'schemaVersion': 2, 'config': desc, 'layers': []})
        root = blob({'schemaVersion': 2, 'manifests': [manifest]}) if nested else manifest
        if tag:
            root['annotations'] = {'io.containerd.image.name': tag}
        blobs['index.json'] = json.dumps({'schemaVersion': 2, 'manifests': [root]}).encode()
        blobs['manifest.json'] = json.dumps([{'Config': 'blobs/sha256/' + exported['digest'].split(':')[1],
                                              'RepoTags': None, 'Layers': []}]).encode()
        if corrupt:
            blobs['blobs/sha256/' + manifest['digest'].split(':')[1]] += b' '
        with tarfile.open(path, 'w:gz') as tar:
            for name, data in blobs.items():
                item = tarfile.TarInfo(name); item.size = len(data)
                tar.addfile(item, io.BytesIO(data))
        return root['digest']

    def test_manifest_and_index_ids_are_bound_to_config(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'image.tar.gz'
            for nested in (False, True):
                expected = self.archive(path, nested=nested)
                remote.validate_image_archive(path, expected)

    def test_corrupt_descriptor_unrelated_config_and_tags_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'image.tar.gz'
            for options in [{'corrupt': True}, {'wrong_config': True}, {'tag': 'duchat-backend:latest'}]:
                expected = self.archive(path, **options)
                with self.assertRaises(ValueError):
                    remote.validate_image_archive(path, expected)

    def test_matching_root_copy_can_be_reused_but_not_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'image.tar.gz'
            target.write_bytes(b'verified')
            expected = hashlib.sha256(b'verified').hexdigest()
            remote.copy_incoming('job', 'image.tar.gz', target, expected, 100)
            with self.assertRaises(ValueError):
                remote.copy_incoming('job', 'image.tar.gz', target, 'bad', 100)
