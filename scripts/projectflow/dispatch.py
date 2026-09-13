#!/usr/bin/env python3
"""Route authenticated Slack commands; ordinary static jobs retain their handler."""
import json
import os
from pathlib import Path
import subprocess
import sys

from common import settings, sources
from jobs import Jobs

PLAN = ('Build the existing reviewed demo without code generation. Run Solid checks, '
        'Phoenix tests with temporary PostgreSQL, and the production release/startup check. '
        'After separate deploy approval, update only preview-demo.marcusasplund.com.')


def duration(seconds):
    seconds = max(0, int(seconds or 0))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return ((str(hours) + 'h ') if hours else '') + ((str(minutes) + 'm ') if minutes else '') + str(seconds) + 's'


def slack_link(url, label):
    return '<' + url + '|' + label + '>'


def model_name(value):
    value = (value or '').split(' (', 1)[0].removeprefix('openai/')
    if value.startswith('gpt-'):
        number, separator, variant = value.removeprefix('gpt-').partition('-')
        return 'GPT-' + number + ((' ' + variant.title()) if separator else '')
    return value or 'Unknown'


def footer(job):
    usage = job.get('model_status') or {}
    progress = job.get('progress') or {}
    items = []
    if progress.get('elapsed_seconds') is not None:
        items.append('⏱ ' + duration(progress['elapsed_seconds']))
    if usage:
        items.append('💰 ~$' + format(usage.get('estimated_cost_usd', 0.0), '.4f'))
        items.append(str(usage.get('calls', 0)) + ' model calls')
    lines = []
    if items:
        lines.append(' · '.join(items))
    if usage:
        lines.append('Model: ' + model_name(usage.get('model')) + ' · Job: `' + job['id'] + '`')
    else:
        lines.append('Job: `' + job['id'] + '`')
    return '\n'.join(lines)


def append_footer(lines, job):
    lines.extend(['', footer(job)])
    return '\n'.join(lines)


def build_status(job):
    status = job['progress']
    lines = ['*🛠 Building project*']
    icons = {'done': '✅', 'running': '⏳', 'failed': '❌', 'waiting': '⬜'}
    for step in status.get('steps', []):
        line = icons.get(step.get('state'), '⬜') + ' ' + step['label']
        if step.get('state') in ('done', 'failed') and 'seconds' in step:
            line += '  ·  ' + duration(step['seconds'])
        lines.append(line)
        if step.get('state') == 'running' and step.get('detail'):
            lines.append('   _' + step['detail'] + '_')
    return append_footer(lines, job)


def details(job):
    plan = json.loads(job['plan'])
    lines = ['*🔎 Project details*',
             'State: `' + job['state'] + '`',
             'Job: `' + job['id'] + '`']
    if plan.get('target'):
        target = 'https://' + plan['target'] + '/'
        lines.append('Target: ' + slack_link(target, plan['target']))
    if job.get('artifact'):
        artifact = json.loads(job['artifact'])
        lines.append('Artifact: `' + job['artifact_hash'] + '`')
        if artifact.get('image'):
            lines.append('Image: `' + artifact['image'] + '`')
        repository = artifact.get('repository')
        if repository:
            lines.append('Repository: ' + slack_link(repository['url'], repository['url']))
            lines.append('Commit: ' + slack_link(repository['commit_url'], repository['commit'][:12]))
        for name, source_hash in sorted((artifact.get('sources') or {}).items()):
            lines.append(name.title() + ' source: `' + source_hash + '`')
    if job.get('release_url'):
        lines.append('Public URL: ' + slack_link(job['release_url'], job['release_url']))
    usage = job.get('model_status') or {}
    if usage:
        lines.extend(['Model: `' + usage.get('model', 'unknown') + '`',
                      'Calls: ' + str(usage.get('calls', 0)),
                      'Manual continuations: ' + str(usage.get('continuations', 0)) + ' / 6',
                      'Tokens: ' + str(usage.get('input_tokens', 0)) + ' input / ' +
                      str(usage.get('output_tokens', 0)) + ' output',
                      'Estimated cost: $' + format(usage.get('estimated_cost_usd', 0.0), '.4f')])
    progress = job.get('progress') or {}
    if progress.get('elapsed_seconds') is not None:
        lines.append('Build time: ' + duration(progress['elapsed_seconds']))
    return '\n'.join(lines)


