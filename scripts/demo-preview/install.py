#!/usr/bin/env python3
"""Manual, fixed-target Lenovo preview. Run as administrator, never via agent sudo."""
import argparse
import copy
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time
from frontend import unpack, install_frontend

IMAGE = 'sha256:81024bd935acebb9f052f2bedc3b83fcce566598c30fc7353624d548f3827a25'
HOST = 'preview-demo.marcusasplund.com'
PROJECT = 'picoclaw-demo-preview'
ROOT = Path('/opt/picoclaw-demo-preview')
PORT = 4188
AUTH = '/etc/nginx/picoclaw-preview.htpasswd'
AVAILABLE = Path('/etc/nginx/sites-available/picoclaw-demo-preview')
ENABLED = Path('/etc/nginx/sites-enabled/picoclaw-demo-preview')
MARKER = '# Owned by picoclaw-demo-preview\n'


def spec(dbimage):
    app = {'image': IMAGE, 'pull_policy': 'never', 'user': '1000:1000',
           'read_only': True, 'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'],
           'tmpfs': ['/tmp:rw,noexec,nosuid,nodev,size=128m,uid=1000,gid=1000'],
           'env_file': ['app.env'], 'networks': ['private'], 'pids_limit': 256,
           'mem_limit': '1g', 'cpus': 2, 'logging': {'driver': 'json-file',
           'options': {'max-size': '10m', 'max-file': '3'}}}
    migration = copy.deepcopy(app)
    migration.update({'profiles': ['migration'], 'restart': 'no',
                      'command': ['bin/demo', 'eval', 'Demo.Release.migrate()']})
    app.update({'networks': ['private', 'web'], 'restart': 'unless-stopped', 'ports': [f'127.0.0.1:{PORT}:4000'],
                'depends_on': {'db': {'condition': 'service_healthy'}}})
    return {'name': PROJECT, 'services': {'app': app, 'migrate': migration,
            'db': {'image': dbimage, 'pull_policy': 'never', 'env_file': ['db.env'],
                   'restart': 'unless-stopped', 'networks': ['private'],
                   'volumes': ['data:/var/lib/postgresql/data'], 'mem_limit': '512m',
                   'cpus': 1, 'pids_limit': 128,
                   'logging': app['logging'], 'healthcheck': {
                       'test': ['CMD', 'pg_isready', '-h', '127.0.0.1', '-U', 'postgres'],
                       'interval': '2s', 'timeout': '3s', 'retries': 30}}},
            'volumes': {'data': {}}, 'networks': {'private': {'internal': True}, 'web': {}}}


def nginx(tls, digest):
    http = f'''server {{
    listen 80;
    listen [::]:80;
    server_name {HOST};
    location /.well-known/acme-challenge/ {{ root /var/www/picoclaw-acme; }}
    location / {{ {'return 301 https://$host$request_uri;' if tls else 'return 503;'} }}
}}
'''
    if not tls:
        return MARKER + http
    return MARKER + http + f'''server {{
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name {HOST};
    ssl_certificate /etc/letsencrypt/live/{HOST}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{HOST}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    auth_basic "PicoClaw preview";
    auth_basic_user_file {AUTH};
    root /var/www/picoclaw-demo-preview/{digest};
    location / {{ try_files $uri $uri/ /index.html; }}
    location /api/ {{
        proxy_pass http://127.0.0.1:{PORT};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Authorization "";
    }}
}}
'''


