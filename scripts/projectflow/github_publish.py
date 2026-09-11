"""Publish verified generated source to a new private GitHub repository."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import subprocess

from common import clean_env


class GitHubPublishError(RuntimeError):
    pass


SECRET_PATTERNS = (
    re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(rb'\b(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})\b'),
    re.compile(rb'\bAKIA[A-Z0-9]{16}\b'),
)


def reject_secrets(root):
    for path in root.rglob('*'):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if any(pattern.search(data) for pattern in SECRET_PATTERNS):
            raise GitHubPublishError('A possible secret was found in ' +
                                     path.relative_to(root).as_posix() + '; no repository was created.')


def command(args, *, cwd=None, capture=False, timeout=180, log=None, env=None, check=True):
    try:
        return subprocess.run(args, cwd=cwd, check=check, timeout=timeout, env=env or clean_env(),
                              stdout=subprocess.PIPE if capture else log, stderr=log,
                              text=capture)
    except subprocess.CalledProcessError:
        raise GitHubPublishError(args[0] + ' failed while publishing the private GitHub repository; see worker.log.') from None
    except subprocess.TimeoutExpired:
        raise GitHubPublishError(args[0] + ' timed out while publishing the private GitHub repository.') from None


def publish(cfg, job, source, source_hashes, state, log):
    """Create one private repo per job and push the exact verified source snapshot."""
    receipt_path = state / 'github.json'
    expected = dict(sorted(source_hashes.items()))
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if receipt.get('sources') != expected:
            raise GitHubPublishError('The GitHub receipt belongs to a different source version.')
        return receipt
    if not cfg.get('github_enabled', True):
        raise GitHubPublishError('GitHub publishing is disabled in projectflow settings.json.')
    if shutil.which('gh') is None or shutil.which('git') is None:
        raise GitHubPublishError('git and gh must be installed on macmini2.')

    owner = command(['gh', 'api', 'user', '--jq', '.login'], capture=True, timeout=30, log=log).stdout.strip()
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})', owner):
        raise GitHubPublishError('Could not read the authenticated GitHub account from gh.')
    prefix = cfg.get('github_repo_prefix', 'picoclaw-app')
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?', prefix):
        raise GitHubPublishError('Ogiltigt github_repo_prefix i settings.json.')
    name = prefix + '-' + job['id']
    full_name = owner + '/' + name
    pending_path = state / 'github-pending.json'
    pending = json.loads(pending_path.read_text()) if pending_path.exists() else None
    if pending and (pending.get('name') != full_name or pending.get('sources') != expected):
        raise GitHubPublishError('A different GitHub attempt requires manual inspection.')

    work = state / 'github-source'
    if work.exists():
        if not pending:
            raise GitHubPublishError('Unexpected local GitHub workspace; inspect the job.')
        shutil.rmtree(work)
    work.mkdir(mode=0o700)
    for side in sorted(expected):
        shutil.copytree(source / side, work / side)
    (work / '.gitignore').write_text('**/.env\n**/.env.*\n**/node_modules/\n**/deps/\n**/_build/\n.DS_Store\n')
    reject_secrets(work)

    date_path = state / 'github-commit-date'
    if date_path.exists():
        commit_date = date_path.read_text().strip()
    else:
        commit_date = datetime.now(timezone.utc).isoformat()
        date_path.write_text(commit_date + '\n')
        date_path.chmod(0o600)

    git_env = clean_env()
    git_env.update({'GIT_AUTHOR_NAME': 'PicoClaw', 'GIT_AUTHOR_EMAIL': 'rootfood@gmail.com',
                    'GIT_COMMITTER_NAME': 'PicoClaw', 'GIT_COMMITTER_EMAIL': 'rootfood@gmail.com',
                    'GIT_AUTHOR_DATE': commit_date,
                    'GIT_COMMITTER_DATE': commit_date})
    command(['git', 'init', '--initial-branch=main'], cwd=work, log=log, env=git_env)
    command(['git', '-c', 'core.hooksPath=/dev/null', 'add', '--all'], cwd=work, log=log, env=git_env)
    command(['git', '-c', 'core.hooksPath=/dev/null', 'commit', '-m', 'Initial verified PicoClaw build'],
            cwd=work, log=log, env=git_env)
    commit = command(['git', 'rev-parse', 'HEAD'], cwd=work, capture=True, log=log, env=git_env).stdout.strip()
    if not re.fullmatch(r'[a-f0-9]{40,64}', commit):
        raise GitHubPublishError('Git skapade inget verifierbart commit-ID.')

    exists = command(['gh', 'repo', 'view', full_name, '--json', 'isPrivate', '--jq', '.isPrivate'],
                     capture=True, timeout=30, log=log, check=False)
    if exists.returncode == 0 and not pending:
        raise GitHubPublishError('GitHub-repot finns redan och adopteras inte automatiskt: ' + full_name)
    if exists.returncode != 0:
        pending_path.write_text(json.dumps({'name': full_name, 'sources': expected}) + '\n')
        pending_path.chmod(0o600)
        command(['gh', 'repo', 'create', full_name, '--private', '--source', str(work), '--remote', 'origin'],
                timeout=60, log=log)
    else:
        if exists.stdout.strip() != 'true':
            raise GitHubPublishError('An unexpected public repository blocks the retry: ' + full_name)
        command(['git', 'remote', 'add', 'origin', 'https://github.com/' + full_name + '.git'],
                cwd=work, log=log, env=git_env)
    command(['git', '-c', 'core.hooksPath=/dev/null', 'push', '--set-upstream', 'origin', 'main'],
            cwd=work, timeout=180, log=log, env=git_env)
    remote_commit = command(['gh', 'api', 'repos/' + full_name + '/commits/main', '--jq', '.sha'],
                            capture=True, timeout=30, log=log).stdout.strip()
    if remote_commit != commit:
        raise GitHubPublishError('The GitHub commit differs from the verified local commit.')
    receipt = {'name': full_name, 'url': 'https://github.com/' + full_name,
               'commit': commit, 'commit_url': 'https://github.com/' + full_name + '/commit/' + commit,
               'private': True, 'sources': expected}
    temporary = state / 'github.tmp'
    temporary.write_text(json.dumps(receipt, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(receipt_path)
    pending_path.unlink(missing_ok=True)
    return receipt
