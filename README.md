# repo-sweep

A Claude Code skill that makes a repository trustworthy for coding agents.

Agents copy what they find. Every stale doc, contradictory instruction, workaround comment and lint escape hatch gets reproduced at agent speed. `repo-sweep` finds that material and helps you replace prose rules with deterministic checks:

- **Audit**: finds duplicated or conflicting agent instruction files (CLAUDE.md, AGENTS.md, Cursor, Copilot, Windsurf…), claims that don't match the code, dead path and script references, stale plans and handoffs, markdown backlogs that belong in an issue tracker, escape hatches, and gaps in the quality gate. Each finding gets evidence and a concrete action.
- **Docs**: consolidates everything into one true instructions file that describes the gate plus the facts the code can't show.
- **Gate**: builds a single `check` command with instructive rule messages, architecture boundaries, banned escape hatches, and baselines that can only shrink.
- **Comments**: bans comment slop with one narrow exception (`Critical: <why>`), harvests durable facts first, and proves each cleanup changed no code.
- **Verify**: adds verification proportionate to the repo: tests in the gate, property-based tests, runtime drivers that produce reviewable artifacts, and formal methods only where they pay off.

It builds on the "inverse pyramid of trust" idea. Constraints in the architecture and the compiler come first, static analysis next, verification infrastructure after that, and prose instructions last, only for what needs judgment.

## Install

```bash
git clone <this repo> ~/src/repo-sweep
ln -s ~/src/repo-sweep/skills/repo-sweep ~/.claude/skills/repo-sweep
```

Or copy `skills/repo-sweep` into a project's `.claude/skills/` to share it with a team.

Then, in Claude Code inside the repo you want to clean:

```
/repo-sweep            # audit, then offer the other phases
/repo-sweep gate       # or jump to a phase: docs | gate | comments | verify
```

## Layout

```
skills/repo-sweep/
  SKILL.md                     workflow and principles
  references/                  loaded per phase: audit, instructions, gate, comments, verification
  scripts/
    inventory.py               read-only survey: instruction files, docs, tooling, comments, escapes, dead refs
    comment_only_diff.py       proves a change touched only comments/docstrings/whitespace (Python, PHP, JS/TS)
    banned_patterns.py         ratcheting, config-driven ban list a repo can adopt
  assets/
    banned_patterns.example.json
    eslint-no-comments.js      ESLint rule: comments banned except `// Critical:` blocks
```

The scripts need only Python 3.9+ and the standard library. `comment_only_diff.py` uses `php` on PATH for PHP files, if present.

## Running the scripts directly

```bash
python3 skills/repo-sweep/scripts/inventory.py /path/to/repo            # markdown report
python3 skills/repo-sweep/scripts/inventory.py /path/to/repo --json
cd /path/to/repo && python3 .../comment_only_diff.py --base main         # exit 1 if code changed
cd /path/to/repo && python3 tools/banned_patterns.py                     # after adopting it
```
