#!/usr/bin/env python3
"""Install project generation worker and command router; keep general agent exec disabled."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from common import sources


def main():
    os.umask(0o077)
    home = Path.home()
    source = Path(__file__).resolve().parent
    target = home / '.picoclaw/projectflow'
    config_path = home / '.picoclaw/config.slack.json'
    config = json.loads(config_path.read_text())
    command = config['channel_list']['slack']['settings']['static_flow_command']
    existing = target / 'settings.json'
    if existing.exists():
        old = json.loads(existing.read_text())
        command = old['static_command']
    if 'staticflow' not in ' '.join(command):
        raise ValueError('Expected the existing staticflow installation')
    subprocess.run(['docker', 'info'], check=True, stdout=subprocess.DEVNULL)
    source_hashes = {}
    for name, report_path in [('frontend', 'demo-solid-001'), ('backend', 'demo-phoenix-001')]:
        report = json.loads((home / 'picoclaw-builds' / report_path / 'report.json').read_text())
        if report['status'] != 'passed':
            raise ValueError('Demo test report must have passed')
        source_hashes[name] = report['source_sha256']
    cfg = {'owner': 'U0ALTHQSWSV', 'state_dir': str(target / 'state'),
           'source': str(home / 'code/picoclaw-demo'), 'source_hashes': source_hashes,
           'static_command': command, 'static_state': str(home / '.picoclaw/staticflow/state'),
           'ssh_key': str(home / '.ssh/picoclaw_deploy'), 'ssh_port': 48039,
           'ssh_target': 'picodeploy@100.74.148.93',
           'github_enabled': True, 'github_repo_prefix': 'picoclaw-app',
           'llm_command': [str(home / '.local/bin/staticflow-llm')],
           'runtime_config': str(Path(os.environ.get('XDG_RUNTIME_DIR', '/run/user/' + str(os.getuid()))) / 'picoclaw-slack/config.json')}
    sources(cfg)
    if not os.access(cfg['llm_command'][0], os.X_OK):
        raise ValueError('Existing staticflow-llm helper is required')
    if config.get('tools', {}).get('exec', {}).get('enabled') is not False:
        raise ValueError('General agent exec must remain disabled')
    # Verify narrow remote capability BEFORE changing the Slack configuration.
    from common import remote
    status = remote(cfg, {'mode': 'status'})
    if status.get('pending'):
        raise ValueError('Lenovo has unresolved deployment state')
    app_status = remote(cfg, {'mode': 'status', 'app': '000000000000'})
    if app_status.get('pending'):
        raise ValueError('Generated app helper needs review')
    service = home / '.config/systemd/user/picoclaw-projectflow.service'
    if service.exists():
        subprocess.run(['systemctl', '--user', 'stop', 'picoclaw-projectflow'], check=True)
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    for file in source.glob('*.py'):
        shutil.copy2(file, target / file.name)
    for name in ['projectbuild', 'demo-preview', 'templates', 'generation-skills']:
        shutil.copytree(source / name, target / name, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))
    (target / 'settings.json').write_text(json.dumps(cfg, indent=2) + '\n')
    shutil.copy2(config_path, str(config_path) + '.backup-projectflow-' + str(time.time_ns()))
    config['channel_list']['slack']['settings']['static_flow_command'] = ['/usr/bin/python3', str(target / 'dispatch.py')]
    # Retain existing agent restrictions; this service is separate from model tools.
    if config.get('tools', {}).get('exec', {}).get('enabled') is not False:
        raise ValueError('General agent exec must remain disabled')
    config_path.write_text(json.dumps(config, indent=2) + '\n')
    service.parent.mkdir(parents=True, exist_ok=True)
    service.write_text('''[Unit]
Description=PicoClaw project generation worker
After=network-online.target picoclaw-slack.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 %h/.picoclaw/projectflow/worker.py
Restart=on-failure
RestartSec=5
KillMode=control-group
TimeoutStopSec=30
UMask=0077
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
''')
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', '--user', 'restart', 'picoclaw-slack'], check=True)
    subprocess.run(['systemctl', '--user', 'enable', '--now', 'picoclaw-projectflow'], check=True)
    subprocess.run(['systemctl', '--user', 'is-active', 'picoclaw-projectflow', 'picoclaw-slack'], check=True)
    print('Installerat. Skriv bygg en todoapp med db i en ny Slack-tråd.')


if __name__ == '__main__':
    main()
