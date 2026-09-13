#!/usr/bin/env python3
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import traceback

from common import BASE, clean_env, remote, settings, ssh_args
from dispatch import describe
from frontend import export as export_frontend, unpack
from jobs import Jobs, digest


def sha(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def extract(archive, target, expected):
    content = archive.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected:
        raise ValueError('Saved source snapshot differs from approved plan')
    target.mkdir()
    with tarfile.open(fileobj=io.BytesIO(content)) as tar:
        for entry in tar:
            path = PurePosixPath(entry.name)
            if not entry.isfile() or path.is_absolute() or '..' in path.parts:
                raise ValueError('Unsafe source snapshot')
            out = target / entry.name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(tar.extractfile(entry).read())


def build(cfg, job, log):
    root = Path(cfg['state_dir']) / job['id']
    plan = json.loads(job['plan'])
    if digest(plan) != job['plan_hash']:
        raise ValueError('Plan hash mismatch')
    if plan.get('kind') == 'generated':
        return build_with_agent(cfg, job, plan, root, log)
    source_hashes = plan['sources']
    for name in ['frontend', 'backend']:
        extract(root / (name + '.tar'), root / name, source_hashes[name])
    def run(script, *args):
        print(f"{job['id']}: {script}", flush=True)
        subprocess.run([sys.executable, str(BASE / 'projectbuild' / script), *map(str, args)],
                       stdout=log, stderr=log, check=True, timeout=5400, env=clean_env())
    run('solid.py', root / 'frontend', '--output', root / 'solid-build')
    run('phoenix.py', root / 'backend', '--output', root / 'phoenix-build')
    run('phoenix_release.py', root / 'backend', '--verified-report', root / 'phoenix-build/report.json',
        '--output', root / 'release-build', '--release', 'demo', '--migration-module', 'Demo.Release')
    release = json.loads((root / 'release-build/report.json').read_text())
    if release['status'] != 'passed' or release['source_sha256'] != source_hashes['backend']:
        raise ValueError('Release verification mismatch')
    export_frontend(root / 'solid-build/report.json', root / 'frontend.json')
    frontend_hash, _ = unpack(root / 'frontend.json')
    image = release['image_id']
    with (root / 'image.tar.gz').open('xb') as output:
        with subprocess.Popen(['docker', 'image', 'save', image], stdout=subprocess.PIPE, stderr=log,
                              env=clean_env()) as process:
            with gzip.GzipFile(fileobj=output, mode='wb') as compressed:
                shutil.copyfileobj(process.stdout, compressed)
            if process.wait() != 0:
                raise ValueError('Image export failed')
    current = remote(cfg, {'mode': 'status'})
    if current.get('pending'):
        raise ValueError('Lenovo has an unresolved deployment journal')
    return {'image': image, 'frontend': frontend_hash, 'image_archive': sha(root / 'image.tar.gz'),
            'frontend_file': sha(root / 'frontend.json'), 'previous': current['version'],
            'target': plan['target'], 'sources': source_hashes}


def build_with_agent(cfg, job, plan, root, log):
    from codeagent import CodeAgent
    import uuid
    materials = json.loads((root / 'generation-bundle.json').read_text())
    number = 1
    while (root / ('build-run-' + str(number))).exists():
        number += 1
    run_root = root / ('build-run-' + str(number))
    run_root.mkdir()
    ledger = Jobs(cfg['state_dir'], cfg['owner'])

    def active():
        row = ledger.db.execute('SELECT state,claim FROM jobs WHERE id=?', (job['id'],)).fetchone()
        return row is not None and row['state'] == 'building' and row['claim'] == job['claim']

    labels = {
        'environment': 'Preparing isolated build environment',
        'dependencies': 'Installing project dependencies',
        'coding': 'Implementing application',
        'frontend': 'Frontend checks',
        'backend': 'Backend and database checks',
        'release': 'Production image and smoke test',
        'github': 'Private GitHub repository',
        'ready': 'Build ready for preview deploy',
    }
    if plan.get('profile') == 'static':
        labels.pop('backend')
        labels['release'] = 'Production frontend package'

    def progress(message, stage='coding'):
        if not active():
            raise ValueError('Jobbet har stoppats.')
        now = time.time()
        progress_path = root / 'progress.json'
        status = json.loads(progress_path.read_text()) if progress_path.exists() else {'started_at': now}
        if status.get('run') != number:
            status.update({'run': number, 'current': None,
                           'steps': [{'key': key, 'label': label, 'state': 'waiting'}
                                     for key, label in labels.items()]})
        previous = status.get('current')
        for item in status['steps']:
            if item['key'] == previous and previous != stage and item['state'] == 'running':
                item['state'] = 'failed' if 'failed' in message.lower() else 'done'
                item['seconds'] = round(now - item.get('started_at', now))
            if item['key'] == stage:
                if item['state'] != 'running':
                    item['started_at'] = now
                item['state'] = 'done' if stage == 'ready' else 'running'
                item['detail'] = message
                if stage == 'ready':
                    item['seconds'] = 0
        status['current'] = stage
        status['elapsed_seconds'] = round(now - status['started_at'])
        progress_path.write_text(json.dumps(status, indent=2) + '\n')
        payload = {**job, 'progress': status, '_status_update': True}
        usage_path = root / 'model-usage.json'
        if usage_path.exists():
            payload['model_status'] = json.loads(usage_path.read_text())
        ledger.db.execute('INSERT OR REPLACE INTO notifications (id,payload,attempts,next_try,sent) VALUES (?,?,0,0,0)',
                          ('status-' + job['id'], json.dumps(payload)))
        notify(cfg, ledger)

    builder_root = BASE / 'projectbuild' if (BASE / 'projectbuild').exists() else BASE.parent / 'projectbuild'
    def run(script, *args):
        if not active():
            raise ValueError('Jobbet har stoppats.')
        subprocess.run([sys.executable, str(builder_root / script), *map(str, args)],
                       stdout=log, stderr=log, check=True, timeout=5400, env=clean_env())

    try:
        continuation_count = ledger.continuation_count(job['id'])
        with CodeAgent({**cfg, '_continuations': continuation_count}, plan, materials,
                       run_root, log, progress, active) as agent:
            agent.work('Build the approved app. Read the scaffold, especially the frontend README, '
                       'PRODUCT.md, DESIGN.md, Layout.tsx, AppSidebar.tsx, Header.tsx, ModeToggle.tsx, '
                       'App.tsx, and routes. Extend the existing shell and compose substantial behavior '
                       'in route/component files; keep App.tsx focused on routing. Only replace the shell '
                       'if the approved brief explicitly requests a different application shape. '
                       'Read the skills, implement the features, and run relevant tests. Install only the '
                       'dependencies this profile needs.')
            for attempt in range(1, 4):
                output = run_root / ('attempt-' + str(attempt))
                output.mkdir()
                sources_dir = output / 'source'
                try:
                    source_hashes = agent.export(sources_dir)
                    progress('Running TypeScript, lint and frontend tests (attempt ' + str(attempt) + '/3).',
                             'frontend')
                    run('solid.py', sources_dir / 'frontend', '--output', output / 'solid-build')
                    if plan.get('profile') == 'fullstack':
                        progress('Running Phoenix tests with an isolated PostgreSQL database.', 'backend')
                        run('phoenix.py', sources_dir / 'backend', '--output', output / 'phoenix-build')
                        progress('Building the production image, running migrations and checking HTTP health.',
                                 'release')
                        run('phoenix_release.py', sources_dir / 'backend', '--verified-report',
                            output / 'phoenix-build/report.json', '--output', output / 'release-build',
                            '--release', 'demo', '--migration-module', 'Demo.Release')
                        release = json.loads((output / 'release-build/report.json').read_text())
                        if release['status'] != 'passed' or release['source_sha256'] != source_hashes['backend']:
                            raise ValueError('Release source/report mismatch')
                    break
                except (subprocess.CalledProcessError, ValueError) as exc:
                    errors = {'failure': str(exc)[:1500]}
                    for path in output.glob('*/build.log'):
                        with path.open('rb') as failed:
                            failed.seek(max(0, path.stat().st_size - 14000))
                            errors[path.parent.name] = failed.read(14000).decode(errors='replace')
                    (output / 'feedback.json').write_text(json.dumps(errors, ensure_ascii=False, indent=2))
                    if attempt == 3:
                        progress('Build validation failed after two repair rounds. Details: build-run-' +
                                 str(number) + '/attempt-3/feedback.json.', 'release')
                        raise
                    progress('A build check failed. The coding agent is repairing the same workspace.', 'coding')
                    agent.escalate('Den fristående byggkontrollen misslyckades')
                    agent.work('Rätta dessa faktiska byggfel i det befintliga projektet. '
                               'Behåll testerna och kör dem igen.\n' + json.dumps(errors, ensure_ascii=False),
                               status='Repairing the project from the build logs.')
            if not active():
                raise ValueError('Jobbet har stoppats.')
            export_frontend(output / 'solid-build/report.json', run_root / 'frontend.json')
            frontend_hash, _ = unpack(run_root / 'frontend.json')
            if plan.get('profile') == 'fullstack':
                image = release['image_id']
                progress('Packaging the verified production image.', 'release')
                with (run_root / 'image.tar.gz').open('xb') as target:
                    with subprocess.Popen(['docker', 'image', 'save', image], stdout=subprocess.PIPE,
                                          stderr=log, env=clean_env()) as process:
                        with gzip.GzipFile(fileobj=target, mode='wb') as compressed:
                            shutil.copyfileobj(process.stdout, compressed)
                        if process.wait() != 0:
                            raise ValueError('Image export failed')
            else:
                progress('Packaging the verified static frontend.', 'release')
            current = remote(cfg, {'mode': 'status', 'app': job['id']})
            if current.get('pending') or current['version'] is not None:
                raise ValueError('Lenovo already has resources or an unfinished deployment for this job.')
            from github_publish import publish as publish_github
            progress('Creating a private repository and verifying the pushed commit.', 'github')
            repository = publish_github(cfg, job, sources_dir, source_hashes, root, log)
            progress('All checks passed. Waiting for preview deploy approval.', 'ready')
            if not active():
                raise ValueError('Jobbet har stoppats.')
            promoted = ['frontend.json'] + (['image.tar.gz'] if plan.get('profile') == 'fullstack' else [])
            for name in promoted:
                if (root / name).exists():
                    (root / name).rename(run_root / ('previous-' + name))
                (run_root / name).replace(root / name)
            (root / 'generated-sources.json').write_text(json.dumps(source_hashes, indent=2))
            if plan.get('profile') == 'static':
                return {'profile': 'static', 'frontend': frontend_hash,
                        'frontend_file': sha(root / 'frontend.json'), 'previous': None,
                        'target': plan['target'], 'sources': source_hashes, 'repository': repository}
            return {'image': image, 'frontend': frontend_hash, 'image_archive': sha(root / 'image.tar.gz'),
                    'frontend_file': sha(root / 'frontend.json'), 'previous': None,
                    'target': plan['target'], 'sources': source_hashes, 'repository': repository}
    finally:
        ledger.db.close()


def deploy(cfg, job, log):
    manifest = json.loads(job['artifact'])
    if digest(manifest) != job['artifact_hash']:
        raise ValueError('Artifact no longer matches approval')
    root = Path(cfg['state_dir']) / job['id']
    if sha(root / 'frontend.json') != manifest['frontend_file']:
        raise ValueError('Artifact files changed after approval')
    if manifest.get('profile') != 'static' and sha(root / 'image.tar.gz') != manifest['image_archive']:
        raise ValueError('Image archive changed after approval')
    # job IDs come only from the ledger, never from Slack shell text.
    import re
    if not re.fullmatch('[a-f0-9]{12}', job['id']):
        raise ValueError('Invalid job ID')
    destination = 'projectflow-incoming/' + job['id']
    subprocess.run([*ssh_args(cfg), 'mkdir -p -m 700 ' + destination], check=True,
                   timeout=30, stdout=log, stderr=log, env=clean_env())
    files = ([str(root / 'frontend.json')] if manifest.get('profile') == 'static' else
             [str(root / 'image.tar.gz'), str(root / 'frontend.json')])
    subprocess.run(['scp', '-i', cfg['ssh_key'], '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
                    '-o', 'StrictHostKeyChecking=yes', '-P', str(cfg['ssh_port']),
                    *files,
                    cfg['ssh_target'] + ':' + destination + '/'],
                   check=True, timeout=1800, stdout=log, stderr=log, env=clean_env())
    receipt = remote(cfg, {'mode': 'deploy', 'job': job['id'], 'manifest': manifest,
                           'approval': job['artifact_hash'],
                           **({'app': job['id']} if json.loads(job['plan']).get('kind') == 'generated' else {})})
    expected = {'frontend': manifest['frontend']}
    if manifest.get('profile') != 'static':
        expected['image'] = manifest['image']
    if receipt.get('approval') != job['artifact_hash'] or receipt.get('version') != expected:
        raise ValueError('Remote receipt differs from approved version')
    (root / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


def release(cfg, job, log):
    manifest = json.loads(job['artifact'])
    if digest(manifest) != job['artifact_hash']:
        raise ValueError('Artifact no longer matches release approval')
    slug = job['release_target']
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,48}[a-z0-9])?', slug):
        raise ValueError('Invalid release subdomain')
    receipt = remote(cfg, {'mode': 'release', 'app': job['id'], 'slug': slug,
                           'approval': job['artifact_hash']})
    if receipt.get('approval') != job['artifact_hash'] or receipt.get('slug') != slug:
        raise ValueError('Lenovo release receipt does not match approval')
    return receipt


