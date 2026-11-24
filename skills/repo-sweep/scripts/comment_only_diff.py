#!/usr/bin/env python3
"""Prove a change only touched comments, docstrings and whitespace.

For each changed file, compares a comment-free normal form of the base
version with the new version:
  .py               AST dump with docstrings removed (stdlib only)
  .php              token stream minus comments/whitespace (needs `php`)
  .js .jsx .ts .tsx .mjs .cjs .mts .cts .vue .svelte
                    built-in lexer: significant tokens with comments and
                    whitespace dropped. Strings, template literals and regex
                    literals are kept verbatim. Lexer ambiguity (e.g. an
                    apostrophe in JSX text) can only cause a false CODE CHANGED,
                    never a false OK.
Anything else is reported UNVERIFIED and does not fail the run.

Usage:
  comment_only_diff.py [--base REF] [--head REF] [--rename OLD=NEW ...] [paths...]

Defaults: base HEAD, head = working tree, paths = all files changed between them.
--rename lets an agreed identifier rename through (applied to the base side).
Exit 1 if any file's code changed or a new version fails to parse.
"""

from __future__ import annotations

import argparse
import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

PY_EXT = {".py", ".pyi"}
PHP_EXT = {".php"}
JS_EXT = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts", ".vue", ".svelte"}

PHP_NORMALIZER = r"""
$src = stream_get_contents(STDIN);
$out = [];
foreach (token_get_all($src) as $t) {
    if (is_array($t)) {
        if (in_array($t[0], [T_COMMENT, T_DOC_COMMENT, T_WHITESPACE], true)) { continue; }
        $out[] = token_name($t[0]) . ':' . $t[1];
    } else {
        $out[] = $t;
    }
}
echo implode("\n", $out);
"""



def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=check)


def read_version(root: Path, ref: str | None, path: str) -> str | None:
    if ref is None:
        p = root / path
        return p.read_text(encoding="utf-8", errors="replace") if p.exists() else None
    r = git(root, "show", f"{ref}:{path}", check=False)
    return r.stdout if r.returncode == 0 else None


def strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]
    return tree


def norm_py(src: str, _root: Path, _path: str) -> str:
    return ast.dump(strip_docstrings(ast.parse(src)), include_attributes=False)


def norm_php(src: str, _root: Path, _path: str) -> str:
    r = subprocess.run(["php", "-d", "display_errors=stderr", "-r", PHP_NORMALIZER], input=src, capture_output=True, text=True)
    if r.returncode != 0:
        raise ValueError(r.stderr.strip() or "php tokenizer failed")
    return r.stdout


REGEX_PREV_KEYWORDS = {"return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case", "do", "else", "yield", "await"}


def norm_js(src: str, _root: Path, _path: str) -> str:
    tokens: list[str] = []
    i, n = 0, len(src)

    def regex_allowed() -> bool:
        if not tokens:
            return True
        prev = tokens[-1]
        if prev in REGEX_PREV_KEYWORDS:
            return True
        return not (prev[-1].isalnum() or prev[-1] in "_$)]}\"'`")

    def scan_quoted(j: int, quote: str) -> int:
        j += 1
        while j < n and src[j] != quote:
            if src[j] == "\\":
                j += 1
            elif src[j] == "\n":
                return j
            j += 1
        return j + 1

    while i < n:
        ch = src[i]
        if ch.isspace():
            i += 1
        elif src.startswith("//", i):
            nl = src.find("\n", i)
            i = n if nl < 0 else nl
        elif src.startswith("/*", i):
            close = src.find("*/", i + 2)
            if close < 0:
                raise ValueError("unterminated block comment")
            i = close + 2
        elif ch in "\"'":
            j = scan_quoted(i, ch)
            tokens.append(src[i:j])
            i = j
        elif ch == "`":
            j, depth = i + 1, 0
            while j < n:
                c = src[j]
                if c == "\\":
                    j += 2
                    continue
                if depth == 0 and c == "`":
                    break
                if src.startswith("${", j):
                    depth += 1
                    j += 2
                    continue
                if depth and c == "}":
                    depth -= 1
                elif depth and c == "{":
                    depth += 1
                j += 1
            tokens.append(src[i:j + 1])
            i = j + 1
        elif ch == "/" and regex_allowed():
            j, in_class = i + 1, False
            while j < n and src[j] != "\n":
                c = src[j]
                if c == "\\":
                    j += 2
                    continue
                if c == "[":
                    in_class = True
                elif c == "]":
                    in_class = False
                elif c == "/" and not in_class:
                    break
                j += 1
            j += 1
            while j < n and (src[j].isalnum()):
                j += 1
            tokens.append(src[i:j])
            i = j
        elif ch.isalnum() or ch in "_$#@":
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] in "_$."):
                if src[j] == "." and not (ch.isdigit()):
                    break
                j += 1
            tokens.append(src[i:j])
            i = j
        else:
            tokens.append(ch)
            i += 1
    return "\n".join(tokens)


