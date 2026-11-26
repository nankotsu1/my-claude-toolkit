# teamkit

エージェント（Claude Code のセッション）のチームで開発するための道具と決まり。1つのリポジトリの仕事を、統括・部・ライン・部下のセッションに分けて受け持ち、各セッションの TASK.md（受け持つ仕事のチェックボックスの一覧）から全体像と計画を出す。

- **全体像の部品**: 各セッションの TASK.md をたどって、仕事のツリー・計画（空き・始められる・人待ち・待ち）・持ち手ごとの帯の図を作る。標準ライブラリだけの1ファイル
- **進め方の共通部分**: TASK.md の型、体制の形、ラインの決まり、実機確認の基準、ひな形
- **スキル5つ**: 全体像を答える・計画を立てる・申し送り・ラインを立てる・スプリントの終わり

語（統括、部、ライン、部下、持ち手、束、前提、作業単位、台帳 など）の意味は `docs/roles.md` の「用語」にある。

## 中身

| ファイル | 何か |
| :--- | :--- |
| `tasktree.py` | 全体像の部品。`python3 teamkit/tasktree.py TASK.md --text`（全体像）・`--plan`（計画）・`--html`（図）・`--list`（絞った一覧）。読むだけで、TASK.md を書き換えない |
| `values.py` | 値の表 `.claude/teamkit.md` を読む部品。スキルのスクリプトが使う。`python3 teamkit/values.py` で全部の値を出す |
| `docs/concept.md` | 設計の考え方（なぜツリーと composite か、状態を1か所に書く理由、トレードオフ）。ほかの文書の芯 |
| `docs/taskmd.md` | TASK.md の型の要求（行・番号・前提・日付・束、名前と番号の決まり）。型の正 |
| `docs/views.md` | 全体像の見え方（部品が TASK.md から出すもの、状態、空き、文字の全体像と計画、図、絞り込み）。見え方の正 |
| `docs/roles.md` | 体制の形（部とライン、人とのやりとり、標準の流れ、持ち場の分離）と用語 |
| `docs/line_rules.md` | ラインの決まりの共通部分（ラインの一生、進め方、実機確認の流れ） |
| `docs/verify.md` | 実機確認が要るかの基準と、手順の書き方の型 |
| `docs/install.md` | 導入の手順（入れるもの、値の表、台帳の形） |
| `templates/` | ひな形と書き方の手引き（`README.md`）。`TASK.template.md`（TASK.md）、`teamkit.template.md`（値の表）、`report.md`（【完了】と報告の写し）、`sprint_report.md`（節目のレポート） |
| `tests/` | 部品とスキルのテスト（`python3 -m unittest discover teamkit/tests`）。スキルのテストは `.claude/skills/` のスクリプトとスキルの文を読む |

## スキル

teamkit のスキルは次の5つ。Claude Code が読む `.claude/skills/` に置く（`teamkit/` の中には入れない。導入の手順は `docs/install.md`）。`.claude/skills/` にあるほかのスキルは、teamkit のものではない。

| スキル | 何をするか |
| :--- | :--- |
| `overview` | 「全体像を出して」「計画を出して」に、部品の書き出しで答え、空いた持ち手に振る案を出す（読むだけ） |
| `planning` | 「計画を立てて」で、仕事を振れる単位と前提の案を作り、人に確かめてから TASK.md に書く |
| `handover` | 区切りごとに TASK.md の末尾の申し送りを書き、「再開して」で申し送りから再開する |
| `line-start` | 統括が、台帳の作業計画とひな形から、新しいラインの TASK.md の下書きと立ち上げの指示文を作る |
| `sprint-end` | スプリントの終わりと目標を閉じるときに、TASK.md を木ごと写しの置き場へ写し、レトロをし、済んだ行を片付ける（開発推進部が使う） |

## 読む順番

1. `docs/concept.md`（設計の考え方）
2. `docs/roles.md`（誰が何をするか、用語）
3. `docs/taskmd.md`（TASK.md の書き方）と `templates/README.md`（ひな形の使い方）
4. ラインを動かすなら `docs/line_rules.md` と `docs/verify.md`
5. 導入するなら `docs/install.md`

## 導入したリポジトリに書くもの

`teamkit/` には、特定のリポジトリの名前や値を書かない。次のものは、導入したリポジトリの値の表 `.claude/teamkit.md`（ひな形は `templates/teamkit.template.md`）と、そこから指す決まりの文書に書く（食い違うときはそちらに従う）:

- 持ち手の置き場所、一時の worktree、写しの置き場、台帳の場所、報告の写し先
- 模擬環境のポート、テストの流し方
- 本番の禁止
- 実機確認の基準（入れるコマンドと戻すコマンド）、レビューの観点
