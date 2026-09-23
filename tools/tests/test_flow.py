"""tools/bin/flow.sh・tools/bin/flow_gate.py・tools/git-hooks の結合テスト。

gh 連携・merge の承認必須化・core.hooksPath・pre-push を重点的に検証する。
"""

from __future__ import annotations

import datetime as dt
import os
import pty
import select
import subprocess
import time

# 秘密情報パターンはテストファイル自体がゲートに引っかからないよう連結で組み立てる
FAKE_GH_TOKEN = "ghp" + "_" + "A1b2C3d4" * 5
FAKE_PASSWORD_LINE = "DB_PASS" + 'WORD = "hunter2hunter2"'


def today_jst() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y%m%d")


def start_branch(sb, slug="feat"):
    res = sb.flow("start", slug)
    assert res.returncode == 0, res.stderr
    return f"work/{today_jst()}-{slug}"


# ------------------------------------------------------------------ setup / hooks


def test_any_subcommand_enables_hooks_path(sandbox):
    assert sandbox.git("config", "--get", "core.hooksPath", check=False).stdout.strip() == ""
    res = sandbox.flow("status")
    assert res.returncode == 0, res.stderr
    assert sandbox.git("config", "--get", "core.hooksPath").stdout.strip() == "tools/git-hooks"


def test_setup_fails_when_gh_unauthenticated(sandbox):
    sandbox.set_gh_state(authed=False)
    res = sandbox.flow("setup")
    assert res.returncode == 1
    assert "gh auth login" in res.stdout


def test_setup_ok(sandbox):
    res = sandbox.flow("setup")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "セットアップ OK" in res.stdout


def test_pre_commit_rejects_commit_on_main(sandbox):
    sandbox.flow("status")
    res = sandbox.commit_file("a.txt", "x\n")
    assert res.returncode != 0
    assert "main 上では直接コミットできません" in res.stderr


def test_pre_commit_runs_gate_and_blocks_secret(sandbox):
    start_branch(sandbox)
    res = sandbox.commit_file("app/settings.py", f'TOKEN = "{FAKE_GH_TOKEN}"\n')
    assert res.returncode != 0
    assert "GitHub トークン" in res.stderr
    # 検出値そのものは出力しない
    assert FAKE_GH_TOKEN not in res.stderr + res.stdout


def test_pre_commit_allow_marker(sandbox):
    start_branch(sandbox)
    res = sandbox.commit_file("app/settings.py", f"{FAKE_PASSWORD_LINE}  # flow:allow-secret\n")
    assert res.returncode == 0, res.stderr


def test_pre_push_rejects_push_to_main(sandbox):
    branch = start_branch(sandbox)
    assert sandbox.commit_file("a.txt", "x\n").returncode == 0
    res = sandbox.git("push", "origin", f"{branch}:main", check=False)
    assert res.returncode != 0
    assert "直接 push は禁止" in res.stderr


def test_hooks_work_inside_worktree(sandbox):
    res = sandbox.flow("start", "wt", "--worktree")
    assert res.returncode == 0, res.stderr
    wt = sandbox.work / ".worktrees" / "wt"
    assert sandbox.git("rev-parse", "--abbrev-ref", "HEAD", cwd=wt).stdout.strip() == f"work/{today_jst()}-wt"
    res = sandbox.commit_file("bad.py", "def f(:\n", cwd=wt)
    assert res.returncode != 0
    assert "構文エラー" in res.stderr


# ------------------------------------------------------------------ gate


def test_gate_detects_env_file_and_large_file(sandbox):
    start_branch(sandbox)
    (sandbox.work / ".env.local").write_text("X=1\n")
    (sandbox.work / ".env.example").write_text("X=\n")
    (sandbox.work / "data.csv").write_bytes(b"0" * (2 * 1024 * 1024))
    sandbox.env["FLOW_MAX_FILE_MB"] = "1"
    res = sandbox.flow("check")
    assert res.returncode == 1
    assert ".env.local" in res.stderr
    assert "    .env.example\n" not in res.stderr
    assert "data.csv (2.0MB)" in res.stderr


def test_gate_only_option_and_unknown_check(sandbox):
    start_branch(sandbox)
    (sandbox.work / "bad.py").write_text("def f(:\n")
    assert sandbox.flow("check", "--only", "secret").returncode == 0
    assert sandbox.flow("check", "--only", "syntax").returncode == 1
    assert sandbox.flow("check", "--only", "nope").returncode == 2


