#!/usr/bin/env python3
"""Manual Solid/Vite verifier. No Slack, credentials or deployment access."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import uuid

IMAGE = "node:22-bookworm-slim"
LIMIT = 20 * 1024 * 1024
EXCLUDE = {".git", ".ssh", ".aws", ".npmrc", ".netrc", "node_modules",
           "dist", "coverage", ".picoclaw", ".codex", ".agents"}


def snapshot(root, kind="solid"):
    if not root.is_dir():
        raise ValueError("Project directory does not exist")
    """Copy only ordinary source files; never dereference source symlinks."""
    excluded = EXCLUDE | ({"deps", "_build", ".elixir_ls", "erl_crash.dump"} if kind == "phoenix" else set())
    files = {}
    total = 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in excluded and not d.startswith('.env'))
        for name in dirs + sorted(names):
            path = Path(directory) / name
            if name in excluded or name.startswith('.env'):
                continue
            if path.is_symlink():
                raise ValueError(f"Symlink is not supported: {path.relative_to(root)}")
            if path.is_dir():
                continue
            if not path.is_file():
                raise ValueError("Special files are not supported")
            if name.endswith(('.pem', '.key', '.p12', '.pfx')):
                raise ValueError(f"Remove credential-like file: {path.relative_to(root)}")
            # O_NOFOLLOW also prevents following a symlink substituted after the check.
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, 'rb') as source:
                data = source.read(LIMIT + 1)
            total += len(data)
            if total > LIMIT or len(files) >= 5000:
                raise ValueError("Source exceeds 20 MiB / 5000 files")
            files[path.relative_to(root).as_posix()] = data
    if kind == "phoenix":
        for name in ('mix.exs', 'mix.lock', 'config/test.exs'):
            if name not in files:
                raise ValueError(f"Missing Phoenix input: {name}")
    else:
        package = json.loads(files['package.json'])
        if 'package-lock.json' not in files:
            raise ValueError("A committed npm package-lock.json is required")
        for script in ('test:types', 'lint', 'test', 'build'):
            if not package.get('scripts', {}).get(script):
                raise ValueError(f"Missing package.json script: {script}")
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w', format=tarfile.USTAR_FORMAT) as tar:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            info.uid = info.gid = 1000
            tar.addfile(info, io.BytesIO(data))
    return archive.getvalue()


def container_args(name, image):
    return ['run', '--detach', '--name', name, '--label', 'picoclaw.projectbuild=true',
            '--user', '1000:1000', '--read-only', '--cap-drop=ALL',
            '--security-opt=no-new-privileges', '--pids-limit=256',
            '--memory=2g', '--memory-swap=2g', '--cpus=2',
            '--tmpfs', '/work:rw,exec,nosuid,nodev,size=1g,uid=1000,gid=1000',
            '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=256m,uid=1000,gid=1000',
            '--workdir', '/work', '--env', 'HOME=/tmp', '--env', 'CI=true',
            '--network', 'bridge', image, 'sleep', '1800']


# Executed with the image's Node, after all build commands finish. Only regular
# dist files are exported, with a total byte limit (no docker cp tar extraction).
EXPORT = r"""
const fs = require('node:fs'); const path = require('node:path');
let total=0; const out={};
function walk(dir) {
  for (const name of fs.readdirSync(dir).sort()) {
    const p=path.join(dir,name); const s=fs.lstatSync(p);
    if (s.isSymbolicLink()) throw Error('dist contains symlink');
    if (s.isDirectory()) walk(p);
    else if (s.isFile()) {
      total+=s.size;
      if(total>20*1024*1024 || Object.keys(out).length>=5000) throw Error('dist too large');
      out[path.relative('/work/dist',p)]=fs.readFileSync(p).toString('base64');
    } else throw Error('dist contains special file');
  }
}
if (!fs.lstatSync('/work/dist').isDirectory()) throw Error('dist must be a directory');
walk('/work/dist'); console.log(JSON.stringify(out));
"""


def write_artifact(payload, output):
    files = json.loads(payload)
    if not isinstance(files, dict) or not files or len(files) > 5000:
        raise ValueError('Invalid dist file list')
    decoded = {}
    total = 0
    for name, encoded in files.items():
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or str(path) != name or '\\' in name:
            raise ValueError('Unsafe dist path')
        data = base64.b64decode(encoded, validate=True)
        total += len(data)
        if total > LIMIT:
            raise ValueError('dist exceeds 20 MiB')
        decoded[name] = data
    if 'index.html' not in decoded:
        raise ValueError('dist/index.html is required')
    digest = hashlib.sha256()
    for name, data in sorted(decoded.items()):
        digest.update(json.dumps([name, hashlib.sha256(data).hexdigest()]).encode() + b'\n')
    output.mkdir()
    for name, data in decoded.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('--output', required=True, type=Path, help='New report/artifact directory outside project')
    args = parser.parse_args()
    root, output = args.project.resolve(), args.output.resolve()
    if root == output or root in output.parents:
        parser.error('--output must be outside the source project')
    archive = snapshot(root)
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    name = 'pico-build-' + uuid.uuid4().hex
    report = {'status': 'failed', 'source_sha256': hashlib.sha256(archive).hexdigest(),
              'image': IMAGE, 'container': name, 'checks': []}
    with (output / 'build.log').open('wb') as log:
        def docker(*argv, capture=False, data=None, timeout=300):
            report['stage'] = argv[0]
            result = subprocess.run(['docker', *argv], input=data, stdout=subprocess.PIPE if capture else log,
                                    stderr=log, timeout=timeout, check=True)
            return result.stdout
        try:
            docker('info', timeout=20)
            docker('pull', IMAGE)
            image = docker('image', 'inspect', '--format', '{{.Id}}', IMAGE, capture=True).decode().strip()
            report['image_id'] = image
            docker(*container_args(name, image))
            docker('exec', '-i', name, 'tar', '-xf', '-', '-C', '/work', data=archive)
            docker('exec', name, 'npm', 'ci', '--ignore-scripts', '--no-audit', '--no-fund', timeout=600)
            # No external network while any lifecycle, test or build script runs.
            docker('network', 'disconnect', 'bridge', name)
            for command in [('npm', 'rebuild'), ('npm', 'run', 'test:types'),
                            ('npm', 'run', 'lint'), ('npm', 'run', 'test', '--', '--run'),
                            ('npm', 'run', 'build')]:
                report['active_check'] = list(command)
                docker('exec', name, *command, timeout=300)
                report['checks'].append(list(command))
            payload = docker('exec', name, '/usr/local/bin/node', '-e', EXPORT, capture=True)
            report['artifact_sha256'] = write_artifact(payload, output / 'dist')
            report['status'] = 'passed'
        except (subprocess.SubprocessError, OSError, ValueError) as exc:
            report['error'] = str(exc)
        finally:
            try:
                docker('rm', '--force', name, timeout=30)
            except (subprocess.SubprocessError, OSError):
                report['cleanup'] = 'Check/remove this container manually: ' + name
            report.pop('stage', None)
            (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'report': str(output / 'report.json')}))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
