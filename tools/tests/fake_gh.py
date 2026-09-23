#!/usr/bin/env python3
"""テスト用の gh (GitHub CLI) 代替。

flow.sh が実際に使う呼び出しパターンだけを実装し、PR 状態を JSON ファイルで保持する。
--jq 式は評価せず、flow.sh がその呼び出しで期待する「最終出力」を直接返す。

環境変数:
  FAKE_GH_STATE  状態ファイル（{"prs": [...], "authed": bool, "calls": [[...], ...]}）
  FAKE_GH_ORIGIN merge 時に squash マージを反映する bare リポジトリのパス
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import traceback


def load() -> dict:
    with open(os.environ["FAKE_GH_STATE"], encoding="utf-8") as fh:
        return json.load(fh)


def save(state: dict) -> None:
    with open(os.environ["FAKE_GH_STATE"], "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)


def opt(args: list[str], name: str, default: str | None = None) -> str | None:
    return args[args.index(name) + 1] if name in args else default


def find(state: dict, number: int) -> dict:
    for pr in state["prs"]:
        if pr["number"] == number:
            return pr
    print(f"no pull requests found for {number}", file=sys.stderr)
    sys.exit(1)


def squash_merge_into_origin(branch: str, title: str) -> None:
    origin = os.environ["FAKE_GH_ORIGIN"]
    with tempfile.TemporaryDirectory() as tmp:
        run = lambda *a: subprocess.run(a, cwd=tmp, check=True, capture_output=True, text=True)  # noqa: E731
        run("git", "clone", "--quiet", origin, ".")
        run("git", "merge", "--squash", f"origin/{branch}")
        run("git", "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "-m", title)
        run("git", "push", "--quiet", "--no-verify", "origin", "HEAD:main")


def main(argv: list[str]) -> int:
    state = load()
    state.setdefault("calls", []).append(argv)
    save(state)

    if argv[:2] == ["auth", "status"]:
        return 0 if state.get("authed", True) else 1

    if argv[:2] == ["repo", "view"]:
        print("owner/repo")
        return 0

    if argv[:2] == ["pr", "list"]:
        head = opt(argv, "--head")
        want = (opt(argv, "--state", "open") or "open").upper()
        hits = [p for p in state["prs"] if p["head"] == head and p["state"] == want]
        if hits:
            print(hits[0]["number"])
        return 0

    if argv[:2] == ["pr", "create"]:
        number = max([p["number"] for p in state["prs"]], default=0) + 1
        body = opt(argv, "--body")
        if body is None and "--body-file" in argv:
            with open(opt(argv, "--body-file"), encoding="utf-8") as fh:
                body = fh.read()
        state["prs"].append(
            {
                "number": number,
                "head": opt(argv, "--head"),
                "base": opt(argv, "--base"),
                "title": opt(argv, "--title"),
                "body": body,
                "state": "OPEN",
                "isDraft": "--draft" in argv,
                "mergeable": "MERGEABLE",
                "reviewDecision": "",
                "checks": "pass",
            }
        )
        save(state)
        print(f"https://github.com/owner/repo/pull/{number}")
        return 0

    if argv[:2] == ["pr", "view"]:
        pr = find(state, int(argv[2]))
        fields = opt(argv, "--json", "")
        if fields == "url":
            print(f"https://github.com/owner/repo/pull/{pr['number']}")
        elif fields == "state":
            print(pr["state"])
        elif fields == "reviews":
            # flow.sh の --jq（Approve または LGTM で始まるコメントレビューの件数）と同じ結果を返す
            print(
                sum(
                    1
                    for r in pr.get("reviews", [])
                    if r["state"] == "APPROVED"
                    or (r["state"] == "COMMENTED" and (r["body"] or "").lstrip().lower().startswith("lgtm"))
                )
            )
        else:
            print(
                "\x1f".join(
                    [pr["state"], str(pr["isDraft"]).lower(), pr["mergeable"], pr["reviewDecision"], pr["title"]]
                )
            )
        return 0

    if argv[:2] == ["pr", "checks"]:
        checks = find(state, int(argv[2]))["checks"]
        if checks == "pass":
            return 0
        if checks == "pending":
            return 8
        if checks == "none":
            print("no checks reported on the 'x' branch", file=sys.stderr)
            return 1
        return 1

    if argv[:2] == ["pr", "review"]:
        pr = find(state, int(argv[2]))
        approve = "--approve" in argv
        # GitHub と同じく、作成者本人の Approve は拒否する（コメントレビューは可）
        if approve and pr.get("author") == "me":
            print("failed to create review: Can not approve your own pull request", file=sys.stderr)
            return 1
        if approve:
            pr["reviewDecision"] = "APPROVED"
        pr.setdefault("reviews", []).append(
            {"state": "APPROVED" if approve else "COMMENTED", "body": opt(argv, "--body")}
        )
        save(state)
        return 0

    if argv[:2] == ["pr", "merge"]:
        pr = find(state, int(argv[2]))
        squash_merge_into_origin(pr["head"], pr["title"])
        pr["state"] = "MERGED"
        save(state)
        return 0

    print(f"fake_gh: 未対応の呼び出し: {argv}", file=sys.stderr)
    return 99


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(98)
