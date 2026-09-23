#!/usr/bin/env python3
"""flow_gate.py — マージ前ゲート（hackathon-starter-kit の共通部品）

tools/bin/flow.sh の `check` サブコマンド、pre-commit フック、GitHub Actions (CI) から呼ばれる。
単体でも実行可。

チェック内容:
  syntax     変更された .py が py_compile を通るか
  secret     追加行に API キー / トークン / パスワード等が混入していないか
  envfile    .env 系ファイル（.env.example 等のテンプレートを除く）がコミットされていないか
  largefile  巨大ファイル（既定 5MB 超）がコミットされていないか（データ・モデルの誤コミット防止）

設計のポイント（2026-09-23）:
  - 比較基準は origin/main を優先する（チーム開発ではローカル main が古いことが多く、差分が過大に出るため）
  - envfile / largefile はハッカソンで典型的な .env と生データの誤コミットを防ぐため
  - 秘密情報の検出値そのものは出力しない（ログ・CI 出力経由の二次漏えいを防ぐ）
  - 想定外の例外は完全なスタックトレースを出して終了コード 2 にする

外部パッケージに依存しない（venv 無しで動く）ことを設計条件とする。
"""

from __future__ import annotations

import argparse
import os
import py_compile
import re
import subprocess
import sys
import tempfile
import traceback

