---
name: repo-sweep
description: Audits and cleans a repository so coding agents can trust it - finds contradictory, stale, duplicated or wrong agent instructions and docs, then helps replace prose rules with deterministic checks (lint rules, ban lists, architecture boundaries, ratcheting baselines), strip comment slop safely, and add verification tooling. Use when the user runs /repo-sweep, or asks to "clean up the repo for agents", "make this repo agent-ready", "find conflicting/stale docs", "consolidate CLAUDE.md / AGENTS.md / cursor rules", "add a quality gate", "ban comments", "set lint baselines", or "make agents trust this codebase".
---

# Repo Sweep

Make a repo a high-trust environment for agents. That means one truthful instructions file, rules enforced by tools instead of prose, and verification that leaves evidence. Agents copy whatever they find. Every stale doc, contradiction, workaround and escape hatch gets reproduced at agent speed, so remove them or fence them in with checks.

Usage: `/repo-sweep [audit|docs|gate|comments|verify] [path]`. With no mode, run **audit**, then offer the other phases in order.

Scripts sit in `scripts/` next to this file. They are stdlib Python 3.9+ and read-only unless noted:

| Script | Purpose |
|---|---|
| `inventory.py [root] [--json]` | Lists instruction files, docs, scratch dirs, tooling, gate scripts, comment counts by kind, escape hatches, type escapes and timers, and flags doc references to paths or scripts that don't exist. |
| `comment_only_diff.py [--base REF] [--head REF] [--rename OLD=NEW]` | Proves a change touched only comments, docstrings or whitespace (Python AST, PHP tokens, JS/TS lexer). Run it after every comment cleanup. |
| `banned_patterns.py` | A ratcheting ban list the repo adopts. Copy it into `tools/` along with a JSON config; see `references/gate.md`. |

Assets to copy into a repo and adapt: `assets/banned_patterns.example.json` (starter rules, including the comment policy) and `assets/eslint-no-comments.js` (an ESLint rule that bans comments except `// Critical:` blocks).

## Principles

1. **One source of agent instructions.** A single root file, usually `CLAUDE.md` with `AGENTS.md` symlinked to it. Per-tool copies (Copilot, Cursor, Windsurf…) drift, so delete them or symlink them.
2. **Rules live in tools, not prose.** Every rule written as prose is a candidate check, and every repeated agent mistake should become a check rather than a new paragraph. The instructions file explains how the gate works and records facts the code can't show.
3. **The lint message is the instruction.** The agent reads a rule's message at the exact moment it makes the mistake. Say what to do instead and why, and cite the incident or issue if one exists.
4. **Baselines are a ratchet.** Existing violations get recorded and may only shrink. Never regenerate a baseline to make new code pass, never use inline ignore comments, and never weaken a rule to get green. If a rule is wrong, change the rule openly.
5. **Wrong guidance is worse than none.** Check every claim in the instructions against the code before keeping it.
6. **Knowledge goes where it stays true.** Constraints go into types and checks. Deferred work goes in the issue tracker. Facts the code can't express go in one "Facts code can't show" section. Git history is the archive, so stale docs get deleted rather than moved to an `old/` folder.
7. **Don't delete what you don't understand.** Some comments guard real invariants, and some docs are the user's own thinking, so ask before removing either. See `references/comments.md` for the `Critical:` exception.
8. **Proportionate, not dogmatic.** Pick the ideas that pay off for this repo's size, risk and stack. A CRUD app doesn't need TLA+, but nearly every repo benefits from one gate command and an honest instructions file.

## Phase 0: Survey (every mode)

1. Find the repo root. Read the full output of `python3 <skill>/scripts/inventory.py <root>`.
2. Read every agent instruction file in full, along with the README and the manifests (package.json, pyproject, composer.json, go.mod, Cargo.toml, Makefile).
3. Find the gate: the single command that is supposed to prove the repo is healthy (`check`, `verify`, `ci`, or whatever CI runs). Run it if one exists and record whether HEAD passes. A gate that is red at HEAD is the first finding.
4. Check `git status`. If the tree is dirty or you're on the default branch, say so before changing anything, and propose a branch.

## Mode: audit (read-only)

Follow `references/audit.md`. Every finding needs evidence (`file:line` or a command and its output), a statement of how it would mislead an agent, and exactly one action from this list: `DELETE`, `FIX`, `MERGE→<target>`, `CONVERT→CHECK`, `MOVE→ISSUE`, `MOVE→FACTS`, `KEEP (reason)`, `ASK`.

Write the report to `.context/repo-sweep/<YYYY-MM-DD>-audit.md`, or to the repo's existing scratch dir for agent work if it has one. Don't commit it unless asked. Then show the user:

- the top 10 findings by impact (gate broken > wrong instructions > contradictions > stale references > prose-only rules > noise);
- the proposed phase order with a size estimate for each phase;
- an `AskUserQuestion` for anything marked `ASK`, plus which phases to run.

## Mode: docs

Follow `references/instructions.md`. Consolidate into one instructions file, fix or delete wrong claims, move deferred work to issues, delete stale plans and handoffs, and fix dead references. Before you delete or rewrite anything a human wrote by hand (strategy notes, specs, roadmaps), confirm with the user. They may want it kept somewhere other than the repo.

## Mode: gate

Follow `references/gate.md`. Build or extend a single `check` command, add the highest-value rules first, baseline the existing violations, ban escape hatches, and wire the gate into CI or a pre-commit hook if the user wants that. Then update the instructions file's gate section so it matches reality.

## Mode: comments

Follow `references/comments.md`. The gate must exist first, because the comment rule plus its baseline is what keeps the cleanup from regressing. Harvest durable facts before deleting anything, keep `Critical:` comments, and verify each batch with `comment_only_diff.py`.

## Mode: verify

Follow `references/verification.md`. Pick the Layer 3 verification that fits the repo: tests in the gate, property tests for invariants, architecture tests, a runtime driver that produces artifacts, and formal methods only where state is distributed and expensive to get wrong.

## Working rules

- Work in small, separately reviewable steps, one concern per commit. The gate must pass after each step, and a step that improves a baseline commits the smaller baseline.
- Commit only when the user agrees. Never push or open PRs unless asked.
- For large mechanical work (stripping comments across hundreds of files, fixing a rule across the tree), split it into batches by directory. Give each batch a frozen contract: what may change, what must not, and the verification command. If parallel subagents or worktrees are available and the user wants speed, run batches in parallel and merge sequentially, re-running the gate after each merge.
- When a check you add fails on a pattern that is actually fine, fix the rule (narrow the regex, add a config-level exclusion with a reason in the rule message). Don't add inline ignores.
- Every new rule gets a fixture proving it fires: a quick throwaway file or a test case. Tools often don't enforce what their names suggest. For example, ESLint's `capitalized-comments` and `multiline-comment-style` format comments but don't ban them.

## Done when

- The audit report exists, and every finding has an action and a status (done, deferred to an issue, or kept with a reason).
- There is one instructions file, and every claim in it about commands, paths and APIs has been checked against the repo.
- `inventory.py` reports no unresolved references in instruction files.
- One gate command exists and passes at HEAD. Its baselines can only shrink, and its rules have instructive messages.
- The final summary to the user lists what was removed, what became checks, what moved to issues, the before/after baseline counts, and the remaining recommended next steps.
