# Comment cleanup

Why: comments go stale silently, humans skim past them, and agents use them two ways. They copy them as patterns ("// HACK: wait for render" spreads), and they write new ones to justify a workaround instead of fixing it. Code, types, names and checks stay true because they are executed. Comments are not.

But some comments guard invariants no tool can see. A blanket strip deletes those too, and the next agent "cleans up" the lock ordering. The policy is therefore **ban all comments except a marked, narrow exception**.

## The policy

- No line, block, or template/HTML comments in product code. Tests may be held to the same rule or exempted; ask the user.
- **Exception: `Critical: <why>`.** Use the language's line-comment syntax, and continuation lines directly below are allowed. Use it only for a constraint that lives next to the code it guards, that the code can't express, and that would cause a bug, security hole or data loss if someone "cleaned it up". Typical cases: lock or transaction ordering, external-system quirks (a mail API that fails open, link scanners prefetching GETs), security reasoning (why a header is ignored), resource limits, and deliberate empty catches. Never use it to narrate what the code does.
- **Docblocks and docstrings** may define only *shape* that native types can't express (array shapes, generics, `list<T>`, `@throws`, typed properties in untyped languages). No prose, no tag descriptions, no `@todo`/`@author`/`@see`. A docblock that only repeats the signature gets deleted.
- **Public library API docs** (published packages, SDKs) are a legitimate exception. The API docs *are* the product there. Scope the rule to internal code.
- Durable knowledge that would have gone in a comment goes in the instructions file's "Facts code can't show" section, or becomes a test whose name states the fact.

Confirm the policy with the user before starting, especially for tests, public API docs and generated code.

## Taxonomy (what to do with each comment)

| Kind | Example | Action |
|---|---|---|
| Narration | `// loop over users` | delete |
| Stale or wrong | `// returns null if missing` (it throws) | delete. Note it: the code may have a bug the comment was hiding. |
| Commented-out code | `// $x = foo();` | delete (git has it) |
| TODO/FIXME/HACK | `// TODO: handle timezones` | open an issue if still real (ask before creating), then delete |
| Lint/type ignore | `// eslint-disable-next-line`, `# type: ignore` | **fix the underlying violation first**, or baseline it in config; then delete |
| Section banner | `// ===== Helpers =====` | delete; extract a module if the file needs sections |
| Justification | `// using setTimeout because state isn't ready` | delete, and fix the root cause or log it as an issue; it marks an architectural clash |
| Critical invariant | `// lock attraction before event to avoid deadlock` | convert to `Critical: ...` and keep |
| Production fact | `// CDN passes real IP in REMOTE_ADDR` | move to Facts (or `Critical:` if it guards this exact line) |
| Shape docblock | `@param array{id:int,name:string} $row` | keep the shape and strip the prose |
| License header | SPDX line | keep if the project requires it; allow-list exactly that pattern |

## Protocol

1. **Gate first.** The comment rule must exist (in `scope: "comment"` mode in `banned_patterns.py`, `assets/eslint-no-comments.js`, or an analyzer rule) with a baseline, so progress is ratcheted and new comments are blocked from day one.
2. **Handle escape hatches before stripping.** Run the gate with all inline ignores removed (on a scratch branch), and list what fails. Fix those violations, or move them to config-level baselines, *before* the bulk strip. Otherwise deleting `phpcs:ignore` / `noqa` breaks the gate mid-batch and blocks every worker.
3. **Pre-pass for critical comments.** Grep for the signals: `lock`, `order`, `race`, `deadlock`, `security`, `never`, `must`, `do not`, `don't`, `because`, `quirk`, `workaround`, `limit`, `max`, `timeout`, `intentional`, `on purpose`, `prefetch`, `idempotent`, `retry`, plus empty catches. Read each hit and mark it convert or harvest *before* any deletion happens.
4. **Batch by directory.** Each batch has a frozen contract:
   - Only comments, docblocks and whitespace change. No renames, no extractions, no moves. (Renames to satisfy a rule are a separate, explicitly agreed step, verified with `--rename OLD=NEW`.)
   - Workers never edit baselines. Baselines are regenerated once, after all batches merge.
   - Workers report harvested facts as `file:line: fact` and don't write them anywhere themselves.
   - Verification: `python3 <skill>/scripts/comment_only_diff.py --base <base-sha>` must exit 0, plus the gate (or the comment rule only, if the baseline is stale mid-run).
5. **Merge, then lock in.** Regenerate baselines once (they must only shrink), run the full gate, and run `comment_only_diff.py` over the whole range.
6. **Fold in the harvest.** Review the reported facts with the user. Add the durable ones to the Facts section and restore any critical ones as `Critical:` comments. Expect a handful per few thousand comments.

## Pitfalls seen in practice

- **Multi-line docblock shapes get truncated** when a worker deletes "prose" lines that are actually continuation lines of an array shape. This produces a docblock parse error that ends up in the baseline. Check the analyzer output for parse errors after each batch.
- **Indentation damage** when a comment was the only content between braces, or in whitespace-sensitive languages. `comment_only_diff.py` ignores whitespace for brace languages, so also run the formatter.
- **Python docstrings** are part of the AST, but `comment_only_diff.py` strips them deliberately. A function whose only body was a docstring now needs `pass` or `...`, and the script reports BROKEN if that was missed.
- **Template comments ship to users** (HTML `<!-- -->`). Removing them is a visible change; confirm nothing parses them (conditional comments, build markers, SSI).
- **Directive comments that aren't comments to the toolchain:** `/// <reference>`, `//go:build`, `//go:embed`, `# -*- coding -*-`, `#!`, `// @ts-check`, `/* webpackChunkName */`, `"use client"` banners, `# frozen_string_literal`, license headers. Allow-list them by exact pattern in the rule.