def describe(job):
    state = job['state']
    plan = json.loads(job['plan'])
    generated = plan.get('kind') == 'generated'
    if state == 'building' and isinstance(job.get('progress'), dict):
        return build_status(job)

    if state in ('queued_plan', 'planning'):
        lines = ['*🧠 Planning*', '', 'Pico is preparing a plan from your description.']
    elif state == 'awaiting_plan':
        lines = ['*📋 Plan ready*', '']
        if plan.get('name'):
            lines.extend(['*' + plan['name'] + '*', plan.get('description', PLAN)])
        else:
            lines.append(plan.get('description', PLAN))
        if plan.get('planning_model'):
            lines.append('_Planned with ' + model_name(plan['planning_model']) + '._')
        if generated:
            static = plan.get('profile') == 'static'
            lines.extend(['', '*Architecture*',
                          '• Profile: ' + ('Static' if static else 'Fullstack'),
                          '• Frontend: SolidJS',
                          '• Storage: ' + ('Browser localStorage' if static else 'PostgreSQL'),
                          '• Backend: ' + ('None' if static else 'Phoenix'),
                          '• Database: ' + ('None' if static else 'PostgreSQL')])
            lines.extend(['', '*Acceptance checks*'])
            lines.extend('• ' + item for item in plan['acceptance'])
            target_note = 'protected preview · no server runtime' if static else 'protected preview · isolated database'
            lines.extend(['', '*Preview target*', '`' + plan['target'] + '` · ' + target_note])
        lines.extend(['', 'Reply `approve` to start the build, or `stop`.'])
    elif state == 'queued_build':
        lines = ['*🛠 Build queued*', '', 'The approved plan is waiting for the isolated build worker.']
        if job.get('continuation_grant'):
            lines.extend(['', '`continue ' + str(job['continuation_grant']) + '/6` approved · '
                          '+30 calls · +15 escalated · +$10 reserve'])
    elif state == 'awaiting_deploy':
        artifact = json.loads(job['artifact'])
        passed = ('Frontend checks and production packaging passed.' if artifact.get('profile') == 'static'
                  else 'Tests, release migrations, and the HTTP startup check passed.')
        lines = ['*✅ Build ready for review*', passed]
        repository = artifact.get('repository')
        if repository:
            lines.extend(['', '*Review*',
                          '• ' + slack_link(repository['url'], 'Source code'),
                          '• ' + slack_link(repository['commit_url'],
                                             'Commit ' + repository['commit'][:8])])
        lines.extend(['', 'Reply `deploy` to create the protected preview, or `stop`.',
                      'Use `details` for image and artifact hashes.'])
    elif state in ('queued_deploy', 'deploying'):
        lines = ['*🚀 Deploying preview*',
                 'The verified artifacts are being deployed to the protected preview.']
    elif state == 'deployed':
        preview = 'https://' + plan['target'] + '/'
        heading = '*🔒 ' + (plan.get('name', 'Preview')) + ' deployed*'
        suggestion = plan.get('suggested_slug', 'app-name')
        lines = [heading, '', slack_link(preview, 'Open protected preview'), '',
                 'When it is approved, reply `release <subdomain>` to create the public address.',
                 'Suggested: `release ' + suggestion + '`']
    elif state in ('queued_release', 'releasing'):
        target = 'https://' + job['release_target'] + '.marcusasplund.com/'
        lines = ['*🚀 Releasing*',
                 'Publishing the approved preview to ' +
                 slack_link(target, job['release_target'] + '.marcusasplund.com') + '.']
    elif state == 'released':
        preview = 'https://' + plan['target'] + '/'
        lines = ['*🎉 Released*', slack_link(job['release_url'], 'Open public app'), '',
                 '• ' + slack_link(preview, 'Protected preview')]
        artifact = json.loads(job['artifact']) if job.get('artifact') else {}
        if artifact.get('repository'):
            lines.append('• ' + slack_link(artifact['repository']['url'], 'Source code'))
    elif state in ('failed', 'interrupted'):
        lines = ['*❌ Project failed*', job.get('error') or 'The current stage did not complete.', '',
                 'No automatic retries were started. Use `details` for the saved job information.']
        if state == 'failed' and 'budget or call limit' in (job.get('error') or '').lower():
            lines.append('Reply `continue` to grant a bounded budget extension and resume this build.')
        elif state == 'failed' and job['artifact']:
            if job.get('release_target'):
                lines.append('After fixing the issue, reply `release ' + job['release_target'] +
                             '` to retry without rebuilding.')
            else:
                lines.append('After fixing the issue, reply `deploy` to retry without rebuilding.')
        elif state == 'failed' and generated and 'bundle_hash' in plan:
            lines.append('After updating the worker, reply `approve` to rebuild the approved plan.')
    elif state == 'cancelled':
        lines = ['*⏹ Project stopped*',
                 'Any in-flight command may finish, but its result will not be deployed.']
    else:
        lines = ['*Project status*', state.replace('_', ' ').title()]
    return append_footer(lines, job)


