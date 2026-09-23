# プラン: AI 駆動開発プロセス（8 ステップ）の取り込み

> ステータス: 実装完了・人間レビュー待ち（主要判断は 2026-09-23 の質疑で決定。§6。Step 6 の指摘は §8）
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
| UT-007 | サブディレクトリで起動した場合（`/` 基準のルール） | ルートと `backend/` の `.env` が deny される | P0-4 |
| UT-008 | リポジトリ外の認証情報・Bash 経由の読み取り | `~/.git-credentials`・`~/.config/gh/**` を deny、`--no-index` を deny、`.env` を含む Bash は ask | P0-4 |
| UT-009 | `flow.sh pr --body-file` | 本文がシェル展開されずにそのまま渡る。`-b` との併用・存在しないファイルはエラー | P0-5 |
| UT-010 | CLAUDE.md の 1 行目 | `flow.sh init` の置換対象と一致する | P0-5 |

## 6. 人間の決定（2026-09-23）

- PR 作成: 現状維持（自動）。PR 本文はテンプレートの構成に揃える
- 適用範囲: 全作業にフル適用
- Sentry Skill: 入れず、ログ・ファイルから解析する Skill を入れる
- ブランチ: PR #3 の上に積む

## 7. スコープ外

- アプリ（backend/frontend）の実コード・コマンド整備（フェーズ 1 以降。`CLAUDE.md` のコマンド欄は未整備と明記）
- CI での AI レビュー自動化（P2）

## 8. レビュー記録

Step 1〜3 は、ユーザーとの質疑（§6）で主要判断を決定して代替した（プロセス導入前のため）。以下は Step 6 の独立レビュー。

| Step | 視点 | 指摘 | 重要度 | 対応 | 状態 |
|---|---|---|---|---|---|
| 6 | 設計 / セキュリティ / 境界値 | レビュアーの Bash 権限が不統一。Bash は許可設定次第で push・PR 作成・秘密情報の読み取りができる | P1 | 全レビュアーを Read・Grep・Glob のみに。差分は呼び出し側が `.review/diff.patch` に保存して渡す。UT-004 で強制 | 対応済み |
| 6 | 設計 / セキュリティ | 優先順位と「止めて報告」が矛盾。プランが Git 運用ルールを上書きできると読める。「明示的な指示」にログ等の文言が含まれ得る | P1 | 矛盾は常に停止、承認ゲートと Git 運用はプランで上書き不可、明示的な指示は会話でのユーザー本人の発言に限定 | 対応済み |
| 6 | セキュリティ / 境界値 | deny の漏れ（`.env.test` 等・`*.pem`・`*.key`・リポジトリ外の認証情報）。`./` はカレント基準のため、サブディレクトリで起動するとルートの `.env` を守れない | P1 | 公式仕様を確認し、gitignore 風ルール + `!` でテンプレートを除外 + `/` 基準のルール + `~/` の認証情報に作り直した。UT-001・002・007・008 | 対応済み |
| 6 | セキュリティ / 境界値 | Bash 経由の読み取り（`git diff --no-index`・スクリプト・`grep -r`）は Read の deny で防げない | P1 | `--no-index` を deny、`.env` を含む Bash を ask に。文書の「機械的に拒否」を正確な表現に修正 | **残存リスク: 人間の受け入れ待ち**（スクリプト・`grep -r` 経由は防げない。サンドボックス / PreToolUse フックは P2 で検討） |
| 6 | セキュリティ | PR 本文をシェル引数に埋め込むと `$(...)` 等が展開され得る。PR 本文に秘密情報を書く禁止が無い | P1 | `flow.sh pr --body-file` を追加し create-pr はファイル経由に。秘密情報・個人データ・生ログを書かない規則を追加。UT-009 | 対応済み |
| 6 | セキュリティ | log-debug-issue: ログ中のコマンド・URL の実行禁止、fork PR の CI ログ、証拠の伏せ字が不足 | P2 | 追記 | 対応済み |
| 6 | 設計 | プランのステータス順がプロセスと逆 | P2 | Draft → 人間承認済み → レビュー済み → 実装完了 に統一 | 対応済み |
| 6 | 設計 | 分析コードの置き場所（`analysis/` と `notebooks/`）が不一致、`.ipynb` がルール対象外 | P2 | `analysis/` に統一（notebook は `analysis/notebooks/`）、rules の paths を `analysis/**/*` に | 対応済み |
| 6 | 設計 | review.md は常時適用なのにルーティングで条件付きに見える。Step 8 の範囲があいまい | P2 | ルーティングに常時適用と明記。Step 8 は定期実行で各タスクの完了条件ではないと明記 | 対応済み |
| 6 | 境界値 | テストの抜け（未知の frontmatter キー、タイトル付き・参照形式リンク、完全一致で派生先が壊れる、init の置換対象） | P2 | 許可キー検証、リンク検出の拡張、部分集合判定、UT-010 を追加 | 対応済み |

## 9. 完了条件

- [x] P0 要件をすべて満たした
- [x] 新規テストケースを実装し、Red（未実装で失敗）→ Green を確認した
- [x] `uv run pytest`・ruff・shellcheck・ゲートが成功した
- [x] 設計・境界値・セキュリティのレビューを完了した（P0 なし。P1 は 1 件を除き対応済み）
- [ ] 人間が差分と残存リスク（§8 の Bash 経由の読み取り）を確認した
