# -*- coding: utf-8 -*-
"""申し送りの節を差し替えるスクリプト（.claude/skills/handover/write.py）のテスト。

本文の「## 申し送り」という文字列に当たって、そこから最後までを消さないように、
行頭の見出しだけを見ること、ほかの節を変えないことを確かめる。

    python3 -m unittest discover -s teamkit/tests -p test_handover_write.py
"""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".claude/skills/handover/write.py"


def load():
    spec = importlib.util.spec_from_file_location("handover_write", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["handover_write"] = mod
    spec.loader.exec_module(mod)
    return mod


TASK = """\
# TASK: ① 画面ライン — 1-B ツリー（#23）

## 進め方

**申し送り**: 区切りごとに、下の「## 申し送り」を更新する。
## 申し送り という文字列が本文の行頭近くにあっても（これは見出しではない行の途中）

```markdown
## 申し送り
（コードブロックの中の見本）
```

## マージ

- squash

## 本番のサーバーには絶対に触れない

- 8765

## 申し送り

更新: 古い
- 古い内容
"""

NEW = "## 申し送り\n\n更新: 新しい\n\n### いまの状態\n- 新しい内容\n"


class WriteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load()

    def test_replaces_only_the_heading_section(self):
        out = self.m.replace_handover(TASK, NEW)
        self.assertEqual(out.split("## 本番のサーバー")[0], TASK.split("## 本番のサーバー")[0])
        self.assertIn("## マージ\n", out)
        self.assertIn("- 8765\n\n## 申し送り\n\n更新: 新しい\n", out)
        self.assertNotIn("古い内容", out)
        self.assertEqual(self.m.replace_handover(out, NEW), out)

    def test_section_in_the_middle_and_missing(self):
        mid = "# T\n\n## 申し送り\n\n古い\n\n## 報告\n\nあり\n"
        out = self.m.replace_handover(mid, "新しい\n")    # 見出しなしで渡しても足す
        self.assertEqual(out, "# T\n\n## 申し送り\n\n新しい\n\n## 報告\n\nあり\n")
        self.assertTrue(self.m.replace_handover("# T\n\n## 報告\n", NEW).endswith("## 報告\n\n" + NEW))

    def test_refuses_dangerous_input(self):
        with self.assertRaises(ValueError):
            self.m.replace_handover(TASK, NEW + "\n## 報告\n")              # 新しい中身に ## 見出し
        with self.assertRaises(ValueError):
            self.m.replace_handover(TASK + "\n## 申し送り\n\n2つ目\n", NEW)  # 申し送りが2つ

    def test_cli_does_not_write_on_error(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "TASK.md"
            p.write_text(TASK, encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(p)], input=NEW + "## x\n",
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertEqual(p.read_text(encoding="utf-8"), TASK)
            r = subprocess.run([sys.executable, str(SCRIPT), str(p)], input=NEW, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("更新: 新しい", p.read_text(encoding="utf-8"))


    def test_warns_odd_headings(self):
        """本文の折り返しが行頭に来た「## 」の行を、書いたあとに警告する（書くのは止めない）。"""
        odd = self.m.odd_headings
        lines = ["# TASK: 見本の持ち手 — 置き場所の TASK.md を指示のパスで決める長い見出し（#12）",
                 "## 報告（PR 16 の本文より。統括が転記）", "## 3. 起こしにくいもの（起きたときに見る。待たない）",
                 "## 申し送り」の行から次の見出しの手前まで（本文の途中を目印にしない）。置き文字だけは最後の発言",
                 "```", "## 申し送りの中の。コードブロック", "```"]
        self.assertEqual([i for i, _ in odd(lines)], [3])
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "TASK.md"
            p.write_text(TASK.replace("## 進め方", "## 進め方\n\n## 作るものの節を写す。ここで折り返した"), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(p)], input=NEW, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("見出しとして不自然", r.stderr)
            self.assertIn("更新: 新しい", p.read_text(encoding="utf-8"))

if __name__ == "__main__":
    unittest.main()
