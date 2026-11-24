# Building the gate

The gate is one command that exits 0 only when the repo is healthy. Agents run it before every commit, and CI runs the same command. Everything the instructions file says is "enforced" must be in it.

## Order of work

1. **Make HEAD green first.** If an existing check fails, fix it or baseline it before adding anything. A gate that is always red teaches agents to ignore it.
2. **Wire a single entry point** in the stack's native runner: `npm run check`, `composer check`, `make check`, `just check`, `uv run task check`. Steps run in order, cheapest first, and the first failure stops the run.
3. **Add rules in value order** (below). For each rule: write it, prove it fires on a fixture, baseline existing violations, and write a message that tells the agent what to do instead.
4. **Ban escape hatches** so the rules can't be bypassed inline.
5. **Run it automatically** in CI and/or a pre-commit hook (ask the user which one).
6. **Document it** in the instructions file's gate table. Keep the table in sync with the actual steps.

## Rule priorities

Start with whatever has already caused real bugs. The best source is `git log --grep='fix'` together with the issue tracker. A rule that cites an incident ("CONCAT() returns NULL…, see #37") is self-justifying and doesn't get removed.

| Priority | Kind | Examples |
|---|---|---|
| 1 | Typecheck and existing linters, passing | `tsc --noEmit`, mypy/pyright, PHPStan level N, `go vet`, clippy |
| 2 | Tests, passing and in the gate | the suite, with skips audited |
| 3 | Security and data footguns from history | raw SQL interpolation, `innerHTML`, `\|noescape`, `eval`, `yaml.load`, `pickle`, trusting `X-Forwarded-For`, local-time `date()` for stored timestamps |
| 4 | Architecture boundaries | layers, renderer ↛ main, domain ↛ infrastructure, UI ↛ DB |
| 5 | Escape-hatch bans | inline ignores, `any`, broad except, `.skip` without an issue |
| 6 | Patch-over patterns | timers/sleeps as synchronization, `console.log`/`print` in shipped code, `alert()`, hand-bumped cache busters |
| 7 | Comment policy | see `comments.md` |
| 8 | Dead code and dependencies | knip, vulture, deptry, cargo-machete, `composer-unused` |

## Messages are instructions

Bad: `Unexpected setTimeout.`
Good: `Timers patch over ordering bugs and caused the double-submit in #212. Derive the state from the event instead, or await the promise that signals readiness.`

Each message should give the right alternative, the reason (cite the incident or issue if there is one), and where the exception path is, if one exists.

## Baselines (the ratchet)

A baseline records violations that predate a rule so the rule can be turned on today. Requirements:

- New violations fail, even in files that already have some. Count per file and per rule, not just globally.
- Fewer violations also fail until the smaller baseline is committed ("lock in the improvement"). Without this, fixes silently free up room for new violations.
- The regenerate command refuses to grow counts. Seeding a brand-new rule is the one exception, and it is explicit.
- The baseline lives in its own file whose diffs are easy to review. Config-level exclusions (per-file-ignores, `ignore_imports`, a known-violations file) are acceptable as baselines. Inline ignore comments are not: they are invisible in review, they spread by copy, and agents learn to reach for them.

Native support, as far as I know. Check the current docs before relying on any of it:

| Tool | Baseline mechanism |
|---|---|
| PHPStan | `--generate-baseline` → `phpstan-baseline.neon`. Set `reportUnmatchedIgnoredErrors: true`. Regenerate only to remove entries, and review the diff. |
| Psalm | `--set-baseline` / `--update-baseline` |
| ESLint ≥ 9.24 | bulk suppressions: `--suppress-all` / `--suppress-rule`, `eslint-suppressions.json`, `--prune-suppressions` |
| basedpyright | `--writebaseline` |
| golangci-lint | `issues.new-from-rev` / `new-from-merge-base`. This only checks new code and doesn't ratchet old code, so pair it with a tracked count. |
| dependency-cruiser | known-violations file via `depcruise-baseline` + `--ignore-known` |
| import-linter | `ignore_imports` per contract |
| ruff, mypy, others | no general native baseline. Scope rules with `per-file-ignores` listing the debt files (the list may only shrink), or turn the rule on for clean directories first and expand. |

