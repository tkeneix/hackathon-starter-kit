# Git 運用ガイド

ブランチ・ゲート・PR・マージ・棚卸しの運用リファレンス。恒久ルールの要約は [../CLAUDE.md](../CLAUDE.md)。
実装は [../tools/bin/flow.sh](../tools/bin/flow.sh) / [../tools/bin/flow_gate.py](../tools/bin/flow_gate.py) /
[../tools/git-hooks/](../tools/git-hooks/)。

## 1. 仕組みの全体像

| 項目 | 内容 |
|---|---|
| PR 操作・認証 | 公式 `gh` CLI（`gh auth login` + `gh auth setup-git`） |
| 既存 PR の判定 | head ブランチ名の一致で判定（無関係な open PR を誤って再利用しない） |
| マージ | **ユーザーの明示指示が必要**。PR 番号必須 + `--approved` |
| マージ方式 | squash（`FLOW_MERGE_METHOD` で変更可） |
| hooks | `core.hooksPath=tools/git-hooks`。pre-commit（main へのコミット拒否 + ゲート）/ pre-push（main への push 拒否） |
| ゲート | syntax / secret / envfile / largefile |
| サーバ側の強制 | GitHub Actions (CI) + ブランチ保護（`flow.sh protect`） |
| ベースブランチ | main |

## 2. 認証

```bash
gh auth login          # GitHub.com / HTTPS / ブラウザ認証を選ぶ
gh auth setup-git      # git push/fetch も gh の認証を使うようにする
```

- **認証はユーザー自身の端末で行う**。AI エージェントに代行させない。トークンをチャット・ファイル・
  コミット・ログに貼らない（貼ってしまったら GitHub 側で失効させる）
- URL にトークンを埋め込む remote 設定はしない（`git remote -v` やシェル履歴に平文で残る）

## 3. 基本フロー

```bash
tools/bin/flow.sh start csv-loader      # origin/main から work/<yyyymmdd>-csv-loader を作成
# ... 作業してコミット（複数回可）。pre-commit でゲートが走る ...
tools/bin/flow.sh pr -t "CSV ローダ追加"   # ゲート → push → PR 作成（既存 PR があれば再利用）
# ... GitHub 上でレビュー・CI 確認 ...
tools/bin/flow.sh approve 12             # レビュアーが承認（コメント既定: LGTM。-m で変更可）
tools/bin/flow.sh merge 12 --approved   # ★ユーザー（チーム）が「マージして」と指示した後だけ
tools/bin/flow.sh sync                  # 他メンバーのマージを取り込む（ローカル main 更新）
```

- 並行作業は `flow.sh start <短い内容> --worktree`（`.worktrees/<短い内容>/` に作成）。
  Claude Code の `EnterWorktree` を使う場合は作成直後に `git branch -m work/<yyyymmdd>-<短い内容>` で規約名に揃える
- `pr` が中断するのは「追跡済みファイルの未コミット変更」がある場合だけ。未追跡ファイルは警告一覧を
  出して続行する（未追跡でも中断させると誤検知が常態化し、回避が習慣化するため）。**警告一覧に PR へ含めるべき
  ファイルが出ていないか毎回目視確認する**
- PR 本文は省略時 [.github/pull_request_template.md](../.github/pull_request_template.md) が入る。`--draft` も可

### merge の安全装置（チーム開発仕様）

- PR 番号の明示が必須（「現在のブランチの PR」を推測しない）
- `--approved` が無い場合、端末からなら y/N 確認、非対話環境（AI エージェント・CI）なら拒否
- draft / コンフリクト / 変更要求 (CHANGES_REQUESTED) / CI 失敗の PR は拒否。CI 実行中・未設定は警告
- Claude Code では `.claude/settings.json` の `ask` ルールで `flow.sh merge` / `gh pr merge` の実行前に
  必ず人間の承認ダイアログが出る
- 最終的な強制は GitHub のブランチ保護（§5）。ローカルの仕組みは回避可能なので、これだけに頼らない

## 4. マージ前ゲート（`check`）

```bash
tools/bin/flow.sh check                    # 全チェック
tools/bin/flow.sh check --only secret      # 一部だけ
```

python3 標準ライブラリのみで動く（venv 不要）。pre-commit フック・`pr`・CI の 3 か所で同じものが走る。

