import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from phoenix_release import build_and_smoke, build_context, checked_source, validate_options

BASE = 'elixir@sha256:' + 'a' * 64


def source_archive():
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w') as tar:
        for name in ['mix.exs', 'Dockerfile', '.dockerignore']:
            info = tarfile.TarInfo(name)
            info.size = 7
            tar.addfile(info, io.BytesIO(b'example'))
    return data.getvalue()


class ReleaseTests(unittest.TestCase):
    def run_release(self, failure=None, migration_code=b'0', health_failure=False):
        calls = []

        def docker(*args, **kwargs):
            calls.append(args)
            if failure and failure(args):
                raise subprocess.CalledProcessError(1, args)
            if health_failure and 'elixir' in args:
                raise subprocess.CalledProcessError(1, args)
            if args[0] == 'wait':
                return migration_code
            if '.RepoDigests' in ' '.join(args):
                return BASE.encode()
            if '{{.State.Running}}' in args:
                return b'true'
            return b'sha256:local-image'

        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            output = Path(temp)
            # Make a failed readiness check exhaust the deadline immediately.
            with patch('phoenix_release.time.monotonic', side_effect=range(0, 10000, 100)):
                report = build_and_smoke(source_archive(), output, 'du_chat', 'DuChat.Release', '/api/', docker)
            self.assertFalse((output / '.smoke.env').exists())
            self.assertEqual(report, json.loads((output / 'report.json').read_text()))
        return report, calls

    def test_only_trusted_dockerfile_controls_build(self):
        context = build_context(source_archive(), BASE, 'du_chat')
        with tarfile.open(fileobj=io.BytesIO(context)) as tar:
            self.assertIn('source/Dockerfile', tar.getnames())
            self.assertNotIn('.dockerignore', tar.getnames())
            dockerfile = tar.extractfile('Dockerfile').read().decode()
        self.assertEqual(dockerfile.count('FROM ' + BASE), 2)
        self.assertIn('RUN --network=none', dockerfile)
        self.assertIn('mix release && test -x _build/prod/rel/du_chat/bin/du_chat', dockerfile)
        self.assertNotIn('mix release du_chat', dockerfile)
        self.assertNotIn('SECRET_KEY_BASE', dockerfile)

    def test_passed_image_is_smoked_by_id_and_not_deployed(self):
        report, calls = self.run_release()
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['checks'], ['production_release_image', 'release_migrations', 'http_health'])
        runs = [a for a in calls if a[0] == 'run']
        self.assertEqual(len(runs), 3)
        self.assertIn('none', runs[0])
        self.assertIn(report['image_id'], runs[-1])
        for run in runs:
            self.assertNotIn('-p', run)
            self.assertNotIn('--publish', run)
        self.assertFalse(any(a[0] in ['push', 'save'] for a in calls))

    def test_migration_failure_prevents_app_start(self):
        report, calls = self.run_release(migration_code=b'1')
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(len([a for a in calls if a[0] == 'run']), 2)
        self.assertEqual(len([a for a in calls if a[0] == 'rm']), 2)

    def test_health_failure_cleans_every_container(self):
        report, calls = self.run_release(health_failure=True)
        self.assertEqual(report['status'], 'failed')
        self.assertNotIn('http_health', report['checks'])
        self.assertEqual(len([a for a in calls if a[0] == 'rm']), 3)

    def test_failed_build_never_starts_runtime(self):
        report, calls = self.run_release(failure=lambda a: a[0] == 'build')
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(any(a[0] == 'run' for a in calls))

    def test_modified_or_failed_source_is_rejected(self):
        archive = b'source'
        good = {'status': 'passed', 'source_sha256': hashlib.sha256(archive).hexdigest(),
                'checks': [['mix', 'test']]}
        with tempfile.TemporaryDirectory() as temp, patch('phoenix_release.snapshot', return_value=archive):
            path = Path(temp) / 'report.json'
            path.write_text(json.dumps(good))
            self.assertEqual(checked_source(Path(temp), path), archive)
            for field, value in [('status', 'failed'), ('source_sha256', 'different'), ('checks', [])]:
                path.write_text(json.dumps({**good, field: value}))
                with self.assertRaises(ValueError):
                    checked_source(Path(temp), path)

    def test_options_cannot_inject_code_or_dockerfile(self):
        for release, module, path in [('a\nRUN echo bad', 'Release', '/'),
                                      ('app', 'Release; IO.puts(1)', '/'),
                                      ('app', 'Release', '/\"')]:
            with self.assertRaises(ValueError):
                validate_options(release, module, path)


if __name__ == '__main__':
    unittest.main()
