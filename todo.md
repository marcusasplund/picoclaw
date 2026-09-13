# Project pipeline tasks

Scope: evolve `scripts/projectflow` into a durable, resumable state machine with optional discovery, independent verification, and evaluated learning. These are planned tasks, not claims of implemented behavior. Preserve existing owner/thread authorization, event deduplication, bounded budgets, claim checks, immutable artifacts, and separate deployment approvals.

## 1. Durable state machine and checkpoints

- [ ] Define and document the transition table for discovery, planning, awaiting approval, building, checking, repairing, reviewing, awaiting deploy, deploying, preview ready, releasing, and released. Include queued phases and paused, failed, blocked, cancelled, and interrupted states; distinguish lifecycle state from the phase to resume.
- [ ] Centralize transitions in the controller. Specify each event's allowed source states, guards, version checks, side effects, and destination. Reject invalid transitions independently of model output.
- [ ] Persist transitions and an audit trail atomically in SQLite. Retain authenticated actor, event ID, job/run ID, prior/new state, reason, claim, and brief/plan/artifact versions. Migrate existing jobs and approvals without losing history.
- [ ] Implement durable phase checkpoints containing source snapshots, brief/plan versions, dependency locks, template/skill versions, check reports, and remaining budget. Resume from persisted files after container or worker loss; never depend on an in-memory session.
- [ ] Implement pause at safe boundaries, with a visible pause-requested state during active commands. Define command termination and cleanup behavior; preserve recoverable work when stopping.
- [ ] Reconcile interrupted external operations against deployment receipts before retrying. Never automatically replay an uncertain deploy, release, or migration.
- [ ] Add state-machine tests for every legal/illegal transition, duplicate and stale events, unauthorized commands, stop/completion races, pause/resume, crashes, checkpoint recovery, and approval invalidation. Verify no late result can publish after cancellation.

## 2. Command registry

- [ ] Create one command registry with syntax, aliases, allowed states, authorization, approval requirements, handler, and help text. Generate state-aware help from it and preserve existing aliases.
- [ ] Implement or align the commands below with the state machine. Clearly report unsupported commands until their handlers exist.

| Command | Required behavior |
| --- | --- |
| `help` | Show commands available in the current state. |
| `status` | Show phase, progress, blocker, budget, checkpoint, and next action. |
| `details` | Show logs, reports, artifacts, transitions, and attempt history. |
| `interview [auto\|on\|off]` | Configure discovery before planning. |
| `skip` | Finish optional discovery with explicit recorded assumptions. |
| `approve` | Approve the exact current plan version. |
| `revise <instructions>` | Revise the brief/plan and invalidate affected approvals and results. |
| `pause` | Request suspension and save a checkpoint at a safe boundary. |
| `resume` | Resume paused work within its remaining budget. |
| `stop` | Cancel the run, prevent further publication, and retain evidence. |
| `retry [phase]` | Start a new attempt from a defined valid checkpoint without resetting usage. |
| `continue` | Grant an explicit bounded budget extension; preserve current compatibility. |
| `revert <checkpoint>` | Restore workspace state and invalidate downstream verification and approvals. |
| `deploy` | Approve the exact verified artifact for protected preview. |
| `release <subdomain>` | Publish the approved preview artifact. |
| `rollback <release>` | Restore a prior compatible deployed version using deployment history. |
| `delete` | Start explicit, scoped app removal with a concrete confirmation. |

- [ ] Define cancellation boundaries for remote operations already in progress. Explain whether an action is still cancellable, requires reconciliation, or needs rollback.
- [ ] Test command parsing, aliases, state-aware help, authorization, version binding, and distinct resume/retry/continue semantics.

## 3. Optional interview and durable brief

- [ ] Add `auto`, `on`, and `off` discovery modes. In auto mode, interview only when uncertainty materially affects scope, implementation, or acceptance; bound question rounds and record assumptions when skipped.
- [ ] Add a grill.me-style product interview covering users, primary journeys, success criteria, scope exclusions, constraints, and assumptions that could invalidate the build. Confirm the intended skill integration before wiring a specific provider.
- [ ] Add an Impeccable design interview for UI projects covering visual references, design direction, responsive behavior, accessibility, and loading/empty/error states. Adapt its setup to generated projects.
- [ ] Persist a versioned brief with acceptance criteria, design decisions, constraints, and unresolved assumptions. Make both planner and verifier consume it.
- [ ] Require plans to map requirements to implementation work and verification evidence. Brief or scope changes must produce a revised plan and invalidate affected approval.

