import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str((BASE if (BASE / 'projectbuild').exists() else BASE.parent) / 'projectbuild'))
sys.path.insert(0, str((BASE if (BASE / 'demo-preview').exists() else BASE.parent) / 'demo-preview'))
from solid import snapshot


def settings():
    return json.loads((BASE / 'settings.json').read_text())


def clean_env():
    return {key: value for key, value in os.environ.items() if key in (
        'PATH', 'HOME', 'USER', 'LOGNAME', 'XDG_RUNTIME_DIR', 'DOCKER_HOST', 'DOCKER_CONTEXT')}


def ssh_args(cfg):
    return ['ssh', '-i', cfg['ssh_key'], '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
            '-p', str(cfg['ssh_port']), cfg['ssh_target']]


def remote(cfg, payload):
    result = subprocess.run([*ssh_args(cfg), 'sudo -n /usr/local/sbin/' + ('picoclaw-app-deploy' if 'app' in payload else 'picoclaw-demo-deploy')],
        input=json.dumps(payload), capture_output=True, text=True, check=True,
        timeout=1500, env=clean_env())
    return json.loads(result.stdout)


def sources(cfg):
    result = {}
    for name, kind in [('frontend', 'solid'), ('backend', 'phoenix')]:
        content = snapshot(Path(cfg['source']) / name, kind=kind)
        if hashlib.sha256(content).hexdigest() != cfg['source_hashes'][name]:
            raise ValueError('Demokoden har ändrats sedan installationen. Granska och installera om projektflödet först.')
        result[name] = content
    return result