def handle(cfg, event):
    ledger = Jobs(cfg['state_dir'], cfg['owner'])
    try:
        ledger.authorize(event)
        parts = event.get('text', '').strip().split()
        command = parts[0].lower() if parts else ''
        command = {'approve': 'plan-ok', 'status': 'jobb', 'stop': 'stoppa'}.get(command, command)
        continuation_grant = None
        in_project = ledger.db.execute('SELECT 1 FROM jobs WHERE owner=? AND channel=? AND thread=?',
            (event['user'], event['channel'], event['thread'])).fetchone()
        is_new = len(parts) >= 2 and command in ('build', 'bygg')
        static_new = is_new and len(parts) >= 3 and parts[1].lower() in ('static', 'statisk')
        if not in_project and (not is_new or static_new):
            if static_new:
                event = {**event, 'text': 'bygg ' + ' '.join(parts[2:])}
            result = subprocess.run(cfg['static_command'], input=json.dumps(event), text=True,
                                    capture_output=True, timeout=420, check=True)
            return result.stdout
        if is_new:
            generated = not (len(parts) == 2 and parts[1].lower() == 'demo')
            if len(event['text']) > 6000:
                return 'Describe the application using no more than 6000 characters.'
            # Never allow a project job to take over an existing static job thread.
            import sqlite3
            static_db = Path(cfg['static_state']) / 'jobs.sqlite'
            if static_db.exists():
                with sqlite3.connect(f'file:{static_db}?mode=ro', uri=True) as db:
                    if db.execute('SELECT 1 FROM jobs WHERE owner=? AND channel=? AND thread=?',
                                  (event['user'], event['channel'], event['thread'])).fetchone():
                        return 'Start the project in a new Slack thread.'
            if generated:
                from generate import bundle
                materials = bundle()
                ledger.create(event, {'kind': 'generated', 'request': ' '.join(parts[1:]),
                                     'materials': materials}, planning=True)
                return describe(ledger.status(event))
            content = sources(cfg)
            result = ledger.create(event, {'description': PLAN, 'sources': cfg['source_hashes'],
                                           'target': 'preview-demo.marcusasplund.com'})
            directory = Path(cfg['state_dir']) / result['id']
            directory.mkdir(mode=0o700, exist_ok=True)
            for name, data in content.items():
                target = directory / (name + '.tar')
                if not target.exists():
                    target.write_bytes(data)
        elif len(parts) == 2 and command == 'release':
            ledger.release(event, parts[1].lower())
        elif len(parts) != 1:
            return ('Use `approve`, `status`, `stop`, `deploy`, `release <subdomain>`, '
                    '`continue`, or `details` in the project thread.')
        elif command in ('plan-ok', 'deploy'):
            ledger.approve(event, command)
        elif command == 'continue':
            continuation_grant = ledger.continue_build(event)['continuations']
        elif command == 'stoppa':
            ledger.cancel(event)
        elif command not in ('jobb', 'details'):
            return ('Project commands: `build`, `approve`, `status`, `stop`, `deploy`, '
                    '`release <subdomain>`, `continue`, and `details`.')
        current = ledger.status(event)
        root = Path(cfg['state_dir']) / current['id']
        usage_path = root / 'model-usage.json'
        if usage_path.exists():
            current['model_status'] = json.loads(usage_path.read_text())
        progress_path = root / 'progress.json'
        if progress_path.exists():
            current['progress'] = json.loads(progress_path.read_text())
        if continuation_grant:
            current['continuation_grant'] = continuation_grant
        return details(current) if command == 'details' else describe(current)
    finally:
        ledger.db.close()


if __name__ == '__main__':
    os.umask(0o077)
    try:
        print(handle(settings(), json.load(sys.stdin)))
    except ValueError as exc:
        print(str(exc))
    except Exception:
        print('The project command failed. Use `status` for the saved state; no approval was recorded automatically.')