# ------------------------------------------------------------------ start


def test_start_rejects_bad_slug_and_duplicate(sandbox):
    assert sandbox.flow("start", "日本語").returncode == 1
    start_branch(sandbox, "dup")
    sandbox.git("switch", "--quiet", "main")
    res = sandbox.flow("start", "dup")
    assert res.returncode == 1
    assert "既に存在" in res.stderr


# ------------------------------------------------------------------ pr


def test_pr_refuses_on_main(sandbox):
    res = sandbox.flow("pr", "-t", "x")
    assert res.returncode == 1
    assert "main 上では PR を作れません" in res.stderr


def test_pr_refuses_with_tracked_changes_but_only_warns_untracked(sandbox):
    start_branch(sandbox)
    assert sandbox.commit_file("a.txt", "x\n").returncode == 0
    (sandbox.work / "a.txt").write_text("changed\n")
    res = sandbox.flow("pr", "-t", "x")
    assert res.returncode == 1
    assert "未コミットの変更" in res.stderr

    sandbox.git("checkout", "--", "a.txt")
    (sandbox.work / "notes.md").write_text("memo\n")
    res = sandbox.flow("pr", "-t", "x")
    assert res.returncode == 0, res.stderr
    assert "未追跡ファイルが 1 件" in res.stderr
    assert "notes.md" in res.stderr


def test_pr_refuses_without_new_commits(sandbox):
    start_branch(sandbox)
    res = sandbox.flow("pr", "-t", "x")
    assert res.returncode == 1
    assert "新しいコミットがありません" in res.stderr


def test_pr_requires_gh_auth(sandbox):
    start_branch(sandbox)
    sandbox.commit_file("a.txt", "x\n")
    sandbox.set_gh_state(authed=False)
    res = sandbox.flow("pr")
    assert res.returncode == 1
    assert "gh が未認証" in res.stderr


def test_pr_creates_then_reuses(sandbox):
    branch = start_branch(sandbox)
    assert sandbox.commit_file("a.txt", "x\n", message="feat: a").returncode == 0
    res = sandbox.flow("pr")
    assert res.returncode == 0, res.stderr
    assert "PR #1" in res.stdout
    assert "merge 1 --approved" in res.stdout

    prs = sandbox.gh_state["prs"]
    assert len(prs) == 1
    assert prs[0]["head"] == branch and prs[0]["base"] == "main"
    assert prs[0]["title"] == "feat: a"  # -t 省略時は最新コミットの件名
    # ブランチが origin に push されている
    assert sandbox.git("ls-remote", "origin", branch).stdout.strip()

    assert sandbox.commit_file("b.txt", "y\n").returncode == 0
    res = sandbox.flow("pr", "-t", "other")
    assert res.returncode == 0, res.stderr
    assert "既存の PR #1 を再利用" in res.stdout
    assert len(sandbox.gh_state["prs"]) == 1


def test_pr_does_not_reuse_pr_of_other_branch(sandbox):
    """別ブランチの open PR を誤って「既存 PR」として再利用しないこと。"""
    start_branch(sandbox, "one")
    sandbox.commit_file("a.txt", "x\n")
    assert sandbox.flow("pr", "-t", "one").returncode == 0
    sandbox.git("switch", "--quiet", "main")
    start_branch(sandbox, "two")
    sandbox.commit_file("b.txt", "y\n")
    res = sandbox.flow("pr", "-t", "two")
    assert res.returncode == 0, res.stderr
    assert "PR #2" in res.stdout
    assert len(sandbox.gh_state["prs"]) == 2


def test_pr_uses_template_body_and_draft(sandbox):
    (sandbox.work / ".github").mkdir()
    (sandbox.work / ".github/pull_request_template.md").write_text("## 概要\n")
    start_branch(sandbox)
    sandbox.git("add", ".github")
    sandbox.git("commit", "-q", "-m", "tpl")
    res = sandbox.flow("pr", "--draft")
    assert res.returncode == 0, res.stderr
    pr = sandbox.gh_state["prs"][0]
    assert pr["body"] == "## 概要\n"
    assert pr["isDraft"] is True


