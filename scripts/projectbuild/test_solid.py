import base64
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from solid import container_args, snapshot, write_artifact


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'package.json').write_text(json.dumps({'scripts': {
            name: 'example' for name in ['test:types', 'lint', 'test', 'build']}}))
        (self.root / 'package-lock.json').write_text('{}')

    def test_snapshot_excludes_credentials_and_dependencies(self):
        for name in ['.env', '.env.production', '.npmrc']:
            (self.root / name).write_text('secret')
        (self.root / 'node_modules').mkdir()
        (self.root / 'node_modules' / 'ignored').write_text('dependency')
        data = snapshot(self.root)
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            self.assertEqual(tar.getnames(), ['package-lock.json', 'package.json'])
        self.assertEqual(data, snapshot(self.root))

    def test_symlink_is_rejected(self):
        (self.root / 'outside').symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            snapshot(self.root)

    def test_missing_check_is_rejected(self):
        (self.root / 'package.json').write_text('{"scripts": {}}')
        with self.assertRaisesRegex(ValueError, 'test:types'):
            snapshot(self.root)

    def test_export_rejects_traversal_before_writing(self):
        for name in ['../escape', '/escape', 'a/../../escape', 'a\\escape']:
            with self.assertRaises(ValueError):
                write_artifact(json.dumps({name: 'eA=='}), self.root / 'dist')
        self.assertFalse((self.root / 'dist').exists())

    def test_artifact_hash_tracks_actual_bytes(self):
        payload = json.dumps({'index.html': base64.b64encode(b'hello').decode()})
        first = write_artifact(payload, self.root / 'one')
        self.assertEqual((self.root / 'one/index.html').read_bytes(), b'hello')
        self.assertEqual(first, write_artifact(payload, self.root / 'two'))
        self.assertNotEqual(first, write_artifact('{"index.html":"eA=="}', self.root / 'three'))

    def test_container_has_no_host_mount_or_privileges(self):
        args = container_args('owned-job', 'sha256:example')
        for forbidden in ['--privileged', '--volume', '-v', '--mount', '--pid=host']:
            self.assertNotIn(forbidden, args)
        self.assertIn('--read-only', args)
        self.assertIn('--cap-drop=ALL', args)
        self.assertIn('1000:1000', args)


if __name__ == '__main__':
    unittest.main()