# 追加行のみを対象に走査する秘密情報パターン
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("秘密鍵", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----")),
    ("AWS アクセスキー", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub トークン", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})")),
    ("Anthropic API キー", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("OpenAI API キー", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}")),
    ("Google API キー", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Slack トークン", re.compile(r"\bxox[abpors]-[A-Za-z0-9-]{10,}")),
    ("Discord Webhook URL", re.compile(r"discord(?:app)?\.com/api/webhooks/\d+/[\w-]{20,}")),
    # 先頭に \b を置かないこと。DB_PASSWORD / access_token のように区切りが "_" だと
    # \b が成立せず取りこぼす（"_" は単語文字のため）。
    ("パスワード直書き", re.compile(r"(?i)(?:password|passwd|pwd)\s*[=:]\s*[\"']?(?!\s*$)[^\s\"'{}$]{6,}")),
    (
        "トークン/APIキー直書き",
        re.compile(r"(?i)(?:token|api[_-]?key|secret[_-]?key|access[_-]?key)\s*[=:]\s*[\"']?[\w-]{20,}"),
    ),
    ("URL 埋め込み認証情報", re.compile(r"://[^/\s:@]+:[^/\s:@]+@")),
]

# この文字列を含む行は秘密情報チェックの対象外にする
SECRET_ALLOW_MARKER = "flow:allow-secret"

# 秘密情報が元から平文でコミットされているファイル（差分が出ても既知として扱う）。
# 先回りでファイル名を登録しない — 実際に見つかった時点で追加する。
SECRET_KNOWN_FILES: set[str] = set()

# .env 系のうちコミットしてよいテンプレート
ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist")

DEFAULT_MAX_FILE_MB = 5.0


class Result:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.warnings: list[str] = []


def run_git(repo_root: str, *args: str) -> str:
    proc = subprocess.run(["git", "-C", repo_root, *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失敗 (rc={proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


def resolve_base_ref(repo_root: str, base: str) -> str:
    """origin/<base> があればそれを、無ければローカルの <base> を比較基準にする。"""
    if "/" in base:
        return base
    for candidate in (f"origin/{base}", base):
        try:
            run_git(repo_root, "rev-parse", "--verify", "--quiet", candidate)
            return candidate
        except RuntimeError:
            continue
    return base


def merge_base_of(repo_root: str, base_ref: str) -> str:
    try:
        return run_git(repo_root, "merge-base", base_ref, "HEAD").strip()
    except RuntimeError:
        return ""


def untracked_files(repo_root: str) -> list[str]:
    out = run_git(repo_root, "status", "--porcelain", "--untracked-files=all")
    return [line[3:].strip().strip('"') for line in out.splitlines() if line.startswith("?? ")]


def changed_files(repo_root: str, base_ref: str) -> list[str]:
    """base_ref との分岐点以降で変更されたファイル（未コミット分を含む）を返す。削除は除く。"""
    paths: set[str] = set()

    merge_base = merge_base_of(repo_root, base_ref)
    if merge_base:
        out = run_git(repo_root, "diff", "--name-only", "--diff-filter=d", merge_base, "HEAD")
        paths.update(line for line in out.splitlines() if line)

    out = run_git(repo_root, "status", "--porcelain", "--untracked-files=all")
    for line in out.splitlines():
        if not line:
            continue
        status, path = line[:2], line[3:]
        if "D" in status:
            continue
        # リネームは "old -> new" 形式
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.add(path.strip().strip('"'))

    return sorted(paths)


def added_lines(repo_root: str, base_ref: str) -> list[tuple[str, int, str]]:
    """(ファイルパス, 行番号, 行内容) の形で追加行を返す。"""
    merge_base = merge_base_of(repo_root, base_ref) or base_ref

    diffs = []
    for args in (
        ["diff", "--unified=0", "--no-color", merge_base, "HEAD"],
        ["diff", "--unified=0", "--no-color", "HEAD"],
    ):
        try:
            diffs.append(run_git(repo_root, *args))
        except RuntimeError:
            pass

    results: list[tuple[str, int, str]] = []
    for diff in diffs:
        current = ""
        lineno = 0
        for line in diff.splitlines():
            if line.startswith("+++ "):
                current = line[6:] if line.startswith("+++ b/") else ""
                continue
            if line.startswith("@@"):
                m = re.search(r"\+(\d+)", line)
                lineno = int(m.group(1)) if m else 0
                continue
            if line.startswith("+"):
                results.append((current, lineno, line[1:]))
                lineno += 1

    # untracked ファイルは全行が追加行
    for path in untracked_files(repo_root):
        full = os.path.join(repo_root, path)
        if not os.path.isfile(full):
            continue
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh, 1):
                    results.append((path, i, line.rstrip("\n")))
        except OSError:
            continue

    return results


def check_syntax(repo_root: str, files: list[str], res: Result) -> None:
    py_files = [f for f in files if f.endswith(".py")]
    if not py_files:
        print("  - syntax     対象の .py 変更なし")
        return

    bad = []
    for rel in py_files:
        full = os.path.join(repo_root, rel)
        if not os.path.isfile(full):
            continue
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                py_compile.compile(full, cfile=os.path.join(tmpdir, "x.pyc"), doraise=True)
        except py_compile.PyCompileError as exc:
            bad.append(f"{rel}: {exc.msg.strip().splitlines()[-1]}")
        except (OSError, ValueError) as exc:
            bad.append(f"{rel}: {exc}")

    if bad:
        res.failures.append("syntax: Python 構文エラー:\n    " + "\n    ".join(bad))
    else:
        print(f"  ✓ syntax     {len(py_files)} ファイルの py_compile 通過")


def check_secret(repo_root: str, base_ref: str, res: Result) -> None:
    hits: list[str] = []
    for path, lineno, line in added_lines(repo_root, base_ref):
        if not path or path in SECRET_KNOWN_FILES:
            continue
        if SECRET_ALLOW_MARKER in line:
            continue
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                # 検出値そのものはログに残さない（伏せ字にして位置だけ示す）
                hits.append(f"{path}:{lineno} [{label}]")
                break

    if hits:
        res.failures.append(
            f"secret: 追加行に秘密情報らしき文字列を検出（誤検知なら行末に `{SECRET_ALLOW_MARKER}` を付与）:\n    "
            + "\n    ".join(hits)
        )
    else:
        print("  ✓ secret     追加行に秘密情報の混入なし")


def is_env_file(path: str) -> bool:
    name = os.path.basename(path)
    if name != ".env" and not name.startswith(".env."):
        return False
    return not name.endswith(ENV_TEMPLATE_SUFFIXES)


def check_envfile(files: list[str], res: Result) -> None:
    bad = [f for f in files if is_env_file(f)]
    if bad:
        res.failures.append(
            "envfile: .env 系ファイルはコミット禁止（テンプレートは .env.example として置く）:\n    "
            + "\n    ".join(bad)
        )
    else:
        print("  ✓ envfile    .env 系ファイルの混入なし")


def check_largefile(repo_root: str, files: list[str], max_mb: float, res: Result) -> None:
    limit = int(max_mb * 1024 * 1024)
    bad = []
    for rel in files:
        full = os.path.join(repo_root, rel)
        if os.path.isfile(full) and os.path.getsize(full) > limit:
            bad.append(f"{rel} ({os.path.getsize(full) / 1024 / 1024:.1f}MB)")
    if bad:
        res.failures.append(
            f"largefile: {max_mb:g}MB を超えるファイル（data/ 等 gitignore 対象へ置く。"
            "閾値は FLOW_MAX_FILE_MB で変更可）:\n    " + "\n    ".join(bad)
        )
    else:
        print(f"  ✓ largefile  {max_mb:g}MB 超のファイルなし")


CHECKS = ("syntax", "secret", "envfile", "largefile")


def main() -> int:
    parser = argparse.ArgumentParser(description="マージ前ゲート")
    parser.add_argument("--repo-root", default=".", help="対象 worktree のルート")
    parser.add_argument("--base-ref", default="main", help="比較元（既定: main。origin/main があれば優先）")
    parser.add_argument("--only", default=",".join(CHECKS), help="実行するチェックをカンマ区切りで指定（既定: 全部）")
    parser.add_argument(
        "--max-file-mb",
        type=float,
        default=float(os.environ.get("FLOW_MAX_FILE_MB", DEFAULT_MAX_FILE_MB)),
        help="largefile の閾値 MB（既定: 環境変数 FLOW_MAX_FILE_MB または 5）",
    )
    args = parser.parse_args()

    repo_root = os.path.abspath(args.repo_root)
    selected = [c.strip() for c in args.only.split(",") if c.strip()]
    unknown = [c for c in selected if c not in CHECKS]
    if unknown:
        print(f"不明なチェック: {', '.join(unknown)}（有効: {', '.join(CHECKS)}）", file=sys.stderr)
        return 2

    base_ref = resolve_base_ref(repo_root, args.base_ref)
    files = changed_files(repo_root, base_ref)
    if not files:
        print(f"{base_ref} との差分なし。チェックをスキップします。")
        return 0

    print(f"ゲート実行: {repo_root}（基準 {base_ref} / 変更 {len(files)} ファイル）")
    res = Result()

    if "syntax" in selected:
        check_syntax(repo_root, files, res)
    if "secret" in selected:
        check_secret(repo_root, base_ref, res)
    if "envfile" in selected:
        check_envfile(files, res)
    if "largefile" in selected:
        check_largefile(repo_root, files, args.max_file_mb, res)

    # stderr へ書く前に stdout を吐き出す（パイプ時に順序が入れ替わるのを防ぐ）
    sys.stdout.flush()

    if res.failures:
        print("\n✗ ゲート不合格:\n", file=sys.stderr)
        for msg in res.failures:
            print(f"  {msg}\n", file=sys.stderr)
        return 1

    print("\n✓ ゲート合格")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — 想定外の失敗は完全なスタックトレース付きで報告する
        print("ゲート実行中に想定外のエラーが発生しました:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(2)
