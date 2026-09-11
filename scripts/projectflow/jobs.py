"""Durable approvals and work claims for the upcoming project workflow."""
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import uuid


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class Jobs:
    def __init__(self, root, owner):
        self.owner = owner
        Path(root).mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db = sqlite3.connect(Path(root) / 'jobs.sqlite', timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, owner TEXT, channel TEXT, thread TEXT,
          state TEXT, plan TEXT, plan_hash TEXT, artifact TEXT, artifact_hash TEXT,
          updated REAL, claim TEXT, error TEXT, release_target TEXT, release_url TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS one_job_per_thread ON jobs(owner,channel,thread);
        CREATE TABLE IF NOT EXISTS events (channel TEXT, event TEXT, result TEXT,
          PRIMARY KEY(channel,event));
        CREATE TABLE IF NOT EXISTS notifications (id TEXT PRIMARY KEY, payload TEXT, attempts INTEGER DEFAULT 0, next_try REAL DEFAULT 0, sent INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS approvals (channel TEXT,event TEXT,job TEXT,
          command TEXT,version TEXT,owner TEXT,PRIMARY KEY(channel,event));
        CREATE TABLE IF NOT EXISTS slack_status (job TEXT PRIMARY KEY, channel TEXT,
          thread TEXT, message_ts TEXT, updated REAL);
        ''')
        columns = {row['name'] for row in self.db.execute('PRAGMA table_info(jobs)')}
        if 'release_target' not in columns:
            self.db.execute("ALTER TABLE jobs ADD COLUMN release_target TEXT DEFAULT ''")
        if 'release_url' not in columns:
            self.db.execute("ALTER TABLE jobs ADD COLUMN release_url TEXT DEFAULT ''")

    def authorize(self, event):
        if event.get('user') != self.owner:
            raise ValueError('The sender is not authorized.')
        for key in ('channel', 'thread', 'event'):
            if not isinstance(event.get(key), str) or not event[key]:
                raise ValueError('The Slack event is incomplete.')

    def transaction(self, operation):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            result = operation()
            self.db.execute('COMMIT')
            return result
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def once(self, event, operation):
        self.authorize(event)
        def apply():
            existing = self.db.execute('SELECT result FROM events WHERE channel=? AND event=?',
                (event['channel'], event['event'])).fetchone()
            if existing:
                return json.loads(existing['result'])
            result = operation()
            self.db.execute('INSERT INTO events VALUES (?,?,?)',
                (event['channel'], event['event'], json.dumps(result)))
            return result
        return self.transaction(apply)

    def create(self, event, plan, planning=False):
        """plan includes source hashes and the fixed build/deploy specification."""
        def apply():
            if self.db.execute('SELECT 1 FROM jobs WHERE owner=? AND channel=? AND thread=?',
                               (self.owner, event['channel'], event['thread'])).fetchone():
                raise ValueError('This thread already has a project. Start a new thread.')
            ident = uuid.uuid4().hex[:12]
            state = 'queued_plan' if planning else 'awaiting_plan'
            directory = Path(self.db.execute('PRAGMA database_list').fetchone()[2]).parent / ident
            directory.mkdir(mode=0o700)
            self.db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (ident, self.owner, event['channel'], event['thread'], state,
                 json.dumps(plan), digest(plan), '', '', time.time(), '', '', '', ''))
            return {'id': ident, 'state': state, 'plan_hash': digest(plan)}
        return self.once(event, apply)

    def scoped(self, event):
        row = self.db.execute('SELECT * FROM jobs WHERE owner=? AND channel=? AND thread=?',
                (self.owner, event['channel'], event['thread'])).fetchone()
        if not row:
            raise ValueError('No project job exists in this thread.')
        return row

    def status(self, event):
        self.authorize(event)
        return dict(self.scoped(event))

    def approve(self, event, command):
        def apply():
            job = self.scoped(event)
            stages = {'plan-ok': ('awaiting_plan', 'queued_build', 'plan_hash'),
                      'deploy': ('awaiting_deploy', 'queued_deploy', 'artifact_hash')}
            if command not in stages:
                raise ValueError('Unknown approval command.')
            before, after, version_key = stages[command]
            timestamp = float(event['event'])
            if not math.isfinite(timestamp) or timestamp < job['updated']:
                raise ValueError('The approval is older than the current stage.')
            retry_deploy = command == 'deploy' and job['state'] == 'failed' and bool(job['artifact'])
            plan = json.loads(job['plan'])
            prior_plan_approval = self.db.execute(
                'SELECT 1 FROM approvals WHERE job=? AND command=? AND version=?',
                (job['id'], 'plan-ok', job['plan_hash'])).fetchone()
            retry_build = (command == 'plan-ok' and job['state'] == 'failed'
                           and not job['artifact'] and plan.get('kind') == 'generated'
                           and 'bundle_hash' in plan and prior_plan_approval is not None
                           and 'budget or call limit' not in (job['error'] or '').lower())
            if job['state'] != before and not retry_deploy and not retry_build:
                raise ValueError('The project cannot be approved in its current state.')
            self.db.execute('INSERT INTO approvals VALUES (?,?,?,?,?,?)',
                (event['channel'], event['event'], job['id'], command, job[version_key], self.owner))
            self.db.execute('UPDATE jobs SET state=?,updated=? WHERE id=?', (after, time.time(), job['id']))
            return {'id': job['id'], 'state': after, 'approved_hash': job[version_key]}
        return self.once(event, apply)

    def continue_build(self, event):
        """Grant one bounded budget extension and resume the approved workspace."""
        def apply():
            job = self.scoped(event)
            timestamp = float(event['event'])
            if not math.isfinite(timestamp) or timestamp < job['updated']:
                raise ValueError('The continuation is older than the current stage.')
            plan = json.loads(job['plan'])
            approved = self.db.execute(
                'SELECT 1 FROM approvals WHERE job=? AND command=? AND version=?',
                (job['id'], 'plan-ok', job['plan_hash'])).fetchone()
            if (job['state'] != 'failed' or job['artifact'] or plan.get('kind') != 'generated'
                    or 'bundle_hash' not in plan or approved is None
                    or 'budget or call limit' not in (job['error'] or '').lower()):
                raise ValueError('Continue is available only after a model budget or call-limit failure.')
            count = self.db.execute(
                "SELECT COUNT(*) FROM approvals WHERE job=? AND command='continue'",
                (job['id'],)).fetchone()[0]
            if count >= 3:
                raise ValueError('This job has reached its three manual continuations.')
            self.db.execute('INSERT INTO approvals VALUES (?,?,?,?,?,?)',
                (event['channel'], event['event'], job['id'], 'continue', job['plan_hash'], self.owner))
            self.db.execute("UPDATE jobs SET state='queued_build',updated=? WHERE id=?",
                            (time.time(), job['id']))
            return {'id': job['id'], 'state': 'queued_build', 'continuations': count + 1}
        return self.once(event, apply)

    def continuation_count(self, ident):
        return self.db.execute(
            "SELECT COUNT(*) FROM approvals WHERE job=? AND command='continue'", (ident,)).fetchone()[0]

    def release(self, event, slug):
        if not isinstance(slug, str) or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,48}[a-z0-9])?', slug):
            raise ValueError('Use a subdomain containing lowercase letters, numbers, and hyphens.')
        def apply():
            job = self.scoped(event)
            retry = (job['state'] == 'failed' and job['release_target'] == slug and bool(job['artifact']))
            if job['state'] != 'deployed' and not retry or not job['artifact']:
                raise ValueError('The preview must be deployed before release.')
            self.db.execute("UPDATE jobs SET state='queued_release',release_target=?,updated=? WHERE id=?",
                            (slug, time.time(), job['id']))
            return {'id': job['id'], 'state': 'queued_release', 'slug': slug}
        return self.once(event, apply)

    def cancel(self, event):
        def apply():
            job = self.scoped(event)
            if job['state'] not in ('queued_plan', 'planning', 'awaiting_plan', 'queued_build', 'building', 'awaiting_deploy', 'queued_deploy'):
                raise ValueError('An active or completed deployment cannot be stopped here.')
            self.db.execute("UPDATE jobs SET state='cancelled',updated=? WHERE id=?", (time.time(), job['id']))
            return {'id': job['id'], 'state': 'cancelled'}
        return self.once(event, apply)

    def claim(self):
        """One worker phase at a time; claim token prevents stale completions."""
        def apply():
            if self.db.execute("SELECT 1 FROM jobs WHERE state IN ('planning','building','deploying','releasing')").fetchone():
                return None
            job = self.db.execute("SELECT * FROM jobs WHERE state IN ('queued_plan','queued_build','queued_deploy','queued_release') ORDER BY updated LIMIT 1").fetchone()
            if not job:
                return None
            state = {'queued_plan': 'planning', 'queued_build': 'building', 'queued_deploy': 'deploying', 'queued_release': 'releasing'}[job['state']]
            claim = uuid.uuid4().hex
            self.db.execute('UPDATE jobs SET state=?,claim=?,updated=? WHERE id=?', (state, claim, time.time(), job['id']))
            return dict(self.db.execute('SELECT * FROM jobs WHERE id=?', (job['id'],)).fetchone())
        return self.transaction(apply)

    def finish(self, ident, claim, artifact=None, error=None):
        def apply():
            job = self.db.execute('SELECT * FROM jobs WHERE id=?', (ident,)).fetchone()
            if not job or job['claim'] != claim or job['state'] not in ('planning', 'building', 'deploying', 'releasing'):
                return False
            if error:
                self.db.execute("UPDATE jobs SET state='failed',error=?,updated=? WHERE id=?", (error, time.time(), ident))
            elif job['state'] == 'planning':
                if not isinstance(artifact, dict) or artifact.get('kind') != 'generated':
                    raise ValueError('Planning must supply a generated project plan')
                self.db.execute("UPDATE jobs SET state='awaiting_plan',plan=?,plan_hash=?,updated=? WHERE id=?",
                    (json.dumps(artifact), digest(artifact), time.time(), ident))
            elif job['state'] == 'building':
                if not isinstance(artifact, dict) or not artifact:
                    raise ValueError('Build must supply an immutable artifact manifest')
                self.db.execute("UPDATE jobs SET state='awaiting_deploy',artifact=?,artifact_hash=?,updated=? WHERE id=?",
                    (json.dumps(artifact), digest(artifact), time.time(), ident))
            elif job['state'] == 'releasing':
                if not isinstance(artifact, dict) or not artifact.get('url'):
                    raise ValueError('Release must supply a remote URL')
                self.db.execute("UPDATE jobs SET state='released',release_url=?,updated=? WHERE id=?",
                                (artifact['url'], time.time(), ident))
            else:
                # Worker must verify remote receipt against approved manifest before finishing.
                self.db.execute("UPDATE jobs SET state='deployed',updated=? WHERE id=?", (time.time(), ident))
            completed = dict(self.db.execute('SELECT * FROM jobs WHERE id=?', (ident,)).fetchone())
            self.db.execute('INSERT INTO notifications (id,payload) VALUES (?,?)', (str(uuid.uuid4()), json.dumps(completed)))
            return True
        return self.transaction(apply)

    def recover(self):
        """Called once after obtaining the exclusive worker process lock on startup."""
        return self.transaction(lambda: self.db.execute(
            "UPDATE jobs SET state='interrupted',error='Worker restarted; inspect remote state before retrying',updated=? WHERE state IN ('planning','building','deploying','releasing')",
            (time.time(),)).rowcount)
