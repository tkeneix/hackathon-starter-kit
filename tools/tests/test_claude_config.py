"""Claude Code 設定（CLAUDE.md・.claude/・docs）の構造テスト。

AI 駆動開発プロセスの設定ファイルは Markdown と JSON の集合で、壊れても実行時エラーにならない
（frontmatter の欠落・リンク切れ・deny パターンの誤りは「静かに効かない」）。構造だけを機械的に検証する。
計画: docs/plans/20260923-ai-driven-process.md の UT-001〜UT-006。
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
LINKED_DOCS = [ROOT / "CLAUDE.md", ROOT / "AGENTS.md", *sorted((ROOT / "docs").rglob("*.md")), *SKILLS, *AGENTS]
# バッククォートのパス表記まで検証するのは、Claude が実際に辿るルーティング文書だけ
# （roadmap の将来予定ファイルや、gitignore 対象の個人設定ファイルへの言及は存在しなくてよい）
ROUTING_DOCS = {
    ROOT / "CLAUDE.md",
    ROOT / "AGENTS.md",
    *(ROOT / "docs" / "process").glob("*.md"),
    *SKILLS,
    *AGENTS,
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
            data[key].append(line.lstrip()[2:].strip().strip('"'))
        else:
            raise AssertionError(f"{path}: 解釈できない frontmatter 行: {line!r}")
    return data


# ------------------------------------------------------------------ UT-001 / UT-002 settings.json


def load_settings() -> dict:
    return json.loads((CLAUDE_DIR / "settings.json").read_text(encoding="utf-8"))


def deny_patterns(tool: str) -> list[str]:
    prefix = f"{tool}("
    return [p[len(prefix) : -1] for p in load_settings()["permissions"].get("deny", []) if p.startswith(prefix)]


def matches(pattern: str, rel_path: str) -> bool:
    """Claude Code の gitignore 風パターンを近似評価する（./ はプロジェクトルート基準、** は任意階層）。"""
    pat = pattern[2:] if pattern.startswith("./") else pattern
    candidates = {pat}
    if pat.startswith("**/"):
        candidates.add(pat[3:])  # **/ は 0 階層も含む
    return any(fnmatch.fnmatchcase(rel_path, c) for c in candidates)


@pytest.mark.parametrize("tool", ["Read", "Edit", "Write"])
@pytest.mark.parametrize("secret", [".env", ".env.local", ".env.production", "backend/.env", "secrets/api.key"])
def test_settings_deny_secret_files(tool, secret):
    assert any(matches(p, secret) for p in deny_patterns(tool)), f"{tool}({secret}) が deny されていない"


@pytest.mark.parametrize("tool", ["Read", "Edit", "Write"])
@pytest.mark.parametrize("allowed", [".env.example", "backend/.env.example", "docs/setup.md"])
def test_settings_do_not_deny_env_template(tool, allowed):
    hit = [p for p in deny_patterns(tool) if matches(p, allowed)]
    assert not hit, f"{tool}({allowed}) が {hit} で deny されてしまう"


def test_settings_keep_merge_and_approve_behind_ask():
    ask = load_settings()["permissions"]["ask"]
    for cmd in ("flow.sh merge", "gh pr merge", "flow.sh approve"):
        assert any(cmd in p for p in ask), cmd


# ------------------------------------------------------------------ UT-003 / UT-004 / UT-005


def test_expected_files_exist():
    assert {p.parent.name for p in SKILLS} == EXPECTED_SKILLS
    assert {p.stem for p in AGENTS} == EXPECTED_AGENTS
    assert {p.stem for p in RULES} == EXPECTED_RULES


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_skill_frontmatter(path):
    fm = parse_frontmatter(path)
    assert fm.get("name") == path.parent.name
    assert isinstance(fm.get("description"), str) and len(fm["description"]) >= 20


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: p.stem)
def test_agent_frontmatter_is_read_only_reviewer(path):
    fm = parse_frontmatter(path)
    assert fm.get("name") == path.stem
    assert isinstance(fm.get("description"), str) and len(fm["description"]) >= 20
    tools = {t.strip() for t in str(fm.get("tools", "")).split(",") if t.strip()}
    assert tools, "tools を明示する（独立レビュアーの権限を限定するため）"
    assert not tools & {"Edit", "Write", "NotebookEdit"}, f"レビュアーは編集権限を持たない: {tools}"


@pytest.mark.parametrize("path", RULES, ids=lambda p: p.stem)
def test_rule_paths_are_string_lists(path):
    fm = parse_frontmatter(path)
    if "paths" in fm:  # paths が無いルールは常時適用
        assert isinstance(fm["paths"], list) and fm["paths"], f"{path}: paths が空"
        assert all(isinstance(p, str) and p for p in fm["paths"])


# ------------------------------------------------------------------ UT-006 リンク・パス表記


def _referenced_paths(doc: Path) -> list[tuple[str, Path]]:
    text = doc.read_text(encoding="utf-8")
    refs: list[tuple[str, Path]] = []
    # Markdown の相対リンク [x](path)
    for target in re.findall(r"\]\(([^)\s#]+)(?:#[^)]*)?\)", text):
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
