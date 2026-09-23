# プラン: AI 駆動開発プロセス（8 ステップ）の取り込み

> ステータス: 人間承認済み（主要判断は 2026-09-23 の質疑で決定。§6）
> 要件: 「AI 駆動開発テンプレート一式」の開発プロセスをスターターキットに取り込む
> 関連: `CLAUDE.md`、`.claude/`、`docs/`、`.github/pull_request_template.md`、`docs/setup.md`
> 作成日: 2026-09-23

## 1. 概要

実装前にプランで曖昧さを除き、観点別の独立レビュー・TDD・人間レビューを経てマージする開発プロセスを、
キット共通部品として組み込む。テンプレートから作る全プロジェクトで、Claude Code が同じ手順で動くようにする。

## 2. 要件

### P0: 必須

- P0-1: 8 ステップのプロセス定義（`docs/process/8-step-development.md`）と人間の承認ゲートを明文化する
- P0-2: `CLAUDE.md` を薄い入口に再構成し、プロセス・ルール・Skill・レビュアーへのルーティングと優先順位を示す
- P0-3: パス別ルール（`.claude/rules/`）、作業手順 Skill（`.claude/skills/`）、独立レビュアー（`.claude/agents/`）を置く
- P0-4: 秘密情報の読み取りを `.claude/settings.json` で機械的に拒否する（`.env.example` は拒否しない）
- P0-5: 既存の Git 運用（PR 自動作成、承認・マージは指示制、ゲート・hooks）と矛盾しない

### P1: 重要

- P1-1: プラン雛形・8 ステッププロンプト・チェックリストを日本語で置く
- P1-2: ログ・ファイルから障害を解析する Skill（Sentry 版の代替）
- P1-3: PR 本文をテンプレートの構成（課題・解決策・テスト・レビュー観点）に揃える
- P1-4: 設定ファイルの構造（frontmatter・リンク切れ・deny パターン）を自動テストで検証する
- P1-5: テンプレート派生先での扱い（キット共通部品 / 育てるもの）を `docs/setup.md` に反映する

### P2: 将来

- CI で AI レビュー結果をチェックする仕組み（チェックリスト「組織導入」項目）

### 受け入れ条件

- Given clone 直後の派生リポジトリ / When Claude Code を起動 / Then `CLAUDE.md` から 8 ステップ・ルール・Skill・レビュアーに辿れる
- Given `.env` と `.env.example` / When Claude が読み取りを試みる / Then `.env` は拒否され `.env.example` は許可される
- Given 設定ファイル群 / When `uv run pytest` / Then frontmatter とリンクの整合性テストが通る

## 3. 詳細設計

| ファイル | 内容 |
|---|---|
| `CLAUDE.md` | 目的・技術・構成・コマンド・必須プロセス・優先順位・ルーティング・承認ゲート・Git 運用・安全 |
| `AGENTS.md` | 他 AI 向けの互換入口（`CLAUDE.md` を正本として参照するだけ） |
| `.claude/settings.json` | 既存の allow/ask に、秘密情報の deny を追加 |
| `.claude/rules/{architecture,testing,review,logging,database}.md` | テンプレートを日本語化し、パスを本キットの構成（`backend/`・`frontend/`・`analysis/` 等）に合わせる |
| `.claude/skills/{plan-document,tdd,eng-practices,create-pr,log-debug-issue}/SKILL.md` | 日本語版を基に本キットのコマンド・`flow.sh` に合わせる |
| `.claude/agents/{design,security,operations,business,test-coverage,edge-case}-reviewer.md` | Step 2・3・6 の観点別レビュアー |
| `docs/process/8-step-development.md`、`docs/process/prompts.md` | プロセス定義と人間向けプロンプト集 |
| `docs/templates/plan-document.md`、`docs/checklists/ai-driven-development.md`、`docs/plans/README.md` | 雛形・チェックリスト・プラン置き場 |

### 設計判断とトレードオフ

| 判断 | 採用理由 | 見送った案 | 代償・残存リスク |
|---|---|---|---|
| PR 作成は自動のまま（Step 7 は GitHub の PR 上で行う） | ユーザー決定。PR をレビューの場にする | テンプレート通り PR 本文を承認後に投稿 | PR 作成は人間ゲートにならない |
| 全作業に 8 ステップをフル適用 | ユーザー決定 | 重要度で 3 段階に分ける | ハッカソンでは 1 機能あたりの時間が増える。typo・書式のみは人間の明示承認で短縮可 |
| Sentry Skill の代わりにログ・ファイル解析 Skill | ユーザー決定。技術選定に Sentry が無い | Sentry Skill を同梱 | 監視 SaaS 連携は将来追加 |
| テンプレートに無い運用・ビジネス・テスト網羅性レビュアーを追加（推測） | Step 2・3 が要求する観点に対応するエージェントがテンプレートに無いため | 汎用エージェントに都度プロンプトで指示 | エージェント定義の保守対象が増える |
| 日本語版（Codex 向け）を基に Claude の構成へ配置 | リポジトリの文書言語に合わせる | 英語版をそのまま配置 | テンプレート更新時の差分追従は手作業 |

## 4. テスト範囲

- 単体: `tools/tests/test_claude_config.py`（settings の JSON・deny パターン、Skill/Agent の frontmatter、rules の paths、Markdown リンク切れ）
- 回帰: 既存の `tools/tests/test_flow.py` がすべて通ること
- 対象外: エージェント・Skill が実際に期待通り振る舞うか（LLM の出力は自動テストしない。運用で確認）

## 5. 新規テストケース

| ID | シナリオ | 期待結果 | 対応要件 |
|---|---|---|---|
| UT-001 | settings.json を読み込む | 有効な JSON で、`.env` の Read/Edit/Write が deny されている | P0-4 |
| UT-002 | deny パターンと `.env.example` | どの deny パターンにも一致しない | P0-4 |
| UT-003 | 各 SKILL.md | `name`（ディレクトリ名と一致）と `description` がある | P0-3 |
| UT-004 | 各エージェント定義 | `name`（ファイル名と一致）・`description`・`tools` があり、Edit/Write を持たない | P0-3 |
| UT-005 | rules の `paths` | 文字列のリスト | P0-3 |
| UT-006 | CLAUDE.md・AGENTS.md・docs の相対リンクと `.claude/`・`docs/` のパス表記 | すべて実在する | P0-2 |

## 6. 人間の決定（2026-09-23）

- PR 作成: 現状維持（自動）。PR 本文はテンプレートの構成に揃える
- 適用範囲: 全作業にフル適用
- Sentry Skill: 入れず、ログ・ファイルから解析する Skill を入れる
- ブランチ: PR #3 の上に積む

## 7. スコープ外

- アプリ（backend/frontend）の実コード・コマンド整備（フェーズ 1 以降。`CLAUDE.md` のコマンド欄は未整備と明記）
- CI での AI レビュー自動化（P2）

## 8. レビュー記録

| 視点 | 指摘 | 重要度 | 対応 | 状態 |
|---|---|---|---|---|
| （Step 6 の結果をここに記録する） | | | | |

## 9. 完了条件

- [ ] P0 要件をすべて満たした
- [ ] 新規テストケースを実装し、Red（未実装で失敗）→ Green を確認した
- [ ] `uv run pytest`・ruff・shellcheck・ゲートが成功した
- [ ] 設計・境界値・セキュリティのレビューを完了した
- [ ] 人間が差分と残存リスクを確認した
