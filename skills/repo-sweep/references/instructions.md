# Consolidating agent instructions

Target state: one root instructions file that every agent reads. It is short, true, and mostly describes how the gate works, plus the few things a tool can't check.

## Steps

1. **Pick the canonical file.** Use `CLAUDE.md` if Claude Code is the main agent, otherwise `AGENTS.md`. Symlink the other name to it (`ln -s CLAUDE.md AGENTS.md`). Delete per-tool copies, or replace them with symlinks if a tool can't follow `AGENTS.md`. Say in the file itself that it is the single source and that per-tool copies are not allowed.
2. **Inventory every claim** across all the old files. Merge into the canonical file only claims that are true (verified per `audit.md` §B), not enforced by a tool, and not obvious from the code.
3. **Fix wrong claims; don't soften them.** If the docs said `Response->json()` and the API is `setJsonResponse(...)`, write the real signature and a short correct example. Agents learn from examples more than from rules.
4. **Delete what a tool enforces.** Replace style paragraphs with the gate table (below).
5. **Delete what the code shows.** Directory descriptions that only restate folder names, lists of every model or route, and summaries of framework docs can all go. Keep a layout sketch only if it encodes *rules* (which layer may call which).
6. **Move deferred work to the issue tracker.** Create the issues (ask first, since that is outward-facing), then delete the markdown, and add one line: where deferred issues live and how to list them.
7. **Delete stale plans, handoffs and specs** for work that shipped or was abandoned, after confirming with the user. If a spec still documents an external contract (a public API others consume), keep it but make sure it matches the code, or generate it from the code.
8. **Fix every dead reference** that `inventory.py` reports, then re-run it.
9. **Nested instruction files:** keep them only for subprojects that truly differ, and have them start with "Extends the root CLAUDE.md; only differences are listed here."

## Shape of the canonical file

Aim for under ~200 lines. Each section has to justify its place.

```markdown
# CLAUDE.md

The single source of agent instructions for this repo. `AGENTS.md` is a symlink to it.
Do not add per-tool copies.

## Project
<2-4 lines: what it is, stack and versions, where framework source lives if it's unusual>

## The gate
Rules live in tools, not in this file. If something keeps going wrong, add a check.
`<one command>` must exit 0 before every commit:

| Step | Command | Enforces |
|---|---|---|
| ... | ... | ... |

### Baselines are a ratchet
<which files, may only shrink, how to lock in an improvement, never regenerate to pass,
 no inline ignores; if a rule is wrong change the rule and say so>

### Comments
<the comment policy and the Critical: exception, if adopted>

## Architecture
<only the rules: layers and allowed dependencies, error-handling contract, data access
 pattern; each with one short correct example; say which are enforced by which check>

## Dev environment
<how to start, run, seed, and drive the app: exact commands>

## Facts code can't show
<dated, verifiable facts: production topology, external-system quirks, why a constraint
 exists. Each line should still be true in a year or say when it was verified.>
Known-but-deferred problems are issues labelled `deferred` (<command to list them>).
Check there before "fixing" something that looks wrong on purpose.
```

## What to cut, with examples

| Cut | Because |
|---|---|
| "Write clean, readable code", "follow best practices" | Not actionable |
| "Use 2-space indentation", "sort imports" | The formatter enforces it |
| "Never use `any`" (when the linter bans it) | The linter's message is the instruction |
| A 40-line list of every route or model | The code shows it, and the list goes stale |
| "We are migrating from X to Y" with no date or check | Agents can't tell which to use. Add a check that bans new X usage, and keep a single line pointing at it. |
| Rationale essays | One line in Facts, or nothing |
| Copy of framework docs | Point at the vendored source or the official docs |

## Keep, and make precise

- Commands that are hard to guess (seeding, running one test, driving the app).
- Contracts between layers (what Logic returns, which exceptions map to which status).
- Security-relevant rules that need judgment, until they can become checks.
- Facts about production that the code can't reveal.

## Repo-local skills and commands

These are instructions too. Apply the same audit to them: true, not duplicated, references resolve. A skill that restates the instructions file should link to it instead.
