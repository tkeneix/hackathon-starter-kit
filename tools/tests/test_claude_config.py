"""Claude Code 設定（CLAUDE.md・.claude/・docs）の構造テスト。

AI 駆動開発プロセスの設定ファイルは Markdown と JSON の集合で、壊れても実行時エラーにならない
（frontmatter の欠落・リンク切れ・deny パターンの誤りは「静かに効かない」）。構造だけを機械的に検証する。
計画: docs/plans/20260923-ai-driven-process.md の UT-001〜UT-010。
"""

from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLAUDE_DIR = ROOT / ".claude"
SKILLS = sorted((CLAUDE_DIR / "skills").glob("*/SKILL.md"))
AGENTS = sorted((CLAUDE_DIR / "agents").glob("*.md"))
RULES = sorted((CLAUDE_DIR / "rules").glob("*.md"))

# Markdown リンクを検証する文書（入口と docs 配下）
LINKED_DOCS = [
    ROOT / "CLAUDE.md",
    ROOT / "AGENTS.md",
    ROOT / "README.md",
    ROOT / ".github" / "pull_request_template.md",
    *sorted((ROOT / "docs").rglob("*.md")),
    *SKILLS,
    *AGENTS,
    *RULES,
]
# バッククォートのパス表記まで検証するのは、Claude が実際に辿るルーティング文書だけ
# （roadmap の将来予定ファイルや、gitignore 対象の個人設定ファイルへの言及は存在しなくてよい）
ROUTING_DOCS = {
    ROOT / "CLAUDE.md",
    ROOT / "AGENTS.md",
    *(ROOT / "docs" / "process").glob("*.md"),
    *SKILLS,
    *AGENTS,
    *RULES,
}

EXPECTED_SKILLS = {"plan-document", "tdd", "eng-practices", "create-pr", "log-debug-issue"}
EXPECTED_AGENTS = {
    "design-reviewer",
    "security-reviewer",
    "operations-reviewer",
    "business-reviewer",
    "test-coverage-reviewer",
    "edge-case-reviewer",
}
EXPECTED_RULES = {"architecture", "testing", "review", "logging", "database"}


ALLOWED_KEYS = {
    "skill": {"name", "description", "disable-model-invocation", "allowed-tools"},
    "agent": {"name", "description", "tools", "model"},
    "rule": {"paths"},
}
# 独立レビュアーに許すツール（読み取り専用。Bash は許可設定次第で push・PR 作成もできるため持たせない）
REVIEWER_TOOLS = {"Read", "Grep", "Glob"}


def parse_frontmatter(path: Path) -> dict[str, object]:
    """YAML frontmatter の最小パーサ（key: value と、paths のような "- 値" のリストだけを扱う）。"""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    assert end != -1, f"{path}: frontmatter が閉じていない"
    data: dict[str, object] = {}
    key = None
    for line in text[4:end].splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if m:
            key, value = m.group(1), m.group(2).strip()
            data[key] = value if value else []
        elif line.lstrip().startswith("- ") and key is not None and isinstance(data[key], list):
            data[key].append(line.lstrip()[2:].strip().strip('"').strip("'"))
        else:
            raise AssertionError(f"{path}: 解釈できない frontmatter 行: {line!r}")
    return data


# ------------------------------------------------------------------ UT-001 / UT-002 settings.json


def load_settings() -> dict:
    return json.loads((CLAUDE_DIR / "settings.json").read_text(encoding="utf-8"))


def deny_patterns(tool: str) -> list[str]:
    prefix = f"{tool}("
    return [p[len(prefix) : -1] for p in load_settings()["permissions"].get("deny", []) if p.startswith(prefix)]


def _pattern_matches(pattern: str, rel_path: str) -> bool:
    """1 パターンの近似評価（https://code.claude.com/docs/en/permissions の Read/Edit ルール）。

    - `/path` はプロジェクトルート基準、`path`・`./path` はカレントディレクトリ基準（ここではルートで起動した場合）
    - スラッシュを含まないパターンは gitignore と同じく任意の階層のファイル名に一致する
    - `~/`・`//` はリポジトリ外なので対象外（別テストで存在だけ確認する）
    """
    if pattern.startswith(("~/", "//")):
        return False
    pat = pattern[1:] if pattern.startswith("/") else pattern[2:] if pattern.startswith("./") else pattern
    if "/" not in pat:
        return fnmatch.fnmatchcase(rel_path.rsplit("/", 1)[-1], pat)
    # 先頭の **/ は 0 階層も含むので、外した形も候補にする（fnmatch の * は / にも一致する）
    candidates = [pat]
    while candidates[-1].startswith("**/"):
        candidates.append(candidates[-1][3:])
    return any(fnmatch.fnmatchcase(rel_path, c) for c in candidates)