def normalizer_for(path: str, root: Path):
    ext = Path(path).suffix.lower()
    if ext in PY_EXT:
        return norm_py, None
    if ext in PHP_EXT:
        return (norm_php, None) if shutil.which("php") else (None, "php not on PATH")
    if ext in JS_EXT:
        return norm_js, None
    return None, f"no normalizer for {ext or 'extensionless'} files"


def apply_renames(text: str, renames: list[tuple[str, str]]) -> str:
    import re
    for old, new in renames:
        text = re.sub(rf"\b{re.escape(old)}\b", new, text)
    return text


def first_difference(a: str, b: str) -> str:
    la, lb = a.splitlines(), b.splitlines()
    for i, (x, y) in enumerate(zip(la, lb)):
        if x != y:
            col = next((j for j, (cx, cy) in enumerate(zip(x, y)) if cx != cy), min(len(x), len(y)))
            start = max(0, col - 40)
            return f"base: {x[start:col + 60]!r}\n      new:  {y[start:col + 60]!r}"
    return f"length differs ({len(la)} vs {len(lb)} normalized lines)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="HEAD")
    ap.add_argument("--head", default=None, help="ref to compare; default is the working tree")
    ap.add_argument("--rename", action="append", default=[], metavar="OLD=NEW")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("paths", nargs="*")
    args = ap.parse_args()

    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").stdout.strip())
    renames = [tuple(r.split("=", 1)) for r in args.rename]
    if args.paths:
        paths = [str(Path(p).resolve().relative_to(root)) if Path(p).is_absolute() or Path(p).exists() else p for p in args.paths]
    else:
        diff_args = ["diff", "--name-only", "--diff-filter=AMR", args.base] + ([args.head] if args.head else [])
        paths = [p for p in git(root, *diff_args).stdout.splitlines() if p]

    results = []
    for path in paths:
        new = read_version(root, args.head, path)
        old = read_version(root, args.base, path)
        if new is None:
            results.append({"path": path, "status": "DELETED"})
            continue
        if old is None:
            results.append({"path": path, "status": "ADDED", "detail": "new file; nothing to compare"})
            continue
        norm, why = normalizer_for(path, root)
        if norm is None:
            results.append({"path": path, "status": "UNVERIFIED", "detail": why})
            continue
        try:
            n_new = norm(new, root, path)
        except (SyntaxError, ValueError) as exc:
            results.append({"path": path, "status": "BROKEN", "detail": f"new version does not parse: {exc}"})
            continue
        try:
            n_old = norm(apply_renames(old, renames), root, path)
        except (SyntaxError, ValueError) as exc:
            results.append({"path": path, "status": "UNVERIFIED", "detail": f"base version does not parse: {exc}"})
            continue
        if n_old == n_new:
            results.append({"path": path, "status": "OK"})
        else:
            results.append({"path": path, "status": "CODE CHANGED", "detail": first_difference(n_old, n_new)})

    failing = [r for r in results if r["status"] in ("CODE CHANGED", "BROKEN")]
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            line = f"{r['status']:<13} {r['path']}"
            if r.get("detail") and r["status"] != "OK":
                line += f"\n      {r['detail']}"
            print(line)
        counts: dict[str, int] = {}
        for r in results:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        print("\n" + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) if counts else "No changed files.")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
