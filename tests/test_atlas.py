"""End-to-end tests for CodeAtlas.

Run with:
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ATLAS = Path(__file__).resolve().parents[1] / "scripts" / "atlas.py"


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class AtlasCLITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="code-atlas-test-")
        cls.root = Path(cls.tmp.name) / "fixture"
        cls.root.mkdir(parents=True)

        write(cls.root, "app/__init__.py", "")
        write(
            cls.root,
            "app/main.py",
            '"""Entrypoint."""\n'
            "from . import helpers\n"
            "from services.auth import AuthService\n"
            "from services.user import UserRepo\n"
            "\n"
            "def main():\n"
            "    repo = UserRepo()\n"
            "    auth = AuthService(repo)\n"
            '    helpers.helper()\n'
            '    return auth.login("alice", "secret")\n',
        )
        write(cls.root, "app/helpers.py", 'def helper():\n    return "ok"\n')
        write(cls.root, "services/__init__.py", "")
        write(
            cls.root,
            "services/auth.py",
            "from utils.security import hash_password, verify_password\n"
            "\n"
            "class AuthService:\n"
            "    def __init__(self, repo):\n"
            "        self.repo = repo\n"
            "\n"
            "    def login(self, user, password):\n"
            "        record = self.repo.find(user)\n"
            "        if record and verify_password(password, record.password):\n"
            "            return self._token(record)\n"
            "        return None\n"
            "\n"
            "    def _token(self, record):\n"
            "        return hash_password(record.id)\n",
        )
        write(
            cls.root,
            "services/user.py",
            "class UserRepo:\n"
            "    def find(self, name):\n"
            "        return None\n"
            "\n"
            "    def save(self, user):\n"
            "        return user\n",
        )
        write(
            cls.root,
            "utils/security.py",
            "def hash_password(value):\n"
            '    return f"hashed:{value}"\n'
            "\n"
            "def verify_password(raw, hashed):\n"
            "    return hash_password(raw) == hashed\n",
        )
        write(
            cls.root,
            "web/types.ts",
            "export interface User {\n"
            "  id: string;\n"
            "  name: string;\n"
            "}\n",
        )
        write(
            cls.root,
            "web/api.ts",
            "import type { User } from './types';\n"
            "import express from 'express';\n"
            "\n"
            "export async function api(path: string, body: unknown): Promise<User | null> {\n"
            "  const res = await fetch(path, { method: 'POST', body: JSON.stringify(body) });\n"
            "  return res.ok ? res.json() : null;\n"
            "}\n",
        )
        write(
            cls.root,
            "web/auth.ts",
            "import { api } from './api';\n"
            "import type { User } from './types';\n"
            "\n"
            "export async function login(user: string, password: string): Promise<User | null> {\n"
            "  return api('/login', { user, password });\n"
            "}\n"
            "\n"
            "export function logout(): void {\n"
            "  localStorage.removeItem('token');\n"
            "}\n",
        )
        write(
            cls.root,
            "web/store.ts",
            "import type { User } from './types';\n"
            "\n"
            "export class SessionStore {\n"
            "  private current: User | null = null;\n"
            "\n"
            "  setUser(user: User): void {\n"
            "    this.current = user;\n"
            "  }\n"
            "\n"
            "  getUser(): User | null {\n"
            "    return this.current;\n"
            "  }\n"
            "}\n",
        )
        write(
            cls.root,
            "tests/test_auth.py",
            "from services.auth import AuthService\n"
            "\n"
            "def test_login_returns_none_for_unknown_user():\n"
            "    service = AuthService(repo=None)\n"
            "    assert service is not None\n",
        )
        write(cls.root, "README.md", "# Fixture\n\nA tiny repository.\n")
        write(
            cls.root,
            "examples/demo/index.js",
            "export function demo() {\n  return 'demo';\n}\n",
        )
        write(cls.root, ".env", "SECRET_KEY=do-not-index-me\n")
        write(cls.root, ".env.example", "SECRET_KEY=replace-me\n")
        write(cls.root, "credentials.json", '{"token": "fake"}\n')
        write(cls.root, "config/secrets.yaml", "token: fake\n")
        write(cls.root, "utils/secret_manager.py", "def rotate():\n    return None\n")
        write(cls.root, "node_modules/junk.js", "module.exports = 1;\n")
        write(cls.root, "dist/bundle.js", "console.log('generated');\n")
        write(cls.root, ".github/workflows/ci.yml", "name: ci\n")

        cls.build = cls.atlas("build", "--no-git")
        cls.index = json.loads(
            (cls.root / ".code-atlas" / "index.json").read_text(encoding="utf-8")
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    @classmethod
    def atlas(cls, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        env = dict(os.environ, NO_COLOR="1", PYTHONIOENCODING="utf-8")
        proc = subprocess.run(
            [sys.executable, str(ATLAS), *args],
            cwd=str(cls.root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=120,
        )
        if check and proc.returncode != 0:
            raise AssertionError(
                f"atlas {' '.join(args)} failed ({proc.returncode})\n"
                f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
        return proc

    def test_build_creates_outputs(self) -> None:
        self.assertEqual(self.build.returncode, 0, self.build.stderr)
        self.assertTrue((self.root / "CODEATLAS.md").exists())
        self.assertTrue((self.root / ".code-atlas" / "diagram.mmd").exists())
        self.assertTrue((self.root / ".code-atlas" / "atlas.html").exists())
        self.assertGreater(self.index["stats"]["files"], 0)
        self.assertGreater(self.index["stats"]["symbols"], 0)

    def test_excludes_secrets_and_generated_dirs(self) -> None:
        files = self.index["files"]
        self.assertNotIn(".env", files)
        self.assertNotIn("credentials.json", files)
        self.assertNotIn("config/secrets.yaml", files)
        self.assertNotIn("node_modules/junk.js", files)
        self.assertNotIn("dist/bundle.js", files)
        self.assertNotIn(".github/workflows/ci.yml", files)
        self.assertIn(".env.example", files)
        self.assertIn("utils/secret_manager.py", files)
        self.assertIn("app/main.py", files)
        self.assertIn("README.md", files)

    def test_python_relative_and_absolute_imports(self) -> None:
        main = self.index["files"]["app/main.py"]
        self.assertIn("app/helpers.py", main["imports"])
        self.assertIn("services/auth.py", main["imports"])
        self.assertIn("services/user.py", main["imports"])
        self.assertIn("utils/security.py", self.index["files"]["services/auth.py"]["imports"])

    def test_typescript_imports_and_class_methods(self) -> None:
        auth = self.index["files"]["web/auth.ts"]
        self.assertIn("web/api.ts", auth["imports"])
        self.assertIn("web/types.ts", auth["imports"])
        api = self.index["files"]["web/api.ts"]
        self.assertNotIn("express", api["imports"])
        self.assertIn("express", api["external"])
        names = {s["name"] for s in self.index["files"]["web/store.ts"]["symbols"]}
        self.assertIn("SessionStore", names)
        self.assertIn("setUser", names)
        self.assertIn("getUser", names)
        self.assertIn(
            "web/store.ts::SessionStore.setUser",
            {s["id"] for s in self.index["files"]["web/store.ts"]["symbols"]},
        )

    def test_call_edges_resolve(self) -> None:
        call_edges = {
            (e["f"], e["t"])
            for e in self.index["edges"]
            if e.get("k") == "c"
        }
        self.assertIn(
            ("app/main.py::main", "services/auth.py::AuthService.login"),
            call_edges,
        )
        self.assertIn(
            ("services/auth.py::AuthService.login", "utils/security.py::verify_password"),
            call_edges,
        )

    def test_map_contains_entrypoint_and_modules(self) -> None:
        proc = self.atlas("map", "--budget", "2500")
        self.assertIn("# CodeAtlas", proc.stdout)
        self.assertIn("## Start here", proc.stdout)
        self.assertIn("app/main.py", proc.stdout)
        self.assertIn("## Modules", proc.stdout)
        self.assertIn("services", proc.stdout)
        self.assertNotIn("examples/demo", proc.stdout)

    def test_where_json(self) -> None:
        proc = self.atlas("where", "AuthService.login", "--json")
        data = json.loads(proc.stdout)
        self.assertTrue(data["matches"])
        self.assertEqual(data["matches"][0]["file"], "services/auth.py")
        self.assertEqual(data["matches"][0]["name"], "login")
        self.assertEqual(data["matches"][0]["kind"], "function")

        broad = json.loads(self.atlas("where", "login", "--json").stdout)
        files = {m["file"] for m in broad["matches"]}
        self.assertIn("services/auth.py", files)
        self.assertIn("web/auth.ts", files)

    def test_where_unknown_returns_one(self) -> None:
        proc = self.atlas("where", "definitely_not_a_symbol_xyz", check=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("No symbol", proc.stdout)

    def test_impact_file(self) -> None:
        proc = self.atlas("impact", "services/auth.py", "--json")
        data = json.loads(proc.stdout)
        self.assertEqual(data["kind"], "file")
        self.assertIn("app/main.py", data["direct_importers"])
        self.assertIn("tests/test_auth.py", data["direct_importers"])
        self.assertIn("tests/test_auth.py", data["tests"])
        self.assertGreaterEqual(data["risk"], 0)
        self.assertIn(data["level"], ("LOW", "MEDIUM", "HIGH"))

    def test_impact_symbol_scopes_callers(self) -> None:
        proc = self.atlas("impact", "AuthService.login", "--json")
        data = json.loads(proc.stdout)
        self.assertEqual(data["kind"], "symbol")
        self.assertIn("app/main.py", data["direct_importers"])
        incoming = {c["symbol"] for c in data["incoming_calls"]}
        self.assertIn("services/auth.py::AuthService.login", incoming)

    def test_path(self) -> None:
        proc = self.atlas("path", "app/main.py", "utils/security.py", "--json")
        data = json.loads(proc.stdout)
        self.assertEqual(data["direction"], "depends on")
        self.assertEqual(data["path"][0], "app/main.py")
        self.assertEqual(data["path"][-1], "utils/security.py")
        self.assertIn("services/auth.py", data["path"])

    def test_pack_respects_focus_and_budget(self) -> None:
        proc = self.atlas("pack", "AuthService", "--budget", "700")
        self.assertIn("# Pack: AuthService", proc.stdout)
        self.assertIn("services/auth.py", proc.stdout)
        self.assertIn("tokens", proc.stdout)
        self.assertNotIn("node_modules", proc.stdout)
        self.assertNotIn(".env", proc.stdout)

    def test_diagram_files_mode(self) -> None:
        proc = self.atlas("diagram", "--files", "--top", "20", "--json")
        data = json.loads(proc.stdout)
        self.assertTrue(Path(data["mermaid"]).exists())
        self.assertTrue(Path(data["html"]).exists())
        self.assertGreater(data["nodes"], 0)
        html = Path(data["html"]).read_text(encoding="utf-8")
        self.assertIn("const DATA =", html)
        self.assertNotIn("<script src=", html)
        mmd = Path(data["mermaid"]).read_text(encoding="utf-8")
        self.assertTrue(mmd.startswith("flowchart LR"))

    def test_doctor_fresh_stale_update(self) -> None:
        fresh = self.atlas("doctor", check=False)
        self.assertEqual(fresh.returncode, 0, fresh.stdout)
        self.assertIn("FRESH", fresh.stdout)

        user = self.root / "services/user.py"
        user.write_text(
            user.read_text(encoding="utf-8") + "\ndef remove(self, name):\n    return None\n",
            encoding="utf-8",
        )
        stale = self.atlas("doctor", check=False)
        self.assertEqual(stale.returncode, 1, stale.stdout)
        self.assertIn("STALE", stale.stdout)
        self.assertIn("services/user.py", stale.stdout)

        self.atlas("update", "--no-git")
        after = self.atlas("doctor", check=False)
        self.assertEqual(after.returncode, 0, after.stdout)
        self.assertIn("FRESH", after.stdout)

    def test_stats_json(self) -> None:
        data = json.loads(self.atlas("stats", "--json").stdout)
        self.assertGreater(data["files"], 0)
        self.assertGreater(data["edges"], 0)
        self.assertIn("python", data["languages"])

    def test_init_writes_config_and_gitignore(self) -> None:
        with tempfile.TemporaryDirectory(prefix="code-atlas-init-") as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text("existing\n", encoding="utf-8")
            env = dict(os.environ, NO_COLOR="1", PYTHONIOENCODING="utf-8")
            proc = subprocess.run(
                [sys.executable, str(ATLAS), "init", "--no-build"],
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((root / ".codeatlas.json").exists())
            gitignore = (root / ".gitignore").read_text(encoding="utf-8")
            self.assertIn("existing", gitignore)
            self.assertIn(".code-atlas/", gitignore)


if __name__ == "__main__":
    unittest.main(verbosity=2)

