#!/usr/bin/env bash
# flow.sh — git ワークフロー CLI（GitHub 版。hackathon-starter-kit の共通部品）
#
# 作業ブランチ作成 → マージ前ゲート → push → GitHub PR 作成 → (ユーザー指示時のみ) マージ
# → ブランチ棚卸し までを扱う。
#
# 設計のポイント（2026-09-23）:
#   - PR 操作・認証は公式 gh CLI に任せる（gh auth login / gh auth setup-git）
#   - 既存 PR の再利用判定は、必ず head ブランチ名の一致で行う（無関係な open PR の誤再利用を防ぐ）
#   - チーム開発のため merge は自動続行しない。PR 番号の明示 + --approved（または対話確認）必須
#     （AI エージェントはユーザーが「マージして」と指示するまで実行しない。CLAUDE.md 参照）
#   - hooks は core.hooksPath=tools/git-hooks で直接参照する
#     （worktree ごとに自分のチェックアウト版のフックが効き、同期漏れが起きない）
#   - squash マージ後はブランチが main の祖先にならないため、prune のマージ判定に
#     GitHub 上の merged PR も使う
#
# 使い方: tools/bin/flow.sh <subcommand> [args]   詳細は `tools/bin/flow.sh help`

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
readonly SCRIPT_DIR
readonly GATE="${SCRIPT_DIR}/flow_gate.py"
readonly BASE_BRANCH="${FLOW_BASE_BRANCH:-main}"
readonly MERGE_METHOD="${FLOW_MERGE_METHOD:-squash}"
readonly HOOKS_PATH="tools/git-hooks"
readonly BRANCH_PREFIX="work/"
readonly LOG_MAX_BYTES=$((1024 * 1024))
readonly LOG_GENERATIONS=7

# テンプレートリポジトリ（init で派生先の値に置き換える対象）
readonly TEMPLATE_REPO="tkeneix/hackathon-starter-kit"
readonly TEMPLATE_NAME="hackathon-starter-kit"

# ---------------------------------------------------------------- 出力・ログ

# ログは <共通 git dir>/flow-logs/flow.log に JST 時刻付きで残す（clone 外には出ない）。
# 1MB を超えたら flow.log.1 .. flow.log.6 へローテーションし、合計 7 ファイルで循環する。
LOG_FILE=""

init_log() {
    local common
    common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || return 0
    mkdir -p "$common/flow-logs" 2>/dev/null || return 0
    LOG_FILE="$common/flow-logs/flow.log"
    if [ -f "$LOG_FILE" ] && [ "$(wc -c <"$LOG_FILE" | tr -d ' ')" -gt "$LOG_MAX_BYTES" ]; then
        local i
        for ((i = LOG_GENERATIONS - 1; i >= 2; i--)); do
            [ -f "$LOG_FILE.$((i - 1))" ] && mv -f "$LOG_FILE.$((i - 1))" "$LOG_FILE.$i"
        done
        mv -f "$LOG_FILE" "$LOG_FILE.1"
    fi
}

log() {
    [ -n "$LOG_FILE" ] || return 0
    printf '%s [%s] %s\n' "$(TZ=Asia/Tokyo date '+%Y-%m-%dT%H:%M:%S%z')" "$1" "${*:2}" >>"$LOG_FILE" 2>/dev/null || true
}

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; log INFO "$*"; }
warn() { printf '\033[1;33m警告:\033[0m %s\n' "$*" >&2; log WARN "$*"; }
die()  { printf '\033[1;31mエラー:\033[0m %s\n' "$*" >&2; log ERROR "$*"; exit 1; }

# ------------------------------------------------------------ リポジトリ情報

require_git_repo() {
    git rev-parse --git-dir >/dev/null 2>&1 || die "git リポジトリ内で実行してください。"
}

# メイン worktree のルート（worktree 内から実行しても同じ値を返す）
main_root() {
    dirname "$(git rev-parse --path-format=absolute --git-common-dir)"
}

current_branch() {
    git symbolic-ref --short HEAD 2>/dev/null || echo ""
}

today_jst() {
    TZ=Asia/Tokyo date +%Y%m%d
}

