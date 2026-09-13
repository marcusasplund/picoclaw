import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import generate
from package import package
from source_files import source_files


class SourceFilesTests(unittest.TestCase):
    def test_generated_trees_are_pruned_and_required_hidden_files_survive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            keep = ['package-lock.json', '.gitignore', '.oxlintrc.json',
                    '.impeccable/live/config.json', 'public/favicon.svg']
            ignored = ['node_modules/pkg/binary', 'dist/bundle.js', 'coverage/index.html',
                       '.git/config', '__pycache__/test.pyc']
            for name in keep + ignored:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'\xff' if name in ignored else b'{}')
            self.assertEqual({p.relative_to(root).as_posix() for p in source_files(root)}, set(keep))

    def test_secret_files_and_symlinked_directories_are_rejected(self):
        for name in ['.env', '.npmrc', '.impeccable/private.json']:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('secret')
                with self.assertRaisesRegex(ValueError, 'hidden'):
                    list(source_files(root))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'source'
            root.mkdir()
            (root / 'linked').symlink_to(Path(temp), target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                list(source_files(root))

    def test_real_archive_round_trip_produces_the_same_flattened_bundle(self):
        expected = generate.bundle()
        prefix = 'templates/application/frontend/'
        self.assertEqual(json.loads(expected[prefix + 'package.json'])['name'], 'solid-multipage')
        for name in ['src/routes/page1.tsx', 'src/routes/page2.tsx', 'package-lock.json',
                     '.oxlintrc.json', '.impeccable/live/config.json', 'public/icons.svg']:
            self.assertIn(prefix + name, expected)
        self.assertFalse(any('/solid-multipage/' in name for name in expected))
        with tempfile.TemporaryDirectory() as temp:
            archive_path = package(generate.BASE, Path(temp) / 'installer.tar.gz')
            installed = Path(temp) / 'installed'
            with tarfile.open(archive_path) as archive:
                for member in archive.getmembers():
                    self.assertTrue(member.isfile())
                    self.assertFalse(set(Path(member.name).parts) & {'node_modules', 'dist', 'coverage', '.git'})
                    target = installed / member.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(member).read())
            with patch('generate.BASE', installed / 'projectflow'):
                self.assertEqual(generate.bundle(), expected)


if __name__ == '__main__':
    unittest.main()
