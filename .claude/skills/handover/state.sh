#!/usr/bin/env bash
# 申し送り（SKILL.md）に書く「いまの状態」を集めて表示する。読むだけで、何も変えない。
#
#   bash .claude/skills/handover/state.sh            # 今の作業フォルダ
#   bash .claude/skills/handover/state.sh --all      # 統括: 全部の worktree と開いている PR も
#   bash .claude/skills/handover/state.sh <フォルダ> [--all]
#
# git fetch はしない（origin/main は最後に取り込んだ時点のもの。表示に時刻を出す）。
# 模擬サーバーのコマンド・本番（数えない）・模擬環境のポートの範囲は、導入したリポジトリの値の表
# （.claude/teamkit.md。teamkit/values.py で読む）から。値の表になければ、その所は出さない。
# PR の番号は「PR 35」の形で出す（申し送りでは、行の終わりの「#35」が Issue の番号と読まれることがあるため）。

all=0
dir=.
for a in "$@"; do
  case "$a" in
    --all) all=1 ;;
    *) dir="$a" ;;
  esac
done
# 相対パスで呼ばれても読めるように、cd の前に求める
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
cd "$dir" || exit 1
here=$(pwd -P)

# 値の表を読む（部品は、いまのリポジトリの teamkit/ か、このスクリプトのあるリポジトリのもの）
# 値の表は、いまの作業ツリー → もとのリポジトリの直下 → このスクリプトのあるリポジトリ の順に、あるものを使う
# （値の表より前に切った worktree を指しても読めるように）。
script_top=$(cd "$script_dir/../../.." && pwd -P)
top=$(git rev-parse --show-toplevel 2>/dev/null || echo "$here")
common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
main_top=${common:+$(dirname "$common")}
values_root=""
for d in "$top" "$main_top" "$script_top"; do
  if [ -n "$d" ] && [ -f "$d/.claude/teamkit.md" ]; then values_root=$d; break; fi
done
values_py=""
for d in "$values_root" "$top" "$script_top"; do
  if [ -n "$d" ] && [ -f "$d/teamkit/values.py" ]; then values_py="$d/teamkit/values.py"; break; fi
done
value() { [ -n "$values_py" ] && [ -n "$values_root" ] && python3 "$values_py" "$1" --root "$values_root" 2>/dev/null; }
server_cmds=$(value 模擬サーバーのコマンド)
prod_paths=$(value '本番（触らない）' | grep -E '^(~|/)' | sed "s#^~#$HOME#")
port_range=$(value 模擬環境のポートの範囲 | head -1)

