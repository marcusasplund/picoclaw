import tempfile
import time
import unittest
from jobs import Jobs


class JobsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.jobs = Jobs(self.tmp.name, 'owner')
        self.addCleanup(self.jobs.db.close)
        self.event = {'user': 'owner', 'channel': 'D', 'thread': '1', 'event': '1'}
        self.plan = {'source': 'source-hash', 'target': 'demo'}
        self.jobs.create(self.event, self.plan)

    def event_at_now(self, **extra):
        return {**self.event, 'event': str(time.time() + 1), **extra}

    def test_duplicate_creation_returns_same_job(self):
        result = self.jobs.create(self.event, self.plan)
        self.assertEqual(result['id'], self.jobs.status(self.event)['id'])
        self.assertEqual(self.jobs.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 1)

    def test_wrong_owner_and_thread_cannot_approve(self):
        for change in [{'user': 'other'}, {'thread': '2'}, {'channel': 'other'}]:
            with self.assertRaises(ValueError):
                self.jobs.approve(self.event_at_now(**change), 'plan-ok')

    def test_stale_event_cannot_approve(self):
        with self.assertRaises(ValueError):
            self.jobs.approve({**self.event, 'event': '0.5'}, 'plan-ok')

    def test_approval_is_idempotent_and_bound_to_manifest(self):
        event = self.event_at_now()
        first = self.jobs.approve(event, 'plan-ok')
        self.assertEqual(first, self.jobs.approve(event, 'plan-ok'))
        job = self.jobs.claim()
        self.assertIsNone(self.jobs.claim())
        self.assertTrue(self.jobs.finish(job['id'], job['claim'], {'image': 'sha256:example', 'frontend': 'hash'}))
        approval = self.jobs.approve(self.event_at_now(), 'deploy')
        self.assertEqual(approval['approved_hash'], self.jobs.status(self.event)['artifact_hash'])

    def test_cancel_discards_inflight_build_result(self):
        self.jobs.approve(self.event_at_now(), 'plan-ok')
        job = self.jobs.claim()
        self.jobs.cancel(self.event_at_now())
        self.assertFalse(self.jobs.finish(job['id'], job['claim'], {'image': 'late'}))
        self.assertEqual(self.jobs.status(self.event)['state'], 'cancelled')

    def test_restart_does_not_repeat_remote_action(self):
        self.jobs.approve(self.event_at_now(), 'plan-ok')
        job = self.jobs.claim()
        self.jobs.finish(job['id'], job['claim'], {'image': 'approved'})
        self.jobs.approve(self.event_at_now(), 'deploy')
        self.jobs.claim()
        self.assertEqual(self.jobs.recover(), 1)
        self.assertIsNone(self.jobs.claim())
        self.assertEqual(self.jobs.status(self.event)['state'], 'interrupted')


if __name__ == '__main__':
    unittest.main()

class RetryTests(unittest.TestCase):
    setUp = JobsTests.setUp
    event_at_now = JobsTests.event_at_now

    def test_deploy_retry_requires_new_approval_and_keeps_artifact(self):
        self.jobs.approve(self.event_at_now(), 'plan-ok')
        build = self.jobs.claim()
        self.jobs.finish(build['id'], build['claim'], {'image': 'approved'})
        self.jobs.approve(self.event_at_now(), 'deploy')
        deploy = self.jobs.claim()
        self.jobs.finish(deploy['id'], deploy['claim'], error='Archive validation failed')
        self.assertIsNone(self.jobs.claim())
        retry = self.jobs.approve(self.event_at_now(), 'deploy')
        self.assertEqual(retry['approved_hash'], deploy['artifact_hash'])
        claimed = self.jobs.claim()
        self.assertEqual(claimed['state'], 'deploying')
        self.assertEqual(claimed['artifact'], deploy['artifact'])

    def test_generated_build_retry_requires_prior_plan_approval(self):
        event = {**self.event, 'thread': 'generated', 'event': '10'}
        plan = {'kind': 'generated', 'bundle_hash': 'approved-bundle', 'target': 'app-test'}
        self.jobs.create(event, plan)
        self.jobs.approve({**event, 'event': str(time.time() + 1)}, 'plan-ok')
        build = self.jobs.claim()
        self.jobs.finish(build['id'], build['claim'], error='Generator output invalid')
        retry = self.jobs.approve({**event, 'event': str(time.time() + 2)}, 'plan-ok')
        self.assertEqual(retry['approved_hash'], build['plan_hash'])
        self.assertEqual(self.jobs.claim()['state'], 'building')

    def test_failed_planning_cannot_be_approved_as_a_build_retry(self):
        event = {**self.event, 'thread': 'planning', 'event': '10'}
        self.jobs.create(event, {'kind': 'generated', 'request': 'todo'}, planning=True)
        planning = self.jobs.claim()
        self.jobs.finish(planning['id'], planning['claim'], error='Invalid plan')
        with self.assertRaises(ValueError):
            self.jobs.approve({**event, 'event': str(time.time() + 1)}, 'plan-ok')
