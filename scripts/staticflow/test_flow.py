import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flow import Flow, digest, validate_files, parse_files, failure_detail
import remote

FILES={'index.html':'<!doctype html><html><body>OK</body></html>','style.css':'body {}','app.js':'console.log("ok");'}

class FlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.calls=[]; self.deploys=[]
        self.cfg={'state_dir':self.tmp.name,'owner':'U_OWNER','domain':'marcusasplund.com'}
        def model(system,prompt):
            self.calls.append(prompt)
            return 'Plan med acceptanskriterier' if len(self.calls)==1 else json.dumps(FILES)
        def publish(mode,job,files):
            self.deploys.append((mode,digest(files)))
            return 'https://'+('preview-' if mode=='preview' else '')+job['slug']+'.marcusasplund.com'
        self.flow=Flow(self.cfg,model,publish)
        self.addCleanup(self.flow.db.close)
        self.seq=0
    def event(self,text,**kw):
        self.seq+=1
        return dict(user='U_OWNER',channel='D1',thread='T1',event=str(self.seq),text=text,**kw)
    def job(self):
        return self.flow.db.execute('SELECT * FROM jobs').fetchone()
    def start(self):
        return self.flow.handle(self.event('bygg app-demo en räknare'))
    def approve(self):
        j=self.job()
        return self.flow.handle(self.event(f"plan-ok {j['id']} {j['plan_hash']}"))
    def test_requires_exact_owner_and_thread(self):
        e=self.event('bygg app-demo en räknare'); e['user']='U_OTHER'
        self.assertIn('behörighet',self.flow.handle(e)); self.assertFalse(self.calls)
        self.start();j=self.job();e=self.event(f"plan-ok {j['id']} {j['plan_hash']}");e['thread']='T2'
        self.assertIn('tråden',self.flow.handle(e));self.assertEqual(len(self.calls),1)
    def test_full_flow_and_wrong_hash(self):
        self.start();j=self.job()
        self.assertIn('Fel status',self.flow.handle(self.event(f"plan-ok {j['id']} bad")))
        self.assertEqual(len(self.calls),1)
        with patch('flow.subprocess.run'):
            self.approve()
        self.assertEqual(self.job()['state'],'awaiting_deploy')
        self.assertEqual([x[0] for x in self.deploys],['preview'])
        j=self.job()
        self.assertIn('Fel status',self.flow.handle(self.event(f"deploy {j['id']} stale")))
        self.assertEqual(len(self.deploys),1)
        self.flow.handle(self.event(f"deploy {j['id']} {j['artifact_hash']}"))
        self.assertEqual(self.job()['state'],'deployed')
        self.assertEqual([x[0] for x in self.deploys],['preview','publish'])
    def test_duplicate_event_does_not_generate_twice(self):
        event=self.event('bygg app-demo en räknare')
        first=self.flow.handle(event)
        self.assertEqual(self.flow.handle(event),first)
        self.assertEqual(len(self.calls),1)
    def test_state_survives_new_process(self):
        self.start();j=self.job()
        other=Flow(self.cfg);self.addCleanup(other.db.close)
        reply=other.handle(self.event('jobb '+j['id']))
        self.assertIn(j['plan'],reply)
    def test_cancel_blocks_approval(self):
        self.start();j=self.job();self.flow.handle(self.event('stoppa '+j['id']))
        self.assertIn('Fel status',self.approve());self.assertEqual(len(self.calls),1)
    def test_changed_artifact_never_published(self):
        self.start()
        with patch('flow.subprocess.run'): self.approve()
        j=self.job()
        with self.flow.db:
            self.flow.db.execute('UPDATE jobs SET files=?',(json.dumps(dict(FILES, **{'app.js':'changed'})),))
        reply=self.flow.handle(self.event(f"deploy {j['id']} {j['artifact_hash']}"))
        self.assertIn('misslyckades',reply);self.assertEqual(len(self.deploys),1)
    def test_stop_while_generating_discards_output(self):
        def model(system,prompt):
            other=Flow(self.cfg)
            try:
                j=other.db.execute('SELECT * FROM jobs').fetchone()
                other.handle(self.event('stoppa '+j['id']))
            finally: other.db.close()
            return 'Plan'
        self.flow.model=model
        self.assertIn('stoppades',self.start())
        self.assertEqual(self.job()['state'],'cancelled')
    def test_generated_paths_and_remote_payload_rejected(self):
        for files in ({'../bad':'x'},dict(FILES, **{'secret.php':'bad'})):
            with self.assertRaises(ValueError): validate_files(files)
        for slug in ('../../etc','duchat.se','app-x;whoami','app-../x'):
            with self.assertRaises(ValueError):
                remote.validate({'mode':'publish','slug':slug,'files':FILES,'digest':digest(FILES)})
        with self.assertRaises(ValueError):
            remote.validate({'mode':'publish','slug':'app-ok','files':FILES,'digest':'bad'})
    def test_fenced_json_parses_without_executing_content(self):
        self.assertEqual(parse_files('```json\n'+json.dumps(FILES)+'\n```'),FILES)
        with self.assertRaises(json.JSONDecodeError): parse_files('not JSON')
    def test_diagnostics_do_not_echo_subprocess_secrets(self):
        import subprocess
        exc=subprocess.CalledProcessError(255,['ssh'],stderr='SECRET_VALUE')
        detail=failure_detail('SSH/preview',exc)
        self.assertIn('255',detail)
        self.assertNotIn('SECRET_VALUE',detail)
    def test_preview_failure_can_retry_saved_bytes_without_model_or_publish(self):
        self.start()
        publish=self.flow.remote
        def fail(*args): raise RuntimeError('preview failure')
        self.flow.remote=fail
        with patch('flow.subprocess.run'): self.approve()
        j=self.job(); self.assertEqual(j['state'],'failed')
        original_hash=j['artifact_hash'];calls=len(self.calls)
        self.flow.remote=publish
        result=self.approve()
        self.assertIn('Preview återställd',result)
        self.assertEqual(len(self.calls),calls)
        self.assertEqual(self.job()['artifact_hash'],original_hash)
        self.assertEqual(self.deploys,[('preview',original_hash)])
        self.assertEqual(self.job()['state'],'awaiting_deploy')
    def test_failed_publish_cannot_be_retried_as_preview(self):
        self.start()
        with patch('flow.subprocess.run'): self.approve()
        j=self.job()
        with self.flow.db: self.flow.update(j['id'],state='failed',error='Fasen deploy misslyckades.')
        self.assertIn('Fel status',self.approve())
    def test_short_approvals_bind_to_saved_versions_and_are_audited(self):
        import time
        self.start()
        j=self.job();ph=j['plan_hash']
        event=self.event('plan-ok');event['event']=str(time.time()+1)
        with patch('flow.subprocess.run'): self.flow.handle(event)
        self.assertEqual(self.job()['state'],'awaiting_deploy')
        ah=self.job()['artifact_hash']
        event=self.event('deploy');event['event']=str(time.time()+2)
        self.flow.handle(event)
        self.assertEqual(self.job()['state'],'deployed')
        rows=self.flow.db.execute('SELECT command,version FROM approvals ORDER BY approved_at').fetchall()
        self.assertEqual([tuple(r) for r in rows],[('plan-ok',ph),('deploy',ah)])
    def test_short_approval_rejects_old_slack_event(self):
        self.start()
        self.assertIn('före det aktuella',self.flow.handle(self.event('plan-ok')))
        self.assertEqual(len(self.calls),1)
    def test_short_approval_rejects_other_thread_and_ambiguous_thread(self):
        import time
        self.start()
        event=self.event('plan-ok');event['thread']='OTHER';event['event']=str(time.time()+1)
        self.assertIn('exakt ett jobb',self.flow.handle(event))
        with self.flow.db:
            self.flow.db.execute("INSERT INTO jobs (id,owner,channel,thread) VALUES ('second','U_OWNER','D1','T1')")
        event=self.event('plan-ok');event['event']=str(time.time()+2)
        self.assertIn('exakt ett jobb',self.flow.handle(event))
        self.assertEqual(len(self.calls),1)
    def short(self,text):
        import time
        event=self.event(text);event['event']=str(time.time()+1)
        return self.flow.handle(event)
    def built(self):
        self.start()
        with patch('flow.subprocess.run'): self.approve()
    def test_delete_requires_confirmation_and_records_exact_version(self):
        self.built();j=self.job();n=len(self.deploys)
        self.assertIn('Fel status',self.short('delete-ok'))
        self.assertEqual(len(self.deploys),n)
        reply=self.short('delete')
        self.assertIn('delete-ok',reply)
        self.assertEqual(len(self.deploys),n)
        self.short('delete-ok')
        self.assertEqual(self.job()['state'],'deleted')
        self.assertEqual(self.deploys[-1],('delete',j['artifact_hash']))
        approval=self.flow.db.execute("SELECT version FROM approvals WHERE command='delete-ok'").fetchone()
        self.assertEqual(approval['version'],j['artifact_hash'])
        n=len(self.deploys);self.short('delete-ok');self.short('delete')
        self.assertEqual(len(self.deploys),n)
    def test_stop_cancels_delete_without_changing_site(self):
        self.built();self.short('delete');n=len(self.deploys)
        self.assertIn('avbruten',self.short('stoppa'))
        self.assertEqual(self.job()['state'],'awaiting_deploy')
        self.assertIn('Fel status',self.short('delete-ok'))
        self.assertEqual(len(self.deploys),n)
    def test_delete_confirmation_expires(self):
        import time
        self.built();self.short('delete')
        with self.flow.db:
            self.flow.db.execute('UPDATE delete_requests SET requested_at=?',(time.time()-601,))
        self.assertIn('gått ut',self.short('delete-ok'))
        self.assertEqual(self.deploys[-1][0],'preview')
    def test_delete_in_wrong_thread_is_rejected(self):
        import time
        self.built();self.short('delete')
        event=self.event('delete-ok');event['event']=str(time.time()+1);event['thread']='OTHER'
        self.assertIn('exakt ett jobb',self.flow.handle(event))
        self.assertEqual(self.job()['state'],'awaiting_delete')
    def test_nginx_routes_protected_preview(self):
        c=remote.config('preview-app-ok.marcusasplund.com',Path('/safe/release'),'abc',True)
        self.assertIn('auth_basic "PicoClaw preview"',c)
        self.assertNotIn('auth_basic "PicoClaw preview"',remote.config('app-ok.marcusasplund.com',Path('/safe/release'),'abc',False))

