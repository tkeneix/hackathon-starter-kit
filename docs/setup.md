# 環境構築ガイド（clone から開発開始まで）

新しいマシン・新しいメンバーが **clone してから最初の PR を出すまで** の手順。
現時点（フェーズ 0）で必要なのは §1〜§4。§5 はアプリ開発フェーズで有効になる（[roadmap.md](roadmap.md)）。

## 1. 前提ツール

| ツール | 用途 | 必須時期 |
|---|---|---|
| git 2.38+ | バージョン管理 | 今すぐ |
| python3 3.11+ | ゲート・フック（標準ライブラリのみ） | 今すぐ |
| gh (GitHub CLI) | PR 作成・認証 | 今すぐ |
| uv | Python 依存関係・テスト実行 | 今すぐ |
| Docker (Desktop / Engine + Compose v2) | DB・アプリのコンテナ起動 | フェーズ 1〜 |
| Node.js 22 LTS + pnpm | フロントエンド・Marp（資料） | フェーズ 3〜 |

```bash
# macOS
brew install git gh uv
brew install --cask docker          # または OrbStack
brew install node pnpm

# Ubuntu / WSL2（Windows は WSL2 上で作業する。改行コード・実行権限の事故を避けるため）
sudo apt install -y git python3
# gh: https://github.com/cli/cli/blob/trunk/docs/install_linux.md
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 2. 認証と clone

```bash
gh auth login              # GitHub.com → HTTPS → ブラウザでログイン（ご自身の端末で）
gh auth setup-git          # git push/fetch に gh の認証を使う
gh repo clone tkeneix/hackathon-starter-kit
cd hackathon-starter-kit
```

## 3. 初期セットアップ

```bash
tools/bin/flow.sh setup    # git hooks 有効化 + 必須ツール・gh 認証の確認（最後に「セットアップ OK」）
uv sync                    # .venv 作成・開発依存（pytest, ruff）インストール
uv run pytest              # 全テストが通ることを確認
```

`flow.sh setup` を実行するまで pre-commit / pre-push フックは効かない。**clone したら必ず最初に実行する**。

Claude Code を使う場合: リポジトリ直下で起動すれば [CLAUDE.md](../CLAUDE.md) と
[.claude/settings.json](../.claude/settings.json)（マージ系コマンドは必ず承認ダイアログ）が自動で効く。
個人用の許可設定は `.claude/settings.local.json`（gitignore 対象）に書く。

## 4. 最初の PR まで

```bash
tools/bin/flow.sh start hello          # work/<yyyymmdd>-hello ブランチ
# ... 編集 ...
git add -A && git commit -m "..."      # pre-commit でゲートが走る
tools/bin/flow.sh pr -t "..."          # PR 作成 → URL が表示される
```

マージはレビュー後、チームで合意してから（[git-workflow.md](git-workflow.md) §3）。

## 5. アプリ開発フェーズ以降（予定）

フェーズ 1 で `docker compose up` / `make` 系の入口と `.env.example` を追加し、本節を更新する。

```bash
cp .env.example .env       # API キー等を記入（コミット禁止・ゲートで検出）
make up                    # DB・API・Web・Jupyter をコンテナで起動（予定）
```

## 6. 環境移行時の注意

- `.env` とデータ（`data/`）は git に入らない。移行先へは別経路（共有ドライブ等）で渡す
- `.git/flow-logs/` と `core.hooksPath` 設定は clone 単位。移行先では §3 をやり直す
- worktree（`.worktrees/`）は移行対象外。未 push のブランチは移行前に push しておく
