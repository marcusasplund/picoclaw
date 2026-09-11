#!/usr/bin/env python3
"""Root-owned, no-argument deployment endpoint for the single demo project."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile
import time

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str((BASE if (BASE / 'demo-preview').exists() else BASE.parent) / 'demo-preview'))
import install as demo
from frontend import unpack, install_frontend
from jobs import digest

STATE = Path('/var/lib/picoclaw-demo-deploy')
INCOMING = Path('/home/picodeploy/projectflow-incoming')


def validate(request):
    if request == {'mode': 'status'}:
        return
    if set(request) != {'mode', 'job', 'manifest', 'approval'} or request['mode'] != 'deploy':
        raise ValueError('Unsupported request')
    if not re.fullmatch('[a-f0-9]{12}', request['job']):
        raise ValueError('Invalid job')
    m = request['manifest']
    if set(m) != {'image', 'frontend', 'image_archive', 'frontend_file', 'previous', 'target', 'sources'}:
        raise ValueError('Invalid manifest')
    if m['target'] != 'preview-demo.marcusasplund.com' or digest(m) != request['approval']:
        raise ValueError('Approval mismatch')
    for version in [m, m['previous']]:
        if not re.fullmatch('sha256:[a-f0-9]{64}', version['image']) or not re.fullmatch('[a-f0-9]{64}', version['frontend']):
            raise ValueError('Invalid version')
    for key in ['image_archive', 'frontend_file']:
        if not re.fullmatch('[a-f0-9]{64}', m[key]):
            raise ValueError('Invalid file hash')


def copy_incoming(job, name, target, expected, limit):
    # A pre-deploy validation failure may leave a complete root-owned copy.
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_file() or target.stat().st_size > limit:
            raise ValueError('Unsafe existing archive')
        with target.open('rb') as existing:
            if hashlib.file_digest(existing, 'sha256').hexdigest() != expected:
                raise ValueError('Existing archive differs from approval; administrator review required')
        return
    # Open each untrusted path component relative to a held directory descriptor.
    with_fd = os.open(INCOMING, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        jobfd = os.open(job, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=with_fd)
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=jobfd)
            with os.fdopen(fd, 'rb') as source, target.open('xb') as output:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                    raise ValueError('Invalid incoming file')
                h = hashlib.sha256()
                size = 0
                while data := source.read(1024 * 1024):
                    size += len(data)
                    if size > limit:
                        raise ValueError('Incoming file too large')
                    h.update(data)
                    output.write(data)
                if h.hexdigest() != expected:
                    raise ValueError('Incoming file differs from approval')
        finally:
            os.close(jobfd)
    finally:
        os.close(with_fd)


def validate_image_archive(path, expected):
    # Do not let docker load replace tags belonging to other applications.
    with tarfile.open(path, 'r:gz') as tar:
        total = 0
        count = 0
        names = set()
        for item in tar:
            if item.name in names:
                raise ValueError('Duplicate archive member')
            names.add(item.name)
            count += 1
            total += item.size
            if count > 10000 or total > 12 * 1024**3 or not (item.isfile() or item.isdir()):
                raise ValueError('Invalid image archive')
        member = tar.getmember('manifest.json')
        if member.size > 65536:
            raise ValueError('Image manifest too large')
        manifest = json.load(tar.extractfile(member))
        if len(manifest) != 1 or manifest[0].get('RepoTags'):
            raise ValueError('Expected one untagged image exported by ID')
        config = tar.getmember(manifest[0]['Config'])
        if config.size > 1024**2:
            raise ValueError('Image config too large')
        config_hash = 'sha256:' + hashlib.sha256(tar.extractfile(config).read()).hexdigest()
        if config_hash != expected:
            validate_oci_identity(tar, expected, config_hash)


def validate_oci_identity(tar, expected, config_hash):
    """Docker containerd IDs identify an OCI manifest/index, not config JSON."""
    def read_json(name):
        member = tar.getmember(name)
        if not member.isfile() or member.size > 1024**2:
            raise ValueError('Invalid OCI metadata')
        data = tar.extractfile(member).read()
        return data, json.loads(data)

    def check_names(value):
        for key in ('org.opencontainers.image.ref.name', 'io.containerd.image.name'):
            annotation = value.get('annotations', {}).get(key)
            if annotation is not None and annotation not in (expected, expected.removeprefix('sha256:')):
                raise ValueError('Tagged OCI image is not allowed')

    _, index = read_json('index.json')
    check_names(index)
    roots = index.get('manifests', [])
    if len(roots) != 1 or roots[0].get('digest') != expected:
        raise ValueError('OCI index does not identify the approved image')
    seen = set()
    found = False
    def visit(descriptor, depth=0):
        nonlocal found
        check_names(descriptor)
        value = descriptor.get('digest', '')
        if depth > 8 or len(seen) >= 32 or not re.fullmatch('sha256:[a-f0-9]{64}', value):
            raise ValueError('Invalid OCI descriptor graph')
        if value in seen:
            return
        seen.add(value)
        data, node = read_json('blobs/sha256/' + value.split(':')[1])
        if 'sha256:' + hashlib.sha256(data).hexdigest() != value or descriptor.get('size') != len(data):
            raise ValueError('OCI descriptor digest or size mismatch')
        check_names(node)
        if 'manifests' in node:
            for child in node['manifests']:
                visit(child, depth + 1)
        elif 'config' in node:
            config_desc = node['config']
            if config_desc.get('digest') == config_hash:
                config_data, _ = read_json('blobs/sha256/' + config_hash.split(':')[1])
                if ('sha256:' + hashlib.sha256(config_data).hexdigest() != config_hash
                        or config_desc.get('size') != len(config_data)):
                    raise ValueError('OCI config descriptor mismatch')
                found = True
        else:
            raise ValueError('Unsupported OCI image metadata')
    visit(roots[0])
    if not found:
        raise ValueError('Approved OCI image does not reference the exported config')


def handle(request, run):
    validate(request)
    def compose(*args, **kw):
        return run('docker', 'compose', '--project-name', demo.PROJECT, '-f', str(demo.ROOT / 'compose.json'), *args, **kw)
    config_path = demo.ROOT / 'compose.json'
    config = json.loads(config_path.read_text())
    version = {'image': config['services']['app']['image'],
               'frontend': (demo.ROOT / 'frontend-hash').read_text().strip()}
    if request['mode'] == 'status':
        return {'version': version, 'pending': (STATE / 'pending.json').exists()}
    directory = STATE / request['job']
    receipt_file = directory / 'receipt.json'
    if receipt_file.exists():
        receipt = json.loads(receipt_file.read_text())
        if receipt['approval'] != request['approval']:
            raise ValueError('Job ID reused with different approval')
        return receipt
    if (STATE / 'pending.json').exists():
        raise ValueError('Prior deployment needs administrator review')
    manifest = request['manifest']
    if manifest['previous'] != version:
        raise ValueError('Another deployment changed the demo; approval is stale')
    if not demo.AVAILABLE.read_text().startswith(demo.MARKER) or not demo.ENABLED.is_symlink() or demo.ENABLED.readlink() != demo.AVAILABLE:
        raise ValueError('Existing demo Nginx configuration is not owned')
    if directory.is_symlink():
        raise ValueError('Unsafe existing job directory')
    directory.mkdir(mode=0o700, exist_ok=True)
    copy_incoming(request['job'], 'image.tar.gz', directory / 'image.tar.gz', manifest['image_archive'], 4 * 1024**3)
    copy_incoming(request['job'], 'frontend.json', directory / 'frontend.json', manifest['frontend_file'], 40 * 1024**2)
    frontend_hash, files = unpack(directory / 'frontend.json')
    if frontend_hash != manifest['frontend']:
        raise ValueError('Frontend digest mismatch')
    validate_image_archive(directory / 'image.tar.gz', manifest['image'])
    run('docker', 'load', '-i', str(directory / 'image.tar.gz'), timeout=900)
    platform = run('docker', 'image', 'inspect', '--format', '{{.Os}}/{{.Architecture}}', manifest['image'], capture=True).strip()
    if platform != b'linux/amd64':
        raise ValueError('Expected Lenovo linux/amd64 image')
    # Root-owned template only. No incoming Compose, Dockerfile, path or command.
    updated = demo.spec(config['services']['db']['image'])
    for name in ['app', 'migrate']:
        updated['services'][name]['image'] = manifest['image']
        updated['services'][name]['entrypoint'] = ['bin/demo']
    updated['services']['app']['command'] = ['start']
    updated['services']['migrate']['command'] = ['eval', 'Demo.Release.migrate()']
    old_config, old_nginx = config_path.read_bytes(), demo.AVAILABLE.read_bytes()
    (directory / 'compose.before.json').write_bytes(old_config)
    (directory / 'nginx.before').write_bytes(old_nginx)
    (STATE / 'pending.json').write_text(json.dumps(request) + '\n')
    try:
        # Backup stays root-only and never leaves Lenovo.
        with (directory / 'database.dump').open('xb') as backup:
            run('docker', 'compose', '--project-name', demo.PROJECT, '-f', str(config_path),
                'exec', '-T', 'db', 'pg_dump', '-U', 'postgres', '-d', 'preview', '-Fc', output=backup)
        install_frontend(frontend_hash, files)
        config_path.write_text(json.dumps(updated, indent=2) + '\n')
        compose('config', '--quiet')
        compose('--profile', 'migration', 'run', '--rm', '--no-deps', 'migrate', timeout=180)
        compose('up', '-d', '--no-deps', 'app')
        good = False
        for _ in range(30):
            try:
                response = run('curl', '--noproxy', '*', '--fail', '--silent', '--max-time', '5',
                               'http://127.0.0.1:4188/api/counter', capture=True)
                value = json.loads(response).get('value')
                if type(value) is int and value >= 0:
                    good = True
                    break
            except subprocess.CalledProcessError:
                pass
            time.sleep(2)
        if not good:
            raise ValueError('Demo database/HTTP health failed')
        container = compose('ps', '-q', 'app', capture=True).decode().strip()
        if run('docker', 'inspect', '--format', '{{.Image}}', container, capture=True).decode().strip() != manifest['image']:
            raise ValueError('Wrong running image')
        demo.AVAILABLE.write_text(demo.nginx(True, frontend_hash))
        demo.AVAILABLE.chmod(0o644)
        run('nginx', '-t')
        run('systemctl', 'reload', 'nginx')
        good = False
        for _ in range(10):
            code = run('curl', '--noproxy', '*', '--silent', '--show-error', '--max-time', '5',
                '--resolve', demo.HOST + ':443:127.0.0.1', '-o', '/dev/null', '-w', '%{http_code}',
                'https://' + demo.HOST + '/', capture=True)
            if code == b'401':
                good = True
                break
            time.sleep(1)
        if not good:
            raise ValueError('HTTPS/auth check failed')
        (demo.ROOT / 'frontend-hash').write_text(frontend_hash + '\n')
        (demo.ROOT / 'image-id').write_text(manifest['image'] + '\n')
        receipt = {'approval': request['approval'], 'version': {'image': manifest['image'], 'frontend': frontend_hash},
                   'url': 'https://' + demo.HOST + '/'}
        receipt_file.write_text(json.dumps(receipt) + '\n')
        (demo.ROOT / 'receipt.json').write_text(json.dumps(receipt) + '\n')
        (STATE / 'pending.json').unlink()
        return receipt
    except BaseException:
        config_path.write_bytes(old_config)
        demo.AVAILABLE.write_bytes(old_nginx)
        demo.AVAILABLE.chmod(0o644)
        (demo.ROOT / 'frontend-hash').write_text(version['frontend'] + '\n')
        (demo.ROOT / 'image-id').write_text(version['image'] + '\n')
        compose('up', '-d', '--no-deps', 'app')
        run('nginx', '-t')
        run('systemctl', 'reload', 'nginx')
        # Keep pending journal: database migrations are not automatically reverted.
        raise


def main():
    if os.geteuid() != 0 or len(sys.argv) != 1:
        raise SystemExit('Requires root with no arguments')
    os.umask(0o077)
    STATE.mkdir(mode=0o700, exist_ok=True)
    with (STATE / 'lock').open('w') as lock, (STATE / 'deploy.log').open('ab') as log:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        raw = sys.stdin.buffer.read(8193)
        if len(raw) > 8192:
            raise SystemExit('Request too large')
        request = json.loads(raw)
        def run(*args, capture=False, output=None, timeout=300):
            return subprocess.run(args, check=True, timeout=timeout, stderr=log,
                stdout=subprocess.PIPE if capture else (output if output is not None else log)).stdout
        try:
            print(json.dumps(handle(request, run)))
        except Exception as exc:
            log.write((type(exc).__name__ + ': ' + str(exc) + '\n').encode())
            print(json.dumps({'error': 'Demo deploy failed; inspect root-owned deploy.log and pending journal'}))
            raise SystemExit(1)


if __name__ == '__main__':
    main()
