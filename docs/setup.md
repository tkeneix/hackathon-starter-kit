# 環境構築ガイド

このリポジトリは GitHub の **テンプレートリポジトリ**（`tkeneix/hackathon-starter-kit`）から作る前提。
プロジェクトごとにテンプレートから新しいリポジトリを作り、メンバーはそれを clone して開発する。

| 誰が | いつ | 手順 |
|---|---|---|
| プロジェクト作成者（1 名） | プロジェクト開始時に 1 回 | §2 テンプレートから作成 |
| メンバー全員 | 参加時・マシン移行時 | §3 clone して開発開始 |
| プロジェクト作成者 | キットが更新されたとき（任意） | §5 キット更新の取り込み |
| キット管理者 | テンプレート自体を直すとき | §6 テンプレートのメンテナンス |

## 1. 前提ツール

| ツール | 用途 | 必須時期 |
|---|---|---|
| git 2.38+ | バージョン管理 | 今すぐ |
| python3 3.11+ | ゲート・フック（標準ライブラリのみ） | 今すぐ |
| gh (GitHub CLI) | リポジトリ作成・PR・認証 | 今すぐ |
| uv | Python 依存関係・テスト実行（`.python-version` の版を自動で使う） | 今すぐ |
| Docker Engine + Compose v2 | DB 等のミドルウェアをコンテナ起動 | フェーズ 1〜 |
| Node.js 22 LTS + pnpm | フロントエンド（Next.js）・Marp（資料） | フェーズ 3〜 |

開発は Linux 上で直接行う想定（devcontainer は使わない。[roadmap.md](roadmap.md) の決定事項）。

```bash
# Ubuntu
sudo apt install -y git python3
# gh: https://github.com/cli/cli/blob/trunk/docs/install_linux.md
curl -LsSf https://astral.sh/uv/install.sh | sh
# Docker Engine: https://docs.docker.com/engine/install/ubuntu/

# macOS
brew install git gh uv node pnpm
```

GitHub の認証（各自、ご自身の端末で 1 回）:

```bash
gh auth login              # GitHub.com → HTTPS → ブラウザでログイン
gh auth setup-git          # git push/fetch に gh の認証を使う
```

## 2. テンプレートから新しいリポジトリを作る（プロジェクト作成者が 1 回）

```bash
# 1. テンプレートから作成して clone（Organization なら <owner> に組織名。公開なら --public）
gh repo create <owner>/<name> --template tkeneix/hackathon-starter-kit --private --clone
cd <name>

# 2. セットアップ確認と初期化
tools/bin/flow.sh setup    # git hooks 有効化・ツール確認
uv sync
tools/bin/flow.sh init     # README・CLAUDE.md・pyproject.toml のプロジェクト名を置き換え、
                           # work/<yyyymmdd>-init ブランチにコミットまで行う

# 3. 初回 PR（ここで CI が初めて走る）
tools/bin/flow.sh pr -t "テンプレートから初期化"

# 4. CI 合格を確認したら main を保護（必須チェック gate は CI が 1 回走った後でないと指定できない）
gh pr checks <PR番号> --watch
tools/bin/flow.sh protect --execute

# 5. 承認してマージ（作成者本人の承認で可。git-workflow.md §3 承認ポリシー）
tools/bin/flow.sh approve <PR番号>
tools/bin/flow.sh merge <PR番号> --approved
```

GitHub の画面で行う設定:

- **Settings → Collaborators**（Organization なら Teams）でメンバーを招待する
- **Settings → General → Pull Requests**: 「Allow squash merging」のみ有効、
  「Automatically delete head branches」を有効（推奨）
- CI で API キー等が必要になったら **Settings → Secrets and variables → Actions** に登録する

**テンプレートから引き継がれないもの**: ブランチ保護・メンバー・Secrets・リポジトリ設定・Issue/PR。
上の手順で都度設定する。コミット履歴は引き継がれず、1 コミットから始まる。

GitHub の画面から作る場合は、テンプレートのページで「Use this template」→「Create a new repository」を選び、
作成後に clone して手順 2 以降を行う。

## 3. clone して開発を始める（メンバー全員）

```bash
gh repo clone <owner>/<name>
cd <name>
tools/bin/flow.sh setup    # git hooks 有効化 + 必須ツール・gh 認証の確認（最後に「セットアップ OK」）
uv sync                    # .venv 作成・開発依存（pytest, ruff）インストール
uv run pytest              # 全テストが通ることを確認
```

**`flow.sh setup` を実行するまで pre-commit / pre-push フックは効かない**。clone したら必ず最初に実行する
（clone 単位の設定のため、マシン移行・再 clone のたびに必要）。

最初の PR まで:

