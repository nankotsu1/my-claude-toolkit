# my-claude-toolkit

Claude Code での開発を、もう少し楽に、快適にするための個人的な道具箱。

> **English summary**: A personal toolbox for making development with [Claude Code](https://claude.com/claude-code) a little easier and more comfortable.
> Each tool fixes a small, everyday pain point found while actually using Claude Code, and grows through daily use.
> The first tool, **teamkit**, runs several Claude Code sessions as a team and shows the whole picture from each session's `TASK.md` (Python standard library only, plus Claude Code skills).
> The documents are written in Japanese.

## 対象

Claude Code での開発で出てくる、細かな困りごとを解決したいとき。

例えば、セッションが増えると全体が見えなくなる、`/clear` のたびに状況を説明し直す、決まりごとを毎回伝える、など。

ここには、そうした困りごとを個人のレベルで少しずつつぶすために作った道具を置いていく。

## ツール

| ツール | つぶす困りごと | 説明 |
| :--- | :--- | :--- |
| teamkit | セッションを増やすと、誰が何をしていて何を待っているかが見えなくなる。`/clear` のあと、どこから再開するかが分からなくなる | [teamkit/README.md](teamkit/README.md) |

ツールは今後も適宜追加予定。

## すぐ試す

teamkit を、自分のリポジトリに入れる例（`<導入先>` は自分のリポジトリの直下）:

```bash
git clone https://github.com/nankotsu1/my-claude-toolkit.git
cp -r my-claude-toolkit/teamkit <導入先>/
mkdir -p <導入先>/.claude/skills
cp -r my-claude-toolkit/.claude/skills/{overview,planning,handover,line-start,sprint-end} <導入先>/.claude/skills/
```

値の表や `TASK.md` の用意など、続きの手順は [teamkit/docs/install.md](teamkit/docs/install.md)。

## 技術スタック

- Python 3.9 以上（標準ライブラリだけ。pip で入れるものはない）
- Claude Code
- git（`gh` はあれば一部で使う）

## 状態

個人で使いながら育てているので、中身や書き方は予告なく変わることがある。

## ライセンス

MIT（[LICENSE](LICENSE)）