For anything regex-shaped, use `scripts/banned_patterns.py`. Copy it to `tools/banned_patterns.py`, write `tools/banned_patterns.json`, seed with `--baseline`, and add `python3 tools/banned_patterns.py` to the gate. Use `--add-rule ID --baseline` when adding a rule later. Its `scope: "code"` ignores matches inside comments and strings. `scope: "comment"` with `allow` implements the comment policy for any language.

## Escape-hatch bans by stack

| Stack | Make inline ignores inert or banned |
|---|---|
| ESLint | `linterOptions: { noInlineConfig: true, reportUnusedDisableDirectives: "error" }` |
| TypeScript | `@typescript-eslint/ban-ts-comment` (all directives), `no-explicit-any`, `no-unsafe-*`, `no-non-null-assertion` |
| ruff | run with `--ignore-noqa` in the gate; `PGH003`/`PGH004` against blanket ignores |
| mypy | `warn_unused_ignores = true`, `enable_error_code = ["ignore-without-code"]`, plus a ban-list rule on `type: ignore` |
| PHPStan / phpcs | ban-list rule on `phpstan-ignore\|phpcs:(ignore\|disable)\|@codingStandardsIgnore` |
| Go | golangci-lint `nolintlint` with `require-explanation` and `require-specific`, plus a ban-list rule if `//nolint` should be banned entirely |
| Rust | `#![deny(clippy::allow_attributes)]` / ban-list rule on `#[allow(` |

## Architecture boundaries by stack

| Stack | Tool | Notes |
|---|---|---|
| JS/TS | dependency-cruiser, or `eslint-plugin-boundaries`, or `no-restricted-imports` with patterns | Boundaries follow top-level directories. Move code so a directory is a layer. |
| Python | import-linter (`layers`, `forbidden`, `independence` contracts) | |
| PHP | phpat (as PHPStan tests) or deptrac | |
| Go | depguard (golangci-lint), or internal packages | `internal/` is a compiler-enforced boundary, so prefer it |
| Rust | crate boundaries in a workspace | the compiler enforces visibility |
| Java/Kotlin | ArchUnit, Konsist | |

## Rules that need an AST

When a regex can't express the rule (for example "only `InvalidArgumentException` messages may reach a response", "docblocks may contain only type tags", "no `useEffect` outside `src/framework`"), write a small custom rule for the stack's analyzer: an ESLint local plugin, a PHPStan `Rule`, a tiny `ast`-walking script in `tools/` for Python (ruff has no plugin API), a go/analysis pass, or a clippy lint via dylint. Keep each one under ~200 lines, give it a fixture test, and its message follows the rules above. `assets/eslint-no-comments.js` is a worked example.

## Proving rules fire

Before relying on a rule, add a violating line to a scratch copy and confirm the gate fails with your message. Configs often don't do what they look like they do:

- ESLint `capitalized-comments` / `multiline-comment-style` format comments; they don't ban them. `no-inline-comments` only bans trailing comments.
- ruff `ERA` flags commented-out code, not prose comments.
- `no-restricted-globals` doesn't catch `window.setTimeout` or `globalThis.setTimeout`. Add `no-restricted-properties` too.
- A rule scoped to `src/**/*.ts` misses `.tsx`, `.mts` and files outside `src`.

## CI and hooks

- CI runs exactly the gate command, so there is no second definition of "passing".
- A pre-commit hook (husky, lefthook, pre-commit) gives agents fast feedback locally. Keep it to the fast steps if the full gate is slow, and say in the instructions file which steps are skipped.
- Protect the gate's own config from casual edits by agents: list gate and baseline files in CODEOWNERS or a review rule. The instructions file should say that changing a rule is allowed but must be stated in the PR.