```bash
tools/bin/flow.sh start hello          # work/<yyyymmdd>-hello ブランチ
# ... 編集 ...
git add -A && git commit -m "..."      # pre-commit でゲートが走る
tools/bin/flow.sh pr -t "..."          # PR 作成 → URL が表示される
```

承認・マージの運用は [git-workflow.md](git-workflow.md) §3。

Claude Code を使う場合: リポジトリ直下で起動すれば [CLAUDE.md](../CLAUDE.md)、`.claude/` のルール・Skill・レビュアー、
[.claude/settings.json](../.claude/settings.json)（承認・マージ系コマンドは確認ダイアログ、`.env` 等の読み取りは拒否）が自動で効く。
開発は [8 ステップ開発プロセス](process/8-step-development.md)で進める。
個人用の許可設定は `.claude/settings.local.json`（gitignore 対象）に書く。

## 4. 構成管理: ファイルの分類

テンプレートから作ったリポジトリでは、ファイルを次の 3 種類として扱う。

| 分類 | ファイル | 派生リポジトリでの扱い |
|---|---|---|
| **キット共通部品** | `tools/`、`.github/`、`.claude/`（settings・rules・skills・agents）、`AGENTS.md`、`.gitignore`、`.gitattributes`、`.python-version`、`docs/git-workflow.md`、`docs/setup.md`、`docs/process/`、`docs/templates/`、`docs/checklists/` | 原則そのまま使う。キット側の更新を §5 で取り込める。独自に変える場合は取り込み時の差分に注意 |
| **プロジェクト固有値** | `README.md`、`CLAUDE.md` の見出し、`pyproject.toml` の `name`、`uv.lock` | `flow.sh init` が自動で置き換える |
| **プロジェクトで育てるもの** | `docs/plans/`（タスクごとのプラン）、`docs/roadmap.md`（決定事項）、アプリ・分析コード、`CLAUDE.md` のプロジェクト固有ルール（技術・構成・コマンド） | 自由に編集する |

- 秘密情報（`.env`）とデータ（`data/`）は git に入れない（ゲートで検出）。テンプレートにも含めない
- 改行コードは `.gitattributes` で LF に統一している（どの OS で clone してもスクリプトが CRLF で壊れない）

## 5. キット更新の取り込み（任意）

テンプレートから作ったリポジトリは元のキットと履歴がつながっていない。キット側の改善を取り込むときは、
**マージではなくファイル単位で**取り込む。

```bash
# 初回のみ: キットをリモート "kit" として登録（誤って push しないよう push 先を無効化）
git remote add kit https://github.com/tkeneix/hackathon-starter-kit.git
git remote set-url --push kit DISABLED

# 取り込み
tools/bin/flow.sh start kit-update
git fetch kit
git diff HEAD kit/main --stat -- tools .github .claude AGENTS.md docs/process docs/templates docs/checklists docs/git-workflow.md docs/setup.md   # 差分を確認
git checkout kit/main -- tools .github/workflows .claude/rules .claude/skills .claude/agents   # 取り込むものだけ選ぶ
uv run pytest && git commit -m "キット更新の取り込み" && tools/bin/flow.sh pr
```

`README.md`・`CLAUDE.md`・`pyproject.toml`・`docs/roadmap.md` はプロジェクト側で編集済みのため、
丸ごと上書きしない（必要な箇所だけ手で反映する）。

## 6. テンプレート自体のメンテナンス（キット管理者向け）

- テンプレート指定（1 回だけ）: `gh repo edit tkeneix/hackathon-starter-kit --template`
  （または Settings → General →「Template repository」）
- テンプレートに入るのは **既定ブランチ（main）の内容だけ**。変更は通常どおり PR → マージで main に入れる
- `flow.sh init` はテンプレート自身では実行できない（誤って置き換えないよう拒否する）
- テンプレート固有値は `tools/bin/flow.sh` 冒頭の `TEMPLATE_REPO` / `TEMPLATE_NAME`。
  リポジトリ名を変えたらここも変える

## 7. アプリ開発フェーズ以降（予定）

フェーズ 1 で `compose.yaml` / `Makefile` と `.env.example` を追加し、本節を更新する。

```bash
cp .env.example .env       # LLM の接続先・API キー等を記入（コミット禁止・ゲートで検出）
make up                    # DB 等をコンテナで起動（予定）
```

## 8. マシン移行時の注意

- `.env` とデータ（`data/`）は git に入らない。移行先へは別経路（共有ドライブ等）で渡す
- `core.hooksPath` 設定と `.git/flow-logs/` は clone 単位。移行先では §3 をやり直す
- worktree（`.worktrees/`）は移行対象外。未 push のブランチは移行前に push しておく
