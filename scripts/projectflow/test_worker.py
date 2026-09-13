import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jobs import digest
from worker import deploy, sha, clean_env


class WorkerTests(unittest.TestCase):
    def test_deploy_binds_files_and_receipt_to_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / '123456abcdef'; root.mkdir()
            (root / 'image.tar.gz').write_bytes(b'image')
            (root / 'frontend.json').write_bytes(b'frontend')
            manifest = {'image': 'sha256:expected', 'frontend': 'frontendhash',
                        'image_archive': sha(root / 'image.tar.gz'), 'frontend_file': sha(root / 'frontend.json')}
            job = {'plan': '{}', 'id': root.name, 'artifact': json.dumps(manifest), 'artifact_hash': digest(manifest)}
            cfg = {'state_dir': temp, 'ssh_key': '/key', 'ssh_target': 'picodeploy@host', 'ssh_port': 48039}
            with patch('worker.subprocess.run') as command, patch('worker.remote', return_value={
                    'approval': digest(manifest), 'version': {'image': manifest['image'], 'frontend': manifest['frontend']}}):
                deploy(cfg, job, None)
                self.assertEqual(command.call_count, 2)
                self.assertTrue((root / 'receipt.json').exists())
            (root / 'image.tar.gz').write_bytes(b'changed')
            with patch('worker.subprocess.run') as command:
                with self.assertRaises(ValueError):
                    deploy(cfg, job, None)
                command.assert_not_called()

    def test_child_process_environment_excludes_slack_and_provider_secrets(self):
        with patch.dict('os.environ', {'SLACK_BOT_TOKEN': 'secret', 'OPENAI_API_KEY': 'secret',
                                       'PICOCLAW_CONFIG': '/runtime-with-secrets', 'PATH': '/usr/bin'}):
            env = clean_env()
            self.assertNotIn('SLACK_BOT_TOKEN', env)
            self.assertNotIn('OPENAI_API_KEY', env)
            self.assertNotIn('PICOCLAW_CONFIG', env)
            self.assertEqual(env['PATH'], '/usr/bin')


if __name__ == '__main__':
    unittest.main()


class GeneratedBuildTests(unittest.TestCase):
    def test_failed_build_repairs_twice_then_stops_without_remote_changes(self):
        import subprocess
        from worker import build
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / '123456abcdef'; root.mkdir()
            (root / 'generation-bundle.json').write_text('{}')
            plan = {'kind': 'generated', 'target': 'app-123456abcdef.marcusasplund.com'}
            job = {'id': root.name, 'plan': json.dumps(plan), 'plan_hash': digest(plan), 'claim': 'claim'}
            hashes = {'frontend': 'a' * 64, 'backend': 'b' * 64}
            with patch('codeagent.CodeAgent') as agent_class, patch('worker.Jobs') as ledger_class, \
                    patch('worker.notify'), \
                    patch('worker.subprocess.run', side_effect=subprocess.CalledProcessError(1, ['builder'])) as command, \
                    patch('worker.remote') as remote:
                agent = agent_class.return_value.__enter__.return_value
                agent.export.return_value = hashes
                ledger = ledger_class.return_value
                ledger.continuation_count.return_value = 0
                ledger.db.execute.return_value.fetchone.return_value = {'state': 'building', 'claim': 'claim'}
                with self.assertRaises(subprocess.CalledProcessError):
                    build({'state_dir': temp, 'owner': 'owner'}, job, None)
                self.assertEqual(command.call_count, 3)
                self.assertEqual(agent.work.call_count, 3)  # Initial work plus two repairs.
                self.assertEqual(agent.escalate.call_count, 2)
                self.assertEqual(agent.export.call_count, 3)
                for attempt in range(1, 4):
                    self.assertTrue((root / 'build-run-1' / f'attempt-{attempt}' / 'feedback.json').exists())
                remote.assert_not_called()
                with self.assertRaises(subprocess.CalledProcessError):
                    build({'state_dir': temp, 'owner': 'owner'}, job, None)
                self.assertTrue((root / 'build-run-1').is_dir())
                self.assertTrue((root / 'build-run-2').is_dir())
                self.assertEqual(command.call_count, 6)
