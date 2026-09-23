# hackathon-starter-kit

ハッカソン向けのスターターキット。チームでデータ分析（Jupyter）→ 企画・発表 → Web アプリ（DB・LLM・コンテナ）
開発までを進めるための土台。

## はじめに

```bash
gh auth login && gh auth setup-git
gh repo clone tkeneix/hackathon-starter-kit && cd hackathon-starter-kit
tools/bin/flow.sh setup      # git hooks 有効化・環境確認
uv sync && uv run pytest
```

詳細: [docs/setup.md](docs/setup.md)

## ドキュメント

- [docs/setup.md](docs/setup.md) — 環境構築（clone から最初の PR まで）
- [docs/git-workflow.md](docs/git-workflow.md) — ブランチ・PR・マージの運用（`tools/bin/flow.sh`）
- [docs/roadmap.md](docs/roadmap.md) — フェーズ計画と開発ツール選定
- [CLAUDE.md](CLAUDE.md) — AI エージェント（Claude Code）向けルール

## 開発フロー（概要）

```bash
tools/bin/flow.sh start <短い内容>     # 作業ブランチ作成
git commit ...                          # pre-commit でゲート（構文・秘密情報・.env・巨大ファイル）
tools/bin/flow.sh pr -t "タイトル"      # PR 作成
# レビュー後、チームの合意で
tools/bin/flow.sh merge <PR番号> --approved
```