| チェック | 内容 |
|---|---|
| `syntax` | 変更された `.py` の `py_compile` |
| `secret` | 追加行への API キー（GitHub / Anthropic / OpenAI / Google / AWS / Slack）・パスワード・秘密鍵等の混入。検出値そのものは出力しない |
| `envfile` | `.env` / `.env.*` のコミット（`.env.example` 等のテンプレートは可） |
| `largefile` | 5MB 超のファイル（`FLOW_MAX_FILE_MB` で変更可）。データは `data/` へ |

- 比較基準は `origin/main`（無ければローカル `main`）との merge-base
- secret の誤検知は行末に `flow:allow-secret` を付けて抑制できる。**付ける前に本当に誤検知か確認する**

### git hooks

`tools/bin/flow.sh` のどのサブコマンドを実行しても `core.hooksPath=tools/git-hooks` が設定される。
**clone 直後は `tools/bin/flow.sh setup` を一度実行する**（実行前の素の `git commit` にはフックが効かない）。

| フック | 内容 |
|---|---|
| `pre-commit` | main 上のコミットを拒否 + ゲート実行 |
| `pre-push` | main への push を拒否 |

- 設定は clone 単位（その clone から作った worktree には全て効く。別 clone には各自 `setup` が必要）
- 1 回だけ意図的にスキップ: `--no-verify`（原則非推奨。理由をコミットメッセージに残す）
- フックの恒久的な廃止は全メンバーに影響するため、独断で行わずチームで合意する

## 5. GitHub 側の設定（リポジトリ管理者が一度だけ）

```bash
tools/bin/flow.sh protect                 # ドライラン: 設定内容を表示
tools/bin/flow.sh protect --execute       # main を保護（承認 1 件・CI gate 必須・force push/削除禁止）
tools/bin/flow.sh protect --reviews 2 --execute   # 後から承認数を増やす場合（再実行で上書き）
```

- **保護は必要以上に強くしない方針**（チーム決定 2026-09-23）。守るのは「main へは PR 経由・CI 合格・
  承認 1 件」「履歴の書き換え・ブランチ削除の禁止」だけ
- 承認 1 件の既定: 作成者は自分の PR を承認できないため、作成者 + レビュアーの最低 2 名が必要
- 緩めている項目: `enforce_admins=false`（締切直前の緊急時に管理者が回避できる）、
  `dismiss_stale_reviews=false`（承認後の追加 push で承認をリセットしない）、
  `strict=false`（PR ブランチに最新 main の取り込みを強制しない）
- 必須チェック `gate` は [.github/workflows/ci.yml](../.github/workflows/ci.yml) のジョブ名。**CI が一度でも
  走ってから** protect を実行する
- 併せて GitHub の Settings → General → Pull Requests で「Allow squash merging」のみ有効、
  「Automatically delete head branches」を有効にすると棚卸しの手間が減る

## 6. リモートブランチの棚卸し（`prune`）

```bash
tools/bin/flow.sh prune --days 30             # ドライラン（既定）
tools/bin/flow.sh prune --days 30 --execute   # 確認の上で削除
```

- squash マージのブランチは main の祖先にならないため、GitHub 上に merged PR があれば「マージ済み」と判定する
- 未マージのブランチは既定で削除しない（`--include-unmerged`）。**削除は取り消せない**。
  `--execute` はユーザーが明示的に指示したときだけ使う

## 7. コマンド一覧

```
flow.sh setup                                  初回セットアップ確認
flow.sh start <短い内容> [--worktree]           作業ブランチ（または worktree）作成
flow.sh check [--only ...]                     マージ前ゲート
flow.sh pr [-t <title>] [-b <body>] [--draft]  ゲート -> push -> PR 作成
flow.sh approve <PR番号> [-m <コメント>]       PR を承認（レビュアー用、コメント既定 LGTM）
flow.sh merge <PR番号> [--approved]             PR マージ（ユーザー指示時のみ）+ ローカル main 更新
flow.sh sync                                   ローカル main を origin に追従
flow.sh list / status                          worktree 一覧 / 現在の状態
flow.sh prune [--days N] [--execute] [--include-unmerged]
flow.sh protect [--reviews N] [--execute]      main のブランチ保護（管理者）
```

ログ: `.git/flow-logs/flow.log`（JST・1MB × 7 世代ローテーション。clone 外には出ない）。

## 8. やってはいけないこと

- main で直接コミット・push する / ゲートを `--no-verify` で迂回する
- **ユーザーの指示なしにマージする**、`gh pr merge` や API で直接マージする
- `.env` や生データ・学習済みモデルをコミットする
- トークン・パスワードをチャット・ファイル・コミット・ログに平文で残す
- `prune --execute` / `protect --execute` / force push を指示なしに実行する