def notify(cfg, ledger):
    rows = ledger.db.execute('SELECT * FROM notifications WHERE sent=0 AND attempts<8 AND next_try<=?',
                             (time.time(),)).fetchall()
    for row in rows:
        try:
            config = json.loads(Path(cfg['runtime_config']).read_text())
            token = config['channel_list']['slack']['settings']['bot_token']
            if not isinstance(token, str) or not token.startswith('xoxb-'):
                raise ValueError('Slack token unavailable')
            job = json.loads(row['payload'])
            usage_path = Path(cfg['state_dir']) / job['id'] / 'model-usage.json'
            if usage_path.exists() and 'model_status' not in job:
                job['model_status'] = json.loads(usage_path.read_text())
            progress_path = Path(cfg['state_dir']) / job['id'] / 'progress.json'
            if progress_path.exists() and 'progress' not in job:
                job['progress'] = json.loads(progress_path.read_text())
            # Do not deliver an old approval prompt after the job has moved on.
            current = ledger.db.execute('SELECT state FROM jobs WHERE id=?', (job['id'],)).fetchone()
            if current['state'] != job['state']:
                ledger.db.execute('UPDATE notifications SET sent=1 WHERE id=?', (row['id'],))
                continue
            status_update = job.get('_status_update') is True
            saved = ledger.db.execute('SELECT * FROM slack_status WHERE job=?', (job['id'],)).fetchone()
            if status_update and saved and time.time() - saved['updated'] < 3:
                ledger.db.execute('UPDATE notifications SET next_try=? WHERE id=?',
                                  (saved['updated'] + 3, row['id']))
                continue
            payload = {'channel': job['channel'], 'text': describe(job)}
            method = 'chat.postMessage'
            if status_update and saved:
                method = 'chat.update'
                payload['ts'] = saved['message_ts']
            else:
                payload.update({'thread_ts': job['thread'], 'unfurl_links': False, 'unfurl_media': False})
            request = urllib.request.Request('https://slack.com/api/' + method,
                data=json.dumps(payload).encode(), headers={'Authorization': 'Bearer ' + token,
                'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(request, timeout=20) as response:
                result = json.load(response)
                if not result.get('ok'):
                    raise ValueError('Slack did not acknowledge message')
            if status_update:
                message_ts = saved['message_ts'] if saved else result.get('ts')
                if not isinstance(message_ts, str) or not message_ts:
                    raise ValueError('Slack status timestamp missing')
                ledger.db.execute('INSERT OR REPLACE INTO slack_status VALUES (?,?,?,?,?)',
                                  (job['id'], job['channel'], job['thread'], message_ts, time.time()))
            ledger.db.execute('UPDATE notifications SET sent=1 WHERE id=?', (row['id'],))
        except Exception:
            ledger.db.execute('UPDATE notifications SET attempts=attempts+1,next_try=? WHERE id=?',
                              (time.time() + min(300, 15 * 2 ** row['attempts']), row['id']))
            print('Slack notification delayed; durable job status remains available.', flush=True)


def main():
    os.umask(0o077)
    cfg = settings()
    ledger = Jobs(cfg['state_dir'], cfg['owner'])
    with (Path(cfg['state_dir']) / 'worker.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ledger.recover()
        while True:
            notify(cfg, ledger)
            job = ledger.claim()
            if job:
                try:
                    with (Path(cfg['state_dir']) / job['id'] / 'worker.log').open('ab') as log:
                        if job['state'] == 'planning':
                            from generate import plan as make_plan
                            from model_policy import ModelPolicy
                            request = json.loads(job['plan'])
                            root = Path(cfg['state_dir']) / job['id']
                            (root / 'generation-bundle.json').write_text(json.dumps(request['materials']))
                            routing = ModelPolicy(cfg, request, root, planning=True)
                            planned = make_plan({**cfg, '_model_policy': routing}, request['request'], request['materials'], job['id'])
                            planned['planning_model'] = routing.label
                            ledger.finish(job['id'], job['claim'], planned)
                        elif job['state'] == 'building':
                            artifact = build(cfg, job, log)
                            ledger.finish(job['id'], job['claim'], artifact)
                        elif job['state'] == 'releasing':
                            receipt = release(cfg, job, log)
                            ledger.finish(job['id'], job['claim'], receipt)
                        else:
                            deploy(cfg, job, log)
                            ledger.finish(job['id'], job['claim'])
                except Exception as exc:
                    with (Path(cfg['state_dir']) / job['id'] / 'worker.log').open('a') as error_log:
                        traceback.print_exc(file=error_log)
                    from model_policy import PolicyError
                    from github_publish import GitHubPublishError
                    message = (str(exc) if isinstance(exc, (PolicyError, GitHubPublishError)) else
                               'The stage failed: ' + type(exc).__name__ +
                               '. Check worker.log and inspect Lenovo before retrying a remote operation.')
                    ledger.finish(job['id'], job['claim'], error=message)
            else:
                time.sleep(2)


if __name__ == '__main__':
    main()
