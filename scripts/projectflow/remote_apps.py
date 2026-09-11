#!/usr/bin/env python3
"""Root-owned creation of isolated generated apps; never accepts host commands/config."""
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import remote
import install as demo
import frontend
from jobs import digest

STATE = Path('/var/lib/picoclaw-app-deploy')
CONFIG = Path('/opt/picoclaw-generated')
WEB = Path('/var/www/picoclaw-generated')
AVAILABLE = Path('/etc/nginx/sites-available')
ENABLED = Path('/etc/nginx/sites-enabled')
LIMIT = 10


def validate(request):
    if not isinstance(request, dict) or not re.fullmatch('[a-f0-9]{12}', request.get('app', '')):
        raise ValueError('Invalid app identity')
    if request == {'mode': 'status', 'app': request['app']}:
        return
    if request.get('mode') == 'release':
        if (set(request) != {'mode', 'app', 'slug', 'approval'}
                or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,48}[a-z0-9])?', request['slug'])
                or not re.fullmatch(r'[a-f0-9]{64}', request['approval'])):
            raise ValueError('Invalid release request')
        return
    if set(request) != {'mode', 'app', 'job', 'manifest', 'approval'} or request['mode'] != 'deploy' or request['job'] != request['app']:
        raise ValueError('Unsupported generated app request')
    m = request['manifest']
    full_fields = {'image', 'frontend', 'image_archive', 'frontend_file', 'previous', 'target', 'sources'}
    static_fields = {'profile', 'frontend', 'frontend_file', 'previous', 'target', 'sources'}
    fields = set(m) if isinstance(m, dict) else set()
    if fields not in (full_fields, full_fields | {'repository'}, static_fields, static_fields | {'repository'}):
        raise ValueError('Invalid app manifest')
    if m['previous'] is not None or m['target'] != 'app-' + request['app'] + '.marcusasplund.com' or digest(m) != request['approval']:
        raise ValueError('App target or approval mismatch')
    static = m.get('profile') == 'static'
    if not static and not re.fullmatch('sha256:[a-f0-9]{64}', m['image']):
        raise ValueError('Invalid image ID')
    for key in (['frontend', 'frontend_file'] if static else ['frontend', 'image_archive', 'frontend_file']):
        if not re.fullmatch('[a-f0-9]{64}', m[key]):
            raise ValueError('Invalid artifact digest')
    expected_sources = {'frontend'} if static else {'frontend', 'backend'}
    if set(m['sources']) != expected_sources or not all(re.fullmatch('[a-f0-9]{64}', x) for x in m['sources'].values()):
        raise ValueError('Invalid source digests')
    if 'repository' in m:
        repo = m['repository']
        if (not isinstance(repo, dict) or set(repo) != {'name', 'url', 'commit', 'commit_url', 'private', 'sources'}
                or repo['private'] is not True or repo['sources'] != m['sources']
                or not re.fullmatch(r'[A-Za-z0-9-]+/[a-z0-9-]+', repo['name'])
                or repo['url'] != 'https://github.com/' + repo['name']
                or not re.fullmatch(r'[a-f0-9]{40,64}', repo['commit'])
                or repo['commit_url'] != repo['url'] + '/commit/' + repo['commit']):
            raise ValueError('Invalid private repository receipt')


def free_port():
    used = {json.loads(p.read_text())['port'] for p in STATE.glob('*/reservation.json')}
    if len(used) >= LIMIT:
        raise ValueError('App limit reached; administrator must review capacity')
    for port in range(4200, 4300):
        if port in used:
            continue
        try:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', port))
            return port
        except OSError:
            continue
    raise ValueError('No free application port')


def compose_spec(project, port, image, database):
    spec = demo.spec(database)
    spec['name'] = project
    spec['services']['app']['ports'] = [f'127.0.0.1:{port}:4000']
    for service in ['app', 'migrate']:
        spec['services'][service]['image'] = image
        spec['services'][service]['entrypoint'] = ['bin/demo']
    spec['services']['app']['command'] = ['start']
    spec['services']['migrate']['command'] = ['eval', 'Demo.Release.migrate()']
    return spec


def nginx(host, port, webroot, tls, public=False):
    # Start from the same reviewed preview policy, substitute only trusted values.
    text = demo.nginx(tls, 'release')
    if public:
        text = text.replace('    auth_basic "PicoClaw preview";\n', '')
        text = text.replace('    auth_basic_user_file /etc/nginx/picoclaw-preview.htpasswd;\n', '')
    return (text.replace(demo.MARKER, '# Owned by picoclaw-generated\n')
            .replace(demo.HOST, host).replace(f'127.0.0.1:{demo.PORT}', f'127.0.0.1:{port}')
            .replace('/var/www/picoclaw-demo-preview/release', str(webroot)))