# ------------------------------------------------------------ git hooks
#
# .git/hooks/ はリポジトリ管理外のため、追跡済みの tools/git-hooks/ を core.hooksPath で直接指す。
# 相対パスは各 worktree のルート基準で解決されるので、worktree ごとにそのブランチ版のフックが効く。
# flow.sh のどのサブコマンドを実行しても自動で設定する（「覚えておく」手順にしない）。
ensure_hooks_installed() {
    [ -d "$(git rev-parse --show-toplevel)/$HOOKS_PATH" ] || return 0
    if [ "$(git config --local --get core.hooksPath || true)" != "$HOOKS_PATH" ]; then
        git config --local core.hooksPath "$HOOKS_PATH"
        info "git hooks を有効化しました (core.hooksPath=$HOOKS_PATH)"
    fi
}

# ---------------------------------------------------------------- gh

require_gh() {
    command -v gh >/dev/null 2>&1 \
        || die "gh (GitHub CLI) がありません。インストール後 'gh auth login' してください（docs/git-workflow.md §2）。"
    gh auth status >/dev/null 2>&1 \
        || die "gh が未認証です。ご自身の端末で 'gh auth login' → 'gh auth setup-git' を実行してください。"
}

# 指定ブランチを head とする open な PR 番号（無ければ空）
open_pr_for_branch() {
    gh pr list --head "$1" --base "$BASE_BRANCH" --state open --json number --jq '.[0].number // empty'
}

# ------------------------------------------------------------ サブコマンド

cmd_setup() {
    require_git_repo
    ensure_hooks_installed

    local ok=1 tool
    echo "必須ツール:"
    for tool in git python3 gh; do
        if command -v "$tool" >/dev/null 2>&1; then
            printf '  ✓ %-8s %s\n' "$tool" "$(command -v "$tool")"
        else
            printf '  ✗ %-8s 未インストール\n' "$tool"; ok=0
        fi
    done
    echo "開発用ツール（アプリ開発フェーズで使用）:"
    for tool in uv docker node pnpm; do
        if command -v "$tool" >/dev/null 2>&1; then
            printf '  ✓ %-8s %s\n' "$tool" "$(command -v "$tool")"
        else
            printf '  - %-8s 未インストール（docs/setup.md 参照）\n' "$tool"
        fi
    done

    if command -v gh >/dev/null 2>&1; then
        if gh auth status >/dev/null 2>&1; then
            echo "  ✓ gh 認証済み"
        else
            echo "  ✗ gh 未認証 → 'gh auth login' と 'gh auth setup-git' をご自身の端末で実行"; ok=0
        fi
    fi

    echo "git hooks: core.hooksPath=$(git config --local --get core.hooksPath || echo '(未設定)')"
    [ "$ok" = 1 ] && info "セットアップ OK" || die "未完了の項目があります（上記 ✗）。"
}

cmd_start() {
    local slug="" use_worktree=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --worktree) use_worktree=1; shift ;;
            -*)         die "不明なオプション: $1" ;;
            *)          slug=$1; shift ;;
        esac
    done
    [ -n "$slug" ] || die "使い方: flow.sh start <短い内容> [--worktree]"
    [[ "$slug" =~ ^[A-Za-z0-9._-]+$ ]] || die "短い内容は英数字と . _ - のみ: $slug"

    local branch
    branch="${BRANCH_PREFIX}$(today_jst)-${slug}"
    git show-ref --verify --quiet "refs/heads/$branch" && die "ブランチ $branch は既に存在します。"

    info "origin/$BASE_BRANCH を取得します"
    git fetch --quiet origin "$BASE_BRANCH" || die "origin/$BASE_BRANCH の fetch に失敗しました。"

    if [ -n "$use_worktree" ]; then
        local dir
        dir="$(main_root)/.worktrees/$slug"
        git worktree add -b "$branch" "$dir" "origin/$BASE_BRANCH"
        git -C "$dir" branch --unset-upstream >/dev/null 2>&1 || true
        info "worktree を作成しました: $dir （ブランチ ${branch}）"
        echo "  cd $dir"
    else
        [ -z "$(git status --porcelain --untracked-files=no)" ] \
            || die "追跡済みファイルに未コミットの変更があります。コミットか退避してから実行してください。"
        git switch --no-track -c "$branch" "origin/$BASE_BRANCH"
        info "ブランチを作成しました: $branch"
    fi
}

