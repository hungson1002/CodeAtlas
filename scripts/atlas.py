#!/usr/bin/env python3
"""
CodeAtlas - a lightweight, dependency-free codebase atlas for AI agents.

Build a local index once, then answer the questions agents actually ask:
  * Where is this symbol?
  * What depends on this file?
  * What breaks if I change it?
  * Which tests should I run?
  * How do I get from A to B?
  * Give me a map / diagram of this repo.

The index lives in .code-atlas/index.json. Everything else is generated:
  CODEATLAS.md            compact map (commit this)
  .code-atlas/diagram.mmd Mermaid dependency graph
  .code-atlas/atlas.html  self-contained interactive map (no CDN)

No third-party packages. Python 3.9+.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import webbrowser
from collections import Counter, defaultdict, deque
from pathlib import Path

VERSION = "1.1.3"
PARSER_VERSION = 1
INDEX_DIR = ".code-atlas"
INDEX_NAME = "index.json"
CONFIG_NAME = ".codeatlas.json"
DEFAULT_MAP = "CODEATLAS.md"

# ---------------------------------------------------------------------------
# Language tables
# ---------------------------------------------------------------------------

EXT_LANG = {
    ".py": "python", ".pyi": "python",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
    ".cs": "csharp", ".rb": "ruby", ".php": "php", ".swift": "swift",
    ".scala": "scala", ".lua": "lua",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".m": "objc", ".mm": "objc",
    ".sh": "shell", ".bash": "shell", ".ps1": "shell",
    ".sql": "sql",
    ".md": "markdown", ".mdx": "markdown", ".rst": "markdown",
    ".json": "config", ".yaml": "config", ".yml": "config", ".toml": "config",
    ".ini": "config", ".cfg": "config", ".conf": "config",
}

CODE_LANGS = {
    "python", "typescript", "javascript", "go", "rust", "java", "kotlin",
    "csharp", "ruby", "php", "swift", "scala", "lua", "c", "cpp", "objc", "shell",
}

NAME_LANG = {
    "dockerfile": "config", "containerfile": "config",
    "makefile": "config", "cmakelists.txt": "config",
    ".gitignore": "config", ".gitattributes": "config", ".dockerignore": "config",
    "procfile": "config", "requirements.txt": "config",
    "gemfile": "ruby", "rakefile": "ruby", "podfile": "ruby",
}

BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svg", ".tiff",
    ".mp3", ".wav", ".ogg", ".flac", ".m4a", ".mp4", ".mov", ".avi", ".mkv", ".webm",
    ".zip", ".gz", ".tar", ".rar", ".7z", ".bz2", ".xz",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a", ".lib",
    ".pyc", ".pyo", ".class", ".jar", ".war", ".wasm", ".node",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".db", ".sqlite", ".sqlite3", ".mdb", ".pickle", ".pkl", ".npy", ".npz",
    ".pt", ".pth", ".onnx", ".safetensors", ".ckpt",
}

LOCK_NAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "cargo.lock", "go.sum", "composer.lock", "gemfile.lock", "uv.lock",
    "pipfile.lock", "bun.lockb", "mix.lock",
}

DEFAULT_EXCLUDES = [
    ".git", ".hg", ".svn", ".idea", ".vscode", ".vs",
    "node_modules", "bower_components", "jspm_packages",
    ".venv", "venv", "env", ".env.d", "virtualenv",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".nox",
    "site-packages", "dist-packages", "eggs", ".eggs",
    "dist", "build", "out", "target", "coverage", ".nyc_output",
    ".next", ".nuxt", ".svelte-kit", ".astro", ".turbo", ".parcel-cache",
    ".cache", ".sass-cache", ".gradle", ".terraform",
    "vendor", "third_party", "third-party", "Pods", "DerivedData",
    "bin", "obj", "Debug", "Release",
    ".github", ".gitlab", ".circleci", ".devcontainer", ".husky",
    ".ssh", ".aws", ".gnupg",
    ".code-atlas",
]

SECRET_NAMES = {
    ".env", ".netrc", ".npmrc", ".pypirc", "id_rsa", "id_dsa", "id_ecdsa",
    "id_ed25519", "credentials", "secrets", "secret", ".htpasswd",
}

SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore", ".jks", ".asc", ".gpg")

KEYWORDS = {
    "if", "elif", "else", "for", "while", "switch", "case", "catch", "return",
    "function", "func", "def", "class", "new", "delete", "throw", "try", "do",
    "with", "match", "when", "loop", "foreach", "using", "sizeof", "typeof",
    "instanceof", "in", "of", "is", "as", "not", "and", "or", "await", "async",
    "yield", "lambda", "super", "self", "this", "print", "echo", "require",
    "import", "export", "package", "public", "private", "protected", "static",
    "void", "int", "float", "double", "string", "bool", "boolean", "char",
    "let", "const", "var", "final", "abstract", "override", "virtual", "async",
}

ENTRY_NAMES = {
    "main.py", "__main__.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "cli.py",
    "index.ts", "index.tsx", "index.js", "index.jsx", "main.ts", "main.tsx",
    "main.js", "main.jsx", "server.ts", "server.js", "app.ts", "app.tsx",
    "main.go", "main.rs", "lib.rs", "program.cs", "application.java",
    "main.kt", "index.php", "app.rb", "main.swift",
}

# Regex symbol specs: (pattern, kind).  Used for non-Python languages.
REGEX_SPECS = {
    "typescript": [
        (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"), "function"),
        (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"), "class"),
        (re.compile(r"^\s*(?:export\s+)?(?:declare\s+)?(?:interface|type|enum)\s+([A-Za-z_$][\w$]*)"), "type"),
        (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"), "function"),
        (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?function\b"), "function"),
    ],
    "javascript": [
        (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"), "function"),
        (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)"), "class"),
        (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"), "function"),
        (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?function\b"), "function"),
        (re.compile(r"^\s*(?:module\.)?exports\.([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?function\b"), "function"),
        (re.compile(r"^\s*(?:module\.)?exports\.([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"), "function"),
        (re.compile(r"^\s*(?:[A-Za-z_$][\w$]*\.)+prototype\.([A-Za-z_$][\w$]*)\s*=\s*function\b"), "function"),
        (re.compile(r"^\s*(?!(?:module\.)?exports\b)[A-Za-z_$][\w$]*\.([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?function\b"), "function"),
    ],
    "go": [
        (re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)"), "function"),
        (re.compile(r"^\s*type\s+([A-Za-z_]\w*)\s+(?:struct|interface)\b"), "class"),
    ],
    "rust": [
        (re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?(?:const\s+)?fn\s+([A-Za-z_]\w*)"), "function"),
        (re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|union)\s+([A-Za-z_]\w*)"), "class"),
    ],
    "java": [
        (re.compile(r"^\s*(?:public|private|protected|abstract|final|static|sealed|non-sealed|\s)*(?:class|interface|enum|record)\s+([A-Za-z_]\w*)"), "class"),
        (re.compile(r"^\s*(?:public|private|protected|static|final|abstract|synchronized|native|default|\s)+[\w<>\[\],.?]+\s+([A-Za-z_]\w*)\s*\("), "function"),
    ],
    "kotlin": [
        (re.compile(r"^\s*(?:public|private|protected|internal|open|abstract|sealed|data|enum|annotation|\s)*(?:class|interface|object)\s+([A-Za-z_]\w*)"), "class"),
        (re.compile(r"^\s*(?:public|private|protected|internal|open|abstract|suspend|inline|tailrec|operator|\s)*fun\s+(?:<[^>]+>\s*)?(?:[\w.]+\.)?([A-Za-z_]\w*)\s*\("), "function"),
    ],
    "csharp": [
        (re.compile(r"^\s*(?:public|private|protected|internal|static|abstract|sealed|partial|\s)*(?:class|interface|struct|enum|record)\s+([A-Za-z_]\w*)"), "class"),
        (re.compile(r"^\s*(?:public|private|protected|internal|static|virtual|override|async|abstract|sealed|partial|extern|unsafe|\s)+[\w<>\[\],.?]+\s+([A-Za-z_]\w*)\s*\("), "function"),
    ],
    "ruby": [
        (re.compile(r"^\s*def\s+(?:self\.)?([A-Za-z_]\w*[!?=]?)"), "function"),
        (re.compile(r"^\s*(?:class|module)\s+([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)"), "class"),
    ],
    "php": [
        (re.compile(r"^\s*(?:abstract\s+|final\s+)?(?:class|interface|trait|enum)\s+([A-Za-z_]\w*)"), "class"),
        (re.compile(r"^\s*(?:public|private|protected|static|abstract|final|\s)*function\s+([A-Za-z_]\w*)"), "function"),
    ],
    "swift": [
        (re.compile(r"^\s*(?:public|private|internal|open|fileprivate|static|class|\s)*(?:func|init)\s+([A-Za-z_]\w*)"), "function"),
        (re.compile(r"^\s*(?:public|private|internal|open|fileprivate|\s)*(?:class|struct|enum|protocol|extension)\s+([A-Za-z_]\w*)"), "class"),
    ],
    "scala": [
        (re.compile(r"^\s*(?:private|protected|final|sealed|abstract|case|\s)*(?:class|object|trait|enum)\s+([A-Za-z_]\w*)"), "class"),
        (re.compile(r"^\s*(?:private|protected|override|final|\s)*def\s+([A-Za-z_]\w*)"), "function"),
    ],
    "lua": [
        (re.compile(r"^\s*(?:local\s+)?function\s+([A-Za-z_]\w*(?:[.:][A-Za-z_]\w*)*)"), "function"),
    ],
    "c": [
        (re.compile(r"^\s*(?:typedef\s+)?(?:struct|union|enum)\s+([A-Za-z_]\w*)"), "class"),
        (re.compile(r"^(?!\s*(?:if|for|while|switch|return|else|do|case|catch)\b)\s*(?:[\w:*&<>,\s]+?)\s+([A-Za-z_]\w*)\s*\([^;]*\)\s*(?:const\s*)?\{?\s*$"), "function"),
    ],
    "cpp": [
        (re.compile(r"^\s*(?:typedef\s+)?(?:class|struct|union|enum)\s+([A-Za-z_]\w*)"), "class"),
        (re.compile(r"^(?!\s*(?:if|for|while|switch|return|else|do|case|catch)\b)\s*(?:[\w:*&<>,\s]+?)\s+([A-Za-z_]\w*)\s*\([^;]*\)\s*(?:const|noexcept|override)?\s*\{?\s*$"), "function"),
    ],
}

REGEX_SPECS["objc"] = REGEX_SPECS["c"]

CALL_RE = re.compile(r"(?<![\w$])([A-Za-z_$][\w$]*)\s*\(")

IMPORT_RES = {
    "typescript": [
        re.compile(r"""(?:import|export)\s[^'"]*?from\s*['"]([^'"]+)['"]"""),
        re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)"""),
        re.compile(r"""import\(\s*['"]([^'"]+)['"]\s*\)"""),
    ],
    "javascript": [
        re.compile(r"""(?:import|export)\s[^'"]*?from\s*['"]([^'"]+)['"]"""),
        re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)"""),
        re.compile(r"""import\(\s*['"]([^'"]+)['"]\s*\)"""),
    ],
    "rust": [re.compile(r"^\s*(?:pub\s+)?use\s+([^;]+);", re.M)],
    "java": [re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;", re.M)],
    "kotlin": [re.compile(r"^\s*import\s+([\w.]+)\s*;?", re.M)],
    "csharp": [re.compile(r"^\s*using\s+([\w.]+)\s*;", re.M)],
    "scala": [re.compile(r"^\s*import\s+([\w.]+)\s*;?", re.M)],
    "swift": [re.compile(r"^\s*import\s+(\w+)", re.M)],
    "ruby": [re.compile(r"""^\s*require(?:_relative)?\s*['"]([^'"]+)['"]""", re.M)],
    "php": [re.compile(r"""(?:require|include)(?:_once)?\s*\(?\s*['"]([^'"]+)['"]""")],
    "c": [re.compile(r'^\s*#\s*include\s+[<"]([^">]+)[">]', re.M)],
    "cpp": [re.compile(r'^\s*#\s*include\s+[<"]([^">]+)[">]', re.M)],
    "objc": [re.compile(r'^\s*#\s*include\s+[<"]([^">]+)[">]', re.M)],
}

LANG_EXTS = {
    "python": [".py", ".pyi"],
    "typescript": [".ts", ".tsx", ".mts", ".cts", ".js", ".jsx"],
    "javascript": [".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"],
    "go": [".go"],
    "rust": [".rs"],
    "java": [".java"],
    "kotlin": [".kt", ".kts"],
    "csharp": [".cs"],
    "ruby": [".rb"],
    "php": [".php"],
    "swift": [".swift"],
    "scala": [".scala"],
    "lua": [".lua"],
    "c": [".c", ".h"],
    "cpp": [".cpp", ".cc", ".cxx", ".hpp", ".hh"],
    "objc": [".m", ".mm"],
}

# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

USE_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def c(text, code):
    if not USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def die(msg, code=2):
    print(c("error: ", "31") + msg, file=sys.stderr)
    raise SystemExit(code)


def est_tokens(text):
    return max(1, round(len(text) / 4))


def human(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def read_text(path):
    try:
        return path.read_text(encoding="utf-8-sig", errors="ignore")
    except OSError:
        return ""


def sha1_file(path):
    h = hashlib.sha1()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def is_binary(path):
    try:
        with open(path, "rb") as fh:
            return b"\x00" in fh.read(4096)
    except OSError:
        return True


def is_secret(name):
    low = name.lower()
    if low in SECRET_NAMES:
        return True
    if low.startswith(".env") and low not in (".env.example", ".env.sample", ".env.template"):
        return True
    if low.endswith(SECRET_SUFFIXES):
        return True
    # credentials.json / secrets.yaml / id_rsa.pub, but not secret_manager.py.
    stem = low.split(".", 1)[0]
    if stem in SECRET_NAMES:
        return True
    return False


def detect_lang(name):
    low = name.lower()
    if low.startswith(".env"):
        return "config"
    if low in NAME_LANG:
        return NAME_LANG[low]
    ext = Path(name).suffix.lower()
    return EXT_LANG.get(ext)


def compile_excludes(patterns):
    names = set()
    globs = []
    for pat in patterns:
        pat = pat.strip().strip("/")
        if not pat or pat.startswith("#") or pat.startswith("!"):
            continue
        if "/" not in pat and not any(ch in pat for ch in "*?["):
            names.add(pat)
        else:
            globs.append(pat)
    return names, globs


def excluded_by(rel, compiled):
    names, globs = compiled
    parts = rel.split("/")
    if any(part in names for part in parts):
        return True
    for pat in globs:
        if "/" in pat:
            if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, pat + "/**"):
                return True
        elif any(fnmatch.fnmatch(part, pat) for part in parts):
            return True
    return False


def included_by(rel, compiled):
    """Return True when a path opts back into a normally excluded tree.

    Includes are path prefixes or gitignore-style globs. A prefix also matches
    its ancestors so the scanner can walk down to it (``bin`` walks ``.`` and
    ``bin``; ``src/generated`` walks ``src``).
    """
    names, globs = compiled
    parts = rel.split("/")
    if any(part in names for part in parts):
        return True
    for pat in globs:
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, pat + "/**"):
            return True
        if pat.startswith(rel + "/"):
            return True
        if "/" not in pat and any(fnmatch.fnmatch(part, pat) for part in parts):
            return True
    return False


def is_excluded(rel, patterns):
    return excluded_by(rel, compile_excludes(patterns))


def module_of(rel, depth=2):
    parts = rel.split("/")[:-1]
    if not parts:
        return "."
    return "/".join(parts[:depth])


def is_test_file(rel):
    low = rel.lower()
    parts = low.split("/")
    name = parts[-1]
    if any(p in ("test", "tests", "__tests__", "spec", "specs", "testing") for p in parts[:-1]):
        return True
    if name.startswith("test_") or name.endswith("_test.py") or name.endswith("_test.go"):
        return True
    if ".test." in name or ".spec." in name or "_spec." in name:
        return True
    if name.endswith("test.java") or name.endswith("tests.cs") or name.endswith("test.kt"):
        return True
    return False


def git(root, *args, timeout=15):
    try:
        r = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, encoding="utf-8", errors="ignore",
            timeout=timeout,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return ""


def find_root(arg=None):
    if arg:
        return Path(arg).resolve()
    p = Path.cwd().resolve()
    for cand in [p, *p.parents]:
        if (cand / INDEX_DIR / INDEX_NAME).exists():
            return cand
    top = git(p, "rev-parse", "--show-toplevel")
    if top:
        return Path(top).resolve()
    return p


# ---------------------------------------------------------------------------
# Config and scanning
# ---------------------------------------------------------------------------

def load_config(root):
    cfg = {
        "exclude": list(DEFAULT_EXCLUDES),
        "include": [],
        "max_file_kb": 512,
        "module_depth": 2,
        "budget": 3500,
        "entrypoints": [],
        "git_churn": True,
        "map_file": DEFAULT_MAP,
    }
    p = root / CONFIG_NAME
    if p.exists():
        try:
            user = json.loads(p.read_text(encoding="utf-8"))
            for k, v in user.items():
                if k == "exclude":
                    cfg["exclude"] = list(DEFAULT_EXCLUDES) + list(v)
                else:
                    cfg[k] = v
        except Exception:
            pass
    # Fold in simple .gitignore patterns so the atlas does not index junk.
    gi = root / ".gitignore"
    if gi.exists():
        patterns = []
        for line in read_text(gi).splitlines()[:400]:
            line = line.strip()
            if line and not line.startswith("!") and not line.startswith("#"):
                patterns.append(line)
        cfg["exclude"] += patterns
    return cfg


def scan_files(root, cfg):
    out = []
    max_bytes = int(cfg.get("max_file_kb", 512)) * 1024
    excludes = compile_excludes(cfg.get("exclude", []))
    includes = compile_excludes(cfg.get("include", []))
    map_name = (cfg.get("map_file") or DEFAULT_MAP).replace("\\", "/")
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        dirnames[:] = sorted(
            d for d in dirnames
            if (included_by(((rel_dir + "/" + d) if rel_dir != "." else d), includes)
                or not excluded_by(((rel_dir + "/" + d) if rel_dir != "." else d), excludes))
            and not d.startswith(".code-atlas")
            and d not in (".git", ".hg", ".svn")
        )
        for fn in sorted(filenames):
            rel = fn if rel_dir == "." else f"{rel_dir}/{fn}"
            if rel == map_name:
                continue
            if excluded_by(rel, excludes) and not included_by(rel, includes):
                continue
            if fn.lower() in LOCK_NAMES or fn.endswith(".min.js") or fn.endswith(".min.css"):
                continue
            if is_secret(fn):
                continue
            p = Path(dirpath) / fn
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_size > max_bytes:
                continue
            ext = p.suffix.lower()
            if ext in BINARY_EXTS:
                continue
            lang = detect_lang(fn)
            if not lang:
                continue
            if is_binary(p):
                continue
            out.append((rel, p, st, lang))
    return out


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def strip_comments(text, line_comment="//", block=("/*", "*/")):
    """Remove comments while preserving strings and line numbers."""
    out = []
    i = 0
    n = len(text)
    quote = None
    in_block = False
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            if ch == "\n":
                out.append("\n")
            i += 1
            continue
        if quote:
            out.append(ch)
            if ch == "\\":
                if nxt:
                    out.append(nxt)
                    i += 2
                    continue
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if line_comment and text.startswith(line_comment, i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        if block and text.startswith(block[0], i):
            in_block = True
            i += len(block[0])
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def dotted_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return dotted_name(node.func)
    return None


def node_signature(text, node):
    try:
        seg = ast.get_source_segment(text, node) or ""
    except Exception:
        seg = ""
    first = seg.strip().splitlines()[0] if seg.strip() else ""
    return re.sub(r"\s+", " ", first)[:180]


def parse_python(rel, text):
    res = {"imports_raw": [], "from_imports": [], "symbols": [], "errors": []}
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        res["errors"].append(f"{exc.msg} (line {exc.lineno})")
        return res

    exports = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    try:
                        val = ast.literal_eval(node.value)
                        if isinstance(val, (list, tuple)):
                            exports = {str(x) for x in val}
                    except Exception:
                        pass

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                res["imports_raw"].append({"spec": a.name, "alias": a.asname or a.name.split(".")[0]})
        elif isinstance(node, ast.ImportFrom):
            mod = "." * (node.level or 0) + (node.module or "")
            if mod == "":
                mod = "."
            for a in node.names:
                if a.name == "*":
                    continue
                res["from_imports"].append({
                    "spec": mod,
                    "name": a.name,
                    "alias": a.asname or a.name,
                })
            res["imports_raw"].append({"spec": mod, "alias": None})
            if node.module is None and node.level:
                # `from . import sibling` imports a module, not just the package.
                for a in node.names:
                    if a.name != "*":
                        res["imports_raw"].append({"spec": "." * node.level + a.name, "alias": None})

    seen = set()

    def add_func(node, prefix=""):
        qual = prefix + node.name
        sid = f"{rel}::{qual}"
        if sid in seen:
            return
        seen.add(sid)
        calls = []
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                name = dotted_name(sub.func)
                if name:
                    calls.append(name)
        res["symbols"].append({
            "id": sid,
            "name": node.name,
            "qualname": qual,
            "kind": "function",
            "file": rel,
            "line": node.lineno,
            "end_line": getattr(node, "end_lineno", node.lineno),
            "signature": node_signature(text, node),
            "exported": (bool(exports and node.name in exports) if exports is not None else not node.name.startswith("_")) and not prefix,
            "doc": (ast.get_docstring(node) or "").strip().splitlines()[0][:160] if ast.get_docstring(node) else "",
            "calls": calls[:80],
        })

    def visit(node, prefix=""):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add_func(node, prefix)
        elif isinstance(node, ast.ClassDef):
            qual = prefix + node.name
            sid = f"{rel}::{qual}"
            if sid not in seen:
                seen.add(sid)
                res["symbols"].append({
                    "id": sid,
                    "name": node.name,
                    "qualname": qual,
                    "kind": "class",
                    "file": rel,
                    "line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "signature": node_signature(text, node),
                    "exported": bool(exports and node.name in exports) if exports is not None else not node.name.startswith("_"),
                    "doc": (ast.get_docstring(node) or "").strip().splitlines()[0][:160] if ast.get_docstring(node) else "",
                    "calls": [],
                })
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    add_func(child, qual + ".")

    for node in tree.body:
        visit(node)
    return res


def parse_regex(rel, text, lang):
    line_comment = "#" if lang in ("ruby", "shell") else "//"
    clean = strip_comments(text, line_comment=line_comment)
    lines = clean.splitlines()
    specs = REGEX_SPECS.get(lang, [])
    found = []
    seen = set()
    for idx, line in enumerate(lines):
        for pattern, kind in specs:
            m = pattern.match(line)
            if not m:
                continue
            name = m.group(1).split(".")[-1].split(":")[-1]
            if not name or name in KEYWORDS:
                continue
            key = (name, idx)
            if key in seen:
                continue
            seen.add(key)
            exported = ("export " in line or "exports." in line or line.strip().startswith("pub ")
                        or (lang in ("go",) and name[:1].isupper())
                        or bool(re.match(r"^\s*public\b", line)))
            found.append({
                "name": name,
                "qualname": name,
                "kind": kind,
                "line": idx + 1,
                "signature": re.sub(r"\s+", " ", line.strip())[:180],
                "exported": exported,
                "doc": "",
                "calls": [],
            })
    # TypeScript/JavaScript class methods are not caught by the declaration
    # patterns above (they are indented and have no `function` keyword).
    if lang in ("typescript", "javascript"):
        method_rx = re.compile(
            r"^\s{2,}(?:(?:public|private|protected|static|async|readonly|abstract|override|get|set)\s+)*"
            r"([A-Za-z_$][\w$]*)\s*(?:<[^>]+>)?\s*\([^)]*\)\s*(?::\s*[^{]+)?\{"
        )
        existing = {(s["name"], s["line"] - 1) for s in found}
        for cls in [s for s in found if s["kind"] == "class"]:
            depth = 0
            started = False
            for i in range(cls["line"] - 1, len(lines)):
                line = lines[i]
                if not started:
                    if "{" in line:
                        started = True
                        depth += line.count("{") - line.count("}")
                    continue
                if depth <= 0:
                    break
                m = method_rx.match(line)
                if m:
                    name = m.group(1)
                    if name not in KEYWORDS and (name, i) not in existing:
                        found.append({
                            "name": name,
                            "qualname": f"{cls['name']}.{name}",
                            "kind": "function",
                            "line": i + 1,
                            "signature": re.sub(r"\s+", " ", line.strip())[:180],
                            "exported": not line.strip().startswith(("private ", "protected ")),
                            "doc": "",
                            "calls": [],
                        })
                        existing.add((name, i))
                depth += line.count("{") - line.count("}")

    found.sort(key=lambda s: s["line"])
    for i, sym in enumerate(found):
        end = found[i + 1]["line"] - 1 if i + 1 < len(found) else len(lines)
        sym["end_line"] = max(sym["line"], end)
        body = "\n".join(lines[sym["line"] - 1:sym["end_line"]])
        calls = []
        for m in CALL_RE.finditer(body):
            name = m.group(1)
            if name not in KEYWORDS:
                calls.append(name)
        sym["calls"] = list(dict.fromkeys(calls))[:80]
    for sym in found:
        sym["id"] = f"{rel}::{sym['qualname']}"
        sym["file"] = rel
    return {"imports_raw": [], "from_imports": [], "symbols": found, "errors": []}


def parse_text_file(rel, text, lang):
    res = {"imports_raw": [], "from_imports": [], "symbols": [], "errors": []}
    if lang == "python":
        res = parse_python(rel, text)
    elif lang in REGEX_SPECS:
        res = parse_regex(rel, text, lang)

    if lang in IMPORT_RES:
        for rx in IMPORT_RES[lang]:
            for m in rx.finditer(text):
                spec = m.group(1).strip()
                if spec and not spec.startswith("node:"):
                    res["imports_raw"].append({"spec": spec, "alias": None})
    elif lang == "go":
        for block in re.finditer(r"import\s*\((.*?)\)", text, re.S):
            for spec in re.findall(r'"([^"]+)"', block.group(1)):
                res["imports_raw"].append({"spec": spec, "alias": None})
        for m in re.finditer(r'^\s*import\s+(?:[\w.]+\s+)?"([^"]+)"', text, re.M):
            res["imports_raw"].append({"spec": m.group(1), "alias": None})

    # Deduplicate import specs.
    seen = set()
    uniq = []
    for imp in res["imports_raw"]:
        key = (imp.get("spec"), imp.get("alias"))
        if key not in seen:
            seen.add(key)
            uniq.append(imp)
    res["imports_raw"] = uniq
    return res


# ---------------------------------------------------------------------------
# Import resolution
# ---------------------------------------------------------------------------

ALL_CODE_EXTS = {e for exts in LANG_EXTS.values() for e in exts}


def expand_candidates(p, lang):
    p = Path(p)
    exts = LANG_EXTS.get(lang, list(ALL_CODE_EXTS))
    out = []
    if p.suffix.lower() in ALL_CODE_EXTS:
        out.append(p)
    else:
        out.append(p)
        for e in exts:
            out.append(Path(str(p) + e))
        for e in exts:
            out.append(p / ("index" + e))
        out.append(p / "__init__.py")
        out.append(p / "mod.rs")
    return out


def resolve_spec(root, from_rel, spec, files_set, basename_index, lang, symbol_files=None):
    if not spec:
        return None
    spec = spec.strip().strip("'\"")
    spec = spec.split("?")[0].split("#")[0]
    if not spec or spec.startswith("node:"):
        return None
    if spec.startswith("."):
        # Python-style relative import: ".utils", "..models", ".".
        dots = len(spec) - len(spec.lstrip("."))
        rest = spec[dots:].lstrip("/")
        base = Path(from_rel).parent
        for _ in range(max(0, dots - 1)):
            base = base.parent
        p = base / rest if rest else base
        cands = expand_candidates(p, lang)
    else:
        raw = spec.replace("\\", "/")
        cands = []
        if raw.startswith("@/") or raw.startswith("~/"):
            cands += expand_candidates(Path("src") / raw[2:], lang)
            cands += expand_candidates(Path(raw[2:]), lang)
        cands += expand_candidates(Path(raw), lang)
        if lang == "python":
            dotted = Path(raw.replace(".", "/"))
            cands += expand_candidates(dotted, lang)
            cands += expand_candidates(Path("src") / dotted, lang)
        if lang in ("java", "kotlin", "csharp", "scala"):
            dotted = Path(raw.replace(".", "/"))
            cands += expand_candidates(dotted, lang)
            if symbol_files:
                cls = raw.split(".")[-1]
                ids = symbol_files.get(cls)
                if ids and len(ids) == 1:
                    return ids[0]

    for cand in cands:
        norm = str(cand).replace("\\", "/")
        while norm.startswith("./"):
            norm = norm[2:]
        if norm in files_set:
            return norm

    # Bare JS/TS specifiers are npm packages, not local files.  Resolving
    # `require('ejs')` to test/acceptance/ejs.js would invent edges.
    if lang in ("typescript", "javascript") and not spec.startswith((".", "@/", "~/")):
        return None

    # Suffix fallback, e.g. "services.auth" -> "app/services/auth.py".
    # Only accept an unambiguous match: guessing between two same-named
    # files would create false edges in the graph.
    raw = spec.replace("\\", "/").lstrip("./")
    stem = raw.replace(".", "/") if lang == "python" else raw
    matches = []
    for rel in files_set:
        if rel == stem or rel.endswith("/" + stem):
            matches.append(rel)
            continue
        for e in LANG_EXTS.get(lang, []):
            if rel.endswith("/" + stem + e):
                matches.append(rel)
                break
    matches = list(dict.fromkeys(matches))
    if len(matches) == 1:
        return matches[0]

    # Basename fallback (unique only).
    base = Path(spec).name
    if base in basename_index and len(basename_index[base]) == 1:
        return basename_index[base][0]
    for e in LANG_EXTS.get(lang, []):
        if base + e in basename_index and len(basename_index[base + e]) == 1:
            return basename_index[base + e][0]
    return None


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def compute_pagerank(files, edges, damping=0.85, iters=20):
    nodes = list(files)
    n = len(nodes)
    if n == 0:
        return {}
    out = defaultdict(set)
    for e in edges:
        if e.get("k") == "i" and e.get("t") in files:
            out[e["f"]].add(e["t"])
    rank = {x: 1.0 / n for x in nodes}
    for _ in range(iters):
        dangling = sum(rank[x] for x in nodes if not out[x])
        base = (1 - damping) / n + damping * dangling / n
        new = {x: base for x in nodes}
        for x in nodes:
            if out[x]:
                share = damping * rank[x] / len(out[x])
                for y in out[x]:
                    new[y] += share
        rank = new
    return rank


def git_churn(root, days=90):
    out = git(root, "log", f"--since={days} days ago", "--name-only", "--pretty=format:", timeout=25)
    counter = Counter()
    for line in out.splitlines():
        line = line.strip()
        if line and "/" not in line[:1]:
            counter[line] += 1
    return dict(counter)


def detect_test_command(root):
    pkg = root / "package.json"
    if pkg.exists():
        try:
            data = json.loads(read_text(pkg))
            test = (data.get("scripts") or {}).get("test")
            if test:
                return test
        except Exception:
            pass
    if (root / "pytest.ini").exists() or (root / "conftest.py").exists() or (root / "pyproject.toml").exists():
        return "pytest"
    if (root / "go.mod").exists():
        return "go test ./..."
    if (root / "Cargo.toml").exists():
        return "cargo test"
    if (root / "pom.xml").exists():
        return "mvn test"
    if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        return "./gradlew test"
    if (root / "Makefile").exists():
        return "make test (if defined)"
    return ""


def detect_entrypoints(files, rank, cfg, importers):
    wanted = set(cfg.get("entrypoints") or [])
    out = []
    for rel, f in files.items():
        if is_test_file(rel) or f.get("lang") in ("markdown", "config", "sql"):
            continue
        score = 0.0
        reasons = []
        name = Path(rel).name.lower()
        exported = [s for s in f.get("symbols", []) if s.get("exported")]
        if rel in wanted:
            score += 20
            reasons.append("configured entrypoint")
        if name in ENTRY_NAMES:
            score += 8
            reasons.append("conventional name")
        if name == "__init__.py" and len(f.get("imports", [])) >= 3:
            score += 8
            reasons.append("package API surface")
        low_parts = rel.lower().split("/")[:-1]
        if any(p in ("examples", "example", "demo", "demos", "samples", "sample", "benchmarks", "benchmark") for p in low_parts):
            score -= 10
        if rel.count("/") == 0:
            score += 2
        if not importers.get(rel) and f.get("imports"):
            score += 5
            reasons.append("nothing imports it")
        elif not importers.get(rel) and exported and f.get("lang") in ("python", "typescript", "javascript"):
            score += 2
            reasons.append("public surface, nothing imports it")
        if exported:
            score += 1
        score += rank.get(rel, 0) * 20
        if score >= 7:
            out.append({"file": rel, "score": round(score, 2), "reason": ", ".join(reasons) or "highly connected"})
    out.sort(key=lambda x: -x["score"])
    return out[:10]


def build_index(root, cfg, full=False, use_git=True, quiet=False):
    t0 = time.time()
    old = None if full else load_index(root, required=False)
    if old and (old.get("version") != 1 or old.get("parser") != PARSER_VERSION):
        old = None

    scanned = scan_files(root, cfg)
    files = {}
    reused = 0
    parse_errors = []

    for rel, path, st, lang in scanned:
        prev = old["files"].get(rel) if old else None
        if prev and prev.get("parser") == PARSER_VERSION and prev.get("size") == st.st_size and int(prev.get("mtime", 0)) == int(st.st_mtime):
            files[rel] = prev
            reused += 1
            continue
        text = read_text(path)
        parsed = parse_text_file(rel, text, lang)
        if parsed["errors"]:
            parse_errors.extend(f"{rel}: {e}" for e in parsed["errors"])
        files[rel] = {
            "lang": lang,
            "size": st.st_size,
            "mtime": int(st.st_mtime),
            "sha1": sha1_file(path),
            "loc": text.count("\n") + (1 if text else 0),
            "module": module_of(rel, int(cfg.get("module_depth", 2))),
            "imports_raw": parsed["imports_raw"],
            "from_imports": parsed["from_imports"],
            "symbols": parsed["symbols"],
            "errors": parsed["errors"],
            "parser": PARSER_VERSION,
        }

    files_set = set(files)
    basename_index = defaultdict(list)
    for rel in files:
        basename_index[Path(rel).name].append(rel)

    # Symbol name -> unique file, for Java-like imports.
    symbol_files = defaultdict(list)
    for rel, f in files.items():
        for s in f.get("symbols", []):
            symbol_files[s["name"]].append(rel)
    symbol_files = {k: list(dict.fromkeys(v)) for k, v in symbol_files.items()}

    for rel, f in files.items():
        resolved = []
        external = []
        for imp in f.get("imports_raw", []):
            target = resolve_spec(root, rel, imp.get("spec", ""), files_set, basename_index, f["lang"], symbol_files)
            if target and target != rel:
                resolved.append(target)
            elif not target:
                external.append(imp.get("spec", ""))
        f["imports"] = sorted(set(resolved))
        f["external"] = sorted(set(external))[:40]

    # Symbol tables for call resolution.
    by_file_name = defaultdict(lambda: defaultdict(list))
    by_name_global = defaultdict(list)
    for rel, f in files.items():
        for s in f.get("symbols", []):
            by_file_name[rel][s["name"]].append(s["id"])
            by_name_global[s["name"]].append(s["id"])

    edges = set()
    for rel, f in files.items():
        for t in f.get("imports", []):
            edges.add((rel, t, "i"))

    for rel, f in files.items():
        alias_map = {}
        from_map = {}
        for imp in f.get("imports_raw", []):
            if imp.get("alias"):
                alias_map[imp["alias"]] = imp["spec"]
        for fi in f.get("from_imports", []):
            from_map[fi["alias"]] = (fi["spec"], fi["name"])

        for sym in f.get("symbols", []):
            for call in sym.get("calls", [])[:80]:
                target = resolve_call(
                    rel, call, files, files_set, basename_index, by_file_name,
                    by_name_global, alias_map, from_map, f["lang"],
                )
                if target and target != sym["id"]:
                    edges.add((sym["id"], target, "c"))

    edge_list = [{"f": a, "t": b, "k": k} for a, b, k in sorted(edges)]

    rank = compute_pagerank(files, edge_list)

    importers = defaultdict(list)
    for e in edge_list:
        if e["k"] == "i":
            importers[e["t"]].append(e["f"])
    for k in importers:
        importers[k] = sorted(set(importers[k]))

    churn = {}
    if use_git and cfg.get("git_churn", True) and (root / ".git").exists():
        churn = git_churn(root)

    entrypoints = detect_entrypoints(files, rank, cfg, importers)
    langs = Counter(f["lang"] for f in files.values())
    total_loc = sum(f.get("loc", 0) for f in files.values())
    total_symbols = sum(len(f.get("symbols", [])) for f in files.values())
    tests = sum(1 for rel in files if is_test_file(rel))
    test_command = detect_test_command(root)
    if not test_command and tests:
        test_langs = {f["lang"] for rel, f in files.items() if is_test_file(rel)}
        if "python" in test_langs:
            test_command = "pytest"
        elif test_langs & {"typescript", "javascript"}:
            test_command = "npm test"

    head = git(root, "rev-parse", "--short", "HEAD") if (root / ".git").exists() else ""

    index = {
        "version": 1,
        "parser": PARSER_VERSION,
        "tool": VERSION,
        "root": str(root).replace("\\", "/"),
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "git_head": head,
        "config": cfg,
        "files": files,
        "edges": edge_list,
        "pagerank": rank,
        "churn": churn,
        "stats": {
            "files": len(files),
            "loc": total_loc,
            "symbols": total_symbols,
            "edges": len(edge_list),
            "languages": dict(langs.most_common()),
            "tests": tests,
            "parse_errors": len(parse_errors),
            "error_samples": parse_errors[:20],
            "entrypoints": entrypoints,
            "test_command": test_command,
            "reused": reused,
            "build_ms": int((time.time() - t0) * 1000),
        },
    }
    return index


def resolve_call(rel, call, files, files_set, basename_index, by_file_name, by_name_global, alias_map, from_map, lang):
    if not call:
        return None
    parts = call.split(".")
    head = parts[0]
    last = parts[-1]

    # 1) same file
    for name in (call, last, head):
        ids = by_file_name[rel].get(name)
        if ids:
            return ids[0]

    # 2) from X import y
    if head in from_map:
        spec, orig = from_map[head]
        target = None
        if spec.endswith(".") and orig:
            # `from . import sibling` may import the sibling module itself.
            target = resolve_spec(Path("."), rel, spec + orig, files_set, basename_index, lang)
        target = target or resolve_spec(Path("."), rel, spec, files_set, basename_index, lang)
        if target:
            name = ".".join(parts[1:]) or orig
            ids = by_file_name[target].get(name) or by_file_name[target].get(orig)
            if ids:
                return ids[0]

    # 3) module alias: import * as api / import api
    if head in alias_map:
        target = resolve_spec(Path("."), rel, alias_map[head], files_set, basename_index, lang)
        if target:
            name = ".".join(parts[1:]) or head
            ids = by_file_name[target].get(name)
            if ids:
                return ids[0]

    # 4) unique global.  For attribute calls (repo.find, auth.login) prefer
    # methods over top-level functions with the same name.
    ids = list(dict.fromkeys(by_name_global.get(last, [])))
    if "." in call:
        methods = [i for i in ids if "." in i.split("::", 1)[-1]]
        if len(methods) == 1:
            return methods[0]
    if len(ids) == 1:
        return ids[0]
    return None


# ---------------------------------------------------------------------------
# Index persistence
# ---------------------------------------------------------------------------

def index_path(root):
    return root / INDEX_DIR / INDEX_NAME


def load_index(root, required=True):
    p = index_path(root)
    if not p.exists():
        if required:
            die(f"no index at {p}\nRun: python atlas.py build")
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        if required:
            die(f"cannot read index: {exc}\nRun: python atlas.py build --full")
        return None


def write_index(root, index):
    d = root / INDEX_DIR
    d.mkdir(parents=True, exist_ok=True)
    p = d / INDEX_NAME
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, p)


def flatten_symbols(index):
    out = []
    for rel, f in index["files"].items():
        for s in f.get("symbols", []):
            out.append(s)
    return out


def importers_map(index):
    out = defaultdict(set)
    for e in index.get("edges", []):
        if e.get("k") == "i":
            out[e["t"]].add(e["f"])
    return out


# ---------------------------------------------------------------------------
# Rendering: map
# ---------------------------------------------------------------------------

def symbol_degree(index):
    """How often a symbol participates in a call edge (in or out)."""
    degree = Counter()
    for e in index.get("edges", []):
        if e.get("k") == "c":
            degree[e["f"]] += 1
            degree[e["t"]] += 1
    return degree


def module_stats(index):
    mods = defaultdict(lambda: {"files": 0, "loc": 0, "langs": Counter(), "symbols": [],
                                "rank": 0.0, "_scores": []})
    deps = defaultdict(Counter)
    files = index["files"]
    rank = index.get("pagerank", {})
    degree = symbol_degree(index)
    for rel, f in files.items():
        m = f.get("module", ".")
        mods[m]["files"] += 1
        mods[m]["loc"] += f.get("loc", 0)
        mods[m]["langs"][f.get("lang", "?")] += 1
        mods[m]["rank"] += rank.get(rel, 0)
        for s in f.get("symbols", []):
            if s.get("exported"):
                mods[m]["_scores"].append((degree.get(s["id"], 0), s["name"]))
        for t in f.get("imports", []):
            tm = files.get(t, {}).get("module")
            if tm and tm != m:
                deps[m][tm] += 1
    for data in mods.values():
        seen = set()
        picked = []
        for _, name in sorted(data["_scores"], key=lambda x: (-x[0], x[1])):
            if name not in seen:
                seen.add(name)
                picked.append(name)
            if len(picked) >= 6:
                break
        data["symbols"] = picked
        del data["_scores"]
    return mods, deps


def is_example_module(name):
    parts = name.lower().split("/")
    return any(p in ("examples", "example", "demo", "demos", "samples", "sample",
                     "benchmarks", "benchmark") for p in parts)


def module_priority(name, data):
    parts = name.lower().split("/")
    if any(p in ("test", "tests", "__tests__", "spec", "specs", "docs", "doc", "examples", "example", "demo", "demos") for p in parts):
        return data["loc"] * 0.15 + data["files"]
    return data["loc"] + data["files"] * 5


def render_map(index, budget=3500):
    stats = index["stats"]
    files = index["files"]
    rank = index.get("pagerank", {})
    mods, deps = module_stats(index)
    ordered_mods = sorted(mods.items(), key=lambda kv: -module_priority(kv[0], kv[1]))
    # Examples are useful to browse but should not crowd the architecture map.
    primary_mods = [(m, d) for m, d in ordered_mods if not is_example_module(m)]
    if primary_mods:
        ordered_mods = primary_mods
    importers = importers_map(index)
    langs = stats.get("languages", {})
    lang_line = " · ".join(f"{k} {v}" for k, v in list(langs.items())[:6])

    def compose(max_mods, max_hot, max_start):
        lines = []
        lines.append("# CodeAtlas")
        lines.append("")
        lines.append(f"> `{Path(index['root']).name}` · {stats['files']} files · {human(stats['loc'])} LOC · {stats['symbols']} symbols")
        lines.append(f"> Generated {index.get('generated','')} · commit `{index.get('git_head') or 'n/a'}` · CodeAtlas v{index.get('tool', VERSION)}")
        lines.append(f"> Languages: {lang_line or 'n/a'}")
        # Only promise a repo-relative command when this repository ships the engine.
        atlas_cmd = "python scripts/atlas.py" if (Path(index["root"]) / "scripts" / "atlas.py").exists() else "atlas"
        lines.append(f"> Refresh: `{atlas_cmd} update` · Query: `{atlas_cmd} where <symbol>`")
        lines.append("")
        lines.append("## Start here")
        lines.append("")
        lines.append("| File | Why |")
        lines.append("|---|---|")
        for ep in stats.get("entrypoints", [])[:max_start]:
            lines.append(f"| `{ep['file']}` | {ep['reason']} |")
        if not stats.get("entrypoints"):
            lines.append("| — | no obvious entrypoint; start from the largest module below |")
        lines.append("")
        lines.append("## Modules")
        lines.append("")
        lines.append("| Module | Files | LOC | Depends on | Key symbols |")
        lines.append("|---|---:|---:|---|---|")
        for m, data in ordered_mods[:max_mods]:
            dep_txt = ", ".join(f"{d} ({n})" for d, n in deps[m].most_common(3)) or "—"
            syms = ", ".join(data["symbols"][:3]) or "—"
            lines.append(f"| `{m}` | {data['files']} | {human(data['loc'])} | {dep_txt} | {syms} |")
        if len(ordered_mods) > max_mods:
            lines.append(f"| _… {len(ordered_mods) - max_mods} more modules_ | | | | |")
        lines.append("")
        lines.append("## Hot files")
        lines.append("")
        lines.append("| File | LOC | Importers |")
        lines.append("|---|---:|---:|")
        hot = sorted(
            files.items(),
            key=lambda kv: (
                kv[1].get("lang") in CODE_LANGS,
                rank.get(kv[0], 0),
                kv[1].get("loc", 0),
            ),
            reverse=True,
        )[:max_hot]
        for rel, f in hot:
            lines.append(f"| `{rel}` | {human(f.get('loc',0))} | {len(importers.get(rel,()))} |")
        lines.append("")
        lines.append("## Tests")
        lines.append("")
        cmd = stats.get("test_command") or "(not detected)"
        lines.append(f"- {stats.get('tests',0)} test files · suggested command: `{cmd}`")
        lines.append("")
        lines.append("## Query recipes")
        lines.append("")
        lines.append("- Find a symbol: `atlas where <name>`")
        lines.append("- What breaks: `atlas impact <file|symbol>`")
        lines.append("- How A reaches B: `atlas path <fileA> <fileB>`")
        lines.append("- Related files under a budget: `atlas pack <area> --budget 8000`")
        lines.append("- Visual map: open `.code-atlas/atlas.html`")
        lines.append("")
        lines.append(f"_~{est_tokens(chr(10).join(lines))} tokens · index: `.code-atlas/index.json`_")
        return "\n".join(lines)

    attempts = [(24, 8, 8), (18, 6, 6), (12, 4, 5), (8, 3, 4), (6, 0, 3)]
    text = ""
    for attempt in attempts:
        text = compose(*attempt)
        if est_tokens(text) <= budget:
            return text
    return text


# ---------------------------------------------------------------------------
# Rendering: Mermaid + HTML
# ---------------------------------------------------------------------------

def esc_mermaid(s):
    return str(s).replace('"', "'").replace("\n", " ")


def render_mermaid(index, mode="modules", top=40):
    files = index["files"]
    rank = index.get("pagerank", {})
    lines = ["flowchart LR"]
    if mode == "files":
        selected = [rel for rel, _ in sorted(files.items(), key=lambda kv: -rank.get(kv[0], 0))[:top]]
        ids = {rel: f"f{i}" for i, rel in enumerate(selected)}
        for rel in selected:
            f = files[rel]
            lines.append(f'  {ids[rel]}["{esc_mermaid(rel)}<br/>{human(f.get("loc",0))} LOC"]')
        for rel in selected:
            for t in files[rel].get("imports", []):
                if t in ids:
                    lines.append(f"  {ids[rel]} --> {ids[t]}")
    else:
        mods, deps = module_stats(index)
        ordered = sorted(mods.items(), key=lambda kv: -module_priority(kv[0], kv[1]))
        ids = {m: f"m{i}" for i, (m, _) in enumerate(ordered)}
        for m, data in ordered:
            lines.append(f'  {ids[m]}["{esc_mermaid(m)}<br/>{data["files"]} files · {human(data["loc"])} LOC"]')
        for m, dd in deps.items():
            for t, w in dd.most_common(12):
                if m in ids and t in ids:
                    lines.append(f"  {ids[m]} -->|{w}| {ids[t]}")
    return "\n".join(lines) + "\n"


def html_data(index, top=80):
    files = index["files"]
    rank = index.get("pagerank", {})
    mods, deps = module_stats(index)
    all_edges = index.get("edges", [])

    # Aggregate import and cross-file call edges into one relationship graph.
    # Imports stay file-to-file; calls are symbol-to-symbol and must be folded
    # back to their owning files before they can be drawn.
    rel_weight = Counter()
    rel_kind = {}
    call_counts = Counter()
    for e in all_edges:
        kind = e.get("k")
        if kind == "c":
            src = (e.get("f") or "").split("::", 1)[0]
            dst = (e.get("t") or "").split("::", 1)[0]
            call_counts[src] += 1
        elif kind == "i":
            src, dst = e.get("f"), e.get("t")
        else:
            continue
        if not src or not dst or src == dst:
            continue
        if src not in files or dst not in files:
            continue
        rel_weight[(src, dst)] += 1
        if kind == "i":
            rel_kind[(src, dst)] = "i"
        else:
            rel_kind.setdefault((src, dst), "c")

    def mod_of(rel):
        return files[rel].get("module", ".")

    def mod_rank(m):
        return sum(rank.get(rel, 0) for rel, f in files.items() if f.get("module") == m)

    module_nodes = []
    for m, data in sorted(mods.items(), key=lambda kv: -module_priority(kv[0], kv[1])):
        module_nodes.append({
            "id": m,
            "label": m,
            "files": data["files"],
            "loc": data["loc"],
            "langs": dict(data["langs"]),
            "symbols": data["symbols"][:8],
            "rank": round(mod_rank(m), 6),
            "deps": [t for t, _ in deps[m].most_common(8)],
        })

    mod_weight = Counter()
    mod_kind = {}
    for (src, dst), w in rel_weight.items():
        sm, dm = mod_of(src), mod_of(dst)
        if sm == dm:
            continue
        mod_weight[(sm, dm)] += w
        if rel_kind[(src, dst)] == "i":
            mod_kind[(sm, dm)] = "i"
        else:
            mod_kind.setdefault((sm, dm), "c")
    module_links = [
        {"s": m, "t": t, "w": w, "k": mod_kind.get((m, t), "i")}
        for (m, t), w in sorted(mod_weight.items())
        if m in mods and t in mods
    ]

    # File view is a code map: docs/config nodes are useful in the module
    # graph and search, but as isolated dots they add noise.  Keep connected
    # code files when there are enough of them so fitView can zoom in.
    pool = {rel: f for rel, f in files.items() if f.get("lang") in CODE_LANGS}
    edge_files = {rel for pair in rel_weight for rel in pair}
    connected = {rel: f for rel, f in pool.items() if rel in edge_files}
    if len(connected) >= 8:
        pool = connected
    if not pool:
        pool = files
    selected = [
        rel
        for rel, _ in sorted(
            pool.items(),
            key=lambda kv: (
                kv[1].get("lang") in CODE_LANGS,
                rank.get(kv[0], 0),
                kv[1].get("loc", 0),
            ),
            reverse=True,
        )[:top]
    ]
    sel_set = set(selected)
    file_nodes = []
    for rel in selected:
        f = files[rel]
        file_nodes.append({
            "id": rel,
            "label": Path(rel).name,
            "path": rel,
            "module": f.get("module", "."),
            "loc": f.get("loc", 0),
            "lang": f.get("lang", "?"),
            "rank": round(rank.get(rel, 0), 6),
            "tests": is_test_file(rel),
            "calls": call_counts.get(rel, 0),
            "symbols": [s["name"] for s in f.get("symbols", []) if s.get("exported")][:10],
            "deps": [t for t in f.get("imports", []) if t in sel_set][:10],
        })
    file_links = [
        {"s": src, "t": dst, "w": w, "k": rel_kind.get((src, dst), "i")}
        for (src, dst), w in sorted(rel_weight.items())
        if src in sel_set and dst in sel_set
    ]

    stats = index["stats"]
    return {
        "meta": {
            "repo": Path(index["root"]).name,
            "generated": index.get("generated", ""),
            "commit": index.get("git_head") or "n/a",
            "files": stats.get("files", 0),
            "loc": stats.get("loc", 0),
            "symbols": stats.get("symbols", 0),
            "edges": stats.get("edges", 0),
            "languages": stats.get("languages", {}),
            "tool": index.get("tool", VERSION),
        },
        "modules": {"nodes": module_nodes, "links": module_links},
        "files": {"nodes": file_nodes, "links": file_links},
    }


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CodeAtlas</title>
<style>
:root{
  --shell:#f1efe8;
  --card:#fffdf9;
  --paper:#faf8f2;
  --ink:#17181c;
  --ink-soft:#525965;
  --muted:#686e79;
  --line:#e6e1d7;
  --line-strong:#d2cbbb;
  --accent:#ff5a36;
  --accent-ui:#bf3a1c;
  --focus:#315bff;
  --stage:#0d0f13;
  --on-stage:#e9ebef;
  --on-stage-muted:#8b93a1;
  --sans:"Segoe UI Variable Display","Segoe UI",system-ui,-apple-system,"Helvetica Neue",sans-serif;
  --mono:"Cascadia Code","SFMono-Regular",Consolas,"Liberation Mono",monospace;
}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--shell);color:var(--ink);font:14px/1.5 var(--sans);overflow:hidden;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
button,input{font:inherit;color:inherit}
button{background:none;border:0;padding:0;cursor:pointer}
button:focus-visible,input:focus-visible,a:focus-visible{outline:2px solid var(--focus);outline-offset:2px;border-radius:4px}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
#app{display:flex;height:100vh;height:100dvh;min-height:100vh;background:var(--shell)}
#stage{position:relative;flex:1;min-width:0;display:flex;flex-direction:column;background:var(--stage)}
.topbar{display:flex;align-items:center;gap:18px;height:62px;padding:0 22px;border-bottom:1px solid var(--line);background:linear-gradient(180deg,#fffefa 0%,#fbf9f3 100%);position:relative;z-index:3;flex:0 0 auto}
.topbar::before{content:"";position:absolute;left:0;top:0;right:0;height:2px;background:linear-gradient(90deg,var(--accent) 0,rgba(255,90,54,.16) 9%,rgba(255,90,54,0) 24%);pointer-events:none}
.brand{display:flex;align-items:center;gap:10px;flex:0 0 auto;color:var(--ink)}
.brand-mark{width:22px;height:19px;color:var(--accent);display:grid;place-items:center;filter:drop-shadow(0 2px 6px rgba(255,90,54,.26));flex:0 0 auto}
.brand-mark svg{display:block;width:22px;height:19px}
.brand-word{font:700 12px/1 var(--mono);letter-spacing:.15em;text-transform:uppercase}
.brand-word .slash{color:var(--accent);padding:0 1px}
.brand:hover .brand-word{color:var(--accent-ui)}
.repo-block{display:flex;flex-direction:column;gap:2px;min-width:0;padding-left:16px;border-left:1px solid var(--line);max-width:248px}
.repo-name{font-weight:650;font-size:13px;line-height:1.3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.repo-meta{font:9.5px/1.5 var(--mono);color:var(--muted);white-space:nowrap;overflow:hidden;display:flex;align-items:center;gap:5px}
.repo-meta .sep{opacity:.42}
.repo-commit{color:var(--ink-soft);background:#f0ede5;border:1px solid var(--line);border-radius:4px;padding:0 4px;font-size:9px;line-height:1.5}
.controls{display:flex;align-items:center;gap:12px;margin-left:auto;min-width:0}
.search{display:flex;align-items:center;gap:8px;height:36px;padding:0 9px 0 11px;background:#f3f0e8;border:1px solid rgba(230,225,215,.7);border-radius:9px;min-width:250px;max-width:360px;flex:1 1 290px;box-shadow:inset 0 1px 2px rgba(20,22,28,.03);transition:background .15s ease,border-color .15s ease,box-shadow .15s ease}
.search svg{opacity:.5;flex:0 0 auto}
.search input{border:0;background:transparent;padding:1px 0;width:100%;min-width:0;font-size:12.5px;outline:none}
.search input::placeholder{color:var(--muted)}
.search:focus-within{background:#fff;border-color:var(--accent);box-shadow:0 0 0 3px rgba(255,90,54,.12),0 1px 2px rgba(20,22,28,.04)}
.search-count{font:10px/1 var(--mono);color:var(--accent-ui);white-space:nowrap}
.kbd{font:10px/1 var(--mono);color:var(--muted);border:1px solid var(--line-strong);border-radius:4px;padding:2px 5px;background:#fffdf9;flex:0 0 auto;transition:opacity .12s ease}
.search:focus-within .kbd{opacity:0}
.tabs{display:flex;align-items:center;gap:2px;background:#efebe2;border:1px solid var(--line);border-radius:9px;padding:3px;flex:0 0 auto}
.tab{font-size:12px;font-weight:600;color:var(--muted);padding:6px 11px;border-radius:6px;display:flex;gap:6px;align-items:center;white-space:nowrap;transition:background .15s ease,color .15s ease,box-shadow .15s ease}
.tab .n{font:9.5px/1 var(--mono);color:var(--muted);background:rgba(21,23,28,.05);border-radius:4px;padding:2px 4px}
.tab:hover{color:var(--ink);background:rgba(255,255,255,.56)}
.tab[aria-pressed="true"]{background:#191b20;color:#fff;box-shadow:0 2px 7px rgba(20,22,28,.18)}
.tab[aria-pressed="true"] .n{background:rgba(255,255,255,.13);color:#ffb6a4}
.textbtn{display:inline-flex;align-items:center;gap:6px;height:34px;padding:0 10px;font-size:11.5px;font-weight:600;color:var(--muted);border:1px solid var(--line);border-radius:8px;background:rgba(255,255,255,.38);white-space:nowrap;flex:0 0 auto;transition:background .15s ease,color .15s ease,border-color .15s ease,box-shadow .15s ease}
.textbtn svg{opacity:.68;flex:0 0 auto;transition:opacity .15s ease,color .15s ease}
.textbtn:hover{background:#fff;border-color:var(--line-strong);color:var(--ink);box-shadow:0 1px 2px rgba(20,22,28,.03)}
.textbtn:hover svg{opacity:1}
.textbtn[aria-pressed="true"]{color:var(--ink);background:#fffdf9;border-color:var(--line-strong);box-shadow:0 1px 2px rgba(20,22,28,.04)}
.textbtn[aria-pressed="true"] svg{color:var(--accent-ui);opacity:1}
#map{position:relative;flex:1;min-height:0;overflow:hidden;background:var(--stage)}
#graph{display:block;width:100%;height:100%;cursor:grab;touch-action:none}
#graph.dragging{cursor:grabbing}
.platefoot{display:flex;align-items:center;gap:16px;min-height:40px;padding:0 20px;border-top:1px solid rgba(255,255,255,.08);background:var(--stage);color:var(--on-stage-muted);flex:0 0 auto}
.map-note{margin:0;font:10px/1.5 var(--mono);color:var(--on-stage-muted);letter-spacing:.01em;min-width:0;flex:1 1 auto}
.map-note strong{color:var(--on-stage);font-weight:600}
.foot-key{color:#7d8798}
.hint{font:9.5px/1.4 var(--mono);color:#7d8798;white-space:nowrap;flex:0 0 auto}
.zoom{display:flex;border:1px solid rgba(255,255,255,.14);border-radius:5px;overflow:hidden;background:rgba(255,255,255,.02);flex:0 0 auto}
.zoom button{width:32px;height:30px;display:grid;place-items:center;font-size:13px;line-height:1;color:var(--on-stage-muted)}
.zoom button+button{border-left:1px solid rgba(255,255,255,.1)}
.zoom button:hover{background:rgba(255,255,255,.08);color:#fff}
#tooltip{position:absolute;z-index:6;pointer-events:none;max-width:290px;padding:8px 10px;background:#fff;border:1px solid var(--line);border-radius:8px;box-shadow:0 14px 34px rgba(0,0,0,.34);opacity:0;transform:translateY(2px);transition:opacity .12s ease,transform .12s ease}
#tooltip.show{opacity:1;transform:none}
.tip-name{font:600 12px/1.35 var(--sans);overflow-wrap:anywhere;color:var(--ink)}
.tip-meta{font:10px/1.45 var(--mono);color:var(--muted);overflow-wrap:anywhere}
#empty{position:absolute;inset:0;display:grid;place-content:center;gap:6px;text-align:center;padding:30px;pointer-events:none}
#empty[hidden]{display:none}
#empty p{margin:0;color:#b9c0cc}
#empty .fine{margin-top:4px;color:#788190}
#panel{width:376px;flex:0 0 376px;border-left:1px solid var(--line);background:radial-gradient(120% 42% at 100% 0,rgba(255,90,54,.05),transparent 60%),linear-gradient(180deg,#fbf9f3 0%,#f7f4ec 100%);overflow-y:auto;padding:26px 26px 42px;scrollbar-width:thin;scrollbar-color:var(--line-strong) transparent}
#panel::-webkit-scrollbar{width:10px}
#panel::-webkit-scrollbar-thumb{background:var(--line-strong);border:3px solid #faf8f2;border-radius:10px}
.panel-kicker{display:flex;justify-content:space-between;align-items:center;gap:12px;font:9.5px/1.2 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.panel-kicker .kicker-label{display:flex;align-items:center;gap:7px}
.kicker-dot{width:6px;height:6px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 3px rgba(255,90,54,.10);flex:0 0 auto}
.panel-kicker .v{font:9px/1 var(--mono);letter-spacing:.02em;text-transform:none;color:var(--accent-ui);background:rgba(255,90,54,.07);border:1px solid rgba(191,58,28,.16);padding:3px 7px;border-radius:999px}
.panel-title{font:650 30px/1.05 var(--sans);letter-spacing:-.032em;margin:13px 0 8px;word-break:break-word}
.panel-lede{margin:0 0 20px;color:var(--ink-soft);font-size:13px;line-height:1.65}
.panel-path{font:11px/1.5 var(--mono);color:var(--muted);word-break:break-all;margin:-2px 0 15px}
.rule{height:1px;background:var(--line);margin:18px 0}
.stats-card{border:1px solid var(--line);border-radius:13px;background:rgba(255,255,255,.78);overflow:hidden;box-shadow:0 1px 2px rgba(20,22,28,.035)}
.stats-head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 13px;border-bottom:1px solid var(--line);background:linear-gradient(90deg,rgba(255,90,54,.05),rgba(91,134,214,.045))}
.stats-head .label{font:9px/1.2 var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.stats-chip{font:9px/1 var(--mono);color:var(--accent-ui);background:rgba(255,90,54,.07);border:1px solid rgba(191,58,28,.15);padding:3px 7px;border-radius:999px;white-space:nowrap}
.facts{display:grid;grid-template-columns:1fr 1fr;gap:0;margin:0;border:1px solid var(--line);border-radius:12px;background:rgba(255,255,255,.72);overflow:hidden;box-shadow:0 1px 2px rgba(20,22,28,.03)}
.facts div{padding:11px 13px;min-width:0}
.facts div:nth-child(odd){border-right:1px solid var(--line)}
.facts div:nth-child(-n+2){border-bottom:1px solid var(--line)}
.facts dt{font:9px/1.2 var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin:0 0 3px}
.facts dd{margin:0;font:650 18px/1.2 var(--sans);color:var(--ink);overflow-wrap:anywhere;font-variant-numeric:tabular-nums}
.stats-card .facts{border:0;border-radius:0;background:transparent;box-shadow:none}
.section-title{font:9.5px/1.2 var(--mono);letter-spacing:.13em;text-transform:uppercase;color:var(--muted);margin:24px 0 10px;display:flex;align-items:center;justify-content:space-between;gap:8px}
.section-title > span:first-child{display:flex;align-items:center;gap:7px}
.section-title > span:first-child::before{content:"";width:10px;height:1px;background:var(--accent);opacity:.6;flex:0 0 auto}
.section-title .count{font:9px/1 var(--mono);letter-spacing:.02em;color:var(--accent-ui);background:rgba(255,90,54,.06);border:1px solid rgba(191,58,28,.12);border-radius:999px;padding:2px 6px}
.legend-card,.lang-card{border:1px solid var(--line);border-radius:12px;background:rgba(255,255,255,.72);padding:12px 13px;box-shadow:0 1px 2px rgba(20,22,28,.03)}
.legend-list{list-style:none;margin:0;padding:0;display:grid;gap:11px}
.legend-list li{display:grid;grid-template-columns:28px minmax(0,1fr);gap:11px;align-items:start;font-size:12px;line-height:1.45;color:var(--ink-soft)}
.legend-list b{color:var(--ink);font-weight:600}
.swatch{width:28px;height:20px;border-radius:5px;background:#11141a;display:grid;place-items:center;justify-self:start;margin-top:1px;box-shadow:inset 0 0 0 1px rgba(255,255,255,.06),inset 0 1px 0 rgba(255,255,255,.05)}
.swatch svg{display:block;width:28px;height:20px}
.langs{list-style:none;margin:0;padding:0;display:grid;gap:2px}
.langs li{display:grid;grid-template-columns:8px minmax(0,1fr) 46px auto;align-items:center;gap:9px;font-size:12px;color:var(--ink-soft);padding:3px 0}
.langs .dot{width:7px;height:7px;border-radius:50%;background:var(--c);box-shadow:0 0 0 2px rgba(21,23,28,.035)}
.langs .name{min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.langs .bar{height:3px;border-radius:99px;background:#ece7dc;overflow:hidden}
.langs .bar i{display:block;height:100%;border-radius:inherit;background:var(--c);opacity:.9}
.langs .n{font:9.5px/1 var(--mono);color:var(--muted);text-align:right;min-width:28px}
.index-meta{margin:24px 0 0;padding-top:14px;border-top:1px solid var(--line);display:flex;flex-wrap:wrap;align-items:center;gap:5px 7px;font:9.5px/1.6 var(--mono);color:var(--muted)}
.index-meta .meta-sep{opacity:.4}
.index-meta .commit{color:var(--ink-soft);background:#efebe2;border:1px solid var(--line);border-radius:4px;padding:0 4px}
.index-meta .ver{color:var(--accent-ui)}
.fine{margin:22px 0 0;font:10px/1.5 var(--mono);color:var(--muted);word-break:break-word}
.back{display:inline-flex;align-items:center;gap:6px;font:10.5px/1.2 var(--mono);color:var(--muted);margin:0 0 18px;padding:4px 10px 4px 8px;border:1px solid var(--line);border-radius:999px;background:rgba(255,255,255,.62);transition:background .12s ease,border-color .12s ease,color .12s ease}
.back:hover{color:var(--ink);background:#fff;border-color:var(--line-strong)}
.crumb{font:9.5px/1.2 var(--mono);letter-spacing:.13em;text-transform:uppercase;color:var(--accent-ui);margin:0 0 8px}
.rows{list-style:none;margin:0;padding:0}
.rows li{margin:0 0 5px}
.row{display:flex;align-items:baseline;justify-content:space-between;gap:12px;width:100%;padding:9px 11px;text-align:left;border:1px solid var(--line);border-radius:9px;background:rgba(255,255,255,.72);transition:background .12s ease,border-color .12s ease,box-shadow .12s ease}
.row:hover{border-color:var(--line-strong);background:#fff;box-shadow:0 1px 3px rgba(20,22,28,.04)}
.row:hover .row-name{color:var(--accent-ui)}
.row-name{font-size:12.5px;color:var(--ink);min-width:0;overflow-wrap:anywhere}
.row-meta{font:10px/1.3 var(--mono);color:var(--muted);white-space:nowrap;flex:0 0 auto}
.row-kind{font:9px/1.2 var(--mono);text-transform:uppercase;letter-spacing:.08em;color:var(--accent-ui);border:1px solid rgba(207,69,37,.25);background:rgba(255,90,54,.07);padding:2px 5px;border-radius:4px;margin-right:7px}
.symbols{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:4px 12px}
.symbols button{font:11px/1.8 var(--mono);color:var(--ink-soft);border-bottom:1px solid transparent;text-align:left;overflow-wrap:anywhere}
.symbols button:hover{color:var(--accent-ui);border-bottom-color:var(--accent-ui)}
.empty-note{margin:0;font-size:12px;line-height:1.5;color:var(--muted);font-style:italic}
@media (max-width:1400px){.repo-block{display:none}}
@media (max-width:1120px){
  #panel{width:320px;flex-basis:320px;padding:22px 20px 30px}
  .search{min-width:220px;flex-basis:240px}
  .topbar{gap:14px;padding:0 18px}
  .hint{display:none}
  .textbtn{width:34px;height:34px;padding:0;justify-content:center}
  .btn-label{display:none}
  .panel-lede{font-size:12.5px;line-height:1.55;margin-bottom:16px}
  .section-title{margin:18px 0 8px}
  .legend-card,.lang-card{padding:10px 12px}
  .legend-list{gap:8px}
  .langs li{padding:2px 0}
  .stats-head{padding:7px 12px}
  .facts div{padding:9px 12px}
  .index-meta{margin-top:16px;padding-top:10px}
}
@media (max-width:860px){
  html,body{height:auto;min-height:100%}
  body{overflow:auto}
  #app{display:block;height:auto;min-height:100dvh}
  #stage{height:66vh;height:66dvh;min-height:430px}
  .topbar{height:auto;flex-wrap:wrap;gap:12px 16px;padding:14px 18px}
  .controls{margin-left:0;width:100%;flex-wrap:wrap;gap:10px 12px}
  .search{flex:1 1 100%;max-width:none;order:3;min-width:0}
  .kbd{display:none}
  .tabs{order:1}
  .textbtn{order:2}
  #panel{width:auto;border-left:0;border-top:1px solid var(--line);padding:22px 20px 40px;overflow:visible}
  .platefoot{padding:0 18px;min-height:48px}
  .tab{padding:8px 11px}
  .textbtn{padding:9px 10px}
  .search{height:38px}
  .zoom button{width:38px;height:34px}
}
@media (max-width:620px){.foot-key{display:none}}
@media (max-width:380px){
  .map-note{font-size:9px}
  .platefoot{gap:10px}
  .zoom button{width:32px;height:30px}
}
@media (max-width:480px){
  #stage{height:64vh;height:64dvh;min-height:400px}
  .brand-word{font-size:11px}
  .tab{font-size:11.5px;padding:6px 8px}
  .textbtn{width:34px;height:34px;padding:0;justify-content:center}
  .btn-label{display:none}
  .panel-title{font-size:24px}
  .facts dd{font-size:16px}
}
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{transition-duration:.001ms!important;animation-duration:.001ms!important;animation-iteration-count:1!important}
}
</style>
</head>
<body>
<div id="app">
  <main id="stage" aria-label="CodeAtlas interactive map">
    <div class="topbar">
      <button class="brand" id="brand" type="button" aria-label="Return to the atlas overview">
        <span class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 24 20" fill="none">
            <path d="M3.2 16.4 8.6 4.2l5.1 9.2 6.8-7.5" stroke="currentColor" stroke-width="1.15" stroke-linecap="round" stroke-linejoin="round" opacity=".72"/>
            <circle cx="3.2" cy="16.4" r="1.8" fill="currentColor"/>
            <circle cx="8.6" cy="4.2" r="1.3" fill="currentColor"/>
            <circle cx="13.7" cy="13.4" r="1.8" fill="currentColor"/>
            <circle cx="20.5" cy="5.9" r="1.3" fill="currentColor"/>
          </svg>
        </span>
        <span class="brand-word">Code<span class="slash">/</span>Atlas</span>
      </button>
      <div class="repo-block">
        <span class="repo-name" id="repo"></span>
        <span class="repo-meta" id="repo-meta"></span>
      </div>
      <div class="controls">
        <label class="search" for="search">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"></circle><path d="m15.5 15.5 4.5 4.5"></path></svg>
          <input id="search" type="search" placeholder="Search files or symbols" autocomplete="off" spellcheck="false" aria-label="Search files, modules, and symbols">
          <span class="kbd" aria-hidden="true">/</span>
          <span class="search-count" id="search-count" aria-live="polite"></span>
        </label>
        <div class="tabs" role="group" aria-label="Map view">
          <button class="tab" id="mode-modules" type="button" aria-pressed="true">Modules <span class="n" id="n-modules"></span></button>
          <button class="tab" id="mode-files" type="button" aria-pressed="false">Files <span class="n" id="n-files"></span></button>
        </div>
        <button class="textbtn" id="labels" type="button" aria-pressed="true" title="Toggle labels" aria-label="Toggle labels">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" aria-hidden="true"><path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8Z"/><circle cx="7.5" cy="7.5" r="1.4"/></svg>
          <span class="btn-label">Labels</span>
        </button>
        <button class="textbtn" id="reset" type="button" title="Fit map to view" aria-label="Fit map to view">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/></svg>
          <span class="btn-label">Fit</span>
        </button>
      </div>
    </div>
    <div id="map">
      <canvas id="graph" role="img" aria-label="Code dependency map"></canvas>
      <div id="empty" hidden>
        <p>No code files to map in this view.</p>
        <p class="fine">Try Modules, or add code files to the repository.</p>
      </div>
      <div id="tooltip" role="status"></div>
    </div>
    <div class="platefoot">
      <p class="map-note" id="map-note"></p>
      <span class="hint">drag to pan · scroll to zoom · hover to trace · click to inspect</span>
      <div class="zoom" role="group" aria-label="Map zoom">
        <button id="zoom-out" type="button" aria-label="Zoom out">−</button>
        <button id="zoom-in" type="button" aria-label="Zoom in">+</button>
        <button id="zoom-fit" type="button" aria-label="Fit map to view">⌂</button>
      </div>
    </div>
  </main>
  <aside id="panel" aria-label="Atlas index"></aside>
  <div id="live" class="sr-only" aria-live="polite"></div>
</div>
<script>
const DATA = /*__ATLAS_DATA__*/null;
const START_MODE = "__START_MODE__";
const STAGE = '#0d0f13';
const INK = '#e9ebef';
const ACCENT = '#ff5a36';
const WHITE = '#ffffff';
const FONT_UI = '600 12px "Segoe UI",system-ui,sans-serif';
const FONT_FILE = '600 11.5px "Segoe UI",system-ui,sans-serif';
const LANG = {"python":"#4d8fba","typescript":"#5b86d6","javascript":"#d4a53a","go":"#47b3c0","rust":"#d97b52","java":"#d98a52","kotlin":"#9b7fd4","csharp":"#6fae6f","ruby":"#d9646f","php":"#7d8fd0","c":"#8a9690","cpp":"#d4708a","swift":"#e0704c","scala":"#d95a6a","lua":"#6e94d6","shell":"#8fa85a","markdown":"#a9927a","config":"#9a9c94","sql":"#d4934a"};

const canvas = document.getElementById('graph');
const ctx = canvas.getContext('2d');
const panel = document.getElementById('panel');
const tooltip = document.getElementById('tooltip');
const search = document.getElementById('search');
const mapNote = document.getElementById('map-note');
const emptyBox = document.getElementById('empty');
const live = document.getElementById('live');
const REDUCED = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
const state = {
  mode: 'modules', nodes: [], links: [], byId: new Map(), moduleHub: new Map(),
  view: {x:0,y:0,k:1}, selected: null, hover: null, labels: true, query: '',
  w: 0, h: 0, userMoved: false, topFiles: new Set(), dupLabels: new Set(), shownByModule: new Map(), enterAt: 0
};
const DUST = Array.from({length:30}, (_,i)=>{
  const s = seedFrom('dust:'+i);
  return {x:(s%997)/997, y:((s>>>10)%991)/991, r:.55+((s>>>20)%100)/100*1.25,
          a:.022+((s>>>7)%60)/100*.05, sp:.35+((s>>>16)%100)/100*.9};
});

const fmt = n => n>=1e6?(n/1e6).toFixed(1)+'M':n>=1e3?(n/1e3).toFixed(1)+'k':String(n);
const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
const $ = sel => document.querySelector(sel);

function h(tag, cls, text){
  const node = document.createElement(tag);
  if(cls) node.className = cls;
  if(text !== undefined && text !== null) node.textContent = text;
  return node;
}
function hexA(hex, a){
  const n = parseInt(hex.slice(1),16);
  return `rgba(${(n>>16)&255},${(n>>8)&255},${n&255},${a})`;
}
function topLang(n){
  if(!n.langs) return n.lang;
  const entries = Object.entries(n.langs).sort((a,b)=>b[1]-a[1]);
  return entries.length ? entries[0][0] : 'config';
}
function colorOf(n){ return LANG[topLang(n)] || '#7a7b74'; }
function displayLabel(n){
  if(n.kind === 'root') return n.label;
  if(n.id === '.' && (n.kind === 'hub' || n.kind === 'module')) return 'root files';
  if((n.kind === 'hub' || n.kind === 'module') && state.mode === 'files' && state.w >= 560 && state.shownByModule.get(n.module) > 1){
    return `${n.label || n.id} · ${state.shownByModule.get(n.module)}`;
  }
  if(n.kind === 'file' && state.dupLabels.has(n.label || n.id)){
    const parts = (n.path || n.id).split('/');
    if(parts.length > 1) return parts.slice(-2).join('/');
  }
  return n.label || n.id;
}
function moduleRadius(n){ return clamp(15 + Math.sqrt(n.loc||1)/5.2 + Math.min(5,(n.files||1)*1.1), 17, 35); }
function hubRadius(n){ return clamp(13 + Math.sqrt(n.loc||1)/9 + Math.min(4,(n.files||1)*1.3), 15, 25); }
function fileRadius(n){ return clamp(4.5 + Math.sqrt(n.loc||1)/4.2, 5.2, 12); }
function matches(n){
  const q = state.query.trim().toLowerCase();
  if(!q) return true;
  if((n.id||'').toLowerCase().includes(q)) return true;
  if((n.label||'').toLowerCase().includes(q)) return true;
  return (n.symbols||[]).some(s=>s.toLowerCase().includes(q));
}
function screenPos(n){
  return {x: state.w/2 + state.view.x + n.x*state.view.k, y: state.h/2 + state.view.y + n.y*state.view.k};
}
function resolveNode(id){ return state.byId.get(id) || state.moduleHub.get(id) || null; }

function seedFrom(text){
  let hsh = 2166136261;
  for(let i=0;i<text.length;i++){ hsh ^= text.charCodeAt(i); hsh = Math.imul(hsh, 16777619); }
  return hsh >>> 0;
}

function buildGraph(mode){
  const rawLinks = [];
  if(mode === 'modules'){
    const root = {id:'__root__', label:DATA.meta.repo, kind:'root', files:DATA.meta.files, loc:DATA.meta.loc, r:27, rank:1};
    const nodes = [root, ...DATA.modules.nodes.map(n=>({...n, kind:'module', r:moduleRadius(n)}))];
    for(const n of nodes.slice(1)) rawLinks.push({s:root.id, t:n.id, k:'contains', w:1});
    for(const l of DATA.modules.links) rawLinks.push({...l, k:l.k || 'i'});
    return finishGraph(nodes, rawLinks, mode);
  }
  const usedModules = new Set(DATA.files.nodes.map(f=>f.module));
  const nodes = [];
  const moduleHub = new Map();
  for(const m of DATA.modules.nodes){
    if(!usedModules.has(m.id)) continue;
    const hub = {...m, id:'module:'+m.id, module:m.id, kind:'hub', r:hubRadius(m)};
    moduleHub.set(m.id, hub);
    nodes.push(hub);
  }
  for(const f of DATA.files.nodes){
    nodes.push({...f, kind:'file', r:fileRadius(f)});
    const hub = moduleHub.get(f.module);
    if(hub) rawLinks.push({s:hub.id, t:f.id, k:'contains', w:1});
  }
  for(const l of DATA.files.links) rawLinks.push({...l, k:l.k || 'i'});
  return finishGraph(nodes, rawLinks, mode, moduleHub);
}
function finishGraph(nodes, rawLinks, mode, moduleHub = new Map()){
  const byId = new Map(nodes.map(n=>[n.id,n]));
  const seen = new Set();
  const links = [];
  for(const l of rawLinks){
    if(!l.s || !l.t || l.s === l.t) continue;
    const a = byId.get(l.s), b = byId.get(l.t);
    if(!a || !b) continue;
    const key = l.k+'|'+l.s+'|'+l.t;
    if(seen.has(key)) continue;
    seen.add(key);
    links.push({...l, a, b, w:l.w || 1});
  }
  const dirKeys = new Set(links.map(l=>l.k+'|'+l.s+'|'+l.t));
  for(const l of links) l.both = l.k !== 'contains' && dirKeys.has(l.k+'|'+l.t+'|'+l.s);
  return {nodes, links, byId, moduleHub, mode};
}

function nodeWeight(n){ return (n.loc||1) + (n.files||1)*40; }
function orderByLinks(nodes, links){
  const byId = new Map(nodes.map(n=>[n.id,n]));
  const adj = new Map(nodes.map(n=>[n.id,[]]));
  for(const l of links){
    if(l.k === 'contains') continue;
    if(adj.has(l.s) && adj.has(l.t)){
      adj.get(l.s).push(l.t);
      adj.get(l.t).push(l.s);
    }
  }
  const seen = new Set();
  const out = [];
  const ordered = nodes.slice().sort((a,b)=>nodeWeight(b)-nodeWeight(a));
  for(const seed of ordered){
    if(seen.has(seed.id)) continue;
    const queue = [seed];
    while(queue.length){
      const n = queue.shift();
      if(seen.has(n.id)) continue;
      seen.add(n.id);
      out.push(n);
      const next = adj.get(n.id).map(id=>byId.get(id)).filter(Boolean)
        .sort((a,b)=>nodeWeight(b)-nodeWeight(a));
      for(const m of next) if(!seen.has(m.id)) queue.push(m);
    }
  }
  return out;
}
function placeRing(items, radius, startAngle, ax = 1, ay = 1){
  const n = items.length;
  for(let i=0;i<n;i++){
    const a = startAngle + i*2*Math.PI/n;
    items[i].x = Math.cos(a)*radius*ax;
    items[i].y = Math.sin(a)*radius*ay;
  }
}
function spiralOf(hub, files, maxFileR){
  const avgR = files.reduce((s,f)=>s+f.r,0)/Math.max(1,files.length);
  const spacing = Math.max(18, avgR*2 + 12);
  return {start: hub.r + maxFileR + 16, spacing};
}
function clusterExtent(hub, files, maxFileR){
  if(files.length <= 7) return hub.r + maxFileR + 26 + maxFileR;
  const {start, spacing} = spiralOf(hub, files, maxFileR);
  return start + spacing*Math.sqrt(files.length-1) + maxFileR;
}
function placeFiles(hub, files, maxFileR){
  files.sort((a,b)=>(b.rank||0)-(a.rank||0) || (b.loc||0)-(a.loc||0));
  if(files.length <= 7){
    const orbit = hub.r + maxFileR + 26;
    placeRing(files, orbit, -Math.PI/2 + .35);
    for(const f of files){ f.x += hub.x; f.y += hub.y; }
    return orbit + maxFileR;
  }
  // A phyllotaxis spiral keeps dense modules compact without visible rings.
  const {start, spacing} = spiralOf(hub, files, maxFileR);
  const golden = Math.PI*(3-Math.sqrt(5));
  const phase = (seedFrom(hub.id)%360)*Math.PI/180;
  for(let i=0;i<files.length;i++){
    const rad = start + spacing*Math.sqrt(i);
    const a = phase + i*golden;
    files[i].x = hub.x + Math.cos(a)*rad;
    files[i].y = hub.y + Math.sin(a)*rad*.95;
  }
  return clusterExtent(hub, files, maxFileR);
}
function layoutGraph(graph, mode){
  const nodes = graph.nodes;
  const links = graph.links;
  if(!nodes.length) return;
  if(mode === 'modules'){
    const root = nodes.find(n=>n.kind === 'root');
    if(root){ root.x = 0; root.y = 0; }
    const mods = orderByLinks(nodes.filter(n=>n.kind === 'module'), links);
    const maxR = mods.reduce((m,n)=>Math.max(m,n.r), 17);
    const spacing = maxR*2 + 54;
    const radius = Math.max(215, (mods.length*spacing)/(2*Math.PI));
    placeRing(mods, radius, -Math.PI/2 + .18, 1.2, .8);
  } else {
    const hubs = orderByLinks(nodes.filter(n=>n.kind === 'hub'), links);
    const clusters = hubs.map(hub=>{
      const files = nodes.filter(n=>n.kind === 'file' && n.module === hub.module);
      const maxFileR = files.reduce((m,f)=>Math.max(m,f.r), 6);
      const extent = clusterExtent(hub, files, maxFileR);
      return {hub, files, maxFileR, extent};
    });
    if(hubs.length === 1){
      hubs[0].x = 0;
      hubs[0].y = 0;
    } else {
      const maxExtent = clusters.reduce((m,c)=>Math.max(m,c.extent), 80);
      const spacing = maxExtent*2 + 64;
      const radius = Math.max(250, (hubs.length*spacing)/(2*Math.PI));
      placeRing(hubs, radius, -Math.PI/2 + .22, 1.15, .82);
    }
    for(const c of clusters){
      c.hub.extent = c.extent;
      placeFiles(c.hub, c.files, c.maxFileR);
    }
  }
  graph.links = links;
}

function fitView(){
  if(!state.nodes.length || !state.w || !state.h) return;
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for(const n of state.nodes){
    const pad = n.r + 26;
    minX = Math.min(minX, n.x-pad); maxX = Math.max(maxX, n.x+pad);
    minY = Math.min(minY, n.y-pad); maxY = Math.max(maxY, n.y+pad);
  }
  const padX = clamp(state.w*.10, 46, 120);
  const padY = clamp(state.h*.11, 46, 110);
  const w = Math.max(1, maxX-minX), hh = Math.max(1, maxY-minY);
  state.view.k = clamp(Math.min((state.w-padX*2)/w, (state.h-padY*2)/hh), .1, 1.6);
  state.view.x = -(minX+maxX)/2 * state.view.k;
  state.view.y = -(minY+maxY)/2 * state.view.k;
  state.userMoved = false;
  requestDraw();
}

let drawQueued = false;
function requestDraw(){
  if(drawQueued) return;
  drawQueued = true;
  requestAnimationFrame(()=>{ drawQueued = false; draw(); });
}
let lastAnimFrame = 0;
function animate(ts){
  requestAnimationFrame(animate);
  if(REDUCED || document.hidden) return;
  if(ts - lastAnimFrame < 32) return;
  lastAnimFrame = ts;
  draw(ts);
}
requestAnimationFrame(animate);

function rectsOverlap(a,b){
  return a.x < b.x+b.w && a.x+a.w > b.x && a.y < b.y+b.h && a.y+a.h > b.y;
}
function circleHitsBox(p,r,box){
  const nx = clamp(p.x,box.x,box.x+box.w);
  const ny = clamp(p.y,box.y,box.y+box.h);
  const dx = p.x-nx, dy = p.y-ny;
  return dx*dx+dy*dy < r*r;
}
function drawClusterWashes(t = 0){
  if(state.mode !== 'files') return;
  for(const hub of state.moduleHub.values()){
    if(!hub.extent) continue;
    const p = screenPos(hub);
    const r = (hub.extent+34)*state.view.k;
    const ring = hub.extent*state.view.k;
    if(r < 12) continue;
    const color = colorOf(hub);
    const g = ctx.createRadialGradient(p.x,p.y,ring*.25,p.x,p.y,r);
    g.addColorStop(0,hexA(color,.10));
    g.addColorStop(1,hexA(color,0));
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(p.x,p.y,r,0,Math.PI*2);
    ctx.fill();
    if(ring > 24){
      ctx.save();
      ctx.globalAlpha = .22*entrance;
      ctx.strokeStyle = hexA(color,.75);
      ctx.lineWidth = 1;
      ctx.setLineDash([2,8]);
      ctx.lineDashOffset = -t*.012;
      ctx.beginPath();
      ctx.arc(p.x,p.y,ring,0,Math.PI*2);
      ctx.stroke();
      ctx.restore();
    }
  }
}

let entrance = 1;
function draw(t = performance.now()){
  if(!state.w || !state.h) return;
  const time = t/1000, w = state.w, h = state.h;
  ctx.clearRect(0,0,w,h);
  ctx.fillStyle = STAGE;
  ctx.fillRect(0,0,w,h);

  // Slow aurora washes keep the stage alive without moving the layout.
  const aurora = [
    [w*(.30+.025*Math.sin(time*.05)), h*(.16+.035*Math.cos(time*.04)), w*(.62+.03*Math.cos(time*.03)), 'rgba(53,96,255,.095)', 'rgba(53,96,255,.018)'],
    [w*(.80+.02*Math.cos(time*.037)), h*(.80+.03*Math.sin(time*.033)), w*.52, 'rgba(255,90,54,.058)', 'rgba(255,90,54,.010)'],
    [w*(.55+.03*Math.sin(time*.028)), h*(.52+.02*Math.cos(time*.045)), w*.44, 'rgba(72,190,178,.032)', 'rgba(72,190,178,0)']
  ];
  for(const [x,y,r,inner,outer] of aurora){
    const g = ctx.createRadialGradient(x,y,0,x,y,Math.max(40,r));
    g.addColorStop(0,inner); g.addColorStop(1,outer);
    ctx.fillStyle = g; ctx.fillRect(0,0,w,h);
  }

  const gap = 30;
  ctx.fillStyle = 'rgba(255,255,255,.030)';
  for(let gx=gap/2; gx<w; gx+=gap){
    for(let gy=gap/2; gy<h; gy+=gap) ctx.fillRect(gx,gy,1,1);
  }

  for(const d of DUST){
    const x = (d.x + Math.sin(time*.11*d.sp + d.sp*7)*.004)*w;
    const y = (d.y + Math.cos(time*.09*d.sp + d.sp*3)*.003)*h;
    const twinkle = .72 + .28*Math.sin(time*.45 + d.sp*9);
    ctx.beginPath(); ctx.arc(x,y,d.r,0,Math.PI*2);
    ctx.fillStyle = `rgba(180,205,255,${d.a*twinkle})`; ctx.fill();
  }

  const vg = ctx.createRadialGradient(w*.5,h*.46,Math.min(w,h)*.18,w*.5,h*.5,Math.max(w,h)*.78);
  vg.addColorStop(0,'rgba(0,0,0,0)'); vg.addColorStop(.62,'rgba(0,0,0,.08)'); vg.addColorStop(1,'rgba(0,0,0,.36)');
  ctx.fillStyle = vg; ctx.fillRect(0,0,w,h);

  if(!state.nodes.length){ emptyBox.hidden = false; return; }
  emptyBox.hidden = true;

  entrance = REDUCED || !state.enterAt ? 1 : clamp((t-state.enterAt)/560,0,1);
  entrance = 1-Math.pow(1-entrance,3);

  drawClusterWashes(t);
  const selected = state.selected;
  const focusNode = selected || state.hover;
  const q = state.query.trim();
  const focus = new Set();
  if(focusNode){
    focus.add(focusNode.id);
    for(const l of state.links){
      if(l.s === focusNode.id) focus.add(l.t);
      if(l.t === focusNode.id) focus.add(l.s);
    }
  }
  const dimAlpha = selected ? .14 : .3;
  for(const l of state.links){
    const dim = q ? !(matches(l.a) || matches(l.b)) : (focusNode && !(focus.has(l.s) || focus.has(l.t)));
    drawLink(l, !!dim, focusNode, t, dimAlpha);
  }
  const ordered = state.nodes.slice().sort((a,b)=>nodeOrder(a)-nodeOrder(b));
  for(const n of ordered){
    const dim = (q && !matches(n)) || (focusNode && !focus.has(n.id));
    drawNode(n, !!dim, n === selected, n === state.hover, t, dimAlpha);
  }
  drawLabels(focus, t);
  ctx.globalAlpha = 1;
}
function nodeOrder(n){
  if(n === state.selected) return 3;
  if(n.kind === 'file') return 2;
  return 1;
}
function linkCurve(l){
  const a = screenPos(l.a), b = screenPos(l.b);
  const dx = b.x-a.x, dy = b.y-a.y, d = Math.hypot(dx,dy) || 1;
  let bend = l.k === 'contains' ? 0 : Math.min(34, d*.095) * ((seedFrom(l.s+'|'+l.t) & 1) ? 1 : -1);
  if(l.k !== 'contains'){
    const cross = state.mode === 'modules' || (l.a.module && l.b.module && l.a.module !== l.b.module);
    if(cross){
      bend = Math.min(46, 14 + d*.075);
      const ox = state.w/2 + state.view.x, oy = state.h/2 + state.view.y;
      const mx = (a.x+b.x)/2 - ox, my = (a.y+b.y)/2 - oy;
      const nx = -dy/d, ny = dx/d;
      if(nx*mx + ny*my < 0) bend = -bend;
    }
  }
  return {a, b, cx:(a.x+b.x)/2 - dy/d*bend, cy:(a.y+b.y)/2 + dx/d*bend};
}
function drawLink(l, dim, focusNode, t, dimAlpha = .14){
  const {a,b,cx,cy} = linkCurve(l);
  const contains = l.k === 'contains';
  const call = l.k === 'c';
  const both = !contains && l.both;
  if(both && l.s > l.t) return;
  const connected = focusNode && (l.s === focusNode.id || l.t === focusNode.id);
  const pad = contains ? 2 : 4;
  const sa = trimToward(a, cx, cy, trimFor(l.a, pad));
  const sb = trimToward(b, cx, cy, trimFor(l.b, pad));
  const weight = Math.max(1, l.w || 1);
  const strength = contains ? 1 : (state.mode === 'files' ? .42 + .58*Math.min(1, weight/4) : .72 + .28*Math.min(1, weight/4));
  const base = contains ? (state.mode === 'files' ? .24 : .64) : (call ? .50 : .36);
  ctx.save();
  ctx.globalAlpha = (dim ? (state.selected ? .035 : .06) : (connected ? 1 : base*strength)) * entrance;
  ctx.strokeStyle = contains ? '#606a7a' : (call ? ACCENT : '#8b95a7');
  ctx.lineWidth = connected ? 1.55 : (contains ? 1 : (call ? 1.2 : 1.05));
  ctx.lineCap = 'round';
  ctx.setLineDash(contains ? [1.5,4.5] : (call ? [4.5,3.5] : []));
  ctx.lineDashOffset = call ? -t*(connected ? .02 : .0035) : 0;
  ctx.beginPath();
  ctx.moveTo(sa.x,sa.y);
  ctx.quadraticCurveTo(cx,cy,sb.x,sb.y);
  ctx.stroke();
  ctx.setLineDash([]);
  if(!contains && !dim){
    // Keep dense clusters readable when zoomed out; let arrows grow when zoomed in.
    const arrowScale = clamp(state.view.k, .6, 1.15);
    const arrowSize = (connected ? 6.4 : 5.2) * arrowScale;
    arrowAt(sb, cx, cy, arrowSize);
    if(both) arrowAt(sa, cx, cy, arrowSize);
  }
  if(connected && !contains){
    const u = ((t*.00040 + (seedFrom(l.s+'|'+l.t)%100)/100) % 1);
    const v = 1-u;
    const px = v*v*a.x + 2*v*u*cx + u*u*b.x;
    const py = v*v*a.y + 2*v*u*cy + u*u*b.y;
    ctx.fillStyle = call ? ACCENT : '#e6eeff';
    ctx.shadowColor = call ? ACCENT : '#7ea6ff';
    ctx.shadowBlur = 9;
    ctx.beginPath(); ctx.arc(px,py,2.1,0,Math.PI*2); ctx.fill();
    ctx.shadowBlur = 0;
  }
  ctx.restore();
}
function trimFor(node, pad){
  const halo = node.kind === 'file' || node.kind === 'root' ? 0 : 7;
  return Math.max(3.5, node.r*state.view.k) + halo*state.view.k + pad;
}
function trimToward(pt, cx, cy, dist){
  const dx = pt.x-cx, dy = pt.y-cy, d = Math.hypot(dx,dy) || 1;
  return {x: pt.x-dx/d*dist, y: pt.y-dy/d*dist};
}
function arrowAt(pt, cx, cy, size = 6.2){
  const tx = pt.x-cx, ty = pt.y-cy;
  const td = Math.hypot(tx,ty) || 1;
  ctx.fillStyle = ctx.strokeStyle;
  drawArrow(pt.x, pt.y, tx/td, ty/td, size);
}
function drawArrow(x,y,ux,uy,size){
  const px = -uy, py = ux;
  ctx.beginPath();
  ctx.moveTo(x,y);
  ctx.lineTo(x-ux*size+px*size*.55, y-uy*size+py*size*.55);
  ctx.lineTo(x-ux*size-px*size*.55, y-uy*size-py*size*.55);
  ctx.closePath();
  ctx.fill();
}
function drawNode(n, dim, selected, hovered, t, dimAlpha = .14){
  const p = screenPos(n);
  const r = Math.max(4.2, n.r*state.view.k);
  const color = colorOf(n);
  const seed = seedFrom(n.id);
  const pulse = .5+.5*Math.sin(t*.0012 + (seed%628)/100);
  const hub = n.kind === 'hub' || n.kind === 'module';
  ctx.save();
  ctx.globalAlpha = (dim ? dimAlpha : 1) * entrance;
  if(selected || hovered){
    ctx.beginPath();
    ctx.arc(p.x,p.y,r+7+pulse*2,0,Math.PI*2);
    ctx.fillStyle = hexA(ACCENT, selected ? .14 : .075);
    ctx.fill();
  }
  if(n.kind === 'root'){
    const g = ctx.createRadialGradient(p.x,p.y,r*.4,p.x,p.y,r*3);
    g.addColorStop(0,'rgba(238,241,245,.28)'); g.addColorStop(1,'rgba(238,241,245,0)');
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(p.x,p.y,r*3,0,Math.PI*2); ctx.fill();
    ctx.beginPath(); ctx.arc(p.x,p.y,r,0,Math.PI*2);
    ctx.fillStyle = '#eef1f5'; ctx.fill();
    ctx.lineWidth = 1.6; ctx.strokeStyle = WHITE; ctx.stroke();
    ctx.beginPath(); ctx.arc(p.x,p.y,Math.max(2.4,r*.18),0,Math.PI*2);
    ctx.fillStyle = STAGE; ctx.fill();
    ctx.globalAlpha = (dim ? dimAlpha : .45) * entrance;
    ctx.strokeStyle = 'rgba(255,255,255,.8)';
    ctx.lineWidth = 1;
    ctx.setLineDash([2,7]);
    ctx.lineDashOffset = -t*.008;
    ctx.beginPath(); ctx.arc(p.x,p.y,r+9,0,Math.PI*2); ctx.stroke();
    ctx.setLineDash([]);
  } else if(hub){
    ctx.beginPath(); ctx.arc(p.x,p.y,r+7+pulse*2,0,Math.PI*2);
    ctx.fillStyle = hexA(color,.035+pulse*.03); ctx.fill();
    ctx.beginPath(); ctx.arc(p.x,p.y,r,0,Math.PI*2);
    ctx.fillStyle = hexA(color,.18); ctx.fill();
    ctx.lineWidth = 1.5; ctx.strokeStyle = color; ctx.stroke();
    ctx.beginPath(); ctx.arc(p.x,p.y,Math.max(2.2,r*.17),0,Math.PI*2);
    ctx.fillStyle = color; ctx.fill();
    ctx.globalAlpha = (dim ? dimAlpha : .42) * entrance;
    ctx.strokeStyle = hexA(color,.85);
    ctx.lineWidth = 1;
    ctx.setLineDash([2,7]);
    ctx.lineDashOffset = t*.012;
    ctx.beginPath(); ctx.arc(p.x,p.y,r+7,0,Math.PI*2); ctx.stroke();
    ctx.setLineDash([]);
  } else {
    ctx.beginPath(); ctx.arc(p.x,p.y,r*1.95,0,Math.PI*2);
    ctx.fillStyle = hexA(color,.045); ctx.fill();
    ctx.beginPath(); ctx.arc(p.x,p.y,r*1.35,0,Math.PI*2);
    ctx.fillStyle = hexA(color,.075); ctx.fill();
    ctx.beginPath(); ctx.arc(p.x,p.y,r,0,Math.PI*2);
    ctx.fillStyle = color; ctx.fill();
    ctx.lineWidth = 1; ctx.strokeStyle = 'rgba(8,10,13,.7)'; ctx.stroke();
    ctx.beginPath(); ctx.arc(p.x-r*.28,p.y-r*.28,Math.max(1,r*.3),0,Math.PI*2);
    ctx.fillStyle = 'rgba(255,255,255,.28)'; ctx.fill();
  }
  if(selected){
    ctx.globalAlpha = entrance;
    const sg = ctx.createRadialGradient(p.x,p.y,r*.6,p.x,p.y,r*4.4);
    sg.addColorStop(0,hexA(ACCENT,.18)); sg.addColorStop(1,hexA(ACCENT,0));
    ctx.fillStyle = sg;
    ctx.beginPath(); ctx.arc(p.x,p.y,r*4.4,0,Math.PI*2); ctx.fill();
    ctx.beginPath(); ctx.arc(p.x,p.y,r+4,0,Math.PI*2);
    ctx.lineWidth = 1.8; ctx.strokeStyle = ACCENT; ctx.stroke();
    ctx.beginPath(); ctx.arc(p.x,p.y,r+8+pulse*2,0,Math.PI*2);
    ctx.lineWidth = 1;
    ctx.setLineDash([4,5]);
    ctx.lineDashOffset = -t*.03;
    ctx.strokeStyle = hexA(ACCENT,.9);
    ctx.stroke();
    ctx.setLineDash([]);
  } else if(hovered){
    ctx.beginPath(); ctx.arc(p.x,p.y,r+3,0,Math.PI*2);
    ctx.lineWidth = 1.4; ctx.strokeStyle = WHITE; ctx.stroke();
  }
  ctx.restore();
}
function pillPath(x,y,w,h,r){
  ctx.beginPath();
  ctx.moveTo(x+r,y);
  ctx.arcTo(x+w,y,x+w,y+h,r);
  ctx.arcTo(x+w,y+h,x,y+h,r);
  ctx.arcTo(x,y+h,x,y,r);
  ctx.arcTo(x,y,x+w,y,r);
  ctx.closePath();
}
function drawLabels(focus, t = 0){
  const q = state.query.trim();
  const boxes = [];
  const order = state.nodes.slice().sort((a,b)=>labelPriority(b)-labelPriority(a));
  for(const n of order){
    const selected = n === state.selected;
    const hovered = n === state.hover;
    const isFile = n.kind === 'file';
    const top = isFile && state.topFiles.has(n.id);
    const show = selected || hovered || (state.labels && (!isFile || top || state.view.k > .9 || state.nodes.length <= 20 || (q && matches(n))));
    if(!show) continue;
    const p = screenPos(n);
    const r = Math.max(4.2, n.r*state.view.k);
    const text = displayLabel(n);
    const small = state.w < 560;
    const font = `600 ${isFile ? (small ? 10 : 11.5) : (small ? 10.5 : 12)}px "Segoe UI",system-ui,sans-serif`;
    ctx.font = font;
    const tw = ctx.measureText(text).width;
    const dotPad = isFile ? 9 : 0;
    const hw = (tw+dotPad)/2 + (small ? 6 : 7), ph = small ? 18 : 20;
    const positions = [];
    if(isFile){
      positions.push(
        {x:p.x, y:p.y+r+16},
        {x:p.x, y:p.y-r-16},
        {x:p.x+r+hw+6, y:p.y},
        {x:p.x-r-hw-6, y:p.y}
      );
    } else if(n.kind === 'hub' && n.extent){
      const out = n.extent*state.view.k + 17;
      positions.push({x:p.x, y:p.y+out}, {x:p.x, y:p.y-out});
      positions.push({x:p.x+r+hw+6, y:p.y}, {x:p.x-r-hw-6, y:p.y});
      positions.push(
        {x:p.x+out*.72, y:p.y+out*.72}, {x:p.x-out*.72, y:p.y+out*.72},
        {x:p.x+out*.72, y:p.y-out*.72}, {x:p.x-out*.72, y:p.y-out*.72}
      );
    } else {
      positions.push(
        {x:p.x, y:p.y+r+16},
        {x:p.x, y:p.y-r-16},
        {x:p.x+r+hw+6, y:p.y},
        {x:p.x-r-hw-6, y:p.y}
      );
      if(!isFile){
        const out = r+26;
        positions.push(
          {x:p.x+out*.72, y:p.y+out*.72}, {x:p.x-out*.72, y:p.y+out*.72},
          {x:p.x+out*.72, y:p.y-out*.72}, {x:p.x-out*.72, y:p.y-out*.72}
        );
      }
    }
    let chosen = null;
    for(const pos of positions){
      const box = {x:pos.x-hw, y:pos.y-ph/2, w:hw*2, h:ph};
      if(box.x < 5 || box.y < 5 || box.x+box.w > state.w-5 || box.y+box.h > state.h-5) continue;
      if(boxes.some(b=>rectsOverlap(b,box))) continue;
      const force = selected || hovered || (state.w < 560 && !isFile);
      if(!force && state.nodes.some(m=>circleHitsBox(screenPos(m), Math.max(4.2,m.r*state.view.k)+2, box))) continue;
      chosen = {pos, box};
      break;
    }
    if(!chosen) continue;
    boxes.push(chosen.box);
    const dimmed = (q && !matches(n)) || (state.selected && !focus.has(n.id)) || (state.hover && n !== state.hover && !focus.has(n.id));
    ctx.save();
    ctx.globalAlpha = (dimmed ? .16 : 1) * entrance;
    const {box} = chosen;
    pillPath(box.x,box.y,box.w,box.h,6);
    ctx.fillStyle = selected ? 'rgba(38,14,9,.94)' : 'rgba(9,11,15,.78)';
    ctx.fill();
    ctx.strokeStyle = selected ? hexA(ACCENT,.55) : 'rgba(255,255,255,.12)';
    ctx.lineWidth = 1;
    ctx.stroke();
    if(isFile){
      ctx.beginPath();
      ctx.arc(box.x+7, box.y+box.h/2, 2.2, 0, Math.PI*2);
      ctx.fillStyle = colorOf(n);
      ctx.fill();
    }
    ctx.font = font;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = selected ? ACCENT : INK;
    ctx.fillText(text, chosen.pos.x+dotPad/2, chosen.pos.y+.5);
    ctx.restore();
  }
}
function labelPriority(n){
  if(n === state.selected) return 100;
  if(n === state.hover) return 90;
  if(n.kind === 'root' || n.kind === 'hub' || n.kind === 'module') return 50;
  if(state.topFiles.has(n.id)) return 45;
  return 10 + (n.rank || 0)*100;
}

function resize(){
  const rect = canvas.getBoundingClientRect();
  state.w = rect.width; state.h = rect.height;
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = Math.max(1, Math.round(rect.width*dpr));
  canvas.height = Math.max(1, Math.round(rect.height*dpr));
  ctx.setTransform(dpr,0,0,dpr,0,0);
  if(state.nodes.length) refreshTopFiles();
  if(!state.userMoved && state.nodes.length) fitView();
  else requestDraw();
}
window.addEventListener('resize', resize);

function zoomBy(factor, cx = state.w/2, cy = state.h/2){
  const k2 = clamp(state.view.k*factor, .18, 4);
  const wx = (cx-(state.w/2+state.view.x))/state.view.k;
  const wy = (cy-(state.h/2+state.view.y))/state.view.k;
  state.view.x = cx-state.w/2-wx*k2;
  state.view.y = cy-state.h/2-wy*k2;
  state.view.k = k2;
  state.userMoved = true;
  requestDraw();
}

function updateChrome(){
  document.title = `${DATA.meta.repo} · CodeAtlas`;
  document.getElementById('repo').textContent = DATA.meta.repo;
  const repoMeta = document.getElementById('repo-meta');
  repoMeta.replaceChildren();
  repoMeta.append(
    document.createTextNode(`${DATA.meta.files} files`),
    h('span','sep','·'),
    document.createTextNode(`${fmt(DATA.meta.loc)} LOC`),
    h('span','sep','·'),
    h('span','repo-commit',DATA.meta.commit)
  );
  document.getElementById('n-modules').textContent = DATA.modules.nodes.length;
  document.getElementById('n-files').textContent = DATA.files.nodes.length;
  document.getElementById('mode-modules').setAttribute('aria-pressed', state.mode === 'modules');
  document.getElementById('mode-files').setAttribute('aria-pressed', state.mode === 'files');
  const deps = state.mode === 'modules' ? DATA.modules.links.length : DATA.files.links.length;
  const count = state.mode === 'modules' ? DATA.modules.nodes.length : DATA.files.nodes.length;
  const noun = state.mode === 'modules' ? 'modules' : 'files';
  const scope = state.mode === 'modules' ? `${count} modules` : `${count}/${DATA.meta.files} files`;
  const kinds = new Set(state.links.filter(l=>l.k !== 'contains').map(l=>l.k));
  const styleBits = [];
  if(kinds.has('i')) styleBits.push('solid import');
  if(kinds.has('c')) styleBits.push('dashed call');
  styleBits.push('dotted membership');
  const depNoun = state.w < 560 ? 'edge' : 'dependency edge';
  mapNote.replaceChildren();
  mapNote.append(h('strong', null, scope));
  mapNote.append(document.createTextNode(deps ? ` · ${deps} ${depNoun}${deps===1?'':'s'}` : ' · containment only'));
  mapNote.append(h('span','foot-key',' · '+styleBits.join(' · ')));
  canvas.setAttribute('aria-label', `Code dependency map: ${scope}, ${deps} dependency edges. Use the atlas index panel for details.`);
}
function updateSearchCount(){
  const q = state.query.trim();
  if(!q){ document.getElementById('search-count').textContent = ''; return; }
  const n = state.nodes.filter(m=>m.kind !== 'root' && matches(m)).length;
  document.getElementById('search-count').textContent = n ? `${n} match${n===1?'':'es'}` : 'No matches';
}

function factList(items){
  const dl = h('dl','facts');
  for(const [key,value] of items){
    const row = h('div');
    row.append(h('dt',null,key), h('dd',null,value));
    dl.append(row);
  }
  return dl;
}
function sectionTitle(title, count){
  const row = h('h2','section-title');
  row.append(h('span',null,title));
  if(count !== undefined && count !== null) row.append(h('span','count',count));
  return row;
}
const GLYPHS = {
  hub: '<svg viewBox="0 0 28 20" fill="none"><circle cx="14" cy="10" r="7.5" stroke="#6f9bff" stroke-opacity=".28" stroke-dasharray="2 3"/><circle cx="14" cy="10" r="4.6" stroke="#7fa8ff" stroke-width="1.4"/><circle cx="14" cy="10" r="1.6" fill="#7fa8ff"/></svg>',
  file: '<svg viewBox="0 0 28 20" fill="none"><circle cx="14" cy="10" r="8" fill="#7fa8ff" fill-opacity=".10"/><circle cx="14" cy="10" r="4" fill="#7fa8ff"/><circle cx="12.8" cy="8.8" r="1" fill="#fff" fill-opacity=".6"/></svg>',
  import: '<svg viewBox="0 0 28 20" fill="none"><path d="M4 10h16" stroke="#aeb8c8" stroke-width="1.4" stroke-linecap="round"/><path d="M20 10l-4.5-3.2v6.4z" fill="#aeb8c8"/><circle cx="4" cy="10" r="1.5" fill="#aeb8c8" fill-opacity=".65"/></svg>',
  call: '<svg viewBox="0 0 28 20" fill="none"><path d="M4 10h16" stroke="#ff7a58" stroke-width="1.4" stroke-dasharray="4 3" stroke-linecap="round"/><path d="M20 10l-4.5-3.2v6.4z" fill="#ff7a58"/><circle cx="4" cy="10" r="1.5" fill="#ff7a58" fill-opacity=".65"/></svg>',
  contain: '<svg viewBox="0 0 28 20" fill="none"><path d="M4 10h20" stroke="#7b8494" stroke-width="1.4" stroke-dasharray="1.5 4" stroke-linecap="round"/><circle cx="4" cy="10" r="1.3" fill="#7b8494" fill-opacity=".6"/><circle cx="24" cy="10" r="1.3" fill="#7b8494" fill-opacity=".6"/></svg>'
};
function legendItem(kind, title, body){
  const li = h('li');
  const sw = h('span','swatch');
  sw.innerHTML = GLYPHS[kind] || '';
  sw.setAttribute('aria-hidden','true');
  const txt = h('span');
  txt.append(h('b',null,title), document.createTextNode(' '+body));
  li.append(sw, txt);
  return li;
}
function formatGenerated(value){
  if(!value) return 'n/a';
  const d = new Date(value.replace(' ','T'));
  if(Number.isNaN(d.getTime())) return value;
  return d.toLocaleString('en-GB',{day:'numeric',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',hour12:false});
}
function panelBack(label, target){
  const btn = h('button','back', '← '+label);
  btn.type = 'button';
  btn.onclick = ()=>select(target);
  return btn;
}
function relKindLabel(k){ return k === 'i' ? 'import' : (k === 'c' ? 'call' : 'contains'); }
function relationRow(target, kind, direction){
  const node = resolveNode(target);
  if(!node) return null;
  const li = h('li');
  const btn = h('button','row');
  btn.type = 'button';
  const name = h('span','row-name');
  name.append(h('span','row-kind', relKindLabel(kind)), document.createTextNode((direction ? direction+' ' : '')+displayLabel(node)));
  btn.append(name, h('span','row-meta', node.kind === 'file' ? fmt(node.loc||0)+' LOC' : `${node.files||1} files`));
  btn.onclick = ()=>select(node);
  li.append(btn);
  return li;
}
function relationGroups(n){
  const groups = new Map();
  for(const l of state.links){
    if(l.k === 'contains' || (l.s !== n.id && l.t !== n.id)) continue;
    const outgoing = l.s === n.id;
    const other = outgoing ? l.t : l.s;
    const key = other+'|'+l.k;
    const group = groups.get(key) || {other, kind:l.k, out:false, inc:false};
    if(outgoing) group.out = true; else group.inc = true;
    groups.set(key, group);
  }
  return [...groups.values()].sort((a,b)=>a.other.localeCompare(b.other) || a.kind.localeCompare(b.kind));
}
function directionMark(group){
  return group.out && group.inc ? '↔' : (group.out ? '→' : '←');
}

function showOverview(){
  panel.replaceChildren();
  const kicker = h('div','panel-kicker');
  const kickerLabel = h('span','kicker-label');
  kickerLabel.append(h('span','kicker-dot'), document.createTextNode('Local index'));
  kicker.append(kickerLabel, h('span','v','v'+DATA.meta.tool));
  panel.append(kicker);
  panel.append(h('h1','panel-title',DATA.meta.repo));
  panel.append(h('p','panel-lede','A local map of modules, files, and static dependencies. Read the shape before opening the code.'));

  const stats = h('div','stats-card');
  const statsHead = h('div','stats-head');
  statsHead.append(h('span','label','Index'), h('span','stats-chip', `${DATA.files.nodes.length} mapped`));
  stats.append(statsHead);
  stats.append(factList([
    ['Files', fmt(DATA.meta.files)],
    ['Lines', fmt(DATA.meta.loc)],
    ['Symbols', fmt(DATA.meta.symbols)],
    ['Symbol edges', fmt(DATA.meta.edges)]
  ]));
  panel.append(stats);

  panel.append(sectionTitle('How to read'));
  const legendCard = h('div','legend-card');
  const legend = h('ul','legend-list');
  legend.append(
    legendItem('hub','Module hub','groups files; size follows lines of code.'),
    legendItem('file','File','colored by language; size follows LOC.'),
    legendItem('import','Import','solid line; arrow points to the target.'),
    legendItem('call','Call','dashed line; brighter means a stronger link.'),
    legendItem('contain','Containment','dotted line; module membership.')
  );
  legendCard.append(legend);
  panel.append(legendCard);

  const langs = Object.entries(DATA.meta.languages || {}).sort((a,b)=>b[1]-a[1]);
  if(langs.length){
    panel.append(sectionTitle('Languages', langs.length));
    const langCard = h('div','lang-card');
    const list = h('ul','langs');
    const total = langs.reduce((sum,[,count])=>sum+count,0) || 1;
    for(const [name,count] of langs.slice(0,9)){
      const li = h('li');
      li.style.setProperty('--c', LANG[name] || '#7a7b74');
      const bar = h('span','bar');
      const fill = h('i');
      fill.style.width = Math.max(2, count/total*100).toFixed(1)+'%';
      bar.append(fill);
      li.append(h('span','dot'), h('span','name',name), bar, h('span','n',String(count)));
      list.append(li);
    }
    langCard.append(list);
    panel.append(langCard);
  }

  const meta = h('div','index-meta');
  meta.append(
    h('span',null,`Generated ${formatGenerated(DATA.meta.generated)}`),
    h('span','meta-sep','·'),
    h('span','commit',DATA.meta.commit),
    h('span','meta-sep','·'),
    h('span','ver','v'+DATA.meta.tool)
  );
  panel.append(meta);
}
function showModule(n){
  const m = DATA.modules.nodes.find(x=>x.id === n.id) || n;
  const files = DATA.files.nodes.filter(f=>f.module === m.id);
  panel.replaceChildren();
  panel.append(panelBack('Atlas index', null));
  panel.append(h('p','crumb','Module'));
  panel.append(h('h1','panel-title',displayLabel(n)));
  panel.append(h('p','panel-path',`${m.files} files · ${fmt(m.loc)} lines`));
  panel.append(factList([
    ['Files in module', m.files],
    ['Lines', fmt(m.loc)],
    ['Influence', (m.rank||0).toFixed(4)],
    ['Language', topLang(m)]
  ]));
  if(files.length){
    panel.append(sectionTitle('Files in this view', files.length));
    const list = h('ul','rows');
    for(const f of files.slice().sort((a,b)=>(b.loc||0)-(a.loc||0))){
      const li = h('li');
      const btn = h('button','row');
      btn.type = 'button';
      btn.append(h('span','row-name',f.label||f.id), h('span','row-meta',fmt(f.loc||0)+' LOC'));
      btn.onclick = ()=>openFile(f.id);
      li.append(btn); list.append(li);
    }
    panel.append(list);
    if(files.length < m.files) panel.append(h('p','fine',`Showing ${files.length} of ${m.files} files in this view.`));
  }
  const rels = relationGroups(n);
  panel.append(sectionTitle('Relations', rels.length));
  if(rels.length){
    const list = h('ul','rows');
    for(const group of rels){
      const row = relationRow(group.other, group.kind, directionMark(group));
      if(row) list.append(row);
    }
    panel.append(list);
  } else {
    panel.append(h('p','empty-note','No cross-module dependencies detected.'));
  }
  if(m.symbols && m.symbols.length){
    panel.append(sectionTitle('Key symbols'));
    const list = h('ul','symbols');
    for(const sym of m.symbols){
      const li = h('li');
      const btn = h('button',null,sym);
      btn.type = 'button';
      btn.onclick = ()=>focusSymbol(sym);
      li.append(btn); list.append(li);
    }
    panel.append(list);
  }
}
function showFile(n){
  const hub = state.moduleHub.get(n.module);
  panel.replaceChildren();
  panel.append(panelBack(hub ? displayLabel(hub) : 'Atlas index', hub || null));
  panel.append(h('p','crumb','File'));
  panel.append(h('h1','panel-title',n.label||n.id));
  panel.append(h('p','panel-path',n.path||n.id));
  panel.append(factList([
    ['Lines', fmt(n.loc||0)],
    ['Influence', (n.rank||0).toFixed(4)],
    ['Module', n.module],
    ['Internal calls', fmt(n.calls||0)]
  ]));
  const rels = relationGroups(n);
  panel.append(sectionTitle('Relations', rels.length));
  if(rels.length){
    const list = h('ul','rows');
    for(const group of rels){
      const row = relationRow(group.other, group.kind, directionMark(group));
      if(row) list.append(row);
    }
    panel.append(list);
  } else {
    panel.append(h('p','empty-note','No cross-file dependencies detected. This node is connected to its module hub only.'));
  }
  if(n.symbols && n.symbols.length){
    panel.append(sectionTitle('Symbols'));
    const list = h('ul','symbols');
    for(const sym of n.symbols){
      const li = h('li');
      const btn = h('button',null,sym);
      btn.type = 'button';
      btn.onclick = ()=>focusSymbol(sym);
      li.append(btn); list.append(li);
    }
    panel.append(list);
  }
  if(n.tests) panel.append(h('p','fine','Indexed as a test file.'));
}
function select(n){
  state.selected = n || null;
  requestDraw();
  if(!n || n.kind === 'root') showOverview();
  else if(n.kind === 'hub' || n.kind === 'module') showModule(n);
  else showFile(n);
  live.textContent = n ? `${displayLabel(n)} selected` : 'Atlas overview';
}
function focusSymbol(sym){
  search.value = sym;
  state.query = sym;
  updateSearchCount();
  requestDraw();
  search.focus();
  search.select();
}
function openFile(id){
  if(state.mode !== 'files') load('files');
  const node = state.byId.get(id);
  if(node) select(node);
}

function refreshTopFiles(){
  const limit = state.w < 560 ? 5 : 8;
  const files = state.nodes.filter(n=>n.kind === 'file');
  const counts = new Map(), shown = new Map();
  for(const f of files){
    counts.set(f.label || f.id, (counts.get(f.label || f.id) || 0) + 1);
    shown.set(f.module, (shown.get(f.module) || 0) + 1);
  }
  state.dupLabels = new Set([...counts].filter(([,c])=>c > 1).map(([k])=>k));
  state.shownByModule = shown;
  state.topFiles = new Set(
    files.sort((a,b)=>(b.rank||0)-(a.rank||0))
      .slice(0,limit).map(n=>n.id)
  );
}
function load(mode){
  state.mode = mode;
  state.selected = null;
  state.hover = null;
  const graph = buildGraph(mode);
  state.nodes = graph.nodes;
  state.links = graph.links;
  state.byId = graph.byId;
  state.moduleHub = graph.moduleHub;
  layoutGraph(graph, mode);
  refreshTopFiles();
  state.enterAt = REDUCED ? 0 : performance.now();
  state.view = {x:0,y:0,k:1};
  state.userMoved = false;
  updateChrome();
  if(state.w) fitView(); else requestDraw();
  showOverview();
  updateSearchCount();
  requestDraw();
}

function hit(e){
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX-rect.left, my = e.clientY-rect.top;
  for(let i=state.nodes.length-1;i>=0;i--){
    const n = state.nodes[i], p = screenPos(n);
    const rr = Math.max(5, n.r*state.view.k+3);
    if((mx-p.x)**2+(my-p.y)**2 <= rr*rr) return n;
  }
  return null;
}
function setTooltip(n, e){
  if(!n){ tooltip.classList.remove('show'); return; }
  tooltip.replaceChildren();
  tooltip.append(h('div','tip-name',displayLabel(n)));
  const meta = n.kind === 'file'
    ? `${n.module} · ${fmt(n.loc||0)} LOC${n.calls?' · '+n.calls+' internal calls':''}`
    : `${n.files||1} files · ${fmt(n.loc||0)} LOC`;
  tooltip.append(h('div','tip-meta',meta));
  const rect = canvas.getBoundingClientRect();
  let x = e.clientX-rect.left+14, y = e.clientY-rect.top+13;
  tooltip.classList.add('show');
  const tw = tooltip.offsetWidth, th = tooltip.offsetHeight;
  if(x+tw > state.w-10) x = e.clientX-rect.left-tw-14;
  if(y+th > state.h-10) y = e.clientY-rect.top-th-13;
  tooltip.style.left = Math.max(8,x)+'px';
  tooltip.style.top = Math.max(8,y)+'px';
}

let drag = null;
canvas.addEventListener('pointerdown', e=>{
  const n = hit(e);
  if(n){ select(n); return; }
  drag = {x:e.clientX, y:e.clientY, vx:state.view.x, vy:state.view.y, moved:false};
  canvas.classList.add('dragging');
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener('pointermove', e=>{
  if(drag){
    const dx = e.clientX-drag.x, dy = e.clientY-drag.y;
    if(Math.abs(dx)+Math.abs(dy) > 3) drag.moved = true;
    state.view.x = drag.vx+dx;
    state.view.y = drag.vy+dy;
    state.userMoved = true;
    tooltip.classList.remove('show');
    requestDraw();
    return;
  }
  const n = hit(e);
  if(n !== state.hover){ state.hover = n; requestDraw(); }
  setTooltip(n, e);
  canvas.style.cursor = n ? 'pointer' : 'grab';
});
canvas.addEventListener('pointerup', e=>{
  if(drag && !drag.moved){
    select(null);
    tooltip.classList.remove('show');
  }
  drag = null;
  canvas.classList.remove('dragging');
  canvas.style.cursor = state.hover ? 'pointer' : 'grab';
});
canvas.addEventListener('pointerleave', ()=>{
  state.hover = null;
  drag = null;
  tooltip.classList.remove('show');
  requestDraw();
});
canvas.addEventListener('wheel', e=>{
  e.preventDefault();
  const rect = canvas.getBoundingClientRect();
  zoomBy(Math.exp(-e.deltaY*.0012), e.clientX-rect.left, e.clientY-rect.top);
}, {passive:false});

search.addEventListener('input', ()=>{
  state.query = search.value.trim();
  updateSearchCount();
  requestDraw();
});
document.getElementById('mode-modules').onclick = ()=>setMode('modules');
document.getElementById('mode-files').onclick = ()=>setMode('files');
function setMode(mode){
  if(mode === state.mode) return;
  load(mode);
}
document.getElementById('labels').onclick = e=>{
  state.labels = !state.labels;
  e.currentTarget.setAttribute('aria-pressed', state.labels);
  requestDraw();
};
document.getElementById('reset').onclick = ()=>{ fitView(); };
document.getElementById('brand').onclick = ()=>{ select(null); fitView(); };
document.getElementById('zoom-in').onclick = ()=>zoomBy(1.2);
document.getElementById('zoom-out').onclick = ()=>zoomBy(1/1.2);
document.getElementById('zoom-fit').onclick = ()=>fitView();
window.addEventListener('keydown', e=>{
  if(e.ctrlKey || e.metaKey || e.altKey) return;
  const typing = e.target && e.target.matches && e.target.matches('input,textarea');
  if(e.key === 'Escape'){
    if(state.query){ search.value=''; state.query=''; updateSearchCount(); requestDraw(); }
    else select(null);
    return;
  }
  if(typing) return;
  if(e.key === '/'){ e.preventDefault(); search.focus(); }
  else if(e.key === '0'){ e.preventDefault(); fitView(); }
  else if(e.key === '+' || e.key === '='){ e.preventDefault(); zoomBy(1.2); }
  else if(e.key === '-'){ e.preventDefault(); zoomBy(1/1.2); }
  else if(e.key.toLowerCase() === 'm'){ setMode('modules'); }
  else if(e.key.toLowerCase() === 'f'){ setMode('files'); }
});

const hashMode = location.hash.replace(/^#\/?/,'');
const initialMode = (hashMode === 'files' || hashMode === 'modules') ? hashMode : (START_MODE === 'files' ? 'files' : 'modules');
resize();
load(initialMode);
</script>
</body>
</html>
"""


def render_html(index, top=80, start_mode="modules"):
    payload = json.dumps(html_data(index, top), ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")
    mode = start_mode if start_mode in ("modules", "files") else "modules"
    return (
        HTML_TEMPLATE
        .replace("/*__ATLAS_DATA__*/null", payload)
        .replace("__START_MODE__", mode)
    )


def write_outputs(root, index, cfg):
    idx_dir = root / INDEX_DIR
    idx_dir.mkdir(parents=True, exist_ok=True)
    mermaid = render_mermaid(index, "modules")
    (idx_dir / "diagram.mmd").write_text(mermaid, encoding="utf-8")
    html_doc = render_html(index, 80)
    (idx_dir / "atlas.html").write_text(html_doc, encoding="utf-8")
    map_path = root / (cfg.get("map_file") or DEFAULT_MAP)
    map_path.write_text(render_map(index, int(cfg.get("budget", 3500))) + "\n", encoding="utf-8")
    return map_path, idx_dir / "diagram.mmd", idx_dir / "atlas.html"


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def find_symbols(index, query, kind=None):
    q = query.lower()
    out = []
    rank = index.get("pagerank", {})
    for rel, f in index["files"].items():
        for s in f.get("symbols", []):
            if kind and s.get("kind") != kind:
                continue
            name = s.get("name", "").lower()
            qual = s.get("qualname", "").lower()
            sig = s.get("signature", "").lower()
            if name == q:
                score = 100
            elif qual == q or qual.endswith("." + q):
                score = 90
            elif name.startswith(q):
                score = 70
            elif q in qual:
                score = 50
            elif q in sig:
                score = 30
            else:
                continue
            out.append((score, s))
    out.sort(key=lambda x: (-x[0], not x[1].get("exported"), -rank.get(x[1]["file"], 0)))
    return [s for _, s in out]


def callers_of(index):
    callers = defaultdict(set)
    callees = defaultdict(set)
    for e in index.get("edges", []):
        if e.get("k") == "c":
            callers[e["t"]].add(e["f"])
            callees[e["f"]].add(e["t"])
    return callers, callees


def cmd_where(index, symbol, limit=20, kind=None, as_json=False):
    matches = find_symbols(index, symbol, kind)
    if not matches:
        if as_json:
            print(json.dumps({"query": symbol, "matches": []}, ensure_ascii=False))
        else:
            print(f"No symbol matching '{symbol}'.")
            print(f"Try: rg -n \"{symbol}\" .   (the atlas only knows statically declared symbols)")
        return 1
    callers, callees = callers_of(index)
    rows = []
    for s in matches[:limit]:
        rows.append({
            "id": s["id"], "name": s["name"], "kind": s["kind"], "file": s["file"],
            "line": s["line"], "signature": s.get("signature", ""),
            "exported": s.get("exported", False),
            "callers": len(callers.get(s["id"], ())),
            "calls": len(callees.get(s["id"], ())),
            "doc": s.get("doc", ""),
        })
    if as_json:
        print(json.dumps({"query": symbol, "matches": rows}, ensure_ascii=False, indent=2))
        return 0
    out = [c(f"{len(matches)} match(es) for '{symbol}'", "36")]
    for r in rows:
        flag = c(" *", "33") if r["exported"] else "  "
        out.append(f"{r['file']}:{r['line']}{flag}  {c(r['kind'], '35')}  {r['signature']}")
        extra = []
        if r["callers"]:
            extra.append(f"{r['callers']} caller(s)")
        if r["calls"]:
            extra.append(f"{r['calls']} call(s)")
        if r["doc"]:
            extra.append(r["doc"])
        if extra:
            out.append("    " + c(" · ".join(extra), "90"))
    if len(matches) > limit:
        out.append(c(f"… {len(matches) - limit} more; use --limit", "90"))
    text = "\n".join(out)
    print(text)
    print(c(f"~{est_tokens(text)} tokens", "90"))
    return 0


def reverse_levels(importers, start, depth):
    levels = {start: 0}
    frontier = [start]
    for d in range(depth):
        nxt = []
        for n in frontier:
            for p in importers.get(n, ()):
                if p not in levels:
                    levels[p] = d + 1
                    nxt.append(p)
        frontier = nxt
    return levels


def resolve_target(index, target):
    files = index["files"]
    t = target.replace("\\", "/").strip().lstrip("./")
    if t in files:
        return "file", t, None
    syms = find_symbols(index, t)
    if syms:
        return "symbol", syms[0]["file"], syms[0]
    # path prefix / module
    pref = [rel for rel in files if rel.startswith(t.rstrip("/") + "/")]
    if pref:
        return "module", t.rstrip("/"), None
    if t in {f.get("module") for f in files.values()}:
        return "module", t, None
    return None, None, None


def cmd_impact(index, target, depth=2, limit=30, as_json=False):
    files = index["files"]
    kind, value, sym = resolve_target(index, target)
    if not kind:
        print(f"Target '{target}' not found. Try `atlas where {target}`.")
        return 1
    if kind == "file":
        targets = [value]
        label = value
    elif kind == "symbol":
        targets = [value]
        label = sym["id"]
    else:
        targets = [rel for rel in files if files[rel].get("module") == value or rel.startswith(value + "/")]
        label = value + "/"

    importers = importers_map(index)
    callers, callees = callers_of(index)
    all_levels = {}
    for t in targets:
        for k, v in reverse_levels(importers, t, depth).items():
            all_levels[k] = min(all_levels.get(k, 99), v)

    direct = [k for k, v in all_levels.items() if v == 1]
    transitive = [k for k, v in all_levels.items() if v >= 2]
    direct.sort(key=lambda r: (is_test_file(r), -index.get("pagerank", {}).get(r, 0)))
    # Tests often import a package entrypoint which re-exports the target, so
    # walk one level further than the risk radius before giving up.
    test_levels = {}
    for t in targets:
        for k, v in reverse_levels(importers, t, max(depth, 4)).items():
            test_levels[k] = min(test_levels.get(k, 99), v)
    tests = sorted({k for k in test_levels if is_test_file(k)})
    # Name-based test heuristic catches tests that exercise the module
    # without importing it directly.
    stems = {Path(t).stem.lower().replace("test_", "").replace("_test", "") for t in targets}
    for rel in files:
        if is_test_file(rel) and any(s and s in rel.lower() for s in stems):
            tests.append(rel)
    tests = sorted(set(tests))

    if kind == "symbol":
        target_syms = [sym]
    else:
        target_syms = [s for t in targets for s in files[t].get("symbols", [])]
    incoming = []
    for s in target_syms:
        for caller in callers.get(s["id"], ()):
            caller_file = caller.split("::", 1)[0]
            # For a file/module target, calls inside the same file are not
            # external impact; for a symbol target they are still useful.
            if kind != "symbol" and caller_file in targets:
                continue
            incoming.append((s, caller))
    exported = sum(1 for s in target_syms if s.get("exported"))
    churn = sum(index.get("churn", {}).get(t, 0) for t in targets)
    score = min(100, round(len(direct) * 6 + len(transitive) * 2 + min(len(incoming), 30) * 1.2 + min(exported, 20) + min(churn, 30) * 0.8))
    level = "LOW" if score < 30 else "MEDIUM" if score < 60 else "HIGH"

    if as_json:
        print(json.dumps({
            "target": label, "kind": kind, "risk": score, "level": level,
            "direct_importers": direct[:limit], "transitive": transitive[:limit],
            "tests": tests[:limit],
            "incoming_calls": [{"symbol": s["id"], "caller": caller} for s, caller in incoming[:limit]],
        }, ensure_ascii=False, indent=2))
        return 0

    out = [c(f"Impact: {label}", "36")]
    out.append(f"Risk: {c(str(score) + '/100 ' + level, '31' if level == 'HIGH' else '33' if level == 'MEDIUM' else '32')}  "
               f"({len(direct)} direct, {len(transitive)} transitive, {exported} exported symbols, churn {churn})")
    if direct:
        out.append(c("\nDirect importers", "1"))
        for rel in direct[:limit]:
            out.append(f"  {rel}")
    if len(transitive) > len(direct):
        out.append(c("\nTransitive (depth ≤ %d)" % depth, "1"))
        for rel in [x for x in transitive if x not in direct][:limit]:
            out.append(f"  {rel}  {c('(depth %d)' % all_levels[rel], '90')}")
    if incoming:
        out.append(c("\nIncoming calls (symbols at risk)", "1"))
        seen = set()
        for s, caller in incoming:
            key = (s["id"], caller)
            if key in seen:
                continue
            seen.add(key)
            out.append(f"  {caller}  →  {s['name']}  ({s['file']}:{s['line']})")
            if len(seen) >= limit:
                break
    if tests:
        out.append(c("\nTests to run", "1"))
        for rel in tests[:limit]:
            out.append(f"  {rel}")
    else:
        out.append(c("\nNo tests import this target (heuristic: none found).", "90"))
    text = "\n".join(out)
    print(text)
    print(c(f"\n~{est_tokens(text)} tokens", "90"))
    return 0


def cmd_path(index, a, b, max_depth=8, as_json=False):
    files = index["files"]
    ka, va, _ = resolve_target(index, a)
    kb, vb, _ = resolve_target(index, b)
    if not ka or not kb:
        print(f"Cannot resolve '{a if not ka else b}'.")
        return 1
    start = va if ka != "module" else None
    end = vb if kb != "module" else None
    if not start or not end:
        print("Path query needs two files or symbols (module endpoints are ambiguous).")
        return 1
    graph = {rel: f.get("imports", []) for rel, f in files.items()}
    rev = defaultdict(list)
    for rel, deps in graph.items():
        for d in deps:
            rev[d].append(rel)

    def bfs(adj, s, t):
        q = deque([(s, [s])])
        seen = {s}
        while q:
            node, path = q.popleft()
            if node == t:
                return path
            if len(path) > max_depth:
                continue
            for nxt in adj.get(node, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    q.append((nxt, path + [nxt]))
        return None

    path = bfs(graph, start, end)
    direction = "depends on"
    if not path:
        path = bfs(rev, start, end)
        direction = "is imported by"
    if not path:
        print(f"No path between {start} and {end} within depth {max_depth}.")
        return 1
    if as_json:
        print(json.dumps({"from": start, "to": end, "direction": direction, "path": path}, indent=2))
        return 0
    print(c(f"{start} {direction} … {end}", "36"))
    for i, rel in enumerate(path):
        arrow_txt = "→ " if i else "  "
        print(f"{arrow_txt}{rel}")
    print(c(f"length {len(path) - 1} hop(s)", "90"))
    return 0


def cmd_pack(index, focus, budget=8000, depth=1, include_tests=False):
    files = index["files"]
    kind, value, sym = resolve_target(index, focus)
    if not kind:
        print(f"Focus '{focus}' not found. Try `atlas map` or `atlas where {focus}`.")
        return 1
    if kind == "file":
        seed = [value]
    elif kind == "symbol":
        seed = [value]
    else:
        seed = [rel for rel in files if rel.startswith(value + "/") or files[rel].get("module") == value]
    if not seed:
        print("No files matched.")
        return 1
    seen = set(seed)
    frontier = list(seed)
    for _ in range(depth):
        nxt = []
        for rel in frontier:
            for t in files[rel].get("imports", []):
                if t not in seen:
                    seen.add(t)
                    nxt.append(t)
        frontier = nxt
    ordered = list(dict.fromkeys(seed + sorted(seen - set(seed), key=lambda r: -index.get("pagerank", {}).get(r, 0))))
    if not include_tests:
        ordered = [r for r in ordered if r in seed or not is_test_file(r)]

    out = [f"# Pack: {focus}", f"> budget {budget} tokens · {len(ordered)} files · index {index.get('generated','')}", ""]
    used = est_tokens("\n".join(out))
    included = 0
    for rel in ordered:
        content = read_text(Path(index["root"]) / rel) if Path(index["root"]).exists() else ""
        if not content:
            continue
        remaining = budget - used
        if remaining < 120:
            out.append(f"… budget reached; {len(ordered) - included} file(s) omitted.")
            break
        limit_chars = remaining * 4
        snippet = content
        truncated = False
        if len(snippet) > limit_chars:
            snippet = snippet[:max(0, limit_chars - 80)]
            truncated = True
        fence = files[rel].get("lang", "")
        out.append(f"## {rel}  ({human(files[rel].get('loc',0))} LOC)")
        out.append(f"```{fence}")
        out.append(snippet.rstrip())
        if truncated:
            out.append("\n… truncated by budget")
        out.append("```")
        out.append("")
        used = est_tokens("\n".join(out))
        included += 1
    text = "\n".join(out)
    text += f"\n\n_~{est_tokens(text)} tokens · {included} files_"
    print(text)
    return 0


# ---------------------------------------------------------------------------
# Diagrams and diagnostics
# ---------------------------------------------------------------------------

def cmd_diagram(root, index, files_mode=False, top=60, open_browser=False, as_json=False):
    mode = "files" if files_mode else "modules"
    mermaid = render_mermaid(index, mode, top)
    p = root / INDEX_DIR / "diagram.mmd"
    p.write_text(mermaid, encoding="utf-8")
    html_doc = render_html(index, top, mode)
    h = root / INDEX_DIR / "atlas.html"
    h.write_text(html_doc, encoding="utf-8")
    payload = html_data(index, top)[mode]
    if as_json:
        print(json.dumps({
            "mermaid": str(p),
            "html": str(h),
            "nodes": len(payload["nodes"]),
            "links": len(payload["links"]),
            "mode": mode,
        }, indent=2))
    else:
        print(f"mermaid : {p}")
        print(f"html    : {h}")
        print(f"mode    : {mode} · {len(payload['nodes'])} nodes · {len(payload['links'])} links")
    if open_browser:
        try:
            webbrowser.open(h.resolve().as_uri() + ("#files" if mode == "files" else ""))
        except Exception:
            pass
    return 0


def cmd_doctor(root, index, fix=False):
    if not index:
        print("NO INDEX. Run: python atlas.py build")
        return 2
    files = index["files"]
    changed, missing = [], []
    for rel, f in files.items():
        p = root / rel
        if not p.exists():
            missing.append(rel)
            continue
        try:
            st = p.stat()
        except OSError:
            missing.append(rel)
            continue
        if st.st_size != f.get("size") or int(st.st_mtime) != int(f.get("mtime", 0)):
            changed.append(rel)
    present = {rel for rel, _, _, _ in scan_files(root, load_config(root))}
    new = sorted(present - set(files))
    head = git(root, "rev-parse", "--short", "HEAD") if (root / ".git").exists() else ""
    stats = index.get("stats", {})
    # A new commit alone does not invalidate the index: file size/mtime and the
    # tracked file set are the real freshness signals. Treating every HEAD move
    # as stale made a committed CODEATLAS.md permanently stale.
    stale = bool(changed or missing or new)
    print(c("CodeAtlas doctor", "36"))
    print(f"  index      : {index_path(root)}")
    print(f"  generated  : {index.get('generated')}  (build {stats.get('build_ms',0)} ms)")
    print(f"  commit     : {index.get('git_head') or 'n/a'}  →  now {head or 'n/a'}")
    print(f"  files      : {stats.get('files',0)} indexed · {stats.get('symbols',0)} symbols · {stats.get('edges',0)} edges")
    print(f"  coverage   : {stats.get('files',0) - len(missing)}/{stats.get('files',0)} present · {stats.get('parse_errors',0)} parse error(s)")
    if stats.get("error_samples"):
        for e in stats["error_samples"][:5]:
            print(f"    - {e}")
    print(f"  changes    : {len(changed)} modified · {len(new)} new · {len(missing)} missing")
    if changed[:8]:
        for rel in changed[:8]:
            print(f"    ~ {rel}")
    if new[:8]:
        for rel in new[:8]:
            print(f"    + {rel}")
    if missing[:8]:
        for rel in missing[:8]:
            print(f"    - {rel}")
    print(f"  verdict    : {c('STALE' if stale else 'FRESH', '33' if stale else '32')}")
    if stale and fix:
        print("  fixing     : rebuilding…")
        cfg = load_config(root)
        idx = build_index(root, cfg, full=False)
        write_index(root, idx)
        write_outputs(root, idx, cfg)
        print("  fixed      : index rebuilt")
        return 0
    return 1 if stale else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def add_common(p):
    p.add_argument("-C", "--root", default=None, help="repository root (default: auto-detect)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--no-color", action="store_true", help="disable ANSI colors")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        prog="atlas",
        description="CodeAtlas - a map before the read. Lightweight codebase atlas for AI agents.",
    )
    parser.add_argument("--version", action="version", version=f"CodeAtlas {VERSION}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create config, .gitignore entry, and build")
    add_common(p)
    p.add_argument("--force", action="store_true")
    p.add_argument("--no-build", action="store_true")
    p.add_argument("--no-git", action="store_true")

    p = sub.add_parser("build", help="build the index (incremental)")
    add_common(p)
    p.add_argument("--full", action="store_true", help="ignore cache and reparse everything")
    p.add_argument("--no-git", action="store_true", help="skip git churn")

    p = sub.add_parser("update", help="refresh the index incrementally")
    add_common(p)
    p.add_argument("--no-git", action="store_true")

    p = sub.add_parser("map", help="print the compact map")
    add_common(p)
    p.add_argument("--budget", type=int, default=None)
    p.add_argument("--write", default=None, help="write to a file instead of stdout")

    p = sub.add_parser("where", help="locate a symbol")
    add_common(p)
    p.add_argument("symbol")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--kind", default=None, help="function | class | type")

    p = sub.add_parser("impact", help="blast radius for a file, symbol, or module")
    add_common(p)
    p.add_argument("target")
    p.add_argument("--depth", type=int, default=2)
    p.add_argument("--limit", type=int, default=30)

    p = sub.add_parser("path", help="shortest dependency path between two files/symbols")
    add_common(p)
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--max-depth", type=int, default=8)

    p = sub.add_parser("pack", help="pack related files under a token budget")
    add_common(p)
    p.add_argument("focus")
    p.add_argument("--budget", type=int, default=8000)
    p.add_argument("--depth", type=int, default=1)
    p.add_argument("--include-tests", action="store_true")

    p = sub.add_parser("diagram", help="write Mermaid + interactive HTML map")
    add_common(p)
    p.add_argument("--files", action="store_true", help="file-level instead of module-level")
    p.add_argument("--top", type=int, default=60)
    p.add_argument("--open", action="store_true")

    p = sub.add_parser("doctor", help="check index freshness and coverage")
    add_common(p)
    p.add_argument("--fix", action="store_true")

    p = sub.add_parser("stats", help="summary statistics")
    add_common(p)

    args = parser.parse_args(argv)
    if getattr(args, "no_color", False):
        global USE_COLOR
        USE_COLOR = False

    root = find_root(getattr(args, "root", None))

    if args.cmd == "init":
        cfgp = root / CONFIG_NAME
        if cfgp.exists() and not args.force:
            print(f"config exists: {cfgp}")
        else:
            cfgp.write_text(json.dumps({
                "exclude": [],
                "include": [],
                "max_file_kb": 512,
                "module_depth": 2,
                "budget": 3500,
                "entrypoints": [],
                "git_churn": True,
            }, indent=2) + "\n", encoding="utf-8")
            print(f"wrote {cfgp}")
        gi = root / ".gitignore"
        marker = INDEX_DIR + "/"
        if gi.exists():
            txt = read_text(gi)
        else:
            txt = ""
        if marker not in txt.splitlines():
            with open(gi, "a", encoding="utf-8") as fh:
                if txt and not txt.endswith("\n"):
                    fh.write("\n")
                fh.write(marker + "\n")
            print(f"updated {gi}")
        if args.no_build:
            return 0
        cfg = load_config(root)
        idx = build_index(root, cfg, full=True, use_git=not args.no_git)
        write_index(root, idx)
        paths = write_outputs(root, idx, cfg)
        print_summary(idx, paths)
        return 0

    if args.cmd in ("build", "update"):
        cfg = load_config(root)
        idx = build_index(root, cfg, full=getattr(args, "full", False), use_git=not getattr(args, "no_git", False))
        write_index(root, idx)
        paths = write_outputs(root, idx, cfg)
        print_summary(idx, paths)
        return 0

    index = load_index(root)
    if args.cmd == "map":
        text = render_map(index, args.budget or int(index.get("config", {}).get("budget", 3500)))
        if args.write:
            Path(args.write).write_text(text + "\n", encoding="utf-8")
            print(f"wrote {args.write}")
        else:
            print(text)
        return 0

    if args.cmd == "where":
        return cmd_where(index, args.symbol, args.limit, args.kind, args.json)

    if args.cmd == "impact":
        return cmd_impact(index, args.target, args.depth, args.limit, args.json)

    if args.cmd == "path":
        return cmd_path(index, args.a, args.b, args.max_depth, args.json)

    if args.cmd == "pack":
        return cmd_pack(index, args.focus, args.budget, args.depth, args.include_tests)

    if args.cmd == "diagram":
        return cmd_diagram(root, index, args.files, args.top, args.open, args.json)

    if args.cmd == "doctor":
        return cmd_doctor(root, index, args.fix)

    if args.cmd == "stats":
        stats = index.get("stats", {})
        if args.json:
            print(json.dumps({**stats, "root": index.get("root"), "generated": index.get("generated")}, ensure_ascii=False, indent=2))
        else:
            print(c("CodeAtlas stats", "36"))
            print(f"  root       : {index.get('root')}")
            print(f"  generated  : {index.get('generated')}  · build {stats.get('build_ms',0)} ms")
            print(f"  files      : {stats.get('files',0)}  ({stats.get('reused',0)} reused)")
            print(f"  lines      : {human(stats.get('loc',0))}")
            print(f"  symbols    : {stats.get('symbols',0)}")
            print(f"  edges      : {stats.get('edges',0)}")
            print(f"  tests      : {stats.get('tests',0)}  · command: {stats.get('test_command') or 'n/a'}")
            print(f"  languages  : " + ", ".join(f"{k} {v}" for k, v in stats.get("languages", {}).items()))
            print(f"  errors     : {stats.get('parse_errors',0)}")
        return 0

    return 0


def print_summary(index, paths):
    stats = index["stats"]
    print(c(f"CodeAtlas built in {stats['build_ms']} ms", "32"))
    print(f"  {stats['files']} files · {human(stats['loc'])} LOC · {stats['symbols']} symbols · {stats['edges']} edges"
          + (f" · {stats['reused']} reused" if stats.get("reused") else ""))
    print(f"  map     : {paths[0]}")
    print(f"  mermaid : {paths[1]}")
    print(f"  html    : {paths[2]}")
    if stats.get("parse_errors"):
        print(c(f"  warnings: {stats['parse_errors']} file(s) failed to parse (see `atlas stats`)", "33"))


if __name__ == "__main__":
    raise SystemExit(main())