def test_pr_stops_on_gate_failure_before_push(sandbox):
    branch = start_branch(sandbox)
    (sandbox.work / "bad.py").write_text("def f(:\n")
    sandbox.git("add", "bad.py")
    sandbox.git("commit", "-q", "--no-verify", "-m", "bad")
    res = sandbox.flow("pr")
    assert res.returncode == 1
    assert "ゲート不合格" in res.stderr
    assert sandbox.git("ls-remote", "origin", branch).stdout.strip() == ""
    assert sandbox.gh_state["prs"] == []


# ------------------------------------------------------------------ merge（チーム開発: 承認必須）


def _open_pr(sb, slug="feat"):
    start_branch(sb, slug)
    assert sb.commit_file(f"{slug}.txt", "x\n", message=f"feat: {slug}").returncode == 0
    assert sb.flow("pr").returncode == 0
    return sb.gh_state["prs"][-1]["number"]


def test_merge_requires_pr_number(sandbox):
    _open_pr(sandbox)
    res = sandbox.flow("merge", "--approved")
    assert res.returncode == 1
    assert "PR 番号は必須" in res.stderr


def test_merge_refuses_without_approval_in_non_interactive(sandbox):
    n = _open_pr(sandbox)
    res = sandbox.flow("merge", str(n))
    assert res.returncode == 1
    assert "明示的な承認が必要" in res.stderr
    assert sandbox.gh_state["prs"][0]["state"] == "OPEN"
    assert not any(c[:2] == ["pr", "merge"] for c in sandbox.gh_state["calls"])


def test_merge_refuses_bad_states(sandbox):
    n = _open_pr(sandbox)
    cases = [
        ({"isDraft": True}, "draft"),
        ({"mergeable": "CONFLICTING"}, "コンフリクト"),
        ({"reviewDecision": "CHANGES_REQUESTED"}, "変更要求"),
        ({"checks": "fail"}, "CI が失敗"),
        ({"state": "CLOSED"}, "open ではありません"),
    ]
    for fields, msg in cases:
        original = {k: sandbox.gh_state["prs"][0][k] for k in fields}
        sandbox.update_pr(n, **fields)
        res = sandbox.flow("merge", str(n), "--approved")
        assert res.returncode == 1, fields
        assert msg in res.stderr, (fields, res.stderr)
        sandbox.update_pr(n, **original)
    assert not any(c[:2] == ["pr", "merge"] for c in sandbox.gh_state["calls"])


def test_merge_with_approval_merges_and_syncs_local_main(sandbox):
    n = _open_pr(sandbox)
    sandbox.update_pr(n, checks="none")  # CI 未設定は警告のみで続行
    res = sandbox.flow("merge", str(n), "--approved")
    assert res.returncode == 0, res.stderr
    assert "CI の結果がありません" in res.stderr
    assert sandbox.gh_state["prs"][0]["state"] == "MERGED"
    assert ["pr", "merge", str(n), "--squash"] in sandbox.gh_state["calls"]
    # 作業ブランチにいてもローカル main が origin/main に追従している
    assert sandbox.git("rev-parse", "main").stdout == sandbox.git("rev-parse", "origin/main").stdout
    assert "feat.txt" in sandbox.git("ls-tree", "--name-only", "main").stdout


def _run_in_pty(sb, args: list[str], answer: str) -> str:
    """擬似端末で実行し、確認プロンプトが出たら answer を入力する（[ -t 0 ] 分岐の検証用）。"""
    master, slave = pty.openpty()
    proc = subprocess.Popen(args, cwd=sb.work, env=sb.env, stdin=slave, stdout=slave, stderr=slave)
    os.close(slave)
    out = b""
    sent = False
    deadline = time.time() + 30
    while time.time() < deadline:
        ready, _, _ = select.select([master], [], [], 0.2)
        if ready:
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
            if not sent and b"[y/N]" in out:
                os.write(master, answer.encode())
                sent = True
        elif proc.poll() is not None:
            break
    proc.wait(timeout=10)
    os.close(master)
    return out.decode("utf-8", errors="replace")


