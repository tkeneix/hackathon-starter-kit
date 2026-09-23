# docs/plans

タスクごとのプランドキュメント（8 ステップの Step 1 の成果物）を置く。

- ファイル名: `<yyyymmdd>-<短い内容>.md`（作業ブランチ `work/<yyyymmdd>-<短い内容>` と揃える）
- 雛形: [../templates/plan-document.md](../templates/plan-document.md)
- 作り方: Claude Code で `/plan-document`（手順は [../process/8-step-development.md](../process/8-step-development.md)）
- ステータス: Draft → AI レビュー中 → 人間承認済み → 実装完了
- レビュー指摘と対応は各プランの「レビュー記録」に残す。マージ後も削除せず、判断の履歴として残す

このディレクトリはプロジェクトで育てるもの（テンプレートからの派生先で自由に増やす）。