cmd_sync() {
    require_git_repo
    local root checked_out
    root=$(main_root)
    checked_out=$(git -C "$root" symbolic-ref --short HEAD 2>/dev/null || echo "")

    # チェックアウト中のブランチは fetch の refspec で直接更新できないため分岐する
    if [ "$checked_out" = "$BASE_BRANCH" ]; then
        git -C "$root" pull --ff-only --quiet origin "$BASE_BRANCH" \
            || { warn "ローカル $BASE_BRANCH の fast-forward に失敗しました。$root で手動確認してください。"; return 1; }
    else
        git -C "$root" fetch --quiet origin "$BASE_BRANCH:$BASE_BRANCH" \
            || { warn "ローカル $BASE_BRANCH の更新に失敗しました。$root で手動確認してください。"; return 1; }
    fi
    info "ローカル $BASE_BRANCH を origin に追従しました: $(git -C "$root" rev-parse --short "$BASE_BRANCH")"
}

cmd_check() {
    local root
    root=$(git rev-parse --show-toplevel)
    python3 "$GATE" --repo-root "$root" --base-ref "$BASE_BRANCH" "$@"
}

cmd_pr() {
    local title="" body="" draft=""
    while [ $# -gt 0 ]; do
        case "$1" in
            -t|--title) [ $# -ge 2 ] || die "$1 に値がありません"; title=$2; shift 2 ;;
            -b|--body)  [ $# -ge 2 ] || die "$1 に値がありません"; body=$2; shift 2 ;;
            --draft)    draft=1; shift ;;
            *)          die "不明なオプション: $1" ;;
        esac
    done

    require_gh

    local branch
    branch=$(current_branch)
    [ -n "$branch" ] || die "detached HEAD では PR を作れません。"
    [ "$branch" != "$BASE_BRANCH" ] || die "$BASE_BRANCH 上では PR を作れません。'flow.sh start <短い内容>' で作業ブランチを作ってください。"

    # 中断するのは「追跡済みファイルの未コミット変更」だけ（未追跡ファイルは PR に影響しない）。
    # 未追跡ファイルでも中断させると、生成物が置かれるたびに誤検知が起き、回避が習慣化してしまう。
    if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
        die "追跡済みファイルに未コミットの変更があります。コミットしてから実行してください。"
    fi

    # 未追跡ファイルは中断させないが黙殺もしない（コミットし忘れの新規ファイルが PR から漏れる事故対策）
    local untracked untracked_count
    untracked=$(git ls-files --others --exclude-standard)
    if [ -n "$untracked" ]; then
        untracked_count=$(printf '%s\n' "$untracked" | wc -l | tr -d ' ')
        warn "未追跡ファイルが ${untracked_count} 件あります（PR には含まれません）:"
        printf '%s\n' "$untracked" | sed 's/^/  - /' >&2
        warn "この PR に含めるべきものがあれば、中断して git add してください。"
    fi

    git fetch --quiet origin "$BASE_BRANCH" || warn "origin/$BASE_BRANCH の fetch に失敗しました（ゲートはローカル情報で実行）"
    if [ -z "$(git rev-list --max-count=1 "origin/$BASE_BRANCH..HEAD" 2>/dev/null)" ]; then
        die "origin/$BASE_BRANCH に対して新しいコミットがありません。"
    fi

    info "マージ前ゲートを実行します"
    cmd_check || die "ゲート不合格のため中断しました。"

    [ -n "$title" ] || title=$(git log -1 --pretty=%s)

    info "ブランチを push: $branch"
    git push --quiet --set-upstream origin "$branch" || die "push に失敗しました。"

    local number url
    number=$(open_pr_for_branch "$branch")
    if [ -n "$number" ]; then
        info "既存の PR #$number を再利用します（push 済みの内容で更新されます）"
    else
        info "PR を作成: $branch -> $BASE_BRANCH"
        local -a args=(--base "$BASE_BRANCH" --head "$branch" --title "$title")
        if [ -n "$body" ]; then
            args+=(--body "$body")
        elif [ -f "$(git rev-parse --show-toplevel)/.github/pull_request_template.md" ]; then
            args+=(--body-file "$(git rev-parse --show-toplevel)/.github/pull_request_template.md")
        else
            args+=(--body "")
        fi
        [ -n "$draft" ] && args+=(--draft)
        gh pr create "${args[@]}" >/dev/null || die "PR 作成に失敗しました。"
        number=$(open_pr_for_branch "$branch")
        [ -n "$number" ] || die "PR を作成しましたが番号を取得できませんでした。GitHub 上で確認してください（重複作成に注意）。"
    fi

    url=$(gh pr view "$number" --json url --jq .url)
    echo
    info "PR #$number: $url"
    echo "  レビュー後、マージはユーザーの指示で: $SCRIPT_DIR/flow.sh merge $number --approved"
}

