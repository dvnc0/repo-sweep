# Audit checklist

The audit is read-only. Its job is to find everything in the repo that could make an agent produce wrong code with confidence. Work through the sections in order. `inventory.py` gives the leads, but you still have to read the files to confirm each one.

## A. Instruction sprawl

- **Multiple instruction files:** `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.cursorrules`, `.cursor/rules/*`, `.github/copilot-instructions.md`, `.github/instructions/*`, `.windsurfrules`, `.clinerules`, `CONVENTIONS.md`, nested `CLAUDE.md` in subdirectories. More than one non-symlinked copy is a finding, even if they agree today.
- **Bootstrap or prompt files** (`prompt.md`, `app.md`, `SPEC_FOR_AI.md`) that were written once to kick off a project and never updated.
- **Repo-local skills, commands and agents** (`.claude/skills|commands|agents`). Do they reference scripts, paths or conventions that no longer exist? Do they duplicate the instructions file?
- **Nested instruction files.** These are legitimate when a subproject truly differs (a separate package with its own stack). They are a finding when they restate root rules or contradict them.

## B. Contradictions

Check each claim in the instruction files against the source of truth:

| Claim type | Verify against |
|---|---|
| Command (`npm run x`, `make y`) | Manifest scripts or Makefile targets (inventory flags unknown ones) |
| Path or directory layout | The tree (inventory flags unresolved ones) |
| API, function or class name in backticks | `grep -rn` for the definition. A name that doesn't exist is the worst kind of finding, because agents will call it. |
| "We use X" (library, pattern, result type) | Manifest plus a grep for real usage. Is X still used, or was it replaced? |
| Style or lint rule written in prose | The linter config. Does a tool enforce it? Does the config say the opposite? |
| Versions (language, runtime, framework) | Manifest, `.nvmrc`, `.tool-versions`, Dockerfile, CI matrix |
| Architecture ("controllers never touch the DB") | A grep for violations. If they exist, the rule is aspirational, and the doc must say so or a check must enforce it. |
| Process ("run X before committing", "file concerns in Y") | Whether X or Y exists and is actually used |

Also compare instruction files with each other, and docs with each other. Two docs describing the same thing differently is a finding even if neither is clearly wrong. Pick one source and delete the other.

## C. Stale material

- **Dead references:** the `unresolved path` / `unknown script` entries in the inventory. Confirm each one, since some are URLs or examples.
- **Plans, specs and RFCs** for work that shipped (the code is now the truth) or was abandoned. Agents treat a spec as intent and may "finish" a design that was dropped.
- **Handoff, progress and status notes,** and dated scratch directories (`.context/`, `notes/`, `plans/`). Check the inventory's last-commit age. Anything older than the most recent large refactor is suspect.
- **Markdown concern, TODO or backlog lists** that duplicate or replace an issue tracker. These can't be closed, linked or queried.
- **Time-relative language** ("currently", "for now", "new", "soon", "temporary") with no date.
- **Examples, templates or sample code** in the repo that show an old pattern. Agents copy them.
- **Dual implementations** (`v1`/`v2`, `old_`/`new_`, `legacy/`) with no marker saying which one to use. Either delete the dead one or ban importing it with a check.

## D. Prose rules that should be checks

List every "always / never / must / don't" sentence in the instructions. For each one, decide:

- **Already enforced** → delete the sentence, or reduce it to a pointer to the gate.
- **Enforceable** (regex, AST rule, import boundary, type, test) → `CONVERT→CHECK`, and name the tool.
- **Needs judgment** → `KEEP`. These are the only rules that belong in prose.

## E. Knowledge in the wrong place

- Deferred bugs or limitations living in markdown → `MOVE→ISSUE` (label them so they can be listed, e.g. `deferred`).
- Production facts, external-system quirks, and "why" knowledge living in comments, PR descriptions or chat → `MOVE→FACTS` (the instructions file's facts section), or keep as a `Critical:` comment if it guards a specific line.
- Copies of upstream tool or framework docs → `DELETE`, and point at the vendored source or the official docs instead.
- Secrets, internal hostnames, or personal data in docs → flag to the user immediately, separately from the report.

## F. Noise that misleads search

- Generated files, build output, coverage reports, or lockfile-like artifacts committed to the repo.
- Large fixtures or dumps that rank highly in grep results.
- Vendored or copied third-party code that isn't excluded from lint or search.
- Dead code: unused exports, files, dependencies. Note the tool that would find them (knip, vulture, deptry, staticcheck, cargo-machete).

## G. Escape hatches

Counts come from the inventory. Confirm a sample by reading it.

- Inline lint or type ignores (`eslint-disable`, `@ts-ignore`, `noqa`, `type: ignore`, `phpstan-ignore`, `nolint`, `#[allow]`).
- `any` / `as unknown as`, broad `except Exception`, empty catches, `pass`.
- Disabled or skipped tests (`.skip`, `xit`, `@pytest.mark.skip` with no reason or issue).
- Timers or sleeps used as synchronization outside tests.
- Commented-out code; TODO/FIXME/HACK with no issue link.

## H. The gate

- Is there one command that runs every check? What is it called?
- Does it pass at HEAD? (Run it.)
- Does it run in CI or a hook, or only when someone remembers?
- Are there baselines? Can they grow silently?
- Are rule messages instructive, or the tool defaults?
- What is missing from it: typecheck, lint, format, tests, architecture boundaries, ban list, dead code, dependency audit?

## Report template

```markdown
# Repo sweep audit: <repo> (<date>, <short sha>)

## Summary
<3-5 sentences: overall state, biggest risks to agent correctness, gate status>

## Findings
| # | sev | area | evidence | how it misleads an agent | action |
|---|---|---|---|---|---|
| 1 | high | B | CLAUDE.md:42 says `Result.ok()`; no such API (`grep` 0 hits) | agents call a nonexistent API | FIX |

## Prose rules -> checks
| rule (file:line) | status | tool / rule |

## Proposed plan
1. docs: ... (est. N files)
2. gate: ...
3. comments: ... (inventory: N comment lines, M escape hatches)
4. verify: ...

## Questions for the user
- ...
```

Severity: **high** = will produce wrong code or a broken gate; **med** = causes confusion, wasted work, or a pattern that spreads; **low** = noise.