def test_merge_interactive_decline(sandbox):
    """端末から実行し、確認に N / Ctrl-D と答えればマージしない。"""
    n = _open_pr(sandbox)
    flow = str(sandbox.work / "tools/bin/flow.sh")
    for answer in ("n\n", "\x04"):
        out = _run_in_pty(sandbox, [flow, "merge", str(n)], answer)
        assert "PR #1「feat: feat」を squash マージします" in out, out
        assert "中止しました" in out, out
    assert sandbox.gh_state["prs"][0]["state"] == "OPEN"
    assert not any(c[:2] == ["pr", "merge"] for c in sandbox.gh_state["calls"])


def test_merge_interactive_accept(sandbox):
    n = _open_pr(sandbox)
    out = _run_in_pty(sandbox, [str(sandbox.work / "tools/bin/flow.sh"), "merge", str(n)], "y\n")
    assert "マージ完了" in out, out
    assert sandbox.gh_state["prs"][0]["state"] == "MERGED"


# ------------------------------------------------------------------ approve


def test_approve_default_comment_is_lgtm(sandbox):
    n = _open_pr(sandbox)
    res = sandbox.flow("approve", str(n))
    assert res.returncode == 0, res.stderr
    assert ["pr", "review", str(n), "--approve", "--body", "LGTM"] in sandbox.gh_state["calls"]
    assert sandbox.gh_state["prs"][0]["reviewDecision"] == "APPROVED"


def test_approve_custom_comment(sandbox):
    n = _open_pr(sandbox)
    res = sandbox.flow("approve", str(n), "-m", "LGTM! 動作確認済み")
    assert res.returncode == 0, res.stderr
    assert sandbox.gh_state["prs"][0]["reviews"][0]["body"] == "LGTM! 動作確認済み"


def test_approve_refuses_bad_input_and_own_pr(sandbox):
    n = _open_pr(sandbox)
    assert "PR 番号は必須" in sandbox.flow("approve").stderr
    sandbox.update_pr(n, author="me")
    res = sandbox.flow("approve", str(n))
    assert res.returncode == 1
    assert "自分が作成した PR" in res.stderr
    sandbox.update_pr(n, author="other", state="MERGED")
    res = sandbox.flow("approve", str(n))
    assert res.returncode == 1
    assert "open ではありません" in res.stderr


# ------------------------------------------------------------------ prune / protect / sync


def test_prune_dry_run_lists_squash_merged_branch(sandbox):
    n = _open_pr(sandbox, "old")
    assert sandbox.flow("merge", str(n), "--approved").returncode == 0
    res = sandbox.flow("prune", "--days", "0")
    assert res.returncode == 0, res.stderr
    # squash マージで祖先ではないが、merged PR があるのでマージ済み扱い
    assert "マージ済み（削除対象）" in res.stdout
    assert f"work/{today_jst()}-old" in res.stdout
    assert "ドライラン" in res.stderr
    assert sandbox.git("ls-remote", "origin", f"work/{today_jst()}-old").stdout.strip()


def test_prune_marks_unmerged(sandbox):
    start_branch(sandbox, "wip")
    sandbox.commit_file("w.txt", "x\n")
    sandbox.git("push", "-q", "origin", f"work/{today_jst()}-wip")
    res = sandbox.flow("prune", "--days", "0")
    assert "未マージ" in res.stdout
    assert "既定では削除しません" in res.stdout


def test_protect_is_dry_run_by_default(sandbox):
    res = sandbox.flow("protect")
    assert res.returncode == 0, res.stderr
    assert '"required_approving_review_count": 1' in res.stdout
    assert '"dismiss_stale_reviews": false' in res.stdout
    assert '"enforce_admins": false' in res.stdout
    assert not any(c[:1] == ["api"] for c in sandbox.gh_state["calls"])


def test_sync_updates_main_when_checked_out(sandbox):
    other = sandbox.root / "other"
    sandbox.git("clone", "-q", str(sandbox.origin), str(other), cwd=sandbox.root)
    (other / "z.txt").write_text("z\n")
    sandbox.git("add", "z.txt", cwd=other)
    sandbox.git("commit", "-q", "-m", "z", cwd=other)
    sandbox.git("push", "-q", "origin", "main", cwd=other)
    res = sandbox.flow("sync")
    assert res.returncode == 0, res.stderr
    assert (sandbox.work / "z.txt").exists()


def test_log_file_written_in_jst(sandbox):
    sandbox.flow("status")
    log = (sandbox.work / ".git/flow-logs/flow.log").read_text()
    assert "cmd=status" in log
    assert "+0900 [INFO]" in log