cmd_merge() {
    local number="" approved=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --approved) approved=1; shift ;;
            -*)         die "不明なオプション: $1" ;;
            *)          number=$1; shift ;;
        esac
    done

    # チーム開発のため、マージ対象は PR 番号で明示させる（「現在のブランチの PR」を推測しない）
    [[ "$number" =~ ^[0-9]+$ ]] || die "使い方: flow.sh merge <PR番号> --approved  （PR 番号は必須）"

    require_gh

    # 区切りはタブではなく US(0x1f) を使う。タブは IFS 空白扱いで連続が畳まれ、
    # reviewDecision が空のとき後続フィールドがずれる（テストで検出、2026-09-23）。
    local info_line state draft mergeable review title
    info_line=$(gh pr view "$number" --json state,isDraft,mergeable,reviewDecision,title \
        --jq '[.state, (.isDraft|tostring), .mergeable, (.reviewDecision // ""), .title] | join("\u001f")') \
        || die "PR #$number の情報を取得できませんでした。"
    IFS=$'\x1f' read -r state draft mergeable review title <<<"$info_line" || true

    [ "$state" = "OPEN" ] || die "PR #$number は open ではありません（state=${state}）。"
    [ "$draft" = "false" ] || die "PR #$number は draft です。'gh pr ready $number' 後に実行してください。"
    [ "$mergeable" != "CONFLICTING" ] || die "PR #$number はコンフリクトしています。$BASE_BRANCH を取り込んで解消してください。"
    [ "$review" != "CHANGES_REQUESTED" ] || die "PR #$number は変更要求 (CHANGES_REQUESTED) が付いています。"
    [ "$review" != "REVIEW_REQUIRED" ] || warn "PR #$number は必須レビューが未完了です（ブランチ保護により GitHub 側で拒否される可能性あり）。"

    # 承認ポリシー: 作成者本人を含め誰か 1 人の承認（Approve または LGTM コメントレビュー）が必要
    local approvals
    approvals=$(approval_count "$number") || die "PR #${number} のレビュー情報を取得できませんでした。"
    [ "${approvals:-0}" -ge 1 ] \
        || die "PR #${number} に承認がありません。'flow.sh approve $number' で承認してください（作成者本人でも可）。"

    # CI が失敗していればマージしない（実行中・未設定は警告のみ）
    # 出力は変数に受けてから判定する（gh ... | grep -q だと pipefail 下で gh の非ゼロ終了が
    # パイプ全体の結果になり「CI 未設定」を「CI 失敗」と誤判定する。テストで検出、2026-09-23）
    local checks_rc=0 checks_out
    checks_out=$(gh pr checks "$number" 2>&1) || checks_rc=$?
    case "$checks_rc" in
        0) ;;
        8) warn "PR #$number の CI がまだ実行中です。" ;;
        *) if printf '%s' "$checks_out" | grep -q "no checks reported"; then
               warn "PR #$number に CI の結果がありません。"
           else
               die "PR #$number の CI が失敗しています（gh pr checks $number で確認）。"
           fi ;;
    esac

    if [ -z "$approved" ]; then
        if [ -t 0 ]; then
            # Ctrl-D (EOF) でも set -e で異常終了させず「いいえ」として扱う
            local answer=""
            read -r -p "PR #${number}「${title}」を $MERGE_METHOD マージします。よろしいですか? [y/N] " answer || answer=""
            case "$answer" in
                [yY]|[yY][eE][sS]) ;;
                *) info "中止しました。"; return 0 ;;
            esac
        else
            die "マージにはユーザーの明示的な承認が必要です。承認済みなら --approved を付けてください。"
        fi
    fi

    info "PR #$number を $MERGE_METHOD マージします: $title"
    log INFO "merge pr=$number method=$MERGE_METHOD approved=${approved:-interactive}"
    gh pr merge "$number" "--$MERGE_METHOD" || die "PR #$number のマージに失敗しました。"

    info "マージ完了。ローカルの $BASE_BRANCH を更新します。"
    cmd_sync || true
    echo "  作業ブランチの片付け: worktree なら 'git worktree remove <dir>'、ブランチは 'git branch -D <branch>'"
}

