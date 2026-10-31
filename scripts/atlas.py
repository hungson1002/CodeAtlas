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

VERSION = "1.0.0"
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
    map_name = (cfg.get("map_file") or DEFAULT_MAP).replace("\\", "/")
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        dirnames[:] = sorted(
            d for d in dirnames
            if not excluded_by((rel_dir + "/" + d) if rel_dir != "." else d, excludes)
            and not d.startswith(".code-atlas")
        )
        for fn in sorted(filenames):
            rel = fn if rel_dir == "." else f"{rel_dir}/{fn}"
            if rel == map_name:
                continue
            if excluded_by(rel, excludes):
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
        lines.append(f"> Refresh: `python scripts/atlas.py update` · Query: `python scripts/atlas.py where <symbol>`")
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
    module_links = []
    for m, dd in deps.items():
        for t, w in dd.items():
            if m in mods and t in mods:
                module_links.append({"s": m, "t": t, "w": w})

    # File view is a code map: docs/config nodes are useful in the module
    # graph and search, but as isolated dots they add noise.  Keep connected
    # code files when there are enough of them so fitView can zoom in.
    pool = {rel: f for rel, f in files.items() if f.get("lang") in CODE_LANGS}
    edge_files = set()
    for e in index.get("edges", []):
        if e.get("k") == "i":
            edge_files.add(e["f"])
            edge_files.add(e["t"])
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
            "symbols": [s["name"] for s in f.get("symbols", []) if s.get("exported")][:10],
            "deps": [t for t in f.get("imports", []) if t in sel_set][:10],
        })
    file_links = []
    for rel in selected:
        for t in files[rel].get("imports", []):
            if t in sel_set:
                file_links.append({"s": rel, "t": t, "w": 1})

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
:root{--bg:#0b1020;--panel:#0f1730;--line:#22315c;--ink:#e8eefc;--muted:#8ea0c8;--accent:#5eead4}
*{box-sizing:border-box}
html,body{height:100%;margin:0;overflow:hidden;background:radial-gradient(1100px 700px at 75% -15%,#1b2a5a 0%,#0b1020 58%);color:var(--ink);font:14px/1.45 ui-sans-serif,system-ui,"Segoe UI",Roboto,sans-serif}
#app{display:flex;height:100%}
#stage{position:relative;flex:1;min-width:0}
canvas{display:block;width:100%;height:100%;cursor:grab}
canvas.dragging{cursor:grabbing}
header{position:absolute;left:0;right:0;top:0;display:flex;align-items:center;gap:8px 10px;padding:14px 18px;pointer-events:none;flex-wrap:wrap}
header>*{pointer-events:auto}
h1{font-size:15px;margin:0 8px 0 0;letter-spacing:.4px;white-space:nowrap;flex:0 0 auto}
h1 b{color:var(--accent)}
.badge{font-size:11px;color:var(--muted);border:1px solid var(--line);padding:3px 8px;border-radius:999px;white-space:nowrap;background:rgba(15,23,48,.6);flex:0 0 auto;max-width:280px;overflow:hidden;text-overflow:ellipsis}
#search{background:rgba(15,23,48,.85);border:1px solid var(--line);color:var(--ink);border-radius:9px;padding:7px 11px;outline:none;width:220px;min-width:140px;font-size:13px;flex:0 1 220px}
#search:focus{border-color:#3b5bb5}
#search::placeholder{color:#61739b}
button{background:rgba(15,23,48,.85);border:1px solid var(--line);color:var(--ink);border-radius:9px;padding:7px 11px;cursor:pointer;font-size:12px}
button:hover{border-color:#3b5bb5}
button.on{background:#17345f;border-color:#4f7ad6;color:#cfe0ff}
#panel{width:330px;flex:0 0 330px;border-left:1px solid var(--line);background:rgba(10,16,32,.78);backdrop-filter:blur(10px);padding:18px;overflow:auto}
#panel h2{font-size:13px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);margin:0 0 10px}
#panel .big{font-size:16px;font-weight:600;word-break:break-word;margin:0 0 4px}
#panel .sub{color:var(--muted);font-size:12px;margin:0 0 14px;word-break:break-word}
.kv{display:grid;grid-template-columns:110px 1fr;gap:6px 10px;font-size:12.5px;margin:0 0 16px}
.kv span:nth-child(odd){color:var(--muted)}
.kv span:nth-child(even){word-break:break-word}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 16px}
.chip{font-size:11px;border:1px solid var(--line);border-radius:999px;padding:2px 8px;color:#c9d6f5;background:rgba(23,52,95,.35)}
.chip.link{cursor:pointer}
.chip.link:hover{border-color:#4f7ad6}
#legend{position:absolute;left:16px;bottom:14px;display:flex;flex-wrap:wrap;gap:8px 12px;max-width:60%;font-size:11px;color:var(--muted)}
#legend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:4px;vertical-align:-1px}
#hint{position:absolute;right:16px;bottom:14px;font-size:11px;color:#5c6d93}
#tooltip{position:absolute;pointer-events:none;background:#0c1428;border:1px solid var(--line);border-radius:8px;padding:6px 9px;font-size:12px;opacity:0;transition:opacity .12s;white-space:nowrap;z-index:5}
hr{border:0;border-top:1px solid var(--line);margin:16px 0}
.small{font-size:11.5px;color:var(--muted)}
a{color:#7dd3fc;text-decoration:none}
</style>
</head>
<body>
<div id="app">
  <div id="stage">
    <canvas id="graph"></canvas>
    <header>
      <h1>Code<b>Atlas</b></h1>
      <span class="badge" id="repo"></span>
      <span class="badge" id="stats"></span>
      <input id="search" placeholder="Search module / file / symbol…" autocomplete="off">
      <button id="mode-modules" class="on">Modules</button>
      <button id="mode-files">Files</button>
      <button id="reset">Reset view</button>
      <button id="labels" class="on">Labels</button>
    </header>
    <div id="legend"></div>
    <div id="hint">scroll = zoom · drag = pan · click = inspect</div>
    <div id="tooltip"></div>
  </div>
  <aside id="panel"></aside>
</div>
<script>
const DATA = /*__ATLAS_DATA__*/null;
const LANG = {"python":"#4b8bbe","typescript":"#4f9cf0","javascript":"#e8d44d","go":"#00add8","rust":"#dea584","java":"#c96a3b","kotlin":"#a97bff","csharp":"#4f9a58","ruby":"#b03a4a","php":"#6b7cc9","c":"#8a93a8","cpp":"#e05a7a","swift":"#f05138","scala":"#c22d40","lua":"#5a7fd8","shell":"#89e051","markdown":"#5b7fb0","config":"#6b7280","sql":"#e38c00"};
const canvas = document.getElementById('graph');
const ctx = canvas.getContext('2d');
const panel = document.getElementById('panel');
const tooltip = document.getElementById('tooltip');
const search = document.getElementById('search');
const state = {mode:'modules',nodes:[],links:[],byId:new Map(),view:{x:0,y:0,k:1},selected:null,hover:null,labels:true,query:'',w:0,h:0,anim:0};

const fmt = n => n>=1e6?(n/1e6).toFixed(1)+'M':n>=1e3?(n/1e3).toFixed(1)+'k':String(n);
const clamp = (v,a,b) => Math.max(a,Math.min(b,v));

function topLang(n){
  if(!n.langs) return n.lang;
  const e = Object.entries(n.langs).sort((a,b)=>b[1]-a[1])[0];
  return e?e[0]:'config';
}
function colorOf(n){ return LANG[topLang(n)] || '#7dd3fc'; }
function radiusOf(n){
  if(state.mode==='modules') return clamp(9+Math.sqrt(n.loc||1)/2.2,10,30);
  return clamp(4.5+Math.sqrt(n.loc||1)/1.8,5,22);
}
function matches(n){
  const q=state.query.trim().toLowerCase();
  if(!q) return true;
  if((n.id||'').toLowerCase().includes(q)) return true;
  if((n.label||'').toLowerCase().includes(q)) return true;
  return (n.symbols||[]).some(s=>s.toLowerCase().includes(q));
}
function screenPos(n){
  return {x: state.w/2 + state.view.x + n.x*state.view.k, y: state.h/2 + state.view.y + n.y*state.view.k};
}

function load(mode){
  state.mode=mode; state.selected=null;
  const g=DATA[mode];
  const nodes=g.nodes.map((n,i)=>{
    const a=i*2.399963, r=60+Math.sqrt(i+1)*26;
    return Object.assign({},n,{x:Math.cos(a)*r+(Math.random()-.5)*10,y:Math.sin(a)*r+(Math.random()-.5)*10,vx:0,vy:0});
  });
  nodes.forEach(n=>{n.r=radiusOf(n);});
  const byId=new Map(nodes.map(n=>[n.id,n]));
  const links=g.links.filter(l=>byId.has(l.s)&&byId.has(l.t)).map(l=>({s:l.s,t:l.t,w:l.w||1,a:byId.get(l.s),b:byId.get(l.t)}));
  state.nodes=nodes; state.links=links; state.byId=byId; state.view={x:0,y:0,k:1};
  for(let i=0;i<280;i++) tick(0.95);
  fitView();
  animate();
  updateHead(); showDefault();
}
function fitView(){
  if(!state.nodes.length || !state.w) return;
  let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
  for(const n of state.nodes){
    minX=Math.min(minX,n.x-n.r); maxX=Math.max(maxX,n.x+n.r);
    minY=Math.min(minY,n.y-n.r); maxY=Math.max(maxY,n.y+n.r);
  }
  const pad=70;
  const w=Math.max(1,maxX-minX), h=Math.max(1,maxY-minY);
  const k=Math.min((state.w-pad*2)/w,(state.h-pad*2)/h,2);
  state.view.k=Math.max(0.22,k);
  state.view.x=-(minX+maxX)/2*state.view.k;
  state.view.y=-(minY+maxY)/2*state.view.k;
}
function tick(alpha){
  const {nodes,links}=state, N=nodes.length;
  if(!N) return;
  const rep = state.mode==='modules' ? 1800 : 5200;
  const rest = state.mode==='modules' ? 110 : 150;
  const gravity = state.mode==='modules' ? 0.0018 : 0.0011;
  for(let i=0;i<N;i++){
    const a=nodes[i];
    for(let j=i+1;j<N;j++){
      const b=nodes[j];
      let dx=a.x-b.x, dy=a.y-b.y, d2=dx*dx+dy*dy;
      if(d2<1){dx=Math.random()-.5;dy=Math.random()-.5;d2=1;}
      if(d2>360000) continue;
      const f=rep*alpha/d2;
      a.vx+=dx*f; a.vy+=dy*f; b.vx-=dx*f; b.vy-=dy*f;
    }
  }
  for(const l of links){
    const dx=l.b.x-l.a.x, dy=l.b.y-l.a.y, d=Math.hypot(dx,dy)||1;
    const f=(d-rest)*0.005*alpha, ux=dx/d, uy=dy/d;
    l.a.vx+=ux*f; l.a.vy+=uy*f; l.b.vx-=ux*f; l.b.vy-=uy*f;
  }
  for(const n of nodes){
    n.vx+=(-n.x)*gravity*alpha; n.vy+=(-n.y)*gravity*alpha;
    n.vx*=0.86; n.vy*=0.86; n.x+=n.vx; n.y+=n.vy;
  }
}
function animate(){
  cancelAnimationFrame(state.anim);
  let a=1;
  const step=()=>{
    if(a<0.025){state.anim=0;draw();return;}
    tick(a); a*=0.985; draw();
    state.anim=requestAnimationFrame(step);
  };
  state.anim=requestAnimationFrame(step);
}
function resize(){
  const r=canvas.getBoundingClientRect(), dpr=window.devicePixelRatio||1;
  state.w=r.width; state.h=r.height;
  canvas.width=Math.round(r.width*dpr); canvas.height=Math.round(r.height*dpr);
  ctx.setTransform(dpr,0,0,dpr,0,0);
  draw();
}
window.addEventListener('resize',resize);

function arrow(x1,y1,x2,y2,r2){
  const dx=x2-x1, dy=y2-y1, d=Math.hypot(dx,dy)||1;
  const ex=x2-dx/d*r2, ey=y2-dy/d*r2;
  const ax=ex-dx/d*7, ay=ey-dy/d*7;
  ctx.beginPath(); ctx.moveTo(ex,ey); ctx.lineTo(ax-dy/d*4,ay+dx/d*4); ctx.lineTo(ax+dy/d*4,ay-dx/d*4); ctx.closePath(); ctx.fill();
  return {x:ex,y:ey};
}
function draw(){
  if(!state.w) return;
  ctx.clearRect(0,0,state.w,state.h);
  const {nodes,links}=state, q=state.query.trim();
  // links first
  for(const l of links){
    const a=screenPos(l.a), b=screenPos(l.b);
    const dim = q && !(matches(l.a)||matches(l.b));
    ctx.globalAlpha = dim?0.05:0.16;
    ctx.strokeStyle = '#7fa8ff';
    ctx.lineWidth = Math.max(.5, Math.min(2.2, (l.w||1)*0.45*state.view.k));
    ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke();
    if(state.view.k>0.8){
      ctx.globalAlpha = dim?0.05:0.28; ctx.fillStyle='#7fa8ff';
      arrow(a.x,a.y,b.x,b.y,l.b.r*state.view.k+1);
    }
  }
  // nodes
  for(const n of nodes){
    const p=screenPos(n), r=Math.max(3,n.r*state.view.k);
    const on=matches(n), sel=n===state.selected;
    ctx.globalAlpha = on?1:0.14;
    ctx.beginPath(); ctx.arc(p.x,p.y,r,0,Math.PI*2);
    ctx.fillStyle=colorOf(n); ctx.fill();
    ctx.lineWidth = sel?2.4:1;
    ctx.strokeStyle = sel?'#ffffff':'rgba(255,255,255,.28)';
    ctx.stroke();
    if(state.labels && (state.mode==='modules' || state.view.k>1.15 || sel || (q&&on) || (n.rank||0)>0.025)){
      const label=n.label||n.id;
      ctx.font='600 11px ui-sans-serif,system-ui';
      ctx.textAlign='center'; ctx.textBaseline='top';
      ctx.globalAlpha = on?1:0.2;
      ctx.fillStyle='#dbe7ff';
      ctx.shadowColor='#050a16'; ctx.shadowBlur=6;
      ctx.fillText(label,p.x,p.y+r+3);
      ctx.shadowBlur=0;
    }
  }
  ctx.globalAlpha=1;
  drawLegend();
}
function drawLegend(){
  const langs=Object.entries(DATA.meta.languages||{}).slice(0,10);
  document.getElementById('legend').innerHTML=langs.map(([k,v])=>`<span><i style="background:${LANG[k]||'#7dd3fc'}"></i>${k} ${v}</span>`).join('');
}
function updateHead(){
  document.getElementById('repo').textContent=DATA.meta.repo;
  document.getElementById('stats').textContent=`${fmt(DATA.meta.files)} files · ${fmt(DATA.meta.loc)} LOC · ${fmt(DATA.meta.symbols)} symbols · ${DATA.meta.commit}`;
}
function showDefault(){
  panel.innerHTML=`<h2>CodeAtlas</h2>
  <p class="big">${DATA.meta.repo}</p>
  <p class="sub">Generated ${DATA.meta.generated} · v${DATA.meta.tool}</p>
  <div class="kv">
    <span>Files</span><span>${fmt(DATA.meta.files)}</span>
    <span>Lines</span><span>${fmt(DATA.meta.loc)}</span>
    <span>Symbols</span><span>${fmt(DATA.meta.symbols)}</span>
    <span>Edges</span><span>${fmt(DATA.meta.edges)}</span>
  </div>
  <h2>How to read</h2>
  <p class="small">Node size = lines of code. Color = dominant language. Arrows point from a file/module to what it imports. Click a node to inspect; use the search box to highlight a symbol.</p>
  <hr>
  <h2>Switch view</h2>
  <p class="small">Modules gives the architecture. Files gives the top ${DATA.files.nodes.length} connected code files by PageRank.</p>`;
}
function chip(text,fn){
  const el=document.createElement('span'); el.className='chip'+(fn?' link':''); el.textContent=text;
  if(fn) el.onclick=fn; return el;
}
function select(n){
  state.selected=n; state.anim||draw();
  if(!n){showDefault();return;}
  const isFile=state.mode==='files';
  panel.innerHTML=`<h2>${isFile?'File':'Module'}</h2>
  <p class="big">${n.label||n.id}</p>
  <p class="sub">${isFile?n.path:n.id}</p>
  <div class="kv">
    <span>Files</span><span>${n.files??1}</span>
    <span>Lines</span><span>${fmt(n.loc||0)}</span>
    <span>Influence</span><span>${(n.rank||0).toFixed(4)}</span>
    ${isFile?`<span>Module</span><span>${n.module}</span>`:''}
    ${isFile?`<span>Test file</span><span>${n.tests?'yes':'no'}</span>`:''}
  </div>`;
  if(n.symbols&&n.symbols.length){
    panel.insertAdjacentHTML('beforeend','<h2>Key symbols</h2><div class="chips" id="sym"></div>');
    const box=panel.querySelector('#sym');
    n.symbols.forEach(s=>box.appendChild(chip(s,()=>{search.value=s;state.query=s;draw();})));
  }
  if(n.deps&&n.deps.length){
    panel.insertAdjacentHTML('beforeend','<h2>Depends on</h2><div class="chips" id="deps"></div>');
    const box=panel.querySelector('#deps');
    n.deps.forEach(d=>box.appendChild(chip(d,()=>{const t=state.byId.get(d); if(t) select(t);})));
  }
  panel.insertAdjacentHTML('beforeend',`<hr><p class="small">Tip: click another node to keep exploring. <a href="#" id="clear">clear selection</a></p>`);
  const cl=panel.querySelector('#clear'); if(cl) cl.onclick=(e)=>{e.preventDefault();select(null);};
}
function hit(e){
  const r=canvas.getBoundingClientRect(), mx=e.clientX-r.left, my=e.clientY-r.top;
  for(let i=state.nodes.length-1;i>=0;i--){
    const n=state.nodes[i], p=screenPos(n), rr=Math.max(5,n.r*state.view.k);
    if((mx-p.x)**2+(my-p.y)**2<=rr*rr) return n;
  }
  return null;
}
let drag=null;
canvas.addEventListener('pointerdown',e=>{
  const n=hit(e);
  if(n){select(n);return;}
  drag={x:e.clientX,y:e.clientY,vx:state.view.x,vy:state.view.y};
  canvas.classList.add('dragging'); canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener('pointermove',e=>{
  if(drag){
    state.view.x=drag.vx+(e.clientX-drag.x);
    state.view.y=drag.vy+(e.clientY-drag.y);
    state.anim||draw();
    return;
  }
  const n=hit(e);
  state.hover=n;
  if(n){
    const p=screenPos(n), r=canvas.getBoundingClientRect();
    tooltip.style.opacity=1;
    tooltip.style.left=(e.clientX-r.left+14)+'px';
    tooltip.style.top=(e.clientY-r.top+12)+'px';
    tooltip.textContent=`${n.label||n.id} · ${fmt(n.loc||0)} LOC`+(n.files?` · ${n.files} files`:'');
  } else tooltip.style.opacity=0;
});
canvas.addEventListener('pointerup',()=>{drag=null;canvas.classList.remove('dragging');});
canvas.addEventListener('pointerleave',()=>{tooltip.style.opacity=0;});
canvas.addEventListener('wheel',e=>{
  e.preventDefault();
  const r=canvas.getBoundingClientRect(), mx=e.clientX-r.left, my=e.clientY-r.top;
  const k2=clamp(state.view.k*Math.exp(-e.deltaY*0.0012),0.22,4);
  const wx=(mx-(state.w/2+state.view.x))/state.view.k;
  const wy=(my-(state.h/2+state.view.y))/state.view.k;
  state.view.x=mx-state.w/2-wx*k2;
  state.view.y=my-state.h/2-wy*k2;
  state.view.k=k2;
  state.anim||draw();
},{passive:false});
search.addEventListener('input',()=>{state.query=search.value;state.anim||draw();});
document.getElementById('mode-modules').onclick=()=>setMode('modules');
document.getElementById('mode-files').onclick=()=>setMode('files');
function setMode(m){
  document.getElementById('mode-modules').classList.toggle('on',m==='modules');
  document.getElementById('mode-files').classList.toggle('on',m==='files');
  load(m);
}
document.getElementById('reset').onclick=()=>{fitView();state.anim||draw();};
document.getElementById('labels').onclick=e=>{state.labels=!state.labels;e.target.classList.toggle('on',state.labels);state.anim||draw();};
window.addEventListener('keydown',e=>{if(e.key==='Escape'){search.value='';state.query='';select(null);draw();}});
resize();
const startView=((new URLSearchParams(location.search).get('view')||location.hash.replace(/^#\/?/,''))==='files')?'files':'modules';
document.getElementById('mode-modules').classList.toggle('on',startView==='modules');
document.getElementById('mode-files').classList.toggle('on',startView==='files');
load(startView);
</script>
</body>
</html>
"""


def render_html(index, top=80):
    payload = json.dumps(html_data(index, top), ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")
    return HTML_TEMPLATE.replace("/*__ATLAS_DATA__*/null", payload)


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
    html_doc = render_html(index, top)
    h = root / INDEX_DIR / "atlas.html"
    h.write_text(html_doc, encoding="utf-8")
    if as_json:
        print(json.dumps({"mermaid": str(p), "html": str(h), "nodes": len(html_data(index, top)[mode]["nodes"])}, indent=2))
    else:
        print(f"mermaid : {p}")
        print(f"html    : {h}")
        print(f"mode    : {mode} · {len(html_data(index, top)[mode]['nodes'])} nodes")
    if open_browser:
        try:
            webbrowser.open(h.resolve().as_uri())
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
