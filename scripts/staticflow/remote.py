#!/usr/bin/python3
"""Root-owned, narrow sudo entry point. Accepts three static files; never runs them."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import logging

BASE=Path('/var/www/picoclaw-static')
ACME=Path('/var/www/picoclaw-acme')
AVAILABLE=Path('/etc/nginx/sites-available')
ENABLED=Path('/etc/nginx/sites-enabled')
AUTH='/etc/nginx/picoclaw-preview.htpasswd'

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=True).encode()).hexdigest()

def validate(data):
    if data.get('mode') not in ('preview','publish','delete'): raise ValueError('mode')
    slug=data.get('slug','')
    if not re.fullmatch(r'app-[a-z0-9]+(?:-[a-z0-9]+)*',slug) or len(slug)>40: raise ValueError('slug')
    files=data.get('files')
    if not isinstance(files,dict) or set(files)!={'index.html','style.css','app.js'}: raise ValueError('files')
    if any(not isinstance(v,str) or len(v.encode())>150000 for v in files.values()): raise ValueError('file size')
    if data.get('digest') != digest(files): raise ValueError('digest')
    return data

def run(*args):
    return subprocess.run(args,capture_output=True,text=True,check=True,timeout=120).stdout

def wait_healthy(host, version):
    # systemctl reload returns before Nginx has necessarily switched workers.
    last='wrong version'
    for attempt in range(10):
        try:
            actual=run('curl','--noproxy','*','--fail','--silent','--show-error',
                       '--max-time','3','--resolve',host+':443:127.0.0.1',
                       'https://'+host+'/__picoclaw_health')
            if actual==version: return
            last='wrong version'
        except subprocess.CalledProcessError as exc:
            last='curl exit '+str(exc.returncode)
            logging.warning('Health check attempt %s failed: %s',attempt+1,exc.stderr)
        except subprocess.TimeoutExpired:
            last='curl timeout'
        if attempt<9: time.sleep(1)
    raise ValueError('health check failed: '+last)

def atomic(path, text):
    fd,name=tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f: f.write(text)
        os.chmod(name,0o644);os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)

def http(host):
    return f'''server {{
 listen 80;
 listen [::]:80;
 server_name {host};
 location /.well-known/acme-challenge/ {{ root {ACME}; }}
 location / {{ return 301 https://{host}$request_uri; }}
}}
'''

def config(host,release,version,preview):
    auth=f'auth_basic "PicoClaw preview"; auth_basic_user_file {AUTH};' if preview else ''
    return http(host)+f'''server {{
 listen 443 ssl;
 listen [::]:443 ssl;
 server_name {host};
 ssl_certificate /etc/letsencrypt/live/{host}/fullchain.pem;
 ssl_certificate_key /etc/letsencrypt/live/{host}/privkey.pem;
 root {release};
 index index.html;
 {auth}
 add_header X-Content-Type-Options nosniff always;
 add_header Referrer-Policy no-referrer always;
 add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'" always;
 location = /__picoclaw_health {{ auth_basic off; default_type text/plain; return 200 "{version}"; }}
 location ~ /\\. {{ deny all; }}
 location / {{ try_files $uri $uri/ =404; }}
}}
'''

def gone_config(host,version):
    # Keep the correct certificate and an explicit 410 instead of falling through
    # to another hosted site's default vhost after removing an enabled file.
    return http(host)+f'''server {{
 listen 443 ssl;
 listen [::]:443 ssl;
 server_name {host};
 ssl_certificate /etc/letsencrypt/live/{host}/fullchain.pem;
 ssl_certificate_key /etc/letsencrypt/live/{host}/privkey.pem;
 # picoclaw-deleted {version}
 default_type text/plain;
 return 410 "Appen har tagits ned.\\n";
}}
'''

def wait_gone(host):
    for attempt in range(10):
        try:
            status=run('curl','--noproxy','*','--silent','--show-error','--output','/dev/null',
                       '--write-out','%{http_code}','--max-time','3','--resolve',
                       host+':443:127.0.0.1','https://'+host+'/')
            if status=='410': return
        except (subprocess.CalledProcessError,subprocess.TimeoutExpired): pass
        if attempt<9: time.sleep(1)
    raise ValueError('withdrawal health check failed')

def withdraw(data,cfg):
    slug=data['slug'];version=data['digest'];domain=cfg['domain']
    release=BASE/slug/version
    sites=[]
    for host in (slug+'.'+domain,'preview-'+slug+'.'+domain):
        site=AVAILABLE/('picoclaw-'+host);link=ENABLED/site.name
        if not link.exists() and not link.is_symlink(): continue
        if not link.is_symlink() or link.resolve()!=site.resolve():
            raise ValueError('unexpected enabled site')
        old=site.read_text()
        if f'root {release};' not in old and f'# picoclaw-deleted {version}' not in old:
            raise ValueError('refusing to withdraw another version')
        sites.append((host,site,old))
    backup=BASE/slug/'withdrawn'/version
    backup.mkdir(parents=True,exist_ok=True,mode=0o755)
    for host,site,old in sites:
        # Keep the original active configuration even on an idempotent retry.
        saved=backup/site.name
        if not saved.exists(): atomic(saved,old)
    try:
        for host,site,old in sites: atomic(site,gone_config(host,version))
        if sites:
            run('nginx','-t');run('systemctl','reload','nginx')
            for host,site,old in sites: wait_gone(host)
    except Exception:
        for host,site,old in sites: atomic(site,old)
        run('nginx','-t');run('systemctl','reload','nginx')
        raise
    return {'url':'https://'+slug+'.'+domain,'digest':version,'deleted':True}

def deploy(data,cfg):
    slug=data['slug'];version=data['digest'];preview=data['mode']=='preview'
    domain=cfg['domain']
    if domain!='marcusasplund.com': raise ValueError('domain')
    if data['mode']=='delete': return withdraw(data,cfg)
    host=('preview-' if preview else '')+slug+'.'+domain
    release=BASE/slug/version
    release.mkdir(parents=True,exist_ok=True,mode=0o755)
    for name,contents in data['files'].items():
        path=release/name
        if path.exists() and path.read_text()!=contents: raise ValueError('immutable release changed')
        if not path.exists(): atomic(path,contents)
    site=AVAILABLE/('picoclaw-'+host)
    link=ENABLED/site.name
    old=site.read_text() if site.exists() else None
    linked=link.is_symlink()
    if link.exists() and not linked: raise ValueError('unexpected enabled file')
    try:
        cert=Path('/etc/letsencrypt/live')/host/'fullchain.pem'
        if not cert.exists():
            atomic(site,http(host))
            if not linked: link.symlink_to(site)
            run('nginx','-t');run('systemctl','reload','nginx')
            run('certbot','certonly','--webroot','-w',str(ACME),'-d',host,
                '--cert-name',host,'--non-interactive','--agree-tos','--email',cfg['email'])
        atomic(site,config(host,release,version,preview))
        if not link.is_symlink(): link.symlink_to(site)
        run('nginx','-t');run('systemctl','reload','nginx')
        wait_healthy(host,version)
    except Exception:
        if old is None:
            if link.is_symlink(): link.unlink()
            site.unlink(missing_ok=True)
        else:
            atomic(site,old)
            if not linked and link.is_symlink(): link.unlink()
        run('nginx','-t');run('systemctl','reload','nginx')
        raise
    return {'url':'https://'+host,'digest':version}

if __name__=='__main__':
    try:
        if os.geteuid()!=0: raise ValueError('root required')
        os.umask(0o077)
        logging.basicConfig(filename='/var/log/picoclaw-static.log',level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
        os.umask(0o022)
        data=validate(json.loads(sys.stdin.buffer.read(600001)))
        cfg=json.loads(Path('/etc/picoclaw-static.json').read_text())
        with open('/run/lock/picoclaw-static.lock','w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            print(json.dumps(deploy(data,cfg)))
    except Exception as exc:
        logging.exception('Static deployment failed')
        if isinstance(exc,subprocess.CalledProcessError):
            logging.error('Command stderr: %s',exc.stderr)
        print('Static deployment failed; see /var/log/picoclaw-static.log.',file=sys.stderr)
        sys.exit(1)
