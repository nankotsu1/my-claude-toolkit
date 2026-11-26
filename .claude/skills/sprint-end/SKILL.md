---
name: sprint-end
description: スプリントの終わり（と統括の目標を閉じるとき）に、全部の TASK.md を木ごと写しの置き場へ写し、レトロをし、止まっている持ち手の済んだ行を片付ける。開発推進部が統括から任されて使う。「スプリントを締めて」「写しと片付け」「スプリントの終わりの手順」と言われたときに使う。Use at the end of a sprint to snapshot and clean up TASK.md files.
---

# スプリントの終わり（sprint-end）

区切りは根の持ち手（統括）が受け持ち、手を動かすのは開発推進部（`teamkit/docs/roles.md`）。決まりは `teamkit/docs/taskmd.md` の4章。スクリプトは `sprint.py`（標準ライブラリだけ）で、リポジトリ直下か worktree の中から流す。写しの置き場は値の表（`.claude/teamkit.md`）の「写しの置き場」から読む（なければ `.worktrees/snapshots/`）。

## 1. 木を確かめる

```bash
python3 .claude/skills/sprint-end/sprint.py files
```

- 根の TASK.md と、束（`→ <フォルダ>`）をたどった先、値の表の「持ち手の置き場所」の TASK.md が出る
- 出てこない TASK.md があれば、束の書き方を持ち主に確かめる（写しにも片付けにも入らない）

## 2. 写す

```bash
python3 .claude/skills/sprint-end/sprint.py snapshot          # 写した先のフォルダを1行目に出す
```

- 写しの置き場の下に `YYYY-MM-DD`（同じ日の2回目は `-2`）を作り、リポジトリ直下からの相対の位置のまま全文を写す（申し送りの節も）。前の写しは上書きしない
- 写したフォルダを `teamkit/tasktree.py` に渡すと、そのスプリントの全体像と図が出る（`teamkit/docs/views.md` の1章）
- 目標を閉じるときも同じ。目標の Issue には、目標と閉じた理由だけを書く（写しは Issue に貼らない）

## 3. レトロ

- 写しをもとに、ひな形 `teamkit/templates/sprint_report.md` でレポートを書き、値の表の「報告の写し先」に置く
- 未完の行は番号を変えずに残す。次のスプリントの計画で並びと着手予定日を引き直す案（要らなければ消す案）を、レポートの「持ち越し」に書いて統括へ
- 仕組みの課題は統括を通してハーネス部へ

## 4. 片付ける

```bash
python3 .claude/skills/sprint-end/sprint.py clean --snapshot <写した先>                       # 消す行を見る
python3 .claude/skills/sprint-end/sprint.py clean --snapshot <写した先> --write <TASK.md> ...  # 消す
```

- 消すのは `## タスク` の済んだ行だけ（`[x]` の行と、枝が全部 `[x]` の束。細目の行も）。申し送りなど、ほかの節には触れない
- **持ち主が止まっている TASK.md だけ**を `--write` に挙げる。動いている持ち手は、止まってからもう一度。統括の TASK.md は、始める前と済んだあとに統括へひと言
- 写したあとに中身が変わった TASK.md は書き換えない（エラーになる）。写し直してからやり直す
- ほかの持ち手の TASK.md の行を消すのは、人の許可を取ってから（AskUserQuestion で、開発推進部が直接聞く）
- 最後に「どの束からも指されなくなるフォルダ」が出たら、部下の置き場所かを確かめ、人の許可で片付ける（worktree なら `git worktree remove`、ブランチも）。スクリプトは消さない

## 5. 知らせる

統括へ【完了】: 写した先、レポートの置き場、片付けた TASK.md と行の数、片付けられなかった持ち手（動いていた・写したあとに変わった）、持ち越しの案。

## してはいけないこと

- 申し送りの節を書き換える、動いている持ち手の TASK.md を書き換える
- 写す前に片付ける
- 写しを git に入れる（写しの置き場は git の外）