def write_private(path, text):
    with open(path, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as file:
        file.write(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('frontend', type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run with sudo python3 install.py IMAGE.tar.gz')
    digest, files = unpack(args.frontend)
    os.umask(0o077)
    # Log commands' output, never print resolved Compose/env configuration.
    with open('/var/log/picoclaw-demo-preview.log', 'ab') as log:
        def run(*cmd, capture=False, timeout=300):
            return subprocess.run(cmd, check=True, timeout=timeout, stderr=log,
                                  stdout=subprocess.PIPE if capture else log).stdout

        def compose(*cmd, **kw):
            return run('docker', 'compose', '--project-name', PROJECT, '--project-directory', str(ROOT),
                       '-f', str(ROOT / 'compose.json'), *cmd, **kw)

        def announce(message):
            print(message, flush=True)
            log.write(('\n' + message + '\n').encode())
            log.flush()

        def poll(check):
            for _ in range(30):
                try:
                    if check():
                        return
                except subprocess.CalledProcessError:
                    pass
                time.sleep(2)
            raise RuntimeError('Health check timed out; inspect /var/log/picoclaw-demo-preview.log')

        announce('Kontrollerar Docker, Nginx och preview-inloggning')
        run('docker', 'compose', 'version')
        run('nginx', '-t')
        if not Path(AUTH).is_file():
            raise RuntimeError('Existing preview htpasswd file is missing')
        if AVAILABLE.is_symlink() or (AVAILABLE.exists() and not AVAILABLE.read_text().startswith(MARKER)):
            raise RuntimeError('Refusing to replace unowned Nginx configuration')
        if ENABLED.exists() or ENABLED.is_symlink():
            if not ENABLED.is_symlink() or ENABLED.readlink() != AVAILABLE:
                raise RuntimeError('Refusing to replace unowned Nginx link')
        new = not ROOT.exists()
        if new:
            config = run('nginx', '-T', capture=True).decode()
            if HOST in config:
                raise RuntimeError('Hostname already occurs in Nginx configuration')
            for kind in ['container', 'volume', 'network']:
                if run('docker', kind, 'ls', '-q', '--filter', 'label=com.docker.compose.project=' + PROJECT,
                       capture=True).strip():
                    raise RuntimeError('Compose project already exists; inspect before adopting it')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', PORT))
        else:
            if ROOT.is_symlink() or (ROOT / 'image-id').read_text().strip() != IMAGE:
                raise RuntimeError('Existing preview state does not match this image')
        announce('Läser in och kontrollerar den godkända imagen')
        run('docker', 'load', '-i', str(args.archive.resolve()), timeout=900)
        actual = run('docker', 'image', 'inspect', '--format', '{{.Id}}', IMAGE, capture=True).decode().strip()
        if actual != IMAGE:
            raise RuntimeError('Image ID mismatch')
        platform = run('docker', 'image', 'inspect', '--format', '{{.Os}}/{{.Architecture}}', IMAGE,
                       capture=True).decode().strip()
        machine = os.uname().machine
        expected = {'x86_64': 'linux/amd64', 'aarch64': 'linux/arm64'}.get(machine)
        if platform != expected:
            raise RuntimeError('Image architecture differs from Lenovo: ' + platform)
        if new:
            run('docker', 'pull', 'postgres:16-bookworm', timeout=600)
            dbimage = run('docker', 'image', 'inspect', '--format', '{{.Id}}', 'postgres:16-bookworm',
                          capture=True).decode().strip()
            ROOT.mkdir(mode=0o700)
            write_private(ROOT / 'image-id', IMAGE + '\n')
            password = secrets.token_hex(32)
            write_private(ROOT / 'db.env', 'POSTGRES_DB=preview\nPOSTGRES_USER=postgres\nPOSTGRES_PASSWORD=' + password + '\n')
            write_private(ROOT / 'app.env', '\n'.join([
                'DATABASE_URL=ecto://postgres:' + password + '@db:5432/preview',
                'SECRET_KEY_BASE=' + secrets.token_hex(64),
                'RELEASE_COOKIE=' + secrets.token_hex(32), 'PHX_HOST=' + HOST,
                'PORT=4000', 'PHX_SERVER=true', 'TRUST_FORWARDED_FOR=true']) + '\n')
            write_private(ROOT / 'compose.json', json.dumps(spec(dbimage), indent=2) + '\n')
        if (ROOT / 'frontend-hash').exists() and (ROOT / 'frontend-hash').read_text().strip() != digest:
            raise RuntimeError('Existing frontend differs; this installer does not update releases')
        install_frontend(digest, files)
        if not (ROOT / 'frontend-hash').exists():
            write_private(ROOT / 'frontend-hash', digest + '\n')
        compose('config', '--quiet')
        announce('Startar egen databas och kör release-migrationer')
        compose('up', '-d', 'db')
        poll(lambda: compose('exec', '-T', 'db', 'pg_isready', '-h', '127.0.0.1', '-U', 'postgres') is None)
        compose('--profile', 'migration', 'run', '--rm', '--no-deps', 'migrate', timeout=180)
        compose('up', '-d', 'app')
        def app_ok():
            body = run('curl', '--noproxy', '*', '--fail', '--silent', '--max-time', '5',
                       f'http://127.0.0.1:{PORT}/api/', capture=True)
            counter = run('curl', '--noproxy', '*', '--fail', '--silent', '--max-time', '5',
                          f'http://127.0.0.1:{PORT}/api/counter', capture=True)
            value = json.loads(counter).get('value')
            return json.loads(body).get('status') == 'ok' and type(value) is int and value >= 0
        poll(app_ok)
        container = compose('ps', '-q', 'app', capture=True).decode().strip()
        if run('docker', 'inspect', '--format', '{{.Image}}', container, capture=True).decode().strip() != IMAGE:
            raise RuntimeError('Running image differs from approved image')
        announce('Installerar skyddad HTTPS-host och verifierar certifikat/inloggningskrav')
        previous = AVAILABLE.read_bytes() if AVAILABLE.exists() else None
        had_link = ENABLED.is_symlink()
        def activate(text):
            AVAILABLE.write_text(text)
            AVAILABLE.chmod(0o644)
            if not ENABLED.is_symlink():
                ENABLED.symlink_to(AVAILABLE)
            run('nginx', '-t')
            run('systemctl', 'reload', 'nginx')
        try:
            if not Path(f'/etc/letsencrypt/live/{HOST}/fullchain.pem').is_file():
                Path('/var/www/picoclaw-acme').mkdir(exist_ok=True)
                activate(nginx(False, digest))
                run('certbot', 'certonly', '--webroot', '-w', '/var/www/picoclaw-acme',
                    '-d', HOST, '--non-interactive', '--agree-tos', '--email', 'rootfood@gmail.com', timeout=180)
            activate(nginx(True, digest))
            def protected():
                code = run('curl', '--noproxy', '*', '--silent', '--show-error', '--max-time', '5',
                           '--resolve', HOST + ':443:127.0.0.1', '-o', '/dev/null', '-w', '%{http_code}',
                           'https://' + HOST + '/api/', capture=True)
                return code.strip() == b'401'
            poll(protected)
        except BaseException:
            if previous is None:
                AVAILABLE.unlink(missing_ok=True)
            else:
                AVAILABLE.write_bytes(previous)
                AVAILABLE.chmod(0o644)
            if not had_link:
                ENABLED.unlink(missing_ok=True)
            run('nginx', '-t')
            run('systemctl', 'reload', 'nginx')
            raise
        (ROOT / 'receipt.json').write_text(json.dumps({'status': 'passed', 'image_id': IMAGE,
            'frontend_hash': digest, 'url': 'https://' + HOST + '/', 'project': PROJECT, 'platform': platform}, indent=2) + '\n')
        announce('Klart: https://' + HOST + '/ — använd befintlig preview-inloggning')


if __name__ == '__main__':
    main()
