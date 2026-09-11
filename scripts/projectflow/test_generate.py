import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import generate
from dispatch import handle
from jobs import Jobs, digest


class GenerationTests(unittest.TestCase):
    def test_free_description_is_durable_and_approval_waits_for_real_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg = {'state_dir': temp, 'owner': 'owner', 'static_state': temp + '/static'}
            event = {'user': 'owner', 'channel': 'D', 'thread': 'T', 'event': '1',
                     'text': 'bygg en bokningsapp med db'}
            with patch('dispatch.sources') as demo, patch('generate.model') as model:
                self.assertIn('Planning', handle(cfg, event))
                self.assertIn('Planning', handle(cfg, event))
                demo.assert_not_called(); model.assert_not_called()
            ledger = Jobs(temp, 'owner'); self.addCleanup(ledger.db.close)
            self.assertEqual(ledger.db.execute('select count(*) from jobs').fetchone()[0], 1)
            with self.assertRaises(ValueError):
                ledger.approve({**event, 'event': str(time.time() + 1)}, 'plan-ok')
            job = ledger.claim()
            self.assertEqual(job['state'], 'planning')
            request = json.loads(job['plan'])
            result = {'name': 'Bookings', 'suggested_slug': 'bookings',
                      'description': 'Bokningar lagras i Postgres.', 'acceptance': ['Skapa en bokning'],
                      'api': 'POST /api/bookings', 'profile': 'fullstack',
                      'storage': 'postgres', 'supported': True}
            with patch('generate.model', return_value=result):
                plan = generate.plan({}, request['request'], request['materials'], job['id'])
            self.assertTrue(ledger.finish(job['id'], job['claim'], plan))
            self.assertIn('app-' + job['id'], handle(cfg, {**event, 'text': 'jobb'}))
            ledger.approve({**event, 'event': str(time.time() + 2)}, 'plan-ok')
            self.assertEqual(ledger.claim()['state'], 'building')
            self.assertEqual(ledger.db.execute('select version from approvals').fetchone()[0], digest(plan))

    def test_generated_files_cannot_change_build_or_deploy_controls(self):
        for name in ['../outside.ex', '/tmp/a.ex', 'backend/mix.exs', 'backend/config/runtime.exs',
                     'frontend/package.json', 'frontend/src/../../settings.json',
                     'backend/lib/demo/release.ex', 'backend/Dockerfile', 'frontend/src/.env.ts',
                     'backend/priv/repo/migrations/create_items.exs',
                     'backend/priv/repo/migrations/nested/20260907120000_items.exs']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                generate.validate_files({'files': {name: 'changed'}}, 'backend')

    def test_file_parser_accepts_common_model_wrappers(self):
        files = {
            'frontend/src/main.tsx': 'export {};',
            'frontend/src/example.test.ts': 'export {};',
        }
        variants = [
            {'files': files, 'explanation': 'done'},
            {'frontend': {'files': files}},
            {'files': [{'path': name, 'content': content} for name, content in files.items()]},
            files,
        ]
        for value in variants:
            with self.subTest(value=value):
                self.assertEqual(generate.validate_files(value, 'frontend'), files)

    def test_frontend_accepts_relative_paths_tsx_tests_and_app_entrypoint(self):
        result = {'files': {
            'src/App.tsx': 'export default function App() { return <main>Todo</main>; }',
            'src/App.test.tsx': 'import { test } from "vitest"; test("todo", () => {});',
        }}
        files = generate.validate_files(result, 'frontend')
        self.assertIn('frontend/src/App.tsx', files)
        self.assertIn('frontend/src/App.test.tsx', files)
        self.assertIn('import App from "./App";', files['frontend/src/main.tsx'])

    def test_frontend_renames_typescript_test_that_contains_jsx(self):
        result = {'files': {
            'src/App.tsx': 'export default function App() { return <main>Todo</main>; }',
            'src/App.test.ts': 'const view = () => <App />;',
        }}
        files = generate.validate_files(result, 'frontend')
        self.assertIn('frontend/src/App.test.tsx', files)
        self.assertNotIn('frontend/src/App.test.ts', files)

    def test_frontend_drops_unavailable_optional_browser_tests(self):
        app = 'export default function App() { return <main>Todo</main>; }'
        invalid_tests = [
            'import { render } from "solid-js/testing";',
            'import { render } from "@testing-library/solid";',
            'expect(value).toBeInTheDocument();',
            'document.querySelector("main");',
            'window.location.reload();',
        ]
        for test in invalid_tests:
            with self.subTest(test=test):
                files = generate.validate_files({'files': {
                    'frontend/src/App.tsx': app,
                    'frontend/src/App.test.ts': test,
                }}, 'frontend')
                self.assertNotIn('frontend/src/App.test.ts', files)
                self.assertNotIn('frontend/src/App.test.tsx', files)
                self.assertIn('frontend/src/main.tsx', files)

    def test_frontend_allows_vitest_and_relative_pure_logic_tests(self):
        files = generate.validate_files({'files': {
            'frontend/src/App.tsx': 'export default function App() { return <main>Todo</main>; }',
            'frontend/src/model.ts': 'export const valid = (s: string) => s.length > 0;',
            'frontend/src/model.test.ts': (
                'import { expect, test } from "vitest"; '
                'import { valid } from "./model"; test("valid", () => expect(valid("x")).toBe(true));'),
        }}, 'frontend')
        self.assertIn('frontend/src/model.test.ts', files)

    def test_model_cannot_replace_locked_runtime_contract(self):
        files = generate.validate_files({'files': {
            'frontend/src/App.tsx': 'export default function App() { return <main />; }',
            'frontend/src/runtime.ts': 'export const apiPath = () => "https://evil";',
        }}, 'frontend')
        self.assertNotIn('frontend/src/runtime.ts', files)

    def test_backend_accepts_paths_relative_to_backend_root(self):
        result = {'backend': {'files': {
            'lib/demo_web/generated/router.ex': 'defmodule DemoWeb.Generated.Router do\nend',
            'test/generated/items_test.exs': 'defmodule ItemsTest do\nend',
        }}}
        files = generate.validate_files(result, 'backend')
        self.assertIn('backend/lib/demo_web/generated/router.ex', files)
        self.assertIn('backend/test/generated/items_test.exs', files)

    def test_file_generation_retries_invalid_shape(self):
        files = {
            'frontend/src/main.tsx': 'export {};',
            'frontend/src/example.test.ts': 'export {};',
        }
        with patch('generate.model', side_effect=[{'message': 'done'}, {'files': files}]) as model:
            self.assertEqual(generate.request_files({}, 'generate', 'frontend'), files)
            self.assertEqual(model.call_count, 2)
            self.assertIn('föregående svar', model.call_args.args[1])

    def test_file_generation_accumulates_partial_frontend_responses(self):
        partial_test = {'files': {
            'frontend/src/App.test.ts': 'import { test } from "vitest"; test("todo", () => {});'}}
        partial_app = {'files': {
            'frontend/src/App.tsx': 'export default function App() { return <main>Todo</main>; }'}}
        with patch('generate.model', side_effect=[partial_test, partial_app]) as model:
            files = generate.request_files({}, 'generate', 'frontend')
            self.assertIn('frontend/src/App.test.ts', files)
            self.assertIn('frontend/src/App.tsx', files)
            self.assertIn('frontend/src/main.tsx', files)
            self.assertIn('App.tsx', model.call_args.args[1])

    def test_repair_requests_existing_files_that_model_omits(self):
        complete = {
            'backend/lib/demo_web/generated/router.ex': 'router',
            'backend/test/generated/required_test.exs': 'required',
        }
        first = {'files': {'backend/lib/demo_web/generated/router.ex': 'fixed router'}}
        second = {'files': {'backend/test/generated/required_test.exs': 'fixed test'}}
        with patch('generate.model', side_effect=[first, second]) as model:
            files = generate.request_files({}, 'repair', 'backend', set(complete))
            self.assertEqual(set(files), set(complete))
            self.assertEqual(model.call_count, 2)

    def test_repair_ignores_reserved_file_and_merges_changed_app_file(self):
        existing = {
            'frontend/src/App.tsx': 'export default function App() { return <main>old</main>; }',
            'frontend/src/main.tsx': 'main',
        }
        response = {'files': {
            'frontend/src/runtime.ts': 'unsafe replacement',
            'frontend/src/App.tsx': 'export default function App() { return <main>fixed</main>; }',
        }}
        with patch('generate.model', return_value=response):
            files = generate.request_files({}, 'repair', 'frontend', set(existing), existing)
        self.assertIn('fixed', files['frontend/src/App.tsx'])
        self.assertNotIn('frontend/src/runtime.ts', files)

    def test_repair_cannot_remove_an_existing_test(self):
        materials = generate.bundle()
        plan = {'bundle_hash': digest(materials)}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            existing = root / 'backend/test/generated/required_test.exs'
            existing.parent.mkdir(parents=True)
            existing.write_text('required')
            response = {'files': {
                'backend/lib/demo_web/generated/router.ex': 'router',
                'backend/test/generated/replacement_test.exs': 'replacement'}}
            with patch('generate.model', return_value=response), self.assertRaises(ValueError):
                generate.repair({}, plan, materials, root, {'phoenix': 'failed'})

    def test_generation_uses_approved_materials_and_keeps_scaffold_immutable(self):
        materials = generate.bundle()
        backend = {'files': {
            'backend/lib/demo_web/generated/router.ex': 'defmodule DemoWeb.Generated.Router do\n use Phoenix.Router\nend\n',
            'backend/test/generated/example_test.exs': 'defmodule ExampleTest do\n use ExUnit.Case\n test "example", do: assert(1 == 1)\nend\n'}}
        front = {'files': {'frontend/src/main.tsx': 'export {};',
                           'frontend/src/example.test.ts': 'export {};'}}
        plan = {'bundle_hash': digest(materials)}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stale = root / 'frontend/src/OldApp.test.ts'
            stale.parent.mkdir(parents=True)
            stale.write_text('const old = () => <OldApp />;')
            with patch('generate.model', side_effect=[backend, front]) as model:
                hashes = generate.generate({}, plan, materials, root)
                self.assertEqual(model.call_count, 2)
                self.assertIn('IMPLEMENTERAD BACKEND', model.call_args.args[1])
            self.assertEqual(set(hashes), {'frontend', 'backend'})
            self.assertEqual((root / 'backend/mix.exs').read_text(),
                             materials['templates/application/backend/mix.exs'])
            self.assertEqual((root / 'frontend/src/runtime.ts').read_text(),
                             generate.RUNTIME_FILES['frontend/src/runtime.ts'])
            self.assertFalse(stale.exists())
            self.assertTrue((root / 'backend.tar').exists())
            with patch('generate.model') as model, self.assertRaises(ValueError):
                generate.generate({}, {'bundle_hash': 'changed'}, materials, root)
            model.assert_not_called()

    def test_model_receives_secrets_only_through_runtime_config_not_build_environment(self):
        with patch('generate.subprocess.run') as run:
            run.return_value.stdout = json.dumps({'content': '{"ok":true}'})
            self.assertEqual(generate.model({'runtime_config': '/runtime', 'llm_command': ['/helper']}, 'plan'), {'ok': True})
            self.assertEqual(run.call_args.kwargs['env']['PICOCLAW_CONFIG'], '/runtime')
            self.assertEqual(run.call_args.args[0], ['/helper'])

    def test_model_extracts_json_from_fenced_or_explained_response(self):
        responses = [
            {'content': '```JSON\n{"ok": true}\n```'},
            {'content': 'Här är planen:\n{"ok": true}\nHoppas det hjälper.'},
        ]
        with patch('generate.subprocess.run') as run:
            for response in responses:
                run.return_value.stdout = json.dumps(response)
                self.assertEqual(generate.model(
                    {'runtime_config': '/runtime', 'llm_command': ['/helper']}, 'plan'), {'ok': True})

    def test_plan_accepts_extra_fields_and_structured_api(self):
        materials = generate.bundle()
        response = {'name': 'Todo', 'suggested_slug': 'todo',
                    'description': 'Todo med databas', 'acceptance': ['Skapa uppgift'],
                    'api': {'POST /api/todos': {'title': 'string'}},
                    'profile': 'fullstack', 'storage': 'postgres',
                    'supported': True, 'implementation_notes': 'extra'}
        with patch('generate.model', return_value=response):
            result = generate.plan({}, 'todo', materials, '123456abcdef')
        self.assertIn('POST /api/todos', result['api'])
        self.assertNotIn('implementation_notes', result)

    def test_browser_only_request_selects_static_profile(self):
        materials = generate.bundle()
        response = {'name': 'Todo', 'suggested_slug': 'todo',
                    'description': 'Todo stored in the browser',
                    'acceptance': ['Tasks survive a reload'], 'api': '',
                    'profile': 'static', 'storage': 'browser', 'supported': True}
        with patch('generate.model', return_value=response):
            result = generate.plan({}, 'simple todo with local storage and no database',
                                   materials, '123456abcdef')
        self.assertEqual(result['profile'], 'static')
        self.assertEqual(result['storage'], 'browser')
        self.assertEqual(result['api'], '')

    def test_invalid_plan_is_retried_twice(self):
        materials = generate.bundle()
        valid = {'name': 'Todo', 'suggested_slug': 'todo',
                 'description': 'Todo', 'acceptance': ['Skapa'],
                 'api': 'POST /api/todos', 'profile': 'fullstack',
                 'storage': 'postgres', 'supported': True}
        with patch('generate.model', side_effect=[{'description': 'incomplete'}, [], valid]) as model:
            result = generate.plan({}, 'todo', materials, '123456abcdef')
        self.assertEqual(result['description'], 'Todo')
        self.assertEqual(model.call_count, 3)

    def test_cancelled_planning_cannot_publish_late_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = Jobs(temp, 'owner'); self.addCleanup(ledger.db.close)
            event = {'user': 'owner', 'channel': 'D', 'thread': 'T', 'event': '1'}
            ledger.create(event, {'kind': 'generated'}, planning=True)
            job = ledger.claim()
            ledger.cancel({**event, 'event': '2'})
            self.assertFalse(ledger.finish(job['id'], job['claim'], {'kind': 'generated'}))
            self.assertEqual(ledger.status(event)['state'], 'cancelled')


if __name__ == '__main__':
    unittest.main()
