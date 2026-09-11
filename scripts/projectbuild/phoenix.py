#!/usr/bin/env python3
"""Verify a reviewed Phoenix project against disposable localhost Postgres."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid

from solid import container_args, snapshot

IMAGE = 'elixir:1.18.4-otp-27'
POSTGRES = 'postgres:16-bookworm'


def database_args(name, image):
    return ['run', '--detach', '--name', name, '--label', 'picoclaw.projectbuild=true',
            '--user', '999:999', '--read-only', '--cap-drop=ALL',
            '--security-opt=no-new-privileges', '--pids-limit=128',
            '--memory=512m', '--memory-swap=512m', '--cpus=1',
            '--tmpfs', '/var/lib/postgresql/data:rw,nosuid,nodev,size=512m,uid=999,gid=999',
            '--tmpfs', '/var/run/postgresql:rw,nosuid,nodev,size=16m,uid=999,gid=999',
            '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=64m',
            '--env', 'POSTGRES_PASSWORD=postgres', '--network', 'bridge', image,
            'postgres', '-c', 'listen_addresses=127.0.0.1']


def builder_args(name, image, database):
    args = container_args(name, image)
    args[args.index('--network') + 1] = 'container:' + database
    # Some native Mix dependencies need executable temporary build files.
    args[args.index('/tmp:rw,noexec,nosuid,nodev,size=256m,uid=1000,gid=1000')] = (
        '/tmp:rw,exec,nosuid,nodev,size=256m,uid=1000,gid=1000')
    pos = args.index(image)
    args[pos:pos] = ['--env', 'MIX_ENV=test', '--env', 'ERL_FLAGS=+S 2:2',
                     '--env', 'DATABASE_URL=ecto://postgres:postgres@127.0.0.1/picoclaw_test']
    return args


def verify(archive, output, invoke=None):
    """invoke injection tests the phase ordering and cleanup without Docker."""
    suffix = uuid.uuid4().hex
    builder, database = 'pico-phx-' + suffix, 'pico-db-' + suffix
    report = {'status': 'failed', 'source_sha256': hashlib.sha256(archive).hexdigest(),
              'image': IMAGE, 'database_image': POSTGRES, 'checks': [],
              'containers': [builder, database]}
    attempted = []
    with (output / 'build.log').open('wb') as log:
        def docker(*argv, capture=False, data=None, timeout=300):
            if invoke:
                return invoke(*argv, capture=capture, data=data, timeout=timeout)
            result = subprocess.run(['docker', *argv], input=data,
                                    stdout=subprocess.PIPE if capture else log,
                                    stderr=log, timeout=timeout, check=True)
            return result.stdout

        def stage(label):
            report['stage'] = label
            print(label, flush=True)
            log.write(('\n=== ' + label + ' ===\n').encode())
            log.flush()

        try:
            stage('Kontrollerar Docker och hämtar Elixir/Postgres (första gången kan ta flera minuter)')
            docker('info', timeout=20)
            images = []
            for image in [IMAGE, POSTGRES]:
                docker('pull', image, timeout=600)
                images.append(docker('image', 'inspect', '--format', '{{.Id}}', image,
                                     capture=True).decode().strip())
            report['image_id'], report['database_image_id'] = images
            stage('Startar tillfällig Postgres')
            attempted.append(database)
            docker(*database_args(database, images[1]))
            deadline = time.monotonic() + 60
            while True:
                try:
                    docker('exec', database, 'pg_isready', '-h', '127.0.0.1', '-U', 'postgres', timeout=5)
                    break
                except subprocess.CalledProcessError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Postgres did not become ready within 60 seconds')
                    time.sleep(1)
            attempted.append(builder)
            docker(*builder_args(builder, images[0], database))
            docker('exec', '-i', builder, 'tar', '-xf', '-', '-C', '/work', data=archive)
            stage('Installerar Hex, Rebar och låsta beroenden')
            for command in [('mix', 'local.hex', '--force'), ('mix', 'local.rebar', '--force'),
                            ('mix', 'deps.get', '--check-locked')]:
                docker('exec', builder, *command, timeout=600)
            # Both containers share a network namespace. Loopback remains for
            # the temporary DB; removing its bridge endpoint removes egress.
            docker('network', 'disconnect', 'bridge', database)
            for command in [('mix', 'deps.compile'), ('mix', 'compile', '--warnings-as-errors'),
                            ('mix', 'ecto.create'), ('mix', 'ecto.migrate'), ('mix', 'test')]:
                stage('Kör ' + ' '.join(command))
                report['active_check'] = list(command)
                docker('exec', builder, *command, timeout=600)
                report['checks'].append(list(command))
            report['status'] = 'passed'
        except (subprocess.SubprocessError, OSError, ValueError) as exc:
            report['error'] = str(exc)
        finally:
            # App first: Postgres owns the shared namespace. Never prune Docker.
            for name in reversed(attempted):
                try:
                    docker('rm', '--force', '--volumes', name, timeout=30)
                except (subprocess.SubprocessError, OSError):
                    report.setdefault('cleanup_required', []).append(name)
            (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    root, output = args.project.resolve(), args.output.resolve()
    if root == output or root in output.parents:
        parser.error('--output must be outside the project')
    archive = snapshot(root, kind='phoenix')
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    report = verify(archive, output)
    print(json.dumps({'status': report['status'], 'report': str(output / 'report.json')}))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