class RemoteTest(unittest.TestCase):
    def test_health_check_waits_for_new_workers(self):
        import subprocess
        with patch.object(remote,'run',side_effect=[subprocess.CalledProcessError(60,['curl']), 'old', 'correct']) as run, patch.object(remote.time,'sleep') as sleep:
            remote.wait_healthy('app-demo.marcusasplund.com','correct')
        self.assertEqual(run.call_count,3)
        self.assertEqual(sleep.call_count,2)
        self.assertIn('--noproxy',run.call_args.args)
    def test_withdraw_keeps_certificates_backups_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);available=root/'available';enabled=root/'enabled';base=root/'releases'
            available.mkdir();enabled.mkdir()
            version=digest(FILES);slug='app-demo'
            originals={}
            for host in (slug+'.marcusasplund.com','preview-'+slug+'.marcusasplund.com'):
                site=available/('picoclaw-'+host)
                text=remote.config(host,base/slug/version,version,host.startswith('preview-'))
                site.write_text(text);(enabled/site.name).symlink_to(site);originals[site]=text
            payload={'mode':'delete','slug':slug,'digest':version,'files':FILES}
            with patch.object(remote,'BASE',base),patch.object(remote,'AVAILABLE',available),patch.object(remote,'ENABLED',enabled),patch.object(remote,'run'),patch.object(remote,'wait_gone',side_effect=ValueError('not ready')):
                with self.assertRaises(ValueError): remote.deploy(payload,{'domain':'marcusasplund.com'})
            for site,old in originals.items(): self.assertEqual(site.read_text(),old)
            with patch.object(remote,'BASE',base),patch.object(remote,'AVAILABLE',available),patch.object(remote,'ENABLED',enabled),patch.object(remote,'run'),patch.object(remote,'wait_gone'):
                self.assertTrue(remote.deploy(payload,{'domain':'marcusasplund.com'})['deleted'])
                self.assertTrue(remote.deploy(payload,{'domain':'marcusasplund.com'})['deleted'])
            for site,old in originals.items():
                self.assertIn('return 410',site.read_text())
                self.assertIn('ssl_certificate ',site.read_text())
                self.assertTrue((enabled/site.name).is_symlink())
                self.assertEqual((base/slug/'withdrawn'/version/site.name).read_text(),old)
    def test_withdraw_refuses_changed_version_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);available=root/'available';enabled=root/'enabled'
            available.mkdir();enabled.mkdir()
            site=available/'picoclaw-app-demo.marcusasplund.com';site.write_text('another version')
            (enabled/site.name).symlink_to(site)
            with patch.object(remote,'BASE',root/'releases'),patch.object(remote,'AVAILABLE',available),patch.object(remote,'ENABLED',enabled),patch.object(remote,'run') as run:
                with self.assertRaises(ValueError):
                    remote.deploy({'mode':'delete','slug':'app-demo','digest':digest(FILES),'files':FILES},{'domain':'marcusasplund.com'})
                run.assert_not_called()
            self.assertEqual(site.read_text(),'another version')
    def test_failed_health_check_restores_previous_nginx_config(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); available=root/'available';enabled=root/'enabled'
            available.mkdir();enabled.mkdir()
            site=available/'picoclaw-app-demo.marcusasplund.com'
            site.write_text('previous config');(enabled/site.name).symlink_to(site)
            calls=[]
            def command(*args):
                calls.append(args)
                if args[0]=='curl': return 'wrong-version'
                return ''
            with patch.object(remote,'BASE',root/'releases'), patch.object(remote,'AVAILABLE',available), patch.object(remote,'ENABLED',enabled), patch.object(remote,'run',command), patch.object(remote.time,'sleep'):
                with self.assertRaises(ValueError):
                    remote.deploy({'mode':'publish','slug':'app-demo','files':FILES,'digest':digest(FILES)}, {'domain':'marcusasplund.com','email':'test@example.com'})
            self.assertEqual(site.read_text(),'previous config')
            self.assertTrue((enabled/site.name).is_symlink())
            self.assertEqual(calls[-1],('systemctl','reload','nginx'))

if __name__=='__main__': unittest.main()