def denied(tool: str, rel_path: str) -> bool:
    """deny リストを先頭から評価する。

    `!` は、それより前にある非アンカー（`path`・`./path`）のルールの一致だけを取り消す。
    `/`・`~/`・`//` で始まるアンカー付きのルールの一致は `!` で取り消せない（公式仕様）。
    """
    anchored_hit = False
    relative_hit = False
    for pattern in deny_patterns(tool):
        if pattern.startswith("!"):
            if _pattern_matches(pattern[1:], rel_path):
                relative_hit = False
        elif _pattern_matches(pattern, rel_path):
            if pattern.startswith(("/", "~/")):
                anchored_hit = True
            else:
                relative_hit = True
    return anchored_hit or relative_hit


def _gate_secret_env_names() -> list[str]:
    """ゲート（flow_gate.is_env_file）が秘密扱いする .env 系の名前。deny の定義をゲートと揃えるために使う。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("flow_gate", ROOT / "tools" / "bin" / "flow_gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    names = [".env", ".env.local", ".env.production", ".env.development", ".env.test", ".env.staging", ".env.prod"]
    assert all(gate.is_env_file(n) for n in names)
    assert not gate.is_env_file(".env.example")
    return names


SECRET_PATHS = [
    *_gate_secret_env_names(),
    *(f"backend/{n}" for n in _gate_secret_env_names()),
    "secrets/api.key",
    "backend/secrets/token.txt",
    "certs/server.pem",
    "backend/private.key",
    ".streamlit/secrets.toml",
]
ALLOWED_PATHS = [".env.example", "backend/.env.example", "frontend/.env.sample", "docs/setup.md", "README.md"]


@pytest.mark.parametrize("tool", ["Read", "Edit", "Write"])
@pytest.mark.parametrize("secret", SECRET_PATHS)
def test_settings_deny_secret_files(tool, secret):
    assert denied(tool, secret), f"{tool}({secret}) が deny されていない"


@pytest.mark.parametrize("tool", ["Read", "Edit", "Write"])
@pytest.mark.parametrize("allowed", ALLOWED_PATHS)
def test_settings_do_not_deny_env_template(tool, allowed):
    assert not denied(tool, allowed), f"{tool}({allowed}) が deny されてしまう"


@pytest.mark.parametrize("tool", ["Read", "Edit", "Write"])
def test_settings_deny_root_env_when_started_in_subdirectory(tool):
    """サブディレクトリで起動すると ./ 基準のルールはルートの .env に届かないため、/ 基準のルールが要る。"""
    anchored = [p for p in deny_patterns(tool) if p.startswith("/")]
    assert any(_pattern_matches(p, ".env") for p in anchored)
    assert any(_pattern_matches(p, "backend/.env") for p in anchored)


def test_settings_deny_credentials_outside_repo():
    patterns = deny_patterns("Read")
    assert "~/.git-credentials" in patterns
    assert "~/.config/gh/**" in patterns


def test_settings_block_bash_reads_that_file_rules_miss():
    """Read の deny は cat 等には効くが、git diff --no-index などには効かない（公式仕様）。"""
    perms = load_settings()["permissions"]
    assert "Bash(*--no-index*)" in perms["deny"]
    assert "Bash(*.env*)" in perms["ask"]


def test_settings_keep_merge_and_approve_behind_ask():
    ask = load_settings()["permissions"]["ask"]
    for cmd in ("flow.sh merge", "gh pr merge", "flow.sh approve"):
        assert any(cmd in p for p in ask), cmd


# ------------------------------------------------------------------ UT-003 / UT-004 / UT-005


def test_expected_files_exist():
    # 派生リポジトリが独自の Skill・Agent・ルールを足しても壊れないよう、部分集合で判定する
    assert EXPECTED_SKILLS <= {p.parent.name for p in SKILLS}
    assert EXPECTED_AGENTS <= {p.stem for p in AGENTS}
    assert EXPECTED_RULES <= {p.stem for p in RULES}


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_skill_frontmatter(path):
    fm = parse_frontmatter(path)
    assert set(fm) <= ALLOWED_KEYS["skill"], f"未知のキー: {set(fm) - ALLOWED_KEYS['skill']}"
    assert fm.get("name") == path.parent.name
    assert isinstance(fm.get("description"), str) and len(fm["description"]) >= 20


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: p.stem)
def test_agent_frontmatter_is_read_only_reviewer(path):
    fm = parse_frontmatter(path)
    assert set(fm) <= ALLOWED_KEYS["agent"], f"未知のキー: {set(fm) - ALLOWED_KEYS['agent']}"
    assert fm.get("name") == path.stem
    assert isinstance(fm.get("description"), str) and len(fm["description"]) >= 20
    tools = {t.strip() for t in str(fm.get("tools", "")).split(",") if t.strip()}
    assert tools, "tools を明示する（独立レビュアーの権限を限定するため）"
    assert tools <= REVIEWER_TOOLS, f"レビュアーは読み取り専用ツールだけを持つ: {tools - REVIEWER_TOOLS}"


@pytest.mark.parametrize("path", RULES, ids=lambda p: p.stem)
def test_rule_paths_are_string_lists(path):
    fm = parse_frontmatter(path)
    assert set(fm) <= ALLOWED_KEYS["rule"], f"未知のキー（paths の誤記?）: {set(fm) - ALLOWED_KEYS['rule']}"
    if "paths" in fm:  # paths が無いルールは常時適用
        assert isinstance(fm["paths"], list) and fm["paths"], f"{path}: paths が空"
        assert all(isinstance(p, str) and p for p in fm["paths"])


# ------------------------------------------------------------------ UT-006 リンク・パス表記


def _referenced_paths(doc: Path) -> list[tuple[str, Path]]:
    text = doc.read_text(encoding="utf-8")
    refs: list[tuple[str, Path]] = []
    # Markdown の相対リンク [x](path)・[x](<path>)・[x](path "title")・参照形式 [x]: path
    inline = re.findall(r"\]\(<?([^)>\s#]+)(?:#[^)>\s]*)?>?(?:\s+\"[^\"]*\")?\)", text)
    reference = re.findall(r"^\s*\[[^\]]+\]:\s*<?([^>\s#]+)", text, flags=re.MULTILINE)
    for target in [*inline, *reference]:
        if re.match(r"^[a-z]+:", target):
            continue  # URL は対象外
        refs.append((target, (doc.parent / target).resolve()))
    if doc not in ROUTING_DOCS:
        return refs
    # バッククォートで書いた .claude/ と docs/ のパス（ルーティング表記）。プレースホルダ・glob は除く
    for target in re.findall(r"`((?:\.claude|docs)/[^`\s]+)`", text):
        if re.search(r"[<>\[\]*{}]", target):
            continue
        refs.append((target, (ROOT / target).resolve()))
    return refs


@pytest.mark.parametrize("doc", LINKED_DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_referenced_paths_exist(doc):
    missing = [t for t, p in _referenced_paths(doc) if not p.exists()]
    assert not missing, f"{doc.relative_to(ROOT)} のリンク切れ: {missing}"


def test_link_regex_detects_title_angle_and_reference_forms(tmp_path):
    """タイトル付き・<...> 囲み・参照形式のリンクも検査対象になること（URL は対象外）。"""
    doc = tmp_path / "x.md"
    doc.write_text('[a](nope1.md "t")\n[b](<nope2.md>)\n[c]: nope3.md\n[d](https://example.com)\n', encoding="utf-8")
    targets = [t for t, _ in _referenced_paths(doc)]
    assert {"nope1.md", "nope2.md", "nope3.md"} <= set(targets)
    assert not any(t.startswith("http") for t in targets)


def test_claude_md_heading_matches_flow_init_target():
    """flow.sh init は CLAUDE.md の 1 行目を置き換える。見出しを変えると init が黙って何もしなくなる。"""
    flow = (ROOT / "tools" / "bin" / "flow.sh").read_text(encoding="utf-8")
    name = re.search(r'^readonly TEMPLATE_NAME="([^"]+)"', flow, flags=re.MULTILINE).group(1)
    assert (ROOT / "CLAUDE.md").read_text(encoding="utf-8").startswith(f"# CLAUDE.md — {name}\n")
