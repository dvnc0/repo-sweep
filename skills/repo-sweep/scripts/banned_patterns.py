#!/usr/bin/env python3
"""Ratcheting ban list. Copy into a repo (e.g. tools/banned_patterns.py) with a
config next to it; stdlib only, Python 3.9+.

Each rule is a regex with a message that tells the agent what to do instead.
Existing violations live in a baseline that may only shrink:
  - a file gaining a violation fails the check;
  - a file losing one also fails, until the smaller baseline is written,
    so improvements get locked in;
  - --baseline refuses to grow any count. A brand-new rule may seed its
    baseline once with --add-rule ID.

Config (JSON, default tools/banned_patterns.json, paths relative to --root):
{
  "rules": {
    "no-timers": {
      "paths": ["src"], "ext": ["ts", "tsx"], "exclude": ["src/framework/**"],
      "regex": "\\\\bsetTimeout\\\\(",
      "message": "Timers patch over state bugs (see #123). Fix the data flow.",
      "scope": "code"
    },
    "no-comments": {
      "paths": ["src"], "ext": ["py"], "regex": ".", "scope": "comment",
      "allow": "^Critical:\\\\s*\\\\S",
      "message": "Comments are banned. Rename or extract instead. Only `# Critical: <why>` is allowed."
    }
  }
}

scope: "line" (default, any line), "code" (line with comments and string
contents blanked), "comment" (comment text only; a comment block whose first
line matches "allow" is exempt, including directly following comment lines).
Comment detection is exact for Python (tokenize) and lexical for //, /* */,
# and <!-- --> languages.

Usage:
  banned_patterns.py [--config PATH] [--root DIR]          check (exit 1 on change)
  banned_patterns.py --baseline [--add-rule ID ...]        write the baseline
  banned_patterns.py --list [RULE]                         print every hit
"""

from __future__ import annotations

import argparse
import fnmatch
import io
import json
import os
import re
import sys
import tokenize
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "vendor", ".venv", "venv", "__pycache__", "dist", "build", ".next", "coverage", "target"}
HASH_EXT = {"py", "pyi", "rb", "sh", "bash", "zsh", "yaml", "yml", "toml", "r", "pl", "ex", "exs", "tf"}
HTML_EXT = {"html", "htm", "xml", "svg", "vue", "svelte", "latte", "twig", "blade", "erb", "hbs", "md"}


def iter_files(root: Path, rule: dict):
    exts = {e.lstrip(".") for e in rule.get("ext", [])}
    excludes = rule.get("exclude", [])
    for base in rule.get("paths", ["."]):
        start = root / base
        if start.is_file():
            candidates = [start]
        elif start.is_dir():
            candidates = []
            for dirpath, dirnames, filenames in os.walk(start):
                dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
                candidates.extend(Path(dirpath, f) for f in sorted(filenames))
        else:
            continue
        for path in candidates:
            rel = path.relative_to(root).as_posix()
            if exts and path.suffix.lstrip(".") not in exts:
                continue
            if rel.endswith((".min.js", ".min.css")) or any(fnmatch.fnmatch(rel, g) for g in excludes):
                continue
            yield rel, path


def python_comments(text: str) -> dict[int, tuple[str, bool]]:
    """line -> (comment text, is a whole-line comment that can continue a block)."""
    out: dict[int, tuple[str, bool]] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT and not (tok.start[0] == 1 and tok.string.startswith("#!")):
                whole_line = not tok.line[: tok.start[1]].strip()
                out[tok.start[0]] = (tok.string[1:].strip(), whole_line)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return lexical_split(text, "py")[1]
    return out


def lexical_split(text: str, ext: str) -> tuple[dict[int, str], dict[int, tuple[str, bool]]]:
    """Return (code_by_line, comments_by_line). Strings are blanked in code.
    comments_by_line maps line -> (text, is a whole-line //-or-# comment)."""
    hash_lang = ext in HASH_EXT
    slash_lang = not hash_lang or ext == "php"
    html_lang = ext in HTML_EXT
    code: dict[int, list[str]] = {}
    comments: dict[int, list[str]] = {}
    kinds: dict[int, str] = {}
    line, i, n = 1, 0, len(text)

    def open_comment(kind):
        comments.setdefault(line, [])
        kinds.setdefault(line, kind)
    mode, quote = "code", ""

    def put(store, ch):
        store.setdefault(line, []).append(ch)

    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            if mode == "line":
                mode = "code"
            i += 1
            continue
        if mode == "code":
            if slash_lang and text.startswith("//", i) and not text[max(0, i - 1)] == ":":
                open_comment("line")
                mode, i = "line", i + 2
                continue
            if slash_lang and text.startswith("/*", i):
                open_comment("block")
                mode, i = "block", i + 2
                continue
            if html_lang and text.startswith("<!--", i):
                open_comment("block")
                mode, i = "html", i + 4
                continue
            if (hash_lang or ext == "php") and ch == "#" and not text.startswith("#[", i) and not (i and text[i - 1] in "$&{"):
                open_comment("line")
                mode, i = "line", i + 1
                continue
            if ch in "\"'`" and not (html_lang and ch == "'"):
                mode, quote = "string", ch
                put(code, ch)
                i += 1
                continue
            put(code, ch)
        elif mode == "string":
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                mode = "code"
                put(code, ch)
        elif mode == "line":
            put(comments, ch)
        else:
            comments.setdefault(line, [])
            kinds.setdefault(line, "block")
            end = "*/" if mode == "block" else "-->"
            if text.startswith(end, i):
                mode, i = "code", i + len(end)
                continue
            put(comments, ch)
        i += 1
    joined = {k: "".join(v) for k, v in code.items()}
    result = {}
    for k, v in comments.items():
        body = "".join(v).strip().lstrip("*").strip()
        whole_line = kinds.get(k) == "line" and not joined.get(k, "").strip()
        result[k] = (body, whole_line)
    return joined, result


