import tempfile
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from dispatch import handle
from jobs import Jobs


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cfg = {'state_dir': self.temp.name, 'owner': 'owner', 'source_hashes': {},
                    'static_state': self.temp.name + '/static', 'static_command': ['existing-static-flow']}
        self.event = {'user': 'owner', 'channel': 'D', 'thread': 'T', 'event': '1', 'text': 'bygg demo'}

    def test_new_demo_returns_plan_without_running_build(self):
        with patch('dispatch.sources', return_value={'frontend': b'f', 'backend': b'b'}), patch('dispatch.subprocess.run') as run:
            reply = handle(self.cfg, self.event)
            self.assertIn('approve', reply)
            run.assert_not_called()
        ledger = Jobs(self.temp.name, 'owner')
        self.assertEqual(ledger.status(self.event)['state'], 'awaiting_plan')
        ledger.db.close()

    def test_static_commands_keep_existing_handler(self):
        with patch('dispatch.subprocess.run') as run:
            run.return_value.stdout = 'static reply'
            self.assertEqual(handle(self.cfg, {**self.event, 'text': 'bygg statisk app-test test'}), 'static reply')
            self.assertEqual(run.call_args.args[0], ['existing-static-flow'])

    def test_project_approval_is_queued_and_no_static_handler_called(self):
        with patch('dispatch.sources', return_value={'frontend': b'f', 'backend': b'b'}):
            handle(self.cfg, self.event)
        with patch('dispatch.subprocess.run') as run:
            reply = handle(self.cfg, {**self.event, 'event': str(time.time() + 1), 'text': 'plan-ok'})
            self.assertIn('Build queued', reply)
            run.assert_not_called()

    def test_only_owner_can_dispatch_even_static(self):
        with patch('dispatch.subprocess.run') as run:
            with self.assertRaises(ValueError):
                handle(self.cfg, {**self.event, 'user': 'other'})
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
