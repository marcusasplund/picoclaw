import contextlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

from phoenix import builder_args, database_args, verify
from solid import snapshot


class PhoenixTests(unittest.TestCase):
    def run_build(self, fail=None):
        calls = []

        def docker(*args, **kwargs):
            calls.append(args)
            if fail and fail(args):
                raise subprocess.CalledProcessError(1, ['docker', *args])
            return b'sha256:test-image\n'

        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            report = verify(b'source', Path(temp), docker)
            self.assertEqual(report, json.loads((Path(temp) / 'report.json').read_text()))
        return report, calls

    def test_success_disconnects_before_compile_and_migrates_before_tests(self):
        report, calls = self.run_build()
        self.assertEqual(report['status'], 'passed')
        disconnect = next(i for i, a in enumerate(calls) if a[:2] == ('network', 'disconnect'))
        compile_at = next(i for i, a in enumerate(calls) if 'deps.compile' in a)
        migrate_at = next(i for i, a in enumerate(calls) if 'ecto.migrate' in a)
        test_at = next(i for i, a in enumerate(calls) if a[-2:] == ('mix', 'test'))
        self.assertLess(disconnect, compile_at)
        self.assertLess(migrate_at, test_at)
        self.assertEqual([a[-1] for a in calls if a[0] == 'rm'], report['containers'])

    def test_migration_failure_stops_tests_and_cleans_both_containers(self):
        report, calls = self.run_build(lambda a: 'ecto.migrate' in a)
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(any(a[-2:] == ('mix', 'test') for a in calls))
        self.assertEqual(len([a for a in calls if a[0] == 'rm']), 2)

    def test_no_compilation_if_network_disconnect_fails(self):
        report, calls = self.run_build(lambda a: a[:2] == ('network', 'disconnect'))
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(any('deps.compile' in a for a in calls))

    def test_pull_failure_does_not_remove_uncreated_resources(self):
        report, calls = self.run_build(lambda a: a[0] == 'pull')
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(any(a[0] == 'rm' for a in calls))

    def test_cleanup_failure_is_reported_and_other_cleanup_continues(self):
        report, calls = self.run_build(lambda a: a[0] == 'rm')
        self.assertEqual(report['cleanup_required'], report['containers'])
        self.assertEqual(len([a for a in calls if a[0] == 'rm']), 2)

    def test_database_is_temporary_and_not_published(self):
        db = database_args('db', 'image')
        app = builder_args('app', 'image', 'db')
        self.assertIn('listen_addresses=127.0.0.1', db)
        self.assertIn('container:db', app)
        self.assertIn('MIX_ENV=test', app)
        for args in [db, app]:
            for flag in ['--publish', '-p', '--volume', '-v', '--privileged']:
                self.assertNotIn(flag, args)

    def test_snapshot_keeps_tests_and_migrations_but_excludes_build_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ['mix.exs', 'mix.lock', 'config/test.exs', 'test/sample_test.exs',
                         'priv/repo/migrations/01_init.exs', 'deps/cache', '_build/cache', '.env']:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('example')
            with tarfile.open(fileobj=io.BytesIO(snapshot(root, kind='phoenix'))) as tar:
                names = tar.getnames()
            self.assertIn('test/sample_test.exs', names)
            self.assertIn('priv/repo/migrations/01_init.exs', names)
            self.assertNotIn('deps/cache', names)
            self.assertNotIn('_build/cache', names)
            self.assertNotIn('.env', names)


if __name__ == '__main__':
    unittest.main()