def hits_for(rule: dict, rel: str, path: Path) -> list[int]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    pattern = re.compile(rule["regex"])
    scope = rule.get("scope", "line")
    ext = path.suffix.lstrip(".").lower()
    if scope == "line":
        return [i for i, l in enumerate(text.splitlines(), 1) if pattern.search(l)]
    if scope == "code":
        code, _ = lexical_split(text, ext)
        return [i for i, l in sorted(code.items()) if pattern.search(l)]
    comments = python_comments(text) if ext in ("py", "pyi") else lexical_split(text, ext)[1]
    allow = re.compile(rule["allow"]) if rule.get("allow") else None
    hits, exempt_block = [], False
    for ln in sorted(comments):
        body, whole_line = comments[ln]
        continues = whole_line and (ln - 1) in comments and comments[ln - 1][1]
        if not continues:
            exempt_block = bool(allow and allow.search(body))
        if not exempt_block and pattern.search(body):
            hits.append(ln)
    return hits


def scan(root: Path, rules: dict) -> dict[str, dict[str, list[int]]]:
    out: dict[str, dict[str, list[int]]] = {}
    for rule_id, rule in sorted(rules.items()):
        for rel, path in iter_files(root, rule):
            lines = hits_for(rule, rel, path)
            if lines:
                out.setdefault(rule_id, {})[rel] = lines
    return out


def counts(hits: dict) -> dict[str, dict[str, int]]:
    return {r: {f: len(l) for f, l in sorted(files.items())} for r, files in sorted(hits.items())}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="tools/banned_patterns.json")
    ap.add_argument("--root", default=".")
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--add-rule", action="append", default=[])
    ap.add_argument("--list", nargs="?", const="*", default=None)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    config_path = root / args.config
    rules = json.loads(config_path.read_text())["rules"]
    baseline_path = config_path.with_name(config_path.stem + ".baseline.json")
    baseline = json.loads(baseline_path.read_text()) if baseline_path.exists() else {}
    hits = scan(root, rules)
    current = counts(hits)

    if args.list:
        for rule_id, files in hits.items():
            if args.list in ("*", rule_id):
                for f, lines in files.items():
                    for ln in lines:
                        print(f"{f}:{ln}: [{rule_id}]")
        return 0

    if args.baseline:
        seeding = set(args.add_rule) | ({*rules} if not baseline_path.exists() else set())
        for rule_id in args.add_rule:
            if rule_id in baseline:
                print(f"--add-rule {rule_id}: rule already has a baseline; it can only shrink.", file=sys.stderr)
                return 1
        for rule_id, files in current.items():
            if rule_id in seeding:
                continue
            for f, n in files.items():
                allowed = baseline.get(rule_id, {}).get(f, 0)
                if n > allowed:
                    print(f"Refusing to grow the baseline: [{rule_id}] {f} {allowed} -> {n}. Fix the new occurrences.", file=sys.stderr)
                    return 1
        baseline_path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
        total = sum(sum(v.values()) for v in current.values())
        print(f"Baseline written: {baseline_path.relative_to(root)} ({total} known violations)")
        return 0

    failed = False
    for rule_id, files in hits.items():
        for f, lines in files.items():
            allowed = baseline.get(rule_id, {}).get(f, 0)
            if len(lines) > allowed:
                failed = True
                print(f"\n[{rule_id}] {f}: {len(lines)} found, baseline allows {allowed} (lines {', '.join(map(str, lines))})")
                print(f"  {rules[rule_id]['message']}")
    shrunk = [f"[{r}] {f}: {n} -> {current.get(r, {}).get(f, 0)}"
              for r, files in baseline.items() for f, n in files.items()
              if current.get(r, {}).get(f, 0) < n]
    if failed:
        print("\nBanned patterns: new violations. Fix the code; do not edit the baseline.")
        return 1
    if shrunk:
        print("Banned patterns: violations went down. Lock it in with `--baseline` and commit:\n  " + "\n  ".join(shrunk))
        return 1
    print("Banned patterns: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