# PR を承認する。コメントは既定で "LGTM"（チーム決定、2026-09-23）。
# 承認ポリシー: 作成者本人を含め、誰か 1 人が承認すればマージしてよい（デモ環境向けの緩和、2026-09-23）。
# GitHub の仕様上、作成者は自分の PR を Approve できないため、その場合は同じ本文の
# コメントレビューを残す。merge はこれも「承認」として数える（has_approval 参照）。
cmd_approve() {
    local number="" message="LGTM"
    while [ $# -gt 0 ]; do
        case "$1" in
            -m|--message) [ $# -ge 2 ] || die "$1 に値がありません"; message=$2; shift 2 ;;
            -*)           die "不明なオプション: $1" ;;
            *)            number=$1; shift ;;
        esac
    done
    [[ "$number" =~ ^[0-9]+$ ]] || die "使い方: flow.sh approve <PR番号> [-m <コメント>]  （PR 番号は必須）"
    [ -n "$message" ] || die "コメントが空です。"

    require_gh

    local state
    state=$(gh pr view "$number" --json state --jq .state) || die "PR #${number} の情報を取得できませんでした。"
    [ "$state" = "OPEN" ] || die "PR #${number} は open ではありません（state=${state}）。"

    info "PR #${number} を承認します（コメント: ${message}）"
    local out
    if out=$(gh pr review "$number" --approve --body "$message" 2>&1); then
        info "PR #${number} を承認しました。"
        return 0
    fi
    if ! printf '%s' "$out" | grep -qi "own pull request"; then
        die "PR #${number} の承認に失敗しました: $out"
    fi

    # 自分の PR: GitHub の Approve は不可のため、コメントレビューで承認の意思を残す
    [[ "$message" =~ ^[[:space:]]*[Ll][Gg][Tt][Mm] ]] \
        || die "自分の PR の承認はコメントレビューで記録するため、コメントは LGTM で始めてください: $message"
    out=$(gh pr review "$number" --comment --body "$message" 2>&1) \
        || die "PR #${number} へのコメントレビューに失敗しました: $out"
    info "自分の PR のため、コメントレビュー「${message}」で承認を記録しました（merge で承認として扱われます）。"
}

# PR に承認があるか（Approve、または本文が LGTM で始まるコメントレビュー。作成者本人のものも可）
approval_count() {
    gh pr view "$1" --json reviews \
        --jq '[.reviews[] | select(.state == "APPROVED" or (.state == "COMMENTED" and (.body | test("^\\s*lgtm"; "i"))))] | length'
}

cmd_list() {
    require_git_repo
    git -C "$(main_root)" worktree list
}

# リモートブランチが BASE_BRANCH に取り込まれ済みか（祖先判定 or GitHub 上で merged な PR がある）。
# squash / rebase マージではブランチが祖先にならないため、PR 状態も見る。
is_merged_branch() {
    local root=$1 branch=$2
    git -C "$root" merge-base --is-ancestor "origin/$branch" "origin/$BASE_BRANCH" 2>/dev/null && return 0
    command -v gh >/dev/null 2>&1 || return 1
    [ -n "$(gh pr list --head "$branch" --state merged --json number --jq '.[0].number // empty' 2>/dev/null)" ]
}