def static_nginx(host, webroot, tls, public=False):
    http = f'''server {{
    listen 80;
    listen [::]:80;
    server_name {host};
    location /.well-known/acme-challenge/ {{ root /var/www/picoclaw-acme; }}
    location / {{ {'return 301 https://$host$request_uri;' if tls else 'return 503;'} }}
}}
'''
    if not tls:
        return '# Owned by picoclaw-generated\n' + http
    auth = '' if public else f'''    auth_basic "PicoClaw preview";
    auth_basic_user_file {demo.AUTH};
'''
    return '# Owned by picoclaw-generated\n' + http + f'''server {{
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name {host};
    ssl_certificate /etc/letsencrypt/live/{host}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{host}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
{auth}    root {webroot};
    location / {{ try_files $uri $uri/ /index.html; }}
}}
'''


def handle(request, run):
    validate(request)
    ident = request['app']
    directory = STATE / ident
    root = CONFIG / ident
    project = 'picoclaw-app-' + ident
    host = 'app-' + ident + '.marcusasplund.com'
    available, enabled = AVAILABLE / project, ENABLED / project
    receipt_file = directory / 'receipt.json'
    if request['mode'] == 'status':
        version = json.loads(receipt_file.read_text())['version'] if receipt_file.exists() else None
        return {'version': version, 'pending': (directory / 'pending.json').exists()}
    if request['mode'] == 'release':
        if not receipt_file.exists():
            raise ValueError('Cannot release an app that is not deployed')
        receipt = json.loads(receipt_file.read_text())
        if receipt['approval'] != request['approval']:
            raise ValueError('Release approval does not match deployed app')
        existing = receipt.get('release')
        if existing:
            if existing['slug'] != request['slug']:
                raise ValueError('App already has another release hostname')
            return receipt
        host = request['slug'] + '.marcusasplund.com'
        public_available = AVAILABLE / ('picoclaw-public-' + request['slug'])
        public_enabled = ENABLED / ('picoclaw-public-' + request['slug'])
        if public_available.exists() or public_enabled.exists():
            raise ValueError('Release hostname already exists')
        if host in run('nginx', '-T', capture=True).decode():
            raise ValueError('Release hostname already appears in Nginx')
        static = receipt.get('profile') == 'static'
        port = None if static else json.loads((directory / 'reservation.json').read_text())['port']
        front_hash = receipt['version']['frontend']
        webroot = WEB / ident / front_hash
        def activate(tls):
            public_available.write_text(static_nginx(host, webroot, tls, public=True) if static else
                                        nginx(host, port, webroot, tls, public=True))
            public_available.chmod(0o644)
            if not public_enabled.is_symlink():
                public_enabled.symlink_to(public_available)
            run('nginx', '-t')
            run('systemctl', 'reload', 'nginx')
        try:
            cert = Path('/etc/letsencrypt/live') / host / 'fullchain.pem'
            if not cert.is_file():
                activate(False)
                run('certbot', 'certonly', '--webroot', '-w', '/var/www/picoclaw-acme', '-d', host,
                    '--non-interactive', '--agree-tos', '--email', 'rootfood@gmail.com', timeout=180)
            activate(True)
            for path in (['/'] if static else ['/', '/api/']):
                for _ in range(30):
                    try:
                        if run('curl', '--noproxy', '*', '--silent', '--show-error', '--max-time', '5',
                               '--resolve', host + ':443:127.0.0.1', '-o', '/dev/null', '-w', '%{http_code}',
                               'https://' + host + path, capture=True).strip() == b'200':
                            break
                    except (subprocess.CalledProcessError, ValueError):
                        pass
                    time.sleep(2)
                else:
                    raise ValueError('Public release readiness check failed')
            receipt['release'] = {'slug': request['slug'], 'url': 'https://' + host + '/',
                                  'host': host}
            temporary = directory / 'receipt.tmp'
            temporary.write_text(json.dumps(receipt) + '\n')
            temporary.replace(receipt_file)
            return {**receipt, 'slug': request['slug'], 'url': receipt['release']['url']}
        except BaseException:
            public_enabled.unlink(missing_ok=True)
            public_available.unlink(missing_ok=True)
            run('nginx', '-t')
            run('systemctl', 'reload', 'nginx')
            raise
    if receipt_file.exists():
        receipt = json.loads(receipt_file.read_text())
        if receipt['approval'] != request['approval']:
            raise ValueError('App already exists with another approval')
        return receipt
    pending_file = directory / 'pending.json'
    resume_static = False
    if pending_file.exists():
        pending = json.loads(pending_file.read_text())
        resume_static = pending == request and request['manifest'].get('profile') == 'static'
        if not resume_static:
            raise ValueError('Inspect unfinished app deployment before retrying')
    # Creation only. Never adopt or update an existing Compose project/site/path.
    if not resume_static:
        for path in [root, available, enabled, WEB / ident]:
            if path.exists() or path.is_symlink():
                raise ValueError('Refusing to adopt existing application resources')
    if not Path(demo.AUTH).is_file():
        raise ValueError('Preview authentication file missing')
    if host in run('nginx', '-T', capture=True).decode():
        raise ValueError('Host already appears in Nginx')
    m = request['manifest']
    if m.get('profile') != 'static':
        for kind in ['container', 'volume', 'network']:
            if run('docker', kind, 'ls', '-q', '--filter', 'label=com.docker.compose.project=' + project, capture=True).strip():
                raise ValueError('Compose resources already exist')
    directory.mkdir(mode=0o700, exist_ok=True)
    remote.copy_incoming(ident, 'frontend.json', directory / 'frontend.json', m['frontend_file'], 40 * 1024**2)
    front_hash, files = frontend.unpack(directory / 'frontend.json')
    if front_hash != m['frontend']:
        raise ValueError('Frontend hash mismatch')
    if m.get('profile') == 'static':
        pending_file.write_text(json.dumps(request) + '\n')
        def activate_static(tls):
            available.write_text(static_nginx(host, WEB / ident / front_hash, tls))
            available.chmod(0o644)
            if not enabled.is_symlink():
                enabled.symlink_to(available)
            run('nginx', '-t')
            run('systemctl', 'reload', 'nginx')
        try:
            old_web = frontend.WEBROOT
            try:
                frontend.WEBROOT = WEB / ident
                frontend.install_frontend(front_hash, files)
            finally:
                frontend.WEBROOT = old_web
            cert = Path('/etc/letsencrypt/live') / host / 'fullchain.pem'
            if not cert.is_file():
                activate_static(False)
                run('certbot', 'certonly', '--webroot', '-w', '/var/www/picoclaw-acme', '-d', host,
                    '--non-interactive', '--agree-tos', '--email', 'rootfood@gmail.com', timeout=180)
            activate_static(True)
            for _ in range(30):
                try:
                    if run('curl', '--noproxy', '*', '--silent', '--show-error', '--max-time', '5',
                           '--resolve', host + ':443:127.0.0.1', '-o', '/dev/null', '-w', '%{http_code}',
                           'https://' + host + '/', capture=True).strip() == b'401':
                        break
                except (subprocess.CalledProcessError, ValueError):
                    pass
                time.sleep(2)
            else:
                raise ValueError('Static preview readiness check failed')
            receipt = {'approval': request['approval'], 'version': {'frontend': front_hash},
                       'url': 'https://' + host + '/', 'profile': 'static'}
            temporary = directory / 'receipt.tmp'
            temporary.write_text(json.dumps(receipt) + '\n')
            temporary.replace(receipt_file)
            pending_file.unlink()
            return receipt
        except BaseException:
            enabled.unlink(missing_ok=True)
            available.unlink(missing_ok=True)
            run('nginx', '-t')
            run('systemctl', 'reload', 'nginx')
            raise
    port = free_port()
    remote.copy_incoming(ident, 'image.tar.gz', directory / 'image.tar.gz', m['image_archive'], 4 * 1024**3)
    remote.validate_image_archive(directory / 'image.tar.gz', m['image'])
    run('docker', 'load', '-i', str(directory / 'image.tar.gz'), timeout=900)
    if run('docker', 'image', 'inspect', '--format', '{{.Os}}/{{.Architecture}}', m['image'], capture=True).strip() != b'linux/amd64':
        raise ValueError('Expected linux/amd64')
    # Reuse only the pinned Postgres image identity, not any demo settings/data.
    database = json.loads((demo.ROOT / 'compose.json').read_text())['services']['db']['image']
    spec = compose_spec(project, port, m['image'], database)
    (directory / 'reservation.json').write_text(json.dumps({'port': port, 'host': host}) + '\n')
    (directory / 'pending.json').write_text(json.dumps(request) + '\n')
    def compose(*args, **kw):
        return run('docker', 'compose', '--project-name', project, '-f', str(root / 'compose.json'), *args, **kw)
    def poll(operation):
        for _ in range(30):
            try:
                if operation():
                    return
            except (subprocess.CalledProcessError, ValueError):
                pass
            time.sleep(2)
        raise ValueError('App readiness check failed')
    def activate(tls):
        available.write_text(nginx(host, port, WEB / ident / front_hash, tls))
        available.chmod(0o644)
        if not enabled.is_symlink():
            enabled.symlink_to(available)
        run('nginx', '-t')
        run('systemctl', 'reload', 'nginx')
    try:
        root.mkdir(mode=0o700)
        password = secrets.token_hex(32)
        demo.write_private(root / 'db.env', f'POSTGRES_DB=preview\nPOSTGRES_USER=postgres\nPOSTGRES_PASSWORD={password}\n')
        demo.write_private(root / 'app.env', '\n'.join([
            f'DATABASE_URL=ecto://postgres:{password}@db:5432/preview',
            'SECRET_KEY_BASE=' + secrets.token_hex(64), 'RELEASE_COOKIE=' + secrets.token_hex(32),
            'PHX_HOST=' + host, 'PORT=4000', 'PHX_SERVER=true']) + '\n')
        demo.write_private(root / 'compose.json', json.dumps(spec, indent=2) + '\n')
        old_web = frontend.WEBROOT
        try:
            frontend.WEBROOT = WEB / ident
            frontend.install_frontend(front_hash, files)
        finally:
            frontend.WEBROOT = old_web
        compose('config', '--quiet')
        compose('up', '-d', 'db')
        def db_ok():
            compose('exec', '-T', 'db', 'pg_isready', '-h', '127.0.0.1', '-U', 'postgres')
            return True
        poll(db_ok)
        compose('--profile', 'migration', 'run', '--rm', '--no-deps', 'migrate', timeout=180)
        compose('up', '-d', 'app')
        poll(lambda: json.loads(run('curl', '--noproxy', '*', '--fail', '--silent', '--max-time', '5',
                                    f'http://127.0.0.1:{port}/api/', capture=True)) == {'status': 'ok'})
        container = compose('ps', '-q', 'app', capture=True).decode().strip()
        if run('docker', 'inspect', '--format', '{{.Image}}', container, capture=True).decode().strip() != m['image']:
            raise ValueError('Wrong running image')
        cert = Path('/etc/letsencrypt/live') / host / 'fullchain.pem'
        if not cert.is_file():
            activate(False)
            run('certbot', 'certonly', '--webroot', '-w', '/var/www/picoclaw-acme', '-d', host,
                '--non-interactive', '--agree-tos', '--email', 'rootfood@gmail.com', timeout=180)
        activate(True)
        for path in ['/', '/api/']:
            poll(lambda: run('curl', '--noproxy', '*', '--silent', '--show-error', '--max-time', '5',
                             '--resolve', host + ':443:127.0.0.1', '-o', '/dev/null', '-w', '%{http_code}',
                             'https://' + host + path, capture=True).strip() == b'401')
        receipt = {'approval': request['approval'], 'version': {'image': m['image'], 'frontend': front_hash},
                   'url': 'https://' + host + '/', 'project': project}
        temporary = directory / 'receipt.tmp'
        temporary.write_text(json.dumps(receipt) + '\n')
        temporary.replace(receipt_file)
        (directory / 'pending.json').unlink()
        return receipt
    except BaseException:
        # Only resources exclusively created above; preserve DB and journal for inspection.
        enabled.unlink(missing_ok=True)
        available.unlink(missing_ok=True)
        run('nginx', '-t')
        run('systemctl', 'reload', 'nginx')
        if (root / 'compose.json').exists():
            compose('stop', 'app')
        raise


def main():
    if os.geteuid() != 0 or len(sys.argv) != 1:
        raise SystemExit('Requires root with no arguments')
    os.umask(0o077)
    for path in [STATE, CONFIG, WEB]:
        if path.is_symlink():
            raise SystemExit('Unsafe root directory')
        path.mkdir(mode=0o755 if path == WEB else 0o700, exist_ok=True)
    with (STATE / 'lock').open('w') as lock, (STATE / 'deploy.log').open('ab') as log:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        def run(*args, capture=False, timeout=300):
            return subprocess.run(args, check=True, timeout=timeout, stderr=log,
                                  stdout=subprocess.PIPE if capture else log).stdout
        try:
            raw = sys.stdin.buffer.read(8193)
            if len(raw) > 8192:
                raise ValueError('Request too large')
            print(json.dumps(handle(json.loads(raw), run)))
        except Exception as exc:
            log.write((type(exc).__name__ + ': ' + str(exc) + '\n').encode())
            raise SystemExit('App deploy failed; inspect /var/lib/picoclaw-app-deploy/deploy.log')


if __name__ == '__main__':
    main()