## 4. Independent verification and bounded repair

- [ ] Define a versioned check manifest per supported stack, including commands, dependencies, timeouts, fixtures, thresholds, report format, and blocking policy. Freeze it for each run.
- [ ] Preserve mandatory type, lint, test, build, Phoenix/database, and release-start checks. Add controller-owned acceptance tests outside the coding agent's editable workspace; prevent success through weakened scripts, skipped tests, or changed thresholds.
- [ ] Run browser acceptance journeys against the built app before preview, covering persistence, permissions where applicable, error handling, browser console errors, and frontend/backend integration.
- [ ] Add automated accessibility checks plus keyboard and responsive browser review. Define which findings block completion and retain supporting evidence.
- [ ] Add scripted performance journeys with repeatable fixtures and noise-tolerant budgets. Activate React Scan only for a supported React profile; current Solid profiles must not require it. Treat profiling as diagnostic evidence unless an explicit threshold adapter exists.
- [ ] Add an Impeccable audit with a stable rubric, severity levels, screenshots, and actionable findings. Keep model judgment distinct from deterministic test results and cap review/repair passes.
- [ ] Normalize failures into structured feedback: check, reproduction, evidence, severity, and probable category. Distinguish code defects, infrastructure failures, flaky checks, and ambiguous requirements before choosing repair, retry, or clarification.
- [ ] Repair within explicit attempt/time/cost limits, rerun affected checks during iteration, then run the complete required suite against the final snapshot. Every code change invalidates affected prior evidence.
- [ ] Detect repeated failure signatures and lack of progress. Escalate diagnosis or mark blocked with evidence instead of exhausting the budget on identical repairs. Do not silently waive flaky or failing required checks.
- [ ] Bind successful reports and review outcomes to the exact source/artifact and policy versions. Test failure paths, exhausted budgets, tampering, and the prohibition on deploying unverified output.

## 5. Evaluated learning cycle

- [ ] Record failure signature, root cause, repair diff, before/after verification, stack, and template/skill versions. Exclude secrets and unnecessary user data from reusable lessons.
- [ ] Classify lessons as project-specific, template defects, deterministic tooling/rules, or reusable skill guidance. Prefer a template fix or executable check when the lesson can be enforced mechanically.
- [ ] Generate proposed skill/template/rule changes as versioned candidates with supporting evidence. Deduplicate recurring lessons; do not automatically rewrite active skills after one successful repair.
- [ ] Build a representative regression corpus and compare baseline versus candidate versions for first-pass success, repair counts, escaped defects, runtime, and cost.
- [ ] Define promotion criteria and review policy. Promote only evaluated improvements, preserve history, and support reverting harmful versions. Active jobs retain their frozen versions.
- [ ] Test candidate rejection, promotion, rollback, and isolation from active jobs. Surface learning outcomes separately from app build success.

## 6. Existing-app revisions and release recovery

- [ ] Introduce stable app identity separate from job/run identity, immutable release history, and isolated workspaces for changes to an existing app.
- [ ] Start revisions from a known release/checkpoint and retain the deployed app until the replacement passes checks and receives the required approval.
- [ ] Implement workspace revert separately from deployment rollback. Require full re-verification of restored or revised code before publication.
- [ ] Define database migration compatibility, backup/restore policy, and recovery procedures. Test upgrades using representative existing data; never assume reverting application code reverts database changes safely.
- [ ] Verify the deployed version and key behavior after preview/release. Record receipts and reconcile partial failures; test compatible rollback and rejected incompatible rollback.
- [ ] Implement scoped app removal with explicit resource inventory, confirmation, and data-retention rules.

## 7. Operations and delivery

- [ ] Expose concise progress, blockers, spend estimates, check outcomes, and links to evidence through status/details. Preserve cumulative usage across resumes and retries.
- [ ] Define retention and capacity limits for previews, logs, source snapshots, images, caches, and databases. Cleanup must protect active jobs, deployed releases, rollback targets, and retained user data.
- [ ] Run a live end-to-end acceptance build covering interview, approval, failure/repair, pause/restart/resume, preview, release, revision, and rollback after controller tests pass.
- [ ] Update projectflow documentation and installation/migration instructions to distinguish shipped behavior from planned features and remove obsolete workflow claims.

Recommended sequence: state machine and checkpoints → command registry → interview and brief → independent checks and browser review → app revision/recovery → evaluated learning promotion. Add operational visibility throughout.
