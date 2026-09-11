#!/usr/bin/env python3
"""Authenticated Slack -> durable static-app jobs. No generated host commands."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
import uuid

SLUG = re.compile(r'app-[a-z0-9]+(?:-[a-z0-9]+)*\Z')
FILES = {'index.html', 'style.css', 'app.js'}

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()

def parse_files(raw):
    # Some models wrap otherwise valid JSON in a Markdown code block.
    text=raw.strip()
    if text.startswith('```'):
        lines=text.splitlines()
        if lines[0].strip().lower() in ('```', '```json') and lines[-1].strip()=='```':
            text='\n'.join(lines[1:-1])
    return validate_files(json.loads(text))

def failure_detail(stage, error):
    # Never return subprocess stderr, model output or request headers to Slack.
    detail=type(error).__name__
    if isinstance(error, subprocess.CalledProcessError):
        detail+=' (exit '+str(error.returncode)+')'
    elif isinstance(error, json.JSONDecodeError):
        detail+=' (rad '+str(error.lineno)+', kolumn '+str(error.colno)+')'
    return stage+': '+detail

def validate_files(files):
    if not isinstance(files, dict) or set(files) != FILES:
        raise ValueError('Bygget måste innehålla index.html, style.css och app.js.')
    if any(not isinstance(v, str) or len(v.encode()) > 150000 for v in files.values()):
        raise ValueError('Ogiltig filstorlek eller filtyp.')
    if '<html' not in files['index.html'].lower():
        raise ValueError('HTML-dokument saknas.')
    return files

class Flow:
    def __init__(self, settings, model=None, remote=None):
        self.cfg = settings
        root = Path(settings['state_dir']); root.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.db = sqlite3.connect(root / 'jobs.sqlite', timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, owner TEXT, channel TEXT, thread TEXT, slug TEXT,
          request TEXT, state TEXT, plan TEXT DEFAULT '', plan_hash TEXT DEFAULT '',
          files TEXT DEFAULT '', artifact_hash TEXT DEFAULT '', updated REAL, error TEXT DEFAULT '');
          CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, reply TEXT);
          CREATE TABLE IF NOT EXISTS delete_requests (job_id TEXT PRIMARY KEY, previous_state TEXT, requested_at REAL);
          CREATE TABLE IF NOT EXISTS approvals (
            event_id TEXT PRIMARY KEY, job_id TEXT, owner TEXT, command TEXT, version TEXT, approved_at REAL);
        ''')
        self.model = model or self.call_model
        self.remote = remote or self.call_remote

    def call_model(self, system, prompt):
        result = subprocess.run(self.cfg['llm_command'], input=json.dumps({'system':system,'prompt':prompt}),
                                capture_output=True, text=True, timeout=200, check=True)
        return json.loads(result.stdout)['content']

    def call_remote(self, mode, job, files):
        payload = {'mode':mode,'slug':job['slug'],'digest':digest(files),'files':files}
        result = subprocess.run(['ssh','-i',self.cfg['ssh_key'],'-o','BatchMode=yes',
             '-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=10',
             '-p',str(self.cfg['ssh_port']),self.cfg['ssh_target'],
             'sudo -n /usr/local/sbin/picoclaw-static-site'],
             input=json.dumps(payload),capture_output=True,text=True,timeout=200,check=True)
        receipt=json.loads(result.stdout)
        if receipt.get('digest') != digest(files):
            raise ValueError('Fel version i deploykvittot.')
        if mode=='delete' and receipt.get('deleted') is not True:
            raise ValueError('Borttagningen saknar bekräftat serverkvitto.')
        return receipt['url']

    def update(self, ident, **fields):
        fields['updated']=time.time()
        self.db.execute('UPDATE jobs SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',[*fields.values(),ident])

    def handle(self, event):
        if event['user'] != self.cfg['owner']:
            return 'Avsändaren saknar behörighet.'
        text=event['text'].strip(); parts=text.split(); command=parts[0].lower()
        event_id='|'.join((event['channel'],event['event']))
        self.db.execute('BEGIN IMMEDIATE')
        seen=self.db.execute('SELECT reply FROM events WHERE id=?',(event_id,)).fetchone()
        if seen:
            self.db.commit(); return seen['reply'] or 'Kommandot är redan mottaget. Kontrollera jobbstatus.'
        self.db.execute('INSERT INTO events VALUES (?,?)',(event_id,''))
        ident=None
        try:
            if command=='bygg':
                if len(parts)<3 or not SLUG.fullmatch(parts[1]) or len(parts[1])>40 or len(text)>6000:
                    raise ValueError('Använd: bygg app-namn beskrivning (högst 6000 tecken).')
                if self.db.execute("SELECT 1 FROM jobs WHERE slug=? AND state!='cancelled'",(parts[1],)).fetchone():
                    raise ValueError('Appnamnet används redan. Välj ett nytt namn.')
                ident=uuid.uuid4().hex[:12]
                self.db.execute('INSERT INTO jobs (id,owner,channel,thread,slug,request,state,updated) VALUES (?,?,?,?,?,?,?,?)',
                  (ident,event['user'],event['channel'],event['thread'],parts[1],text.split(None,2)[2],'planning',time.time()))
                phase='plan'
            else:
                if len(parts)==1:
                    candidates=self.db.execute('SELECT id FROM jobs WHERE owner=? AND channel=? AND thread=?',
                        (event['user'],event['channel'],event['thread'])).fetchall()
                    if len(candidates)!=1:
                        raise ValueError('Tråden måste innehålla exakt ett jobb. Ange annars jobb-ID efter kommandot.')
                    parts.append(candidates[0]['id'])
                ident=parts[1]
                job=self.db.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone()
                if not job or (job['owner'],job['channel'],job['thread']) != (event['user'],event['channel'],event['thread']):
                    raise ValueError('Jobbet saknas i den här tråden. Svara i jobbets ursprungliga Slack-tråd.')
                if job['state'] in ('planning','building','previewing','deploying','deleting') and time.time()-job['updated']>600:
                    self.update(ident,state='interrupted',error='Avbrutet efter timeout/omstart. Kontrollera fjärrstatus innan nytt jobb.')
                    job=self.db.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone()
                if command=='jobb':
                    reply=f"Jobb {ident}: {job['state']}\n{job['error']}"
                    if job['state']=='awaiting_plan': reply+=f"\n{job['plan']}\nSvara plan-ok i denna tråd."
                    if job['state']=='awaiting_deploy': reply+=f"\nhttps://preview-{job['slug']}.{self.cfg['domain']}\nSvara deploy i denna tråd."
                    if job['state']=='failed' and job['files'] and job['error'].startswith('Fasen build '): reply+=f"\nÅterförsök endast preview, utan ny generering:\nSvara plan-ok i denna tråd."
                    if job['state']=='awaiting_delete': reply+='\nSvara delete-ok för att bekräfta borttagning, eller stoppa.'
                    if job['state']=='deleted': reply+='\nApp och preview nedtagna. Byggfilerna är bevarade.'
                    if job['state']=='deployed': reply+=f"\nhttps://{job['slug']}.{self.cfg['domain']}"
                    return self.finish(event_id,reply)
                if command=='delete':
                    if len(parts)!=2: raise ValueError('Svara delete i jobbets tråd.')
                    if job['state']=='deleted': return self.finish(event_id,'Appen och preview är redan nedtagna.')
                    if job['state'] not in ('deployed','awaiting_deploy','failed','awaiting_delete','interrupted') or not job['files']:
                        raise ValueError('Jobbet kan inte tas ned i nuvarande steg.')
                    previous=job['state']
                    if previous=='awaiting_delete':
                        previous=self.db.execute('SELECT previous_state FROM delete_requests WHERE job_id=?',(ident,)).fetchone()['previous_state']
                    self.db.execute('INSERT OR REPLACE INTO delete_requests VALUES (?,?,?)',(ident,previous,time.time()))
                    self.update(ident,state='awaiting_delete')
                    return self.finish(event_id,f"Ta ned {job['slug']}.{self.cfg['domain']} och preview-{job['slug']}.{self.cfg['domain']}? Byggfiler och certifikat behålls.\nSvara delete-ok inom 10 minuter, eller stoppa för att avbryta.")
                if command=='stoppa':
                    if job['state']=='awaiting_delete':
                        previous=self.db.execute('SELECT previous_state FROM delete_requests WHERE job_id=?',(ident,)).fetchone()['previous_state']
                        self.update(ident,state=previous)
                        self.db.execute('DELETE FROM delete_requests WHERE job_id=?',(ident,))
                        return self.finish(event_id,'Borttagningen avbruten. Appen är oförändrad.')
                    if job['state'] in ('previewing','deploying','deployed','deleting','deleted'):
                        raise ValueError('Publicering pågår eller är klar. Stoppa ändrar inte en fjärrpublicering.')
                    self.update(ident,state='cancelled')
                    return self.finish(event_id,'Jobbet stoppat. Eventuellt pågående modellresultat kommer att ignoreras.')
                if len(parts)==2 and command in ('plan-ok','deploy','delete-ok'):
                    # Resolve the immutable version while holding the write transaction.
                    # Delayed Slack events from before this stage must not approve it.
                    event_time=float(event['event'])
                    if not math.isfinite(event_time) or event_time<job['updated']:
                        raise ValueError('Godkännandet skickades före det aktuella steget. Svara igen i tråden.')
                    parts.append(job['plan_hash'] if command=='plan-ok' else job['artifact_hash'])
                if len(parts)!=3:
                    raise ValueError('Svara plan-ok eller deploy i jobbets tråd.')
                if command=='delete-ok' and job['state']=='awaiting_delete' and parts[2]==job['artifact_hash']:
                    request=self.db.execute('SELECT requested_at FROM delete_requests WHERE job_id=?',(ident,)).fetchone()
                    event_time=float(event['event'])
                    if not request or time.time()-request['requested_at']>600 or not math.isfinite(event_time) or event_time<request['requested_at']:
                        raise ValueError('Bekräftelsen har gått ut eller är för gammal. Svara delete igen.')
                    self.update(ident,state='deleting'); phase='delete'
                elif command=='plan-ok' and job['state']=='failed'  and job['files'] and job['error'].startswith('Fasen build ') and parts[2]==job['plan_hash']:
                    self.update(ident,state='previewing'); phase='preview'
                elif command=='plan-ok' and job['state']=='awaiting_plan' and parts[2]==job['plan_hash']:
                    self.update(ident,state='building'); phase='build'
                elif command=='deploy' and job['state']=='awaiting_deploy' and parts[2]==job['artifact_hash']:
                    self.update(ident,state='deploying'); phase='deploy'
                else:
                    raise ValueError('Fel status eller versionshash. Inget bygge eller deploy startades.')
                self.db.execute('INSERT INTO approvals VALUES (?,?,?,?,?,?)',
                    (event_id,ident,event['user'],command,parts[2],time.time()))
            # At most one expensive phase at a time, across independent Slack deliveries.
            if self.db.execute("SELECT 1 FROM jobs WHERE id!=? AND state IN ('planning','building','previewing','deploying','deleting') AND updated>?",(ident,time.time()-600)).fetchone():
                raise ValueError('Ett annat jobb arbetar. Försök igen när det är klart.')
            self.db.commit()
        except ValueError as exc:
            self.db.rollback()
            return str(exc)
        job=dict(self.db.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone())
        stage='modellanrop'
        try:
            if phase=='plan':
                plan=self.model('Du planerar små statiska appar. Svara på svenska med scope, acceptanskriterier och testplan. Ingen backend, externa beroenden eller hemligheter. Högst 2000 tecken. Markera krav som inte kan uppfyllas statiskt.',job['request'])
                if not plan.strip() or len(plan)>5000: raise ValueError('Planen är tom eller för lång.')
                self.db.execute('BEGIN IMMEDIATE')
                if self.current_state(ident)!='planning': return self.finish(event_id,'Jobbet stoppades; planen sparades inte.')
                ph=digest(plan)
                self.update(ident,state='awaiting_plan',plan=plan,plan_hash=ph)
                reply=f"Jobb {ident}: {job['slug']}\n{plan}\n\nGodkänn i denna tråd:\nplan-ok"
            elif phase=='preview':
                stage='validera sparat bygge'
                files=validate_files(json.loads(job['files']))
                if digest(files)!=job['artifact_hash']: raise ValueError('Bygginnehållet har ändrats.')
                stage='SSH/preview på Lenovo'
                url=self.remote('preview',job,files)
                self.db.execute('BEGIN IMMEDIATE')
                self.update(ident,state='awaiting_deploy',error='')
                reply=f"Preview återställd: {url}\nReviewa och godkänn sedan i denna tråd:\nSvara deploy i denna tråd."
            elif phase=='build':
                raw=self.model('Generate exactly a JSON object with three string values: index.html, style.css, app.js. Complete static app, no Markdown fences, no external dependencies, no fetch, forms to servers, remote scripts or secrets. Use relative ./style.css and ./app.js URLs. Accessible responsive UI. Never execute host commands.',job['request']+'\nAPPROVED PLAN:\n'+job['plan'])
                stage='tolka modellens fil-JSON'
                files=parse_files(raw)
                stage='JavaScript-syntaxkontroll (node --check)'
                subprocess.run([self.cfg.get('node_binary','node'),'--check'],input=files['app.js'],text=True,capture_output=True,timeout=15,check=True)
                self.db.execute('BEGIN IMMEDIATE')
                if self.current_state(ident)!='building': return self.finish(event_id,'Jobbet stoppades; bygget publicerades inte.')
                self.update(ident,state='previewing',files=json.dumps(files),artifact_hash=digest(files))
                self.db.commit()
                stage='SSH/preview på Lenovo'
                url=self.remote('preview',job,files)
                self.db.execute('BEGIN IMMEDIATE')
                self.update(ident,state='awaiting_deploy')
                reply=f"Jobb {ident}: preview klar\n{url}\nAnvänd preview-inloggningen du skapade på Lenovo.\nKontroller: filformat/storlek och JavaScript-syntax. Funktion och utseende behöver din review.\n\nPublicera exakt detta bygge:\ndeploy"
            else:
                files=validate_files(json.loads(job['files']))
                if digest(files)!=job['artifact_hash']: raise ValueError('Bygginnehållet matchar inte godkännandet.')
                stage='SSH/borttagning på Lenovo' if phase=='delete' else 'SSH/publicering på Lenovo'
                url=self.remote('delete' if phase=='delete' else 'publish',job,files)
                self.db.execute('BEGIN IMMEDIATE'); self.update(ident,state='deleted' if phase=='delete' else 'deployed',error='')
                if phase=='delete':
                    self.db.execute('DELETE FROM delete_requests WHERE job_id=?',(ident,))
                    reply=f"Appen {job['slug']} och dess preview är nedtagna. Byggfiler och certifikat finns kvar för återställning."
                else:
                    reply=f"Publicerat: {url}\nVersion: {job['artifact_hash']}"
            return self.finish(event_id,reply)
        except Exception as exc:
            detail=failure_detail(stage,exc)
            self.db.rollback()
            self.db.execute('BEGIN IMMEDIATE')
            if self.current_state(ident)!='cancelled':
                self.update(ident,state='failed',error='Fasen '+('build' if phase=='preview' else phase)+' misslyckades: '+detail+'. Fjärrändringar kan ha slutförts om anslutningen bröts; kontrollera servern innan nytt försök.')
            return self.finish(event_id,f'Jobb {ident} misslyckades i {phase}: {detail}. Inga automatiska återförsök. Använd jobb {ident}.')

    def current_state(self, ident):
        return self.db.execute('SELECT state FROM jobs WHERE id=?',(ident,)).fetchone()['state']

    def finish(self,event_id,reply):
        self.db.execute('UPDATE events SET reply=? WHERE id=?',(reply,event_id));self.db.commit();return reply

if __name__=='__main__':
    os.umask(0o077)
    try:
        settings=json.loads(Path(sys.argv[1]).read_text())
        print(Flow(settings).handle(json.load(sys.stdin)))
    except Exception:
        print('Jobbflödet kunde inte läsa konfiguration eller meddelande. Kontrollera installationen.')
        sys.exit(1)
