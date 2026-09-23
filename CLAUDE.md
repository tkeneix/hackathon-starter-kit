# CLAUDE.md — hackathon-starter-kit

ハッカソン向けスターターキット。**チーム開発**で、データ分析（Jupyter）→ アプリ企画 → 資料作成・発表
→ 仕様決め → Web アプリ開発（DB・LLM 利用、コンテナ起動）までを 1 リポジトリで進める。
全体計画は [docs/roadmap.md](docs/roadmap.md)、環境構築は [docs/setup.md](docs/setup.md)。
GitHub のテンプレートリポジトリから作る前提で、`tools/`・`.github/` などはキット共通部品として扱う
（ファイルの分類は [docs/setup.md](docs/setup.md) §4。共通部品を変えるときはキット側への反映も検討する）。

このファイルはリポジトリにコミットされ、clone 先のどの環境でも効く。個人マシン側の共通ガイドライン
（上位ディレクトリの CLAUDE.md 等）が無い環境でも、以下のルールだけで運用が成立するように書いている。

## Git 運用ルール（必須）

詳細は [docs/git-workflow.md](docs/git-workflow.md)。すべて `tools/bin/flow.sh` 経由で行う。

1. **main に直接コミット・push しない**。pre-commit / pre-push フックで技術的にも拒否される。
2. **作業単位 = 1 指示 = 1 ブランチ**。着手時に `tools/bin/flow.sh start <短い内容>` で
   `work/<yyyymmdd>-<短い内容>` を origin/main から作る（並行作業は `--worktree`）。
   新しい指示が今のブランチのスコープを明らかに外れる場合は、着手前に
   「ここで一区切りつけて PR にしますか？」とユーザーに確認する。
3. 作業完了時は `tools/bin/flow.sh pr -t "タイトル"`（ゲート → push → PR 作成）まで行い、PR の URL を報告する。
   ブランチ作成・コミット・push・PR 作成は都度の許可不要。
4. **マージはユーザーが「マージして」と明示的に指示するまで絶対に実行しない**（チーム開発のため、
   PR はレビューを経る）。指示を受けたら `tools/bin/flow.sh merge <PR番号> --approved`。
   `gh pr merge` や GitHub API で直接マージしない。PR 作成後に「続けてマージしますか？」と促すこともしない。
   PR の承認（`tools/bin/flow.sh approve <PR番号>`、コメント既定 "LGTM"）も、ユーザーの指示があるときだけ行う。
   承認ポリシー: 作成者本人を含め誰か 1 人の承認があればマージしてよい（`merge` は承認 0 件の PR を拒否する）。
5. ゲート（`flow.sh check`）が落ちたら直す。`--no-verify` で迂回しない。秘密情報の誤検知は
   本当に誤検知か確認したうえで行末に `flow:allow-secret` を付ける。
6. force push・履歴書き換え・未コミット変更の破棄・リモートブランチ削除（`prune --execute`）・
   ブランチ保護変更（`protect --execute`）は都度ユーザーに確認する。
7. 認証は `gh auth login`（ユーザー自身の端末で実行）。トークン・パスワードを読む・表示する・
   ファイルやログに書くことはしない。

## 開発の原則

- 変更前に既存コードを読み、既存の書き方・コメント密度に合わせる。修正の背景はコメントに残す。
- **モック・ダミーデータをユーザーの許可なく作らない**（テスト用のフィクスチャは除く）。
- 例外処理では失敗した操作・入力の特徴・スタックトレースを出す。秘密情報はログに出さない。
- 秘密情報は `.env`（コミット禁止、ゲートで検出）に置き、テンプレートは `.env.example` に置く。
- 大きなデータ・モデルは `data/`（gitignore 対象）に置く。ゲートは 5MB 超のファイルを拒否する。
- 変更後は必ずテストと動作確認を行う。エラーが解決しなければ未完成と報告する。
- 「検討」「考察」の指示では実装に進まず分析のみ行う。

## コマンド

```bash
tools/bin/flow.sh setup        # clone 直後（hooks 有効化・必須ツール・gh 認証の確認）
tools/bin/flow.sh init         # テンプレートから作成した直後に作成者が 1 回（プロジェクト名の置き換え）
uv sync                        # Python 依存関係
uv run pytest                  # テスト（tools/tests: git ワークフローの結合テスト）
uv run ruff check . && uv run ruff format --check .
tools/bin/flow.sh check        # マージ前ゲート
```
