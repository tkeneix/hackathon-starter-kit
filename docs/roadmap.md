# ロードマップと開発ツール選定

ハッカソンの流れ（データ分析 → 企画 → 資料・発表 → 仕様決め → Web アプリ + DB + LLM をコンテナで起動）を
チームで回すために、このリポジトリに何を入れておくかの計画。2026-09-23 作成。

**方針**: 「テンプレートから作成 → clone → `flow.sh setup` → `make up` で全員が同じ環境」を最優先にする。ハッカソンは時間が
最大の制約なので、選定基準は (1) 環境差で詰まらない (2) 学習コストが低い (3) 生成 AI（Claude Code）が
扱いやすい情報量の多い定番、の順。

## フェーズ一覧

| # | フェーズ | 状態 | 主な成果物 |
|---|---|---|---|
| 0 | チーム開発の土台（PR フロー・テンプレート化） | 完了 | flow.sh・ゲート・hooks・CI・CLAUDE.md・setup.md・`flow.sh init` |
| 1 | 開発環境の骨格 | 未着手 | compose.yaml・Makefile・.env.example・uv workspace |
| 2 | データ分析 | 未着手 | notebooks/・data/ 規約・nbstripout・分析用依存 |
| 3 | 企画・資料・発表 | 未着手 | docs/ideas テンプレ・Marp スライド雛形 |
| 4 | 仕様決め | 未着手 | 仕様書・ADR・Issue テンプレ |
| 5 | アプリ開発 | 未着手 | backend（API + DB + LLM）・frontend・E2E |

## フェーズ 0: チーム開発の土台

- `tools/bin/flow.sh`（ブランチ・PR・マージの CLI）・`flow_gate.py`・pre-commit/pre-push hooks
- GitHub Actions: ゲート + shellcheck + ruff + pytest（ジョブ名 `gate` をブランチ保護の必須チェックに）
- PR テンプレート、`.claude/settings.json`（マージ系は承認必須）、CLAUDE.md（マージはユーザー指示時のみ）
- GitHub テンプレートリポジトリとして配布。`flow.sh init` でプロジェクト固有値を置き換え、ファイルを
  「キット共通部品 / プロジェクト固有値 / プロジェクトで育てるもの」に分類（[setup.md](setup.md) §4）
- 結合テスト（bare リポジトリ + fake gh で GitHub に触れずに検証）

## フェーズ 1: 開発環境の骨格

| 項目 | 選定 | 理由 |
|---|---|---|
| コンテナ | Docker Compose v2（`compose.yaml`） | 全員の環境を揃える唯一の現実解。`profiles` で jupyter 等を任意起動 |
| devcontainer | **標準にしない**（決定 2026-09-23: Linux ホスト上で直接開発） | 依存はホストに uv/pnpm で入れ、DB 等のミドルウェアだけ compose で起動 |
| タスクランナー | Makefile（`make setup/up/down/test/lint`） | 追加インストール不要。コマンドを覚えなくてよい |
| Python 管理 | uv workspace（`backend/`・`analysis/` をメンバーに） | 速い・lock で再現性。既に採用済み |
| 設定・秘密 | `.env.example` + pydantic-settings | ゲートの envfile チェックと対 |
| lint/format | ruff（Python）・Biome or ESLint+Prettier（TS） | ruff は採用済み |

## フェーズ 2: データ分析（Jupyter）

| 項目 | 選定 | 理由 |
|---|---|---|
| 実行環境 | JupyterLab（uv の `analysis` グループ / compose の `jupyter` profile） | ローカル・コンテナ両対応 |
| データ処理 | pandas + polars + DuckDB | DuckDB は CSV/Parquet を SQL で即集計でき、アプリ側 DB への移行も楽 |
| 可視化 | matplotlib / seaborn / plotly | 発表資料への貼り込み（静的）とデモ（対話）の両方 |
| notebook の git 管理 | **nbstripout**（出力を除去してコミット） | 差分肥大・マージ衝突・出力経由の秘密情報/個人情報漏えいを防ぐ。チーム開発では必須 |
| データ置き場 | `data/raw` `data/processed`（gitignore）+ `DATA_DIR` 環境変数 | worktree ではデータが空になる問題を `DATA_DIR` を絶対パスで指して回避 |
| 共有 | 生データは共有ドライブ等、取得スクリプトを `analysis/` にコミット | 5MB 超はゲートで拒否 |

## フェーズ 3: 企画・資料作成・発表

| 項目 | 選定 | 理由 |
|---|---|---|
| アイデア整理 | `docs/ideas/*.md` テンプレ（課題・ターゲット・解決策・デモシナリオ） | PR でレビューでき履歴が残る |
| スライド | **Marp**（Markdown → PDF/PPTX、`npx @marp-team/marp-cli`） | git 管理・差分レビュー可能、Claude が直接書ける。図は Mermaid |
| 代替 | Claude の Slides / pptx 生成 | 見栄え重視の最終版が必要な場合 |

## フェーズ 4: 仕様決め

- `docs/spec.md`（機能一覧・画面・API・データモデル）、`docs/adr/`（技術選定の記録）
- `.github/ISSUE_TEMPLATE/`（機能 / バグ）+ GitHub Projects でタスク分担
- API 仕様は FastAPI の OpenAPI 自動生成を正とし、フロントの型は openapi-typescript で生成

## フェーズ 5: アプリ開発（Web + DB + LLM、コンテナ起動）

| 層 | 第一候補 | 代替 | 理由 |
|---|---|---|---|
| Backend | **FastAPI** + Pydantic v2 | — | 分析コード（Python）をそのまま流用、OpenAPI 自動生成 |
| DB | **PostgreSQL 16 + pgvector** | SQLite（最小構成） | RAG のベクトル検索を同じ DB で扱える |
| ORM/マイグレーション | SQLAlchemy 2 + Alembic | SQLModel | 定番で情報量が多い |
| LLM | **事務局提供の LiteLLM エンドポイント**（OpenAI 互換 API）に OpenAI SDK で接続。`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` を `.env` で指定 | 開発中の代替として Claude 等を直接利用（同じ IF で base_url だけ切替） | LiteLLM は各社 LLM を OpenAI 互換 IF に揃えるプロキシ。モデル名は事務局の指定に従う |
| Frontend | **Next.js（App Router）+ TypeScript**（pnpm）（決定 2026-09-23） | — | API は FastAPI 側に置き、Next.js は画面と BFF 程度に留める |
| テスト | pytest + httpx、Vitest、Playwright（E2E・デモ動画撮影にも） | — | |
| 起動 | `docker compose up`（db / api / web / jupyter） | — | 本番デプロイ先はハッカソン規定に合わせて後で決定 |

## 決定事項（2026-09-23）

| 項目 | 決定 |
|---|---|
| フロントエンド | Next.js |
| LLM | ハッカソン事務局が LiteLLM（OpenAI 互換）のエンドポイントを提供 |
| PR の承認 | 作成者本人を含め誰か 1 人の承認でマージ可（デモ環境向け）。GitHub 側の必須承認数は 0。ブランチ保護は必要以上に強くしない |
| 開発環境 | Linux 上で直接開発。devcontainer は標準にしない |

## 未決事項

1. `flow.sh protect --execute` の実施時期（CI が一度走った後）
2. デプロイ先（ハッカソンの提出形式: デモ動画のみ / URL 提出 / コンテナ提出）
3. LiteLLM エンドポイントで使えるモデル名・レート制限（事務局からの情報待ち）
