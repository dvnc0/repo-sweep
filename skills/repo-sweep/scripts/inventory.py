#!/usr/bin/env python3
"""Deterministic survey of a repo's agent-facing surface.

Finds agent instruction files, docs, scratch dirs, quality tooling, and
comment / escape-hatch counts, and cross-checks doc claims (paths and script
names) against the tree. Read-only. Output is markdown, or JSON with --json.

Usage: inventory.py [repo_root] [--json] [--top N]
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

SKIP_DIRS = {
    ".git", "node_modules", "vendor", ".venv", "venv", "env", "__pycache__",
    "dist", "build", "out", "target", ".next", ".nuxt", "coverage", ".tox",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", ".turbo", ".cache",
}
MAX_BYTES = 1_000_000

INSTRUCTION_PATTERNS = [
    r"(^|/)CLAUDE(\.local)?\.md$", r"(^|/)AGENTS\.md$", r"(^|/)GEMINI\.md$",
    r"(^|/)\.cursorrules$", r"^\.cursor/rules/", r"^\.github/copilot-instructions\.md$",
    r"^\.github/instructions/", r"^\.github/prompts/", r"(^|/)\.windsurfrules$",
    r"^\.windsurf/rules/", r"(^|/)\.clinerules", r"^\.aider", r"(^|/)CONVENTIONS\.md$",
    r"^\.claude/(skills|commands|agents|rules)/", r"^\.junie/", r"^\.kiro/steering/",
    r"(^|/)CONTRIBUTING\.md$",
]
SCRATCH_PATTERNS = [
    r"^\.context/", r"^\.planning/", r"^plans?/", r"^notes?/", r"^specs?/",
    r"^docs/(plans?|specs?|notes|rfcs?|adr|decisions)/", r"(^|/)TODO\.md$",
    r"(^|/)(NOTES|SCRATCH|HANDOFF|PROGRESS|STATUS)\.md$", r"(^|/)DECISIONS\.md$",
    r"(^|/)CHANGELOG\.md$",
]

LANG_BY_EXT = {
    ".py": "py", ".pyi": "py",
    ".js": "c", ".jsx": "c", ".mjs": "c", ".cjs": "c", ".ts": "c", ".tsx": "c",
    ".mts": "c", ".cts": "c", ".java": "c", ".kt": "c", ".go": "c", ".rs": "c",
    ".c": "c", ".h": "c", ".cc": "c", ".cpp": "c", ".hpp": "c", ".cs": "c",
    ".swift": "c", ".scala": "c", ".dart": "c", ".php": "php",
    ".rb": "hash", ".sh": "hash", ".bash": "hash", ".zsh": "hash",
    ".ex": "hash", ".exs": "hash", ".r": "hash", ".pl": "hash",
    ".vue": "c", ".svelte": "c", ".latte": "c",
}

ESCAPE_RE = re.compile(
    r"eslint-disable|@ts-ignore|@ts-expect-error|@ts-nocheck|biome-ignore|"
    r"\bnoqa\b|type:\s*ignore|pyright:\s*ignore|pylint:\s*disable|pragma:\s*no cover|"
    r"phpstan-ignore|phpcs:(ignore|disable)|psalm-suppress|@codingStandardsIgnore|"
    r"\bnolint\b|#\[allow\(|@SuppressWarnings|NOSONAR|istanbul ignore|c8 ignore|"
    r"prettier-ignore|rubocop:disable|shellcheck disable"
)
TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX|TEMP|WORKAROUND)\b")
CODEISH_RE = re.compile(
    r"([;{}]\s*$)|(^\s*(if|for|while|return|import|from|def|class|function|const|let|var|"
    r"public|private|echo|print|console\.|await|try|catch)\b)|(^\s*[\w.$>\[\]-]+\s*=\s*\S)|"
    r"(^\s*\w+(\.\w+)*\(.*\)\s*;?\s*$)"
)
CRITICAL_RE = re.compile(r"^\s*(Critical|SAFETY|INVARIANT|SECURITY)\s*:", re.I)
TYPE_ESCAPE_RES = {
    "ts-any": re.compile(r"(:\s*any\b|\bas\s+any\b|<any>)"),
    "ts-nonnull-cast": re.compile(r"\bas\s+unknown\s+as\b"),
    "py-cast-any": re.compile(r"\bcast\(\s*Any\b"),
}
TIMER_RE = re.compile(r"\b(setTimeout|setInterval|requestAnimationFrame|requestIdleCallback)\s*\(|\btime\.sleep\(|\basyncio\.sleep\(")

PATH_TOKEN_RE = re.compile(r"`([^`\s]+)`")
SCRIPT_REF_RES = {
    "npm": re.compile(r"\b(?:npm run|pnpm(?: run)?|yarn(?: run)?|bun run)\s+([\w:.-]+)"),
    "composer": re.compile(r"\bcomposer\s+(?:run(?:-script)?\s+)?([\w:.-]+)"),
    "make": re.compile(r"\bmake\s+([\w.-]+)"),
    "just": re.compile(r"\bjust\s+([\w.-]+)"),
}
NPM_BUILTINS = {"install", "i", "ci", "add", "remove", "test", "start", "exec", "dlx", "x", "create", "init", "run", "publish", "link", "update", "outdated", "audit", "why", "list", "ls", "version", "pack"}
COMPOSER_BUILTINS = {"install", "update", "require", "remove", "dump-autoload", "dumpautoload", "show", "outdated", "validate", "create-project", "global", "config", "diagnose", "audit", "why", "depends", "init", "run", "run-script", "exec", "self-update", "clear-cache", "status", "licenses", "fund", "bump", "check-platform-reqs", "suggests", "search", "archive", "reinstall"}


def git(root: Path, *args: str) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def skipped(rel: str) -> bool:
    return any(part in SKIP_DIRS for part in rel.split("/")) or bool(re.search(r"\.min\.(js|css)$|\.(map|lock)$", rel))


def list_files(root: Path) -> tuple[list[str], bool]:
    out = git(root, "ls-files", "-co", "--exclude-standard")
    if out is not None:
        return sorted({p for p in out.splitlines() if p and not skipped(p)}), True
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            rel = str(Path(dirpath, name).relative_to(root))
            if not skipped(rel):
                files.append(rel)
    return sorted(files), False


def last_commit_ages(root: Path, is_git: bool) -> dict[str, int]:
    """Days since each path was last touched in git history (one pass over the log)."""
    if not is_git:
        return {}
    out = git(root, "log", "--name-only", "--format=@@%ct", "--no-renames")
    if not out:
        return {}
    now = time.time()
    ages: dict[str, int] = {}
    stamp = now
    for line in out.splitlines():
        if line.startswith("@@"):
            stamp = int(line[2:])
        elif line and line not in ages:
            ages[line] = int((now - stamp) // 86400)
    return ages


def read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:4096]:
        return None
    return data.decode("utf-8", errors="replace")


def matches(path: str, patterns: list[str]) -> bool:
    return any(re.search(p, path) for p in patterns)


def comment_lines(text: str, lang: str) -> list[str]:
    """Approximate comment extraction. Good enough to rank files, not to edit them."""
    out: list[str] = []
    in_block = False
    for raw in text.splitlines():
        line = raw.strip()
        if lang in ("c", "php"):
            if in_block:
                out.append(line.lstrip("*").strip())
                if "*/" in line:
                    in_block = False
                continue
            if line.startswith("/*"):
                out.append(line[2:].lstrip("*").strip())
                in_block = "*/" not in line[2:]
                continue
            if line.startswith("//") or (lang == "php" and line.startswith("#") and not line.startswith("#[")):
                out.append(line.lstrip("/#").strip())
                continue
            idx = raw.find(" // ")
            if idx > 0 and raw[:idx].count('"') % 2 == 0 and raw[:idx].count("'") % 2 == 0 and "://" not in raw[idx - 1: idx + 4]:
                out.append(raw[idx + 4:].strip())
        elif lang in ("py", "hash"):
            if line.startswith("#!"):
                continue
            if line.startswith("#"):
                out.append(line.lstrip("#").strip())
            else:
                idx = raw.find("  #")
                if idx > 0 and raw[:idx].count('"') % 2 == 0 and raw[:idx].count("'") % 2 == 0:
                    out.append(raw[idx + 3:].strip())
    return out


def classify(comment: str) -> str:
    if ESCAPE_RE.search(comment):
        return "escape"
    if CRITICAL_RE.search(comment):
        return "critical"
    if TODO_RE.search(comment):
        return "todo"
    if comment and CODEISH_RE.search(comment):
        return "commented-code"
    if comment.startswith("@") or not comment:
        return "docblock-tag"
    return "prose"


def detect_tooling(root: Path, files: list[str]) -> dict:
    fileset = set(files)
    found: dict[str, list[str]] = defaultdict(list)
    scripts: dict[str, dict[str, str]] = {}

    def has(*names: str) -> bool:
        return any(n in fileset or (root / n).exists() for n in names)

    pkg = root / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text())
        except (ValueError, OSError):
            data = {}
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        scripts["npm"] = data.get("scripts", {}) or {}
        for name in ["eslint", "typescript", "prettier", "@biomejs/biome", "vitest", "jest", "mocha",
                     "playwright", "@playwright/test", "cypress", "dependency-cruiser", "knip",
                     "fast-check", "eslint-plugin-boundaries", "madge", "ts-prune", "husky", "lefthook",
                     "lint-staged", "stryker", "@stryker-mutator/core"]:
            if name in deps:
                found["node"].append(name)
    pyproject = root / "pyproject.toml"
    py_text = (pyproject.read_text(errors="replace") if pyproject.exists() else "")
    for extra in ["requirements-dev.txt", "requirements.txt", "setup.cfg", "tox.ini"]:
        if (root / extra).exists():
            py_text += (root / extra).read_text(errors="replace")
    for name in ["ruff", "mypy", "pyright", "basedpyright", "pytest", "hypothesis", "import-linter",
                 "importlinter", "pylint", "black", "bandit", "vulture", "deptry", "mutmut"]:
        if re.search(rf"(^|[\s\"'\[]){re.escape(name)}\b", py_text):
            found["python"].append(name)
    composer = root / "composer.json"
    for cpath in [composer, *[root / f for f in files if f.endswith("/composer.json") and f.count("/") == 1]]:
        if cpath.exists():
            try:
                cdata = json.loads(cpath.read_text())
            except (ValueError, OSError):
                continue
            cdeps = {**cdata.get("require", {}), **cdata.get("require-dev", {})}
            for name in cdeps:
                if any(k in name for k in ["phpstan", "phpcs", "squizlabs", "phpunit", "phpat", "psalm", "rector", "pest", "infection", "deptrac"]):
                    found["php"].append(name)
            scripts.setdefault("composer", {}).update(cdata.get("scripts", {}) or {})
    if has("go.mod"):
        found["go"].append("go.mod")
        if any(re.search(r"(^|/)\.golangci\.(ya?ml|toml|json)$", f) for f in files):
            found["go"].append("golangci-lint config")
    if has("Cargo.toml"):
        found["rust"].append("Cargo.toml")
        if has("clippy.toml", ".clippy.toml"):
            found["rust"].append("clippy.toml")
    makefile = root / "Makefile"
    if makefile.exists():
        targets = re.findall(r"^([\w.-]+):", makefile.read_text(errors="replace"), re.M)
        scripts["make"] = {t: "" for t in targets}
    justfile = root / "justfile"
    if justfile.exists():
        scripts["just"] = {t: "" for t in re.findall(r"^@?([\w-]+)[^\n:=]*:(?!=)", justfile.read_text(errors="replace"), re.M)}
    ci = [f for f in files if f.startswith(".github/workflows/") or f in (".gitlab-ci.yml", ".circleci/config.yml", "bitbucket-pipelines.yml", "azure-pipelines.yml")]
    hooks = [f for f in files if re.search(r"(^|/)(\.pre-commit-config\.yaml|lefthook\.ya?ml|\.husky/)", f)]
    configs = [f for f in files if re.search(
        r"(^|/)(eslint\.config\.[cm]?[jt]s|\.eslintrc(\.\w+)?|biome\.jsonc?|tsconfig[\w.-]*\.json|\.dependency-cruiser\.c?js|"
        r"knip\.jsonc?|ruff\.toml|\.ruff\.toml|mypy\.ini|pyrightconfig\.json|\.importlinter|phpstan[\w.-]*\.neon(\.dist)?|"
        r"phpcs\.xml(\.dist)?|psalm\.xml|deptrac\.ya?ml|\.golangci\.\w+|clippy\.toml|vitest\.config\.\w+|jest\.config\.\w+|"
        r"playwright\.config\.\w+|phpunit\.xml(\.dist)?|pytest\.ini|eslint-suppressions\.json|[\w.-]*baseline[\w.-]*)$", f)]
    gate_names = {"check", "verify", "ci", "validate", "gate", "lint", "typecheck", "test"}
    gates = {kind: sorted(k for k in s if k.split(":")[0] in gate_names) for kind, s in scripts.items()}
    return {"tools": dict(found), "scripts": scripts, "gate_scripts": gates, "ci": ci, "hooks": hooks, "configs": configs}


def check_doc_refs(root: Path, doc: str, text: str, fileset: set[str], dirset: set[str], scripts: dict) -> list[str]:
    problems = []
    doc_dir = str(Path(doc).parent)
    seen = set()
    for token in PATH_TOKEN_RE.findall(text):
        tok = token.strip().rstrip(".,:;)")
        if tok in seen or "://" in tok or tok.startswith(("$", "-", "@", "<", "~", "#")) or "*" in tok or "{" in tok:
            continue
        looks_path = "/" in tok and re.fullmatch(r"[\w./-]+", tok) and not re.fullmatch(r"\d+/\d+", tok)
        looks_file = re.fullmatch(r"[\w.-]+\.(md|json|ya?ml|toml|py|ts|tsx|js|php|go|rs|sh|neon|xml|ini|cfg|lock)", tok)
        if not (looks_path or looks_file):
            continue
        seen.add(tok)
        if re.match(r"^[\w-]+\.(com|org|net|io|dev|app|ai|co|gov|edu|us|uk)(/|$)", tok):
            continue
        if any((root / d / tok).exists() for d in ("vendor", "node_modules", "src/vendor", "src/node_modules")):
            continue
        cand = tok.lstrip("./").rstrip("/")
        if tok.startswith("/") and not (root / cand).exists():
            if not any(f.endswith(cand) for f in fileset):
                continue
        options = {cand, os.path.normpath(os.path.join(doc_dir, cand))}
        if any(o in fileset or o in dirset or (root / o).exists() for o in options):
            continue
        if looks_file and not looks_path and any(f.endswith("/" + cand) or f == cand for f in fileset):
            continue
        if any(f.endswith("/" + cand) or f.startswith(cand + "/") or ("/" + cand + "/") in f for f in fileset):
            continue
        problems.append(f"unresolved path `{tok}`")
    for kind, pattern in SCRIPT_REF_RES.items():
        known = scripts.get(kind)
        if known is None:
            continue
        builtins = NPM_BUILTINS if kind == "npm" else COMPOSER_BUILTINS if kind == "composer" else set()
        for name in sorted(set(pattern.findall(text))):
            if name in builtins or name in known:
                continue
            problems.append(f"unknown {kind} script `{name}`")
    return problems


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    as_json = "--json" in sys.argv
    top = 15
    if "--top" in sys.argv:
        top = int(sys.argv[sys.argv.index("--top") + 1])
        args = [a for a in args if a != str(top)]
    root = Path(args[0] if args else ".").resolve()
    top_level = git(root, "rev-parse", "--show-toplevel")
    if top_level:
        root = Path(top_level.strip())

    files, is_git = list_files(root)
    fileset = set(files)
    dirset = {str(Path(f).parent) for f in files} | {p for f in files for p in [str(x) for x in Path(f).parents]}
    ages = last_commit_ages(root, is_git)
    tooling = detect_tooling(root, files)

    instructions, docs, scratch = [], [], []
    comment_stats: dict[str, Counter] = defaultdict(Counter)
    comment_totals: Counter = Counter()
    escapes_by_file: Counter = Counter()
    todos_by_file: Counter = Counter()
    type_escapes: dict[str, Counter] = defaultdict(Counter)
    timers_by_file: Counter = Counter()
    source_files = 0

    for rel in files:
        path = root / rel
        is_instruction = matches(rel, INSTRUCTION_PATTERNS)
        is_scratch = matches(rel, SCRATCH_PATTERNS)
        ext = path.suffix.lower()
        if is_instruction or is_scratch or ext in (".md", ".mdx", ".rst", ".txt") and not rel.startswith(("tests/", "test/")):
            text = read_text(path) if path.is_file() else None
            if text is None and not path.is_symlink():
                continue
            entry = {
                "path": rel,
                "lines": text.count("\n") + 1 if text else 0,
                "days_since_commit": ages.get(rel),
                "symlink_to": os.readlink(path) if path.is_symlink() else None,
            }
            if text and ext in (".md", ".mdx", ".rst", "") or is_instruction:
                entry["ref_problems"] = check_doc_refs(root, rel, text or "", fileset, dirset, tooling["scripts"])
            (instructions if is_instruction else scratch if is_scratch else docs).append(entry)
            continue
        lang = LANG_BY_EXT.get(ext)
        if not lang:
            continue
        text = read_text(path)
        if text is None:
            continue
        source_files += 1
        for comment in comment_lines(text, lang):
            kind = classify(comment)
            comment_stats[rel][kind] += 1
            comment_totals[kind] += 1
            if kind == "escape":
                escapes_by_file[rel] += 1
            if kind == "todo":
                todos_by_file[rel] += 1
        if ext in (".ts", ".tsx", ".mts", ".cts", ".vue", ".svelte"):
            for name in ("ts-any", "ts-nonnull-cast"):
                n = len(TYPE_ESCAPE_RES[name].findall(text))
                if n:
                    type_escapes[name][rel] += n
        if lang == "py":
            n = len(TYPE_ESCAPE_RES["py-cast-any"].findall(text))
            if n:
                type_escapes["py-cast-any"][rel] += n
        n = len(TIMER_RE.findall(text))
        if n and not re.search(r"(^|/)(tests?|__tests__|spec|e2e)/|\.(test|spec)\.", rel):
            timers_by_file[rel] += n

    comments_by_file = Counter({f: sum(c.values()) for f, c in comment_stats.items()})
    report = {
        "root": str(root),
        "git": is_git,
        "file_count": len(files),
        "source_files": source_files,
        "instructions": instructions,
        "docs": docs,
        "scratch": scratch,
        "tooling": tooling,
        "comments": {
            "totals": dict(comment_totals),
            "top_files": [{"path": f, "total": n, **comment_stats[f]} for f, n in comments_by_file.most_common(top)],
        },
        "escapes_top": escapes_by_file.most_common(top),
        "todos_top": todos_by_file.most_common(top),
        "type_escapes": {k: {"total": sum(v.values()), "top": v.most_common(top)} for k, v in type_escapes.items()},
        "timers_top": timers_by_file.most_common(top),
    }
    if as_json:
        print(json.dumps(report, indent=2))
        return 0
    print_markdown(report)
    return 0


def fmt_age(days: int | None) -> str:
    return "untracked" if days is None else f"{days}d"


def print_markdown(r: dict) -> None:
    p = print
    p(f"# Repo inventory: {r['root']}\n")
    p(f"{r['file_count']} files ({r['source_files']} source), git: {r['git']}\n")

    p("## Agent instruction files\n")
    if not r["instructions"]:
        p("None found.\n")
    else:
        p("| path | lines | last commit | symlink | ref problems |\n|---|---|---|---|---|")
        for e in r["instructions"]:
            probs = "; ".join(e.get("ref_problems") or []) or ""
            p(f"| {e['path']} | {e['lines']} | {fmt_age(e['days_since_commit'])} | {e['symlink_to'] or ''} | {probs} |")
        p("")

    for title, key in (("Scratch / planning / decision files", "scratch"), ("Other docs", "docs")):
        entries = r[key]
        p(f"## {title} ({len(entries)})\n")
        if not entries:
            p("None.\n")
            continue
        by_dir: dict[str, list] = defaultdict(list)
        for e in entries:
            by_dir[str(Path(e["path"]).parent)].append(e)
        collapsed = {d for d, es in by_dir.items() if len(es) >= 6 and not any(x.get("ref_problems") for x in es)}
        p("| path | lines | last commit | ref problems |\n|---|---|---|---|")
        for d in sorted(collapsed):
            es = by_dir[d]
            ds = [x["days_since_commit"] for x in es if x["days_since_commit"] is not None]
            span = f"{min(ds)}d-{max(ds)}d" if ds else "untracked"
            p(f"| {d}/ ({len(es)} files, likely content) | {sum(x['lines'] for x in es)} | {span} | |")
        entries = [e for e in entries if str(Path(e["path"]).parent) not in collapsed]
        for e in sorted(entries, key=lambda e: -(e["days_since_commit"] or 0)):
            probs = "; ".join(e.get("ref_problems") or [])
            p(f"| {e['path']} | {e['lines']} | {fmt_age(e['days_since_commit'])} | {probs} |")
        p("")

    t = r["tooling"]
    p("## Quality tooling\n")
    for eco, names in t["tools"].items():
        p(f"- **{eco}**: {', '.join(sorted(set(names)))}")
    if not t["tools"]:
        p("- No linters, type checkers or test runners detected.")
    p(f"- **gate-like scripts**: {json.dumps(t['gate_scripts']) if any(t['gate_scripts'].values()) else 'none'}")
    p(f"- **CI**: {', '.join(t['ci']) or 'none'}")
    p(f"- **hooks**: {', '.join(t['hooks']) or 'none'}")
    p(f"- **configs/baselines**: {', '.join(t['configs']) or 'none'}\n")

    c = r["comments"]
    p("## Comments (approximate, line-based)\n")
    p("Totals: " + (", ".join(f"{k} {v}" for k, v in sorted(c["totals"].items(), key=lambda kv: -kv[1])) or "none") + "\n")
    if c["top_files"]:
        kinds = ["prose", "commented-code", "todo", "escape", "critical", "docblock-tag"]
        p("| file | total | " + " | ".join(kinds) + " |\n|---|---|" + "---|" * len(kinds))
        for row in c["top_files"]:
            p(f"| {row['path']} | {row['total']} | " + " | ".join(str(row.get(k, 0)) for k in kinds) + " |")
        p("")

    def counter_section(title: str, rows: list) -> None:
        p(f"## {title}\n")
        if not rows:
            p("None.\n")
            return
        for path, n in rows:
            p(f"- {path}: {n}")
        p("")

    counter_section("Lint/type escape hatches (top files)", r["escapes_top"])
    counter_section("TODO/FIXME/HACK (top files)", r["todos_top"])
    for name, data in r["type_escapes"].items():
        counter_section(f"Type escapes: {name} (total {data['total']})", data["top"])
    counter_section("Imperative timers / sleeps outside tests (top files)", r["timers_top"])


if __name__ == "__main__":
    sys.exit(main())
