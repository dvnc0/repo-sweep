# Delivery: push gate, CI, gated deploy, smoke tests

The gate only builds trust if nothing reaches production without passing it. This phase chains the checks together: the gate runs locally before a push, CI runs it again on the remote, deploys refuse anything CI hasn't passed, and a read-only smoke test confirms production afterwards. Every link refuses by default and its error message says how to get unstuck.

Ask the user before changing deploy scripts or CI. Both reach outside the repo.

## 1. Pre-push hook that tests the commit being pushed

A hook that runs the gate against the working tree proves nothing about the commit being pushed. Make it refuse when the two could differ:

- **Dirty tree, including untracked files** (`git status --porcelain` is not empty): uncommitted changes would be tested in place of the pushed commit. Tell the user to commit or `git stash -u`.
- **Pushed commit is not HEAD**: for each ref on stdin, resolve `local_sha^{commit}` and compare it with `git rev-parse HEAD`. Skip deletions (all-zero sha).
- **Required services are down** (dev stack, DB): probe them with a short timeout and say how to start them. Don't let e2e fail with a confusing timeout.

Then run the full gate, plus e2e if it's fast enough (a few minutes is fine for pushes). Keep the hook in a checked-in dir (`.githooks/`) and have the install step enable it, so nobody has to remember: `"post-install-cmd": "git config core.hooksPath .githooks || true"` (composer), a `prepare` script (npm), or the project's bootstrap. The instructions file says never to bypass it with `--no-verify` and to fix the failure instead.

Pre-push rather than pre-commit, because agents commit often and the full gate plus e2e is too slow to run on every commit. If the user also wants pre-commit, limit it to the fast steps.

## 2. CI runs the same gate

- CI runs exactly the gate command, with no second definition of passing.
- Pin the runtime and the extensions the gate requires (see "Environment is part of the gate" in `verification.md`). Cache dependencies on the lockfile hash.
- `concurrency` with `cancel-in-progress` so superseded pushes don't queue, plus a `timeout-minutes` cap and `permissions: contents: read`.
- If CI has no DB or browser and those tests skip there, say so in the instructions file, and track giving CI a seeded DB as an issue. A skip that nobody knows about is a gap (see `verification.md`).
- Dependency audits (`npm audit`, `composer audit`, `pip-audit`, `cargo audit`) go in a separate job. Make it non-blocking (`continue-on-error`) only while an issue tracks the existing findings, and name the issue in the job title.

## 3. Deploy refuses anything CI hasn't passed

One script (`./deploy.sh`, `make deploy`) is the only sanctioned way to deploy. Before it ships anything:

1. Fetch, and refuse if local `main` differs from `origin/main`. Most deploy tools ship the remote, not your tree.
2. Find the CI run for that exact SHA (`gh run list --workflow ci.yml --commit <sha>`). Retry briefly if the run hasn't registered yet, wait (`gh run watch`) if it's in progress, and refuse unless it concluded `success`. Print the command that shows the failure (`gh run view <id> --log-failed`).
3. Deploy, then run the smoke tests.

## 4. Read-only smoke tests against production

After the deploy, the same tooling used in dev runs against the production URL (pass the base URL as an env var):

- proofs of the main pages (screenshots, console errors, failed first-party requests; see `verification.md`);
- the e2e specs that are **read-only**. Mark them by file (`browse.spec`), and state in the instructions file that only read-only specs may ever target production: no sign-ups, no form posts, no emails;
- a cheap endpoint check (sitemap, health route).

Offer `--smoke-only` to re-run them without deploying. On failure, say plainly that the deploy is live, and give the rollback steps (revert, push, deploy again).

Production quirks show up here first. Example: a CDN served a 403 bot challenge to headless browsers that sent no `Accept-Language`, so the browser contexts set a locale. Record quirks like this as `Critical:` comments in the tooling or as facts.

## Done when

- A push from a dirty tree, or of a commit other than HEAD, is refused with a message that says what to do.
- A fresh clone plus the install step enables the hook.
- CI runs the gate on every push to the default branch, and the instructions file says what CI skips.
- Deploy refuses a SHA without a green CI run, and runs the smoke tests after shipping.
- The instructions file's gate section describes the whole chain in a few lines.
