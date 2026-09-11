#!/usr/bin/env python3
"""Build a reviewed Phoenix release image and smoke-test it locally."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tarfile
import time
import uuid

from phoenix import IMAGE, POSTGRES, database_args
from solid import snapshot


def validate_options(release, module, health_path):
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', release):
        raise ValueError('Invalid release name')
    if not re.fullmatch(r'[A-Z][A-Za-z0-9_]*(\.[A-Z][A-Za-z0-9_]*)*', module):
        raise ValueError('Invalid migration module')
    if not re.fullmatch(r'/[a-zA-Z0-9/_-]*', health_path):
        raise ValueError('Invalid health path')


def checked_source(project, previous):
    archive = snapshot(project, kind='phoenix')
    report = json.loads(previous.read_text())
    digest = hashlib.sha256(archive).hexdigest()
    if (report.get('status') != 'passed' or report.get('source_sha256') != digest
            or ['mix', 'test'] not in report.get('checks', [])):
        raise ValueError('Source must match a passed Phoenix test report. Run phoenix.py first.')
    return archive


def build_context(archive, base, release):
    if not re.fullmatch(r'[a-zA-Z0-9_./:-]+@sha256:[0-9a-f]{64}', base):
        raise ValueError('Expected a pinned base image repository digest')
    validate_options(release, 'Release', '/')
    dockerfile = f'''FROM {base} AS build
WORKDIR /build
RUN chown 1000:1000 /build
USER 1000:1000
ENV HOME=/tmp MIX_ENV=prod ERL_FLAGS="+S 2:2"
COPY --chown=1000:1000 source/ ./
RUN mix local.hex --force && mix local.rebar --force && mix deps.get --only prod --check-locked
RUN --network=none mix deps.compile && mix compile --warnings-as-errors && mix release && test -x _build/prod/rel/{release}/bin/{release} && rm -f _build/prod/rel/{release}/releases/COOKIE

FROM {base} AS runtime
WORKDIR /app
COPY --from=build --chown=1000:1000 /build/_build/prod/rel/{release}/ ./
USER 1000:1000
ENV HOME=/tmp MIX_ENV=prod RELEASE_TMP=/tmp RELEASE_DISTRIBUTION=none ERL_FLAGS="+S 2:2" PHX_SERVER=true
EXPOSE 4000
CMD ["bin/{release}", "start"]
'''
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.USTAR_FORMAT) as out:
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            for entry in source:
                data = source.extractfile(entry).read()
                entry.name = 'source/' + entry.name
                out.addfile(entry, io.BytesIO(data))
        info = tarfile.TarInfo('Dockerfile')
        data = dockerfile.encode()
        info.size = len(data)
        info.mode = 0o644
        out.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def runtime_args(name, database, image, envfile):
    return ['run', '--detach', '--name', name, '--label', 'picoclaw.projectbuild=true',
            '--user', '1000:1000', '--read-only', '--cap-drop=ALL',
            '--security-opt=no-new-privileges', '--pids-limit=256',
            '--memory=1g', '--memory-swap=1g', '--cpus=2',
            '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=128m,uid=1000,gid=1000',
            '--network', 'container:' + database, '--env-file', str(envfile), image]


def smoke_env():
    # These are disposable values, generated AFTER image build and never baked in.
    return {'DATABASE_URL': 'ecto://postgres:postgres@127.0.0.1/postgres',
            'SECRET_KEY_BASE': secrets.token_hex(64), 'JWT_SECRET': secrets.token_hex(32),
            'RELEASE_COOKIE': secrets.token_hex(32), 'PHX_HOST': 'localhost', 'PORT': '4000'}


def health_probe(path):
    validate_options('app', 'Release', path)
    return (':inets.start(); '
            '{:ok, {{_, 200, _}, _, body}} = :httpc.request(:get, '
            '{~c"http://127.0.0.1:4000' + path + '", []}, '
            '[timeout: 3000], []); '
            r'true = Regex.match?(~r/^\s*\{\s*"status"\s*:\s*"ok"\s*\}\s*$/, IO.iodata_to_binary(body))')


def build_and_smoke(archive, output, release, module, health_path, invoke=None):
    validate_options(release, module, health_path)
    suffix = uuid.uuid4().hex
    database, migration, app = ('pico-rel-' + kind + '-' + suffix for kind in ['db', 'migration', 'app'])
    tag = 'picoclaw-local/' + release + ':' + suffix
    envfile = output / '.smoke.env'
    report = {'status': 'failed', 'source_sha256': hashlib.sha256(archive).hexdigest(),
              'image_tag': tag, 'release': release, 'checks': []}
    attempted = []
    with (output / 'build.log').open('wb') as log:
        def docker(*args, capture=False, data=None, timeout=300):
            if invoke:
                return invoke(*args, capture=capture, data=data, timeout=timeout)
            return subprocess.run(['docker', *args], input=data,
                                  stdout=subprocess.PIPE if capture else log, stderr=log,
                                  check=True, timeout=timeout).stdout

        def stage(label):
            report['stage'] = label
            print(label, flush=True)
            log.write(('\n=== ' + label + ' ===\n').encode())
            log.flush()

        def retry(operation):
            deadline = time.monotonic() + 60
            while True:
                try:
                    return operation()
                except subprocess.CalledProcessError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Readiness check failed after 60 seconds')
                    time.sleep(2)

        try:
            stage('Hämtar och låser basimages')
            docker('info', timeout=20)
            for image in [IMAGE, POSTGRES]:
                docker('pull', image, timeout=600)
            base = docker('image', 'inspect', '--format', '{{index .RepoDigests 0}}', IMAGE,
                          capture=True).decode().strip()
            dbimage = docker('image', 'inspect', '--format', '{{.Id}}', POSTGRES,
                             capture=True).decode().strip()
            report['base_digest'], report['database_image_id'] = base, dbimage
            stage('Bygger produktionsrelease och Docker-image (kan ta flera minuter)')
            docker('build', '--tag', tag, '--label', 'picoclaw.projectbuild=true',
                   '--progress=plain', '-', data=build_context(archive, base, release), timeout=1800)
            image = docker('image', 'inspect', '--format', '{{.Id}}', tag, capture=True).decode().strip()
            report['image_id'] = image
            report['platform'] = docker('image', 'inspect', '--format', '{{.Os}}/{{.Architecture}}',
                                        image, capture=True).decode().strip()
            report['checks'].append('production_release_image')
            with open(envfile, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as env:
                env.write(''.join(f'{k}={v}\n' for k, v in smoke_env().items()))
            stage('Startar ny Postgres utan externt nätverk')
            args = database_args(database, dbimage)
            args[args.index('--network') + 1] = 'none'
            attempted.append(database)
            docker(*args)
            retry(lambda: docker('exec', database, 'pg_isready', '-h', '127.0.0.1', '-U', 'postgres', timeout=5))
            stage('Kör migrationer från den byggda releasen')
            attempted.append(migration)
            docker(*runtime_args(migration, database, image, envfile),
                   'bin/' + release, 'eval', module + '.migrate()')
            code = docker('wait', migration, capture=True, timeout=120).decode().strip()
            docker('logs', '--tail', '200', migration)
            if code != '0':
                raise ValueError('Release migration failed; see build.log')
            report['checks'].append('release_migrations')
            stage('Startar produktionsimagen och väntar på HTTP 200 + status ok')
            attempted.append(app)
            docker(*runtime_args(app, database, image, envfile))
            probe = health_probe(health_path)
            retry(lambda: docker('exec', app, 'elixir', '-e', probe, timeout=15))
            running = docker('inspect', '--format', '{{.State.Running}}', app, capture=True).decode().strip()
            if running != 'true':
                raise ValueError('App stopped after health check')
            report['checks'].append('http_health')
            report['status'] = 'passed'
        except (subprocess.SubprocessError, OSError, ValueError) as exc:
            report['error'] = str(exc)
        finally:
            for name in reversed(attempted):
                try:
                    docker('logs', '--tail', '100', name, timeout=10)
                except (subprocess.SubprocessError, OSError):
                    pass
                try:
                    docker('rm', '--force', '--volumes', name, timeout=30)
                except (subprocess.SubprocessError, OSError):
                    report.setdefault('cleanup_required', []).append(name)
            envfile.unlink(missing_ok=True)
            (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('--verified-report', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--release', default='du_chat')
    parser.add_argument('--migration-module', default='DuChat.Release')
    parser.add_argument('--health-path', default='/api/')
    args = parser.parse_args()
    validate_options(args.release, args.migration_module, args.health_path)
    root, output = args.project.resolve(), args.output.resolve()
    if output == root or root in output.parents:
        parser.error('--output must be outside the source project')
    archive = checked_source(root, args.verified_report)
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    report = build_and_smoke(archive, output, args.release, args.migration_module, args.health_path)
    print(json.dumps({'status': report['status'], 'report': str(output / 'report.json'),
                      'image': report.get('image_id')}))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
