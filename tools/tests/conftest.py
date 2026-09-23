"""flow.sh / flow_gate.py / git hooks の結合テスト用フィクスチャ。

構成（すべて tmp_path 配下、実際の GitHub には一切アクセスしない）:
  origin.git   bare リポジトリ（GitHub 上のリモートの代わり）
  work/        開発者の clone。tools/bin・tools/git-hooks を本リポジトリからコピー済み
  bin/gh       fake_gh.py（PR 状態を gh_state.json に保持）
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Sandbox:
    root: Path
    origin: Path
    work: Path
    env: dict[str, str]
    state_file: Path

    def run(self, *args: str, cwd: Path | None = None, check: bool = False, stdin: str | None = None):
        proc = subprocess.run(
            list(args),
            cwd=cwd or self.work,
            env=self.env,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            input=stdin,
        )
        if check and proc.returncode != 0:
            raise AssertionError(
                f"コマンド失敗 rc={proc.returncode}: {' '.join(args)}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
        return proc

    def git(self, *args: str, cwd: Path | None = None, check: bool = True):
        return self.run("git", *args, cwd=cwd, check=check)

    def flow(self, *args: str, cwd: Path | None = None, stdin: str | None = None):
        return self.run(str((cwd or self.work) / "tools/bin/flow.sh"), *args, cwd=cwd, stdin=stdin)

    def commit_file(self, rel: str, content: str, message: str = "change", cwd: Path | None = None):
        base = cwd or self.work
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.git("add", rel, cwd=base)
        return self.git("commit", "-m", message, cwd=base, check=False)

    @property
    def gh_state(self) -> dict:
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def set_gh_state(self, **updates) -> None:
        state = self.gh_state
        state.update(updates)
        self.state_file.write_text(json.dumps(state), encoding="utf-8")

    def update_pr(self, number: int, **fields) -> None:
        state = self.gh_state
        for pr in state["prs"]:
            if pr["number"] == number:
                pr.update(fields)
        self.state_file.write_text(json.dumps(state), encoding="utf-8")


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    bindir = tmp_path / "bin"
    state_file = tmp_path / "gh_state.json"
    state_file.write_text(json.dumps({"prs": [], "authed": True, "calls": []}), encoding="utf-8")

    # fake gh を PATH 先頭に置く
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(f"#!/bin/sh\nexec '{sys.executable}' '{Path(__file__).parent / 'fake_gh.py'}' \"$@\"\n")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)

    home = tmp_path / "home"
    home.mkdir()
    env = {
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "FAKE_GH_STATE": str(state_file),
        "FAKE_GH_ORIGIN": str(origin),
    }
    (home / ".gitconfig").write_text("[init]\n\tdefaultBranch = main\n[advice]\n\tdetachedHead = false\n")

    sb = Sandbox(root=tmp_path, origin=origin, work=work, env=env, state_file=state_file)
    sb.git("init", "--quiet", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    sb.git("clone", "--quiet", str(origin), str(work), cwd=tmp_path)

    # 本リポジトリのワークフロー一式をコピーして main の初期コミットにする（この時点では hooks 未有効）
    for rel in ("tools/bin", "tools/git-hooks"):
        shutil.copytree(REPO_ROOT / rel, work / rel)
    (work / ".gitignore").write_text(".worktrees/\n.env\n")
    (work / "README.md").write_text("# sandbox\n")
    sb.git("add", "-A")
    sb.git("commit", "--quiet", "-m", "init")
    sb.git("push", "--quiet", "origin", "main")
    return sb