# TASK.md の見出しと、「## 申し送り」の更新の行（コードブロックの中の見本は数えない。最後の節を使う）
task_title() { grep -m1 '^#' "$1/TASK.md" 2>/dev/null; }
handover_updated() {
  [ -f "$1/TASK.md" ] || return 0
  awk '
    /^```/ { fence = !fence; next }
    fence { next }
    /^## 申し送り[[:space:]]*$/ { inside = 1; upd = ""; next }
    /^## / { inside = 0 }
    inside && upd == "" && /^更新:/ { upd = $0 }
    END { print upd }
  ' "$1/TASK.md"
}

# origin/main を最後に取り込んだ時刻（worktree ごとの FETCH_HEAD と、共通のものの新しいほう）
fetched_at() {
  local f t best=""
  for f in "$(git rev-parse --git-dir)/FETCH_HEAD" "$(git rev-parse --git-common-dir)/FETCH_HEAD"; do
    [ -f "$f" ] || continue
    t=$(stat -c '%Y' "$f")
    if [ -z "$best" ] || [ "$t" -gt "$best" ]; then best=$t; fi
  done
  [ -n "$best" ] && date -d "@$best" '+%Y-%m-%d %H:%M'
}

# 模擬サーバー（値の表の「模擬サーバーのコマンド」を動かしているプロセス）。本番の置き場所（値の表の
# 「本番（触らない）」のうち ~ か / で始まるもの）から動いているものは除く。
# 自分の作業フォルダのものは、コマンドのパスか、プロセスの作業ディレクトリで見分ける。
# リポジトリ直下から見たときは、.worktrees/ の下（ほかのライン）のものを除く。
# そのプロセスが、名前に当たるファイルを動かしているか。1つめの引数（実行ファイル）が名前に当たるか、
# 1つめが python で、オプション（-u・-X dev など）を飛ばした最初の引数が名前に当たるもの。
# エディタで開いているだけのもの（vim x.py）や、sh -c の文の中に名前が出るだけのものは数えない。
runs_server() {
  local pid=$1 name=$2 a first="" skip_next=0
  local -a argv
  mapfile -d '' -t argv < "/proc/$pid/cmdline" 2>/dev/null || return 1
  [ "${#argv[@]}" -gt 0 ] || return 1
  case "${argv[0]##*/}" in *"$name"*) return 0 ;; python*) ;; *) return 1 ;; esac
  for a in "${argv[@]:1}"; do
    if [ "$skip_next" = 1 ]; then skip_next=0; continue; fi
    case "$a" in
      -X|-W|-Q) skip_next=1 ;;
      -c|-m) return 1 ;;
      -*) ;;
      *) first=$a; break ;;
    esac
  done
  case "$first" in *"$name"*) return 0 ;; esac
  return 1
}

server_procs() {
  local mine_only=$1 pid cmd pat cwd hit name p skip
  [ -n "$server_cmds" ] || return 0
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    pat=$(printf '%s' "$name" | sed 's/[][\.*^$+?(){}|]/\\&/g')     # 名前は語として探す（正規表現にしない）
    for pid in $(pgrep -f -- "$pat" 2>/dev/null); do
      [ "$pid" = "$$" ] && continue
      cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null) || continue
      [ -n "$cmd" ] || continue
      runs_server "$pid" "$name" || continue
      skip=0
      while IFS= read -r p; do
        [ -n "$p" ] && case "$cmd" in *"$p"*) skip=1 ;; esac
      done <<< "$prod_paths"
      [ "$skip" = 1 ] && continue
      if [ "$mine_only" = 1 ]; then
        cwd=$(readlink -f "/proc/$pid/cwd" 2>/dev/null)
        hit=0
        case "$cmd" in *"$here/"*) hit=1 ;; esac
        case "$cwd/" in "$here/"*) hit=1 ;; esac
        case "$cmd $cwd/" in *"$here/.worktrees/"*) hit=0 ;; esac
        [ "$hit" = 1 ] || continue
      fi
      echo "  $pid $cmd"
    done
  done <<< "$server_cmds"
}

echo "時刻: $(date '+%Y-%m-%d %H:%M')"
echo "作業フォルダ: $here"
if [ -f TASK.md ]; then
  echo "TASK.md: $(task_title .)"
  upd=$(handover_updated .)
  echo "申し送り: ${upd:-（まだない）}"
else
  echo "TASK.md: （ない）"
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "git: （git の外）"
  exit 0
fi

br=$(git branch --show-current)
echo
echo "ブランチ: ${br:-（ブランチなし）}  最新: $(git log -1 --format='%h %s（%cr）')"
if git rev-parse -q --verify origin/main >/dev/null; then
  f=$(fetched_at)
  echo "main との差: $(git rev-list --count origin/main..HEAD) 件先・$(git rev-list --count HEAD..origin/main) 件遅れ（origin/main は ${f:-不明} 時点）"
fi
if git rev-parse -q --verify '@{u}' >/dev/null 2>&1; then
  echo "push していないコミット: $(git rev-list --count '@{u}..HEAD') 件"
else
  echo "push: 上流のブランチなし（まだ push していない）"
fi

echo
echo "未コミット:"
st=$(git status --short)
if [ -n "$st" ]; then echo "$st" | head -40 | sed 's/^/  /'; else echo "  なし"; fi

if command -v gh >/dev/null 2>&1 && [ -n "$br" ]; then
  echo
  echo "PR（このブランチ）:"
  prs=$(gh pr list --head "$br" --state all --limit 5 \
        --json number,state,title --jq '.[] | "  PR \(.number) \(.state) \(.title)"' 2>/dev/null)
  if [ -n "$prs" ]; then
    echo "$prs"
    num=$(gh pr list --head "$br" --state open --limit 1 --json number --jq '.[0].number' 2>/dev/null)
    if [ -n "$num" ]; then
      echo "  CI（PR $num）:"
      gh pr checks "$num" 2>/dev/null | cut -f1,2 | sed 's/^/    /'
    fi
  else
    echo "  なし"
  fi
fi

echo
if [ -z "$server_cmds" ]; then
  echo "動かしているもの: （値の表に「模擬サーバーのコマンド」がないので数えない）"
elif [ "$all" = 1 ]; then
  echo "動かしているもの（全部の作業フォルダの模擬サーバー。本番は除く）:"
  procs=$(server_procs 0)
else
  echo "動かしているもの（この作業フォルダの模擬サーバー）:"
  procs=$(server_procs 1)
fi
if [ -n "$server_cmds" ]; then
  if [ -n "$procs" ]; then echo "$procs"; else echo "  なし"; fi
fi
lo=$(echo "$port_range" | grep -oE '[0-9]+' | sed -n 1p)
hi=$(echo "$port_range" | grep -oE '[0-9]+' | sed -n 2p)
if [ -n "$lo" ] && [ -n "$hi" ]; then
  ports=$(ss -ltn 2>/dev/null | awk -v lo="$lo" -v hi="$hi" '{n = $4; sub(/.*:/, "", n); if (n + 0 >= lo && n + 0 <= hi) print n}' | sort -un | tr '\n' ' ')
  [ -n "$ports" ] && echo "  聞いているテスト用のポート（この PC 全体。ほかの作業フォルダの分も入る）: $ports"
fi

if [ "$all" = 1 ]; then
  echo
  echo "worktree:"
  git worktree list --porcelain | { cat; echo; } | {
    path="" branch=""
    while IFS= read -r line; do
      case "$line" in
        "worktree "*) path=${line#worktree } ;;
        "branch "*) branch=${line#branch refs/heads/} ;;
        "detached") branch="（ブランチなし）" ;;
        "")
          [ -n "$path" ] || continue
          echo "  $path [$branch]"
          t=$(task_title "$path"); [ -n "$t" ] && echo "      $t"
          u=$(handover_updated "$path"); [ -n "$u" ] && echo "      申し送り $u"
          c=$(git -C "$path" status --short 2>/dev/null | wc -l)
          [ "$c" -gt 0 ] && echo "      未コミット $c 件"
          path="" branch="" ;;
      esac
    done
  }
  if command -v gh >/dev/null 2>&1; then
    echo
    echo "開いている PR:"
    out=$(gh pr list --state open --json number,title,headRefName \
          --jq '.[] | "  PR \(.number) \(.headRefName) \(.title)"' 2>/dev/null) || out="  （gh で取れません）"
    echo "${out:-  なし}"
  fi
fi
