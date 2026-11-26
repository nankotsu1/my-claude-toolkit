# -*- coding: utf-8 -*-
"""値の表を読む部品（teamkit/values.py）のテスト。

    python3 -m unittest discover teamkit/tests
"""
import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("teamkit_values_test", ROOT / "teamkit/values.py")
V = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(V)

# スキルとスクリプトが名前で読む項目（handover・line-start・planning・overview）
KEYS = ("決まりの文書", "台帳", "報告の写し先", "持ち手の置き場所", "作業の場所", "一時の worktree", "写しの置き場", "テスト（関係する所）", "テスト（全部）", "本番（触らない）",
        "模擬サーバーのコマンド", "模擬環境のポートの範囲", "ラインのポートの始まり", "ラインのポートの枠の数",
        "ラインのポートの枠の幅", "コンテキストの目安の見え方", "実機確認の基準", "レビューの観点")

MD = """\
# 値

説明の文。| 項目 | 値 | のような表の外の文は読まない。

| 項目 | 値 | 使う所 |
| :--- | :--- | :--- |
| 台帳 | `docs/backlog.md` | line-start |
| 持ち手の置き場所 | `.worktrees/Req`、`.worktrees/Harness` | handover |
| 本番（触らない） | `8080`、`~/.app/`（本番のサーバー。`install` は人だけ） | |
| テスト（全部） | `make test 2>&1 \\| tail -5` | |
| コンテキストの目安の見え方 | 約15万トークン（ステータス行） | |
| 申し送りの注意 | — | |

| 空行のあとの項目 | `after-blank` | 表の途中の空行のあとも同じ表 |
| 使わない項目 | —（使わない。`docs/x.md` は古い） | |
| 括弧だけ | （なし） | |
| 空の項目 |  | |
| 台帳 | `second.md` | 2つめは読まない |

```markdown
| 見本 | `コードブロックの中は読まない` |
```

| 持ち手 | 置き場所 |
| :--- | :--- |
| Req-main | `.worktrees/Req` |
"""


class ValuesTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".md")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(MD)

    def tearDown(self):
        os.unlink(self.path)

    def test_load(self):
        v = V.load(path=self.path)
        self.assertEqual(v["台帳"], ["docs/backlog.md"])                         # 同じ項目は最初のもの
        self.assertEqual(v["持ち手の置き場所"], [".worktrees/Req", ".worktrees/Harness"])
        self.assertEqual(v["本番（触らない）"], ["8080", "~/.app/"])              # 括弧の中のコードは説明
        self.assertEqual(v["テスト（全部）"], ["make test 2>&1 | tail -5"])        # \\| はセルの中の |
        self.assertEqual(v["コンテキストの目安の見え方"], ["約15万トークン（ステータス行）"])   # 文の項目はそのまま
        for missing in ("申し送りの注意", "空の項目", "見本", "項目", "使わない項目", "括弧だけ",
                        "Req-main", "持ち手"):                         # 見出しが「項目」でない表は読まない
            self.assertNotIn(missing, v)
        self.assertEqual(v["空行のあとの項目"], ["after-blank"])
        self.assertEqual(V.first(v, "台帳"), "docs/backlog.md")
        self.assertEqual(V.first(v, "ない", "既定"), "既定")

    def test_no_table(self):
        self.assertEqual(V.load(path=os.path.join(tempfile.gettempdir(), "no-such-teamkit.md")), {})

    def test_cli(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = V.main(["持ち手の置き場所", "--file", self.path])
        self.assertEqual((code, out.getvalue()), (0, ".worktrees/Req\n.worktrees/Harness\n"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = V.main(["申し送りの注意", "--file", self.path])
        self.assertEqual((code, out.getvalue()), (1, ""))

    def test_template_items(self):
        """ひな形に、スキルとスクリプトが名前で読む項目がそろっていて、どれも値として読める。"""
        v = V.load(path=str(ROOT / "teamkit/templates/teamkit.template.md"))
        for key in KEYS:
            self.assertIn(key, v)

    @unittest.skipUnless((ROOT / ".claude/teamkit.md").exists(), "値の表のないリポジトリ")
    def test_repo_values_follow_template(self):
        """導入したリポジトリの値の表の項目が、ひな形の項目と同じ並び（項目を足したら両方に）。"""
        tmpl = V.parse((ROOT / "teamkit/templates/teamkit.template.md").read_text(encoding="utf-8"))
        repo = V.parse((ROOT / ".claude/teamkit.md").read_text(encoding="utf-8"))
        self.assertEqual(list(tmpl), list(repo))


if __name__ == "__main__":
    unittest.main()