cmd_prune() {
    local days=365 execute="" include_unmerged=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --days)             [ $# -ge 2 ] || die "--days に値がありません"; days=$2; shift 2 ;;
            --execute)          execute=1; shift ;;
            --include-unmerged) include_unmerged=1; shift ;;
            *)                  die "不明なオプション: $1" ;;
        esac
    done
    [[ "$days" =~ ^[0-9]+$ ]] || die "--days には数値を指定してください: $days"

    local root
    root=$(main_root)
    info "origin を fetch しています（削除済みリモートブランチの追跡も整理）..."
    git -C "$root" fetch --prune --quiet origin || die "origin の fetch に失敗しました。"

    local cutoff now
    now=$(date +%s)
    cutoff=$((now - days * 86400))

    local -a stale_merged=() stale_unmerged=()
    local ref branch ts age
    while read -r ref; do
        branch=${ref#origin/}
        [ "$branch" = "$BASE_BRANCH" ] && continue
        [ "$branch" = "HEAD" ] || [ "$branch" = "origin" ] && continue

        ts=$(git -C "$root" log -1 --format=%ct "$ref")
        [ "$ts" -gt "$cutoff" ] && continue
        age=$(((now - ts) / 86400))

        if is_merged_branch "$root" "$branch"; then
            stale_merged+=("$age|$branch")
        else
            stale_unmerged+=("$age|$branch")
        fi
    done < <(git -C "$root" branch -r --format='%(refname:short)' | grep '^origin/' | grep -v '/HEAD$')

    if [ ${#stale_merged[@]} -eq 0 ] && [ ${#stale_unmerged[@]} -eq 0 ]; then
        info "${days}日より古いリモートブランチはありません。"
        return 0
    fi

    # bash 3.2 (macOS) では set -u 下で空配列の "${a[@]}" 展開がエラーになるため長さで分岐する
    local -a targets=()
    local e
    if [ ${#stale_merged[@]} -gt 0 ]; then
        echo "${BASE_BRANCH} へマージ済み（削除対象）:"
        while read -r e; do
            printf '  %5d日  %s\n' "${e%%|*}" "${e#*|}"
            targets+=("${e#*|}")
        done < <(printf '%s\n' "${stale_merged[@]}" | sort -t'|' -k1 -rn)
    fi
    if [ ${#stale_unmerged[@]} -gt 0 ]; then
        echo
        echo "${BASE_BRANCH} へ未マージ（作業が失われる可能性あり）:"
        while read -r e; do
            printf '  %5d日  %s\n' "${e%%|*}" "${e#*|}"
            [ -n "$include_unmerged" ] && targets+=("${e#*|}")
        done < <(printf '%s\n' "${stale_unmerged[@]}" | sort -t'|' -k1 -rn)
        [ -z "$include_unmerged" ] && echo "  -> 既定では削除しません（--include-unmerged で対象に含める）"
    fi

    echo
    if [ -z "$execute" ]; then
        warn "ドライラン（既定）。実際に削除するには --execute を付けてください。"
        echo "  tools/bin/flow.sh prune --days $days --execute"
        return 0
    fi
    [ ${#targets[@]} -gt 0 ] || { info "削除対象はありません。"; return 0; }

    # リモートブランチの削除は取り消せないため、実行前に必ず確認を取る
    echo "上記 ${#targets[@]} 本を origin から削除します。この操作は取り消せません。"
    local answer=""
    read -r -p "続行しますか? [y/N] " answer || answer=""
    case "$answer" in
        [yY]|[yY][eE][sS]) ;;
        *) info "中止しました。"; return 0 ;;
    esac

    local b
    for b in "${targets[@]}"; do
        info "削除: origin/$b"
        git -C "$root" push origin --delete "$b" || warn "origin/$b の削除に失敗しました。"
    done
    git -C "$root" fetch --prune --quiet origin || true
    info "完了しました。"
}

cmd_protect() {
    # GitHub 側の必須承認数の既定は 0（チーム決定、2026-09-23。2 → 1 → 0 と緩和）。
    # GitHub は作成者本人の Approve を認めないため、「本人を含め誰かが承認すればよい」ポリシーは
    # GitHub では表現できない。承認の確認は flow.sh merge 側（approval_count）で行う。
    local execute="" reviews=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --execute) execute=1; shift ;;
            --reviews) [ $# -ge 2 ] || die "--reviews に値がありません"; reviews=$2; shift 2 ;;
            *)         die "不明なオプション: $1" ;;
        esac
    done
    [[ "$reviews" =~ ^[0-6]$ ]] || die "--reviews は 0〜6: $reviews"

    # main への直接 push・force push・削除を禁止し、PR + CI(gate) 合格 + 承認 N 件を必須にする。
    # 保護は必要以上に強くしない方針（2026-09-23）:
    #   enforce_admins=false        緊急時に管理者が回避できる余地を残す（ハッカソンの時間制約を考慮）
    #   dismiss_stale_reviews=false 承認後の追加 push で承認をリセットしない（軽微な修正のたびに再承認を求めない）
    #   strict=false                PR ブランチが最新 main を取り込み済みであることを求めない
    local payload
    payload=$(cat <<EOF
{
  "required_status_checks": {"strict": false, "contexts": ["gate"]},
  "enforce_admins": false,
  "required_pull_request_reviews": {"required_approving_review_count": $reviews, "dismiss_stale_reviews": false},
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": false
}
EOF
)
    local repo
    require_gh
    repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
    echo "対象: $repo ブランチ $BASE_BRANCH"
    echo "$payload"
    if [ -z "$execute" ]; then
        warn "ドライラン（既定）。GitHub に適用するには --execute を付けてください（リポジトリ管理者権限が必要）。"
        return 0
    fi
    printf '%s' "$payload" | gh api -X PUT "repos/$repo/branches/$BASE_BRANCH/protection" --input - >/dev/null \
        || die "ブランチ保護の設定に失敗しました（管理者権限・プランを確認）。"
    info "ブランチ保護を設定しました: $repo:$BASE_BRANCH"
}

# GitHub のリモート URL から owner/repo を取り出す（https / ssh 両対応）
repo_slug_from_remote() {
    local url
    url=$(git config --get remote.origin.url 2>/dev/null) || return 1
    url=${url%.git}
    case "$url" in
        https://github.com/*)   printf '%s\n' "${url#https://github.com/}" ;;
        git@github.com:*)       printf '%s\n' "${url#git@github.com:}" ;;
        ssh://git@github.com/*) printf '%s\n' "${url#ssh://git@github.com/}" ;;
        *) return 1 ;;
    esac
}

# テンプレートから作成した直後のリポジトリを、そのプロジェクト用に初期化する（2026-09-23）。
# 作業ブランチ work/<yyyymmdd>-init を作り、プロジェクト固有の値を置き換えてコミットするところまで行う。
# push と PR 作成は利用者が flow.sh pr で行う（その PR で CI が初めて走り、ブランチ保護を設定できる）。
cmd_init() {
    local slug="" name=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --repo) [ $# -ge 2 ] || die "--repo に値がありません"; slug=$2; shift 2 ;;
            --name) [ $# -ge 2 ] || die "--name に値がありません"; name=$2; shift 2 ;;
            *)      die "不明なオプション: $1" ;;
        esac
    done

    if [ -z "$slug" ]; then
        slug=$(repo_slug_from_remote) \
            || die "origin から owner/repo を判定できません。--repo <owner>/<repo> を指定してください。"
    fi
    [[ "$slug" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || die "--repo は <owner>/<repo> 形式で指定してください: $slug"
    [ "$slug" != "$TEMPLATE_REPO" ] \
        || die "テンプレートリポジトリ自身では実行できません（テンプレートから作成したリポジトリで実行してください）。"
    [ -n "$name" ] || name=${slug#*/}
    [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || die "--name は英数字と . _ - のみ: $name"

    local root
    root=$(git rev-parse --show-toplevel)
    grep -q "^name = \"${TEMPLATE_NAME}\"" "$root/pyproject.toml" 2>/dev/null \
        || die "初期化済みのようです（pyproject.toml の name が ${TEMPLATE_NAME} ではありません）。"

    info "テンプレートから初期化します: repo=$slug name=$name"
    cmd_start init

    # 置き換えは python3 で文字列として行う（sed の区切り文字・エスケープ問題を避ける）。
    # 対象ファイルと置換内容は明示的に限定する（キット共通部品は触らない）。
    python3 - "$root" "$TEMPLATE_REPO" "$slug" "$TEMPLATE_NAME" "$name" <<'PY' \
        || die "プロジェクト固有値の置き換えに失敗しました。"
import pathlib, sys
root, old_repo, new_repo, old_name, new_name = sys.argv[1:]
root = pathlib.Path(root)
targets = [
    ("README.md", [(old_repo, new_repo), (f"# {old_name}\n", f"# {new_name}\n"), (f"cd {old_name}", f"cd {new_name}")]),
    ("CLAUDE.md", [(f"# CLAUDE.md — {old_name}\n", f"# CLAUDE.md — {new_name}\n")]),
    ("pyproject.toml", [(f'name = "{old_name}"', f'name = "{new_name.lower()}"')]),
]
for rel, pairs in targets:
    path = root / rel
    if not path.is_file():
        print(f"  - {rel} が無いためスキップ")
        continue
    text = path.read_text(encoding="utf-8")
    for old, new in pairs:
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
    print(f"  ✓ {rel}")
PY

    if [ -f "$root/uv.lock" ]; then
        if command -v uv >/dev/null 2>&1; then
            (cd "$root" && uv lock --quiet) || die "uv lock に失敗しました。"
            echo "  ✓ uv.lock"
        else
            warn "uv が無いため uv.lock を更新していません。uv を入れて 'uv lock' を実行してください。"
        fi
    fi

    git -C "$root" add -A
    git -C "$root" commit --quiet -m "テンプレートから初期化: $name" \
        || die "コミットに失敗しました（ゲートの出力を確認してください）。"
    info "初期化をコミットしました。続けて:"
    cat <<NEXT
  1. tools/bin/flow.sh pr -t "テンプレートから初期化"      # 初回 PR（ここで CI が初めて走る）
  2. CI 合格を確認後: tools/bin/flow.sh protect --execute  # main のブランチ保護
  3. tools/bin/flow.sh approve <PR番号> → tools/bin/flow.sh merge <PR番号> --approved
  4. GitHub の Settings → Collaborators でメンバーを招待
NEXT
}

cmd_status() {
    require_git_repo
    local root here branch
    root=$(main_root)
    here=$(git rev-parse --show-toplevel)
    branch=$(current_branch)

    echo "メインツリー : $root"
    echo "現在の場所   : $here$([ "$here" = "$root" ] && echo "  (メインツリー)" || echo "  (worktree)")"
    echo "ブランチ     : ${branch:-(detached)}"
    echo "hooks        : core.hooksPath=$(git config --local --get core.hooksPath || echo '(未設定)')"
    if command -v gh >/dev/null 2>&1; then
        gh auth status >/dev/null 2>&1 && echo "gh 認証      : 済" || echo "gh 認証      : 未（gh auth login）"
    else
        echo "gh 認証      : gh 未インストール"
    fi
    echo "未コミット   : $(git status --porcelain | wc -l | tr -d ' ') ファイル"
    [ -n "$LOG_FILE" ] && echo "ログ         : $LOG_FILE"
    return 0
}

cmd_help() {
    cat <<'EOF'
flow.sh — git ワークフロー CLI（GitHub 版）

  setup                初回セットアップ確認（hooks 有効化・必須ツール・gh 認証）。clone 直後に実行
  init [--repo <owner>/<repo>] [--name <名前>]
                       テンプレートから作成したリポジトリの初期化（プロジェクト名等の置き換え）。
                       作業ブランチ work/<yyyymmdd>-init を作ってコミットまで行う（作成者が 1 回だけ実行）
  start <短い内容> [--worktree]
                       origin/main から work/<yyyymmdd>-<短い内容> ブランチを作成
                       --worktree なら .worktrees/<短い内容> に worktree として作成
  check [--only syntax,secret,envfile,largefile]
                       マージ前ゲート
  pr [-t <title>] [-b <body>] [--draft]
                       ゲート -> push -> GitHub に PR 作成（同ブランチの open PR があれば再利用）
  merge <PR番号> --approved
                       PR をマージし、ローカル main を更新する。
                       ★チーム開発のため、ユーザーの明示的な指示があるときだけ実行する。
                       PR 番号必須。--approved が無い場合は対話確認（非対話環境では拒否）。
                       承認（approve）が 1 件も無い PR、draft・コンフリクト・変更要求・CI 失敗の PR は拒否する。
  approve <PR番号> [-m <コメント>]
                       PR を承認する（作成者本人も可）。コメント既定: LGTM
                       自分の PR は GitHub 仕様上 Approve できないため LGTM コメントレビューで記録
  sync                 ローカル main を origin/main に追従させる
  list                 worktree の一覧
  status               現在地・ブランチ・hooks・gh 認証の表示
  prune [--days N] [--execute] [--include-unmerged]
                       N 日（既定 365）より古いリモートブランチを棚卸し。既定はドライラン。
                       月次棚卸しは --days 30 を明示。未マージは既定で対象外。
  protect [--reviews N(既定 0)] [--execute]
                       main のブランチ保護（PR 必須・CI gate 必須・承認 N 件・force push 禁止）。
                       既定はドライラン。リポジトリ管理者のみ。

環境変数:
  FLOW_BASE_BRANCH   ベースブランチ（既定: main）
  FLOW_MERGE_METHOD  squash | merge | rebase（既定: squash）
  FLOW_MAX_FILE_MB   ゲートの巨大ファイル閾値（既定: 5）
EOF
}

# ------------------------------------------------------------------ ディスパッチ

main() {
    local cmd=${1:-help}
    shift || true
    case "$cmd" in
        help|-h|--help) cmd_help; return 0 ;;
    esac
    require_git_repo
    init_log
    log INFO "invoke cmd=$cmd args=$* cwd=$PWD branch=$(current_branch)"
    ensure_hooks_installed
    case "$cmd" in
        setup)   cmd_setup   "$@" ;;
        init)    cmd_init    "$@" ;;
        start)   cmd_start   "$@" ;;
        check)   cmd_check   "$@" ;;
        pr)      cmd_pr      "$@" ;;
        merge)   cmd_merge   "$@" ;;
        approve) cmd_approve "$@" ;;
        sync)    cmd_sync    "$@" ;;
        list)    cmd_list    "$@" ;;
        prune)   cmd_prune   "$@" ;;
        protect) cmd_protect "$@" ;;
        status)  cmd_status  "$@" ;;
        *)       die "不明なサブコマンド: ${cmd}（flow.sh help を参照）" ;;
    esac
}

main "$@"
