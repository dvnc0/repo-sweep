# Verification (Layer 3)

Static checks prove code is well-formed. Verification proves it *works*, and it leaves artifacts a human can review faster than reading the diff. Add the levels below in order and stop once the repo's risk is covered.

## 1. Tests that gate

- The suite runs inside the gate command and passes at HEAD.
- Audit skips: each `.skip`, `xit` or `@skip` needs a reason that links an issue. Ban bare skips with a ban-list rule.
- Flaky tests get quarantined with a linked issue. A flaky gate trains agents to re-run until green.
- Make the test-file mirror rule explicit (e.g. `tests/` mirrors `src/`) so agents know where a test goes. Enforce it with a check if it matters.
- **Environment is part of the gate.** Tests that skip because an extension, binary or service is missing are silent gaps that look green. Make the gate's first step assert the environment (`composer check-platform-reqs` with the `ext-*` in `composer.json`, `engines` + `engine-strict` for Node, `requires-python`, a `tools/doctor` script), so a missing prerequisite fails loudly.
- **Read the test log, not just the exit code.** Expected errors that print on every run train people to ignore output. Capture and assert them (also check they don't leak secrets or PII), and treat a new skip or warning as a finding. Resource limits cause skips too: a dev DB's default `max_connections` made the last DB tests skip as "database unavailable".
- Optional: mutation testing (Stryker, mutmut, Infection, cargo-mutants) on the core modules to measure whether the tests actually catch changes. Run it occasionally, not in the gate.

## 2. Property-based tests for invariants

Use these when a function has a rule that must hold for *all* inputs: parsers, serializers (round-trip), pagination and virtualization math, money and time arithmetic, permission checks, state reducers.

| Stack | Library |
|---|---|
| Python | hypothesis |
| JS/TS | fast-check |
| Rust | proptest, quickcheck |
| Go | `testing/quick`, rapid |
| PHP | eris |
| JVM | jqwik, kotest-property |

Write the invariant as the test name (`start_index_never_exceeds_end`). That is the comment that stays true.

## 3. Architecture tests

These are boundary checks that run as tests (phpat, ArchUnit, import-linter contracts, dependency-cruiser) when they're not already in the gate. See `gate.md`.

## 4. Runtime verification an agent can drive

Agents verify UI and integration behavior far better when they can drive the real app and capture evidence:

- **One-command dev environment** with seeded data (`make dev`, `docker compose up`, a seed script). Document the exact commands in the instructions file.
- **A feature map**: a checked-in JSON or YAML mapping feature IDs to routes and entry points (and test IDs for key elements). Agents and humans then share vocabulary, and agents stop guessing selectors. Keep it honest with a test that every route in it resolves.
- **A verify script**: `npm run verify -- <feature-id>` (Playwright/CDP for web and Electron, an HTTP client for APIs, a CLI driver for CLIs). It runs a scenario and writes artifacts to `artifacts/` (gitignored): screenshots, a trace or video, a HAR, console errors, a response transcript. It exits non-zero on console errors or failed assertions.
- **A proof command for any UI change**, separate from the e2e suite: `npm run proof -- /path [/path ...]` saves desktop and mobile screenshots (viewport and full page) plus a `report.json`, and fails on console errors, uncaught exceptions and failed first-party requests. The instructions file tells agents to look at the screenshot, not just read the verdict.
- **Stub third parties in browser runs.** Answer analytics, ads, external images and map tiles with an empty 204 and let only same-origin and the CDNs you depend on load. Runs stay fast and deterministic, and test traffic never lands in production analytics. Also load analytics only when the app knows it's live, so dev traffic stays out.
- **Make side effects observable locally.** Add a dev mail driver that writes each message to a file (`tmp/mail/*.json`) so e2e can follow reset and confirm links. Do the same for SMS, webhooks and queues. The e2e global setup clears that outbox and any rate limits. Never let e2e call a real external API (a newsletter confirm that subscribes someone for real, a payment).
- **Use system Chrome** (`channel: 'chrome'`) when it's available, to skip the browser download. In shared fixtures, call `unrouteAll({ behavior: 'ignoreErrors' })` before teardown, or each test pays seconds waiting for route handlers.
- **Stable selectors**: `data-testid` (or roles and labels) on interactive elements, enforced by a lint rule if the UI is large.
- **Artifact-driven review**: the instructions file tells agents to run the relevant verify scenario and cite artifact paths in the PR description. Reviewers look at the screenshots and traces first.

For size and performance questions, measure production, not the dev seed data. Dev databases are usually a small subset and give the wrong answer (41 rows in dev against 200+ and a 27 MB page in prod).

Keep the script small and boring. Its value comes from being the one sanctioned way to exercise a feature.

## 5. Formal methods (rarely)

Reach for these only when a bug is expensive and the state space is too big for tests:

- **TLA+ / PlusCal / P**: multi-device sync, distributed protocols, queue and retry semantics, leader election.
- **Lean / Coq / Dafny / Kani (Rust) / CBMC**: core algorithms where a proof is cheaper than the bugs it prevents.
- **Statecharts (XState and similar)**: complex UI flows. A visualized machine doubles as a review artifact.

Recommend one of these only with a concrete target in the codebase and a sentence on why tests aren't enough. Otherwise leave it out.

## 6. The outer loop (mention, don't build unasked)

For mature repos: scheduled agents that fuzz or explore the app after each release, file issues, and propose fixes that must pass the full gate. This only works once levels 1-4 are trustworthy. Mention it as a next step; don't set it up without explicit direction.
