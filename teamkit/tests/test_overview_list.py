# -*- coding: utf-8 -*-
"""overview スキルの絞り込み（.claude/skills/overview/SKILL.md の 1c）の呼び方が、部品の --list で動くかのテスト。

スキルの置き換えの表と例のコマンドから引数を取り出し、日付と名前の置き場所（<今日> など）を埋めて、
見本のツリーに teamkit/tasktree.py --list で流す。部品の引数の名前が変わったら、ここで分かる。

    python3 -m unittest discover -s teamkit/tests -p test_overview_list.py
"""
import datetime as dt
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = (ROOT / ".claude/skills/overview/SKILL.md").read_text(encoding="utf-8")
TASKTREE = ROOT / "teamkit/tasktree.py"

TODAY = dt.date.today()


def md(d):
    return f"{d.month}/{d.day}"


FILL = {
    "<今日>": md(TODAY),
    "<明日>": md(TODAY + dt.timedelta(1)),
    "<今日から n-1 日あと>": md(TODAY + dt.timedelta(2)),
    "<その週の日曜>": md(TODAY + dt.timedelta(6 - TODAY.weekday())),
    "<次の月曜>": md(TODAY + dt.timedelta(7 - TODAY.weekday())),
    "<その次の日曜>": md(TODAY + dt.timedelta(13 - TODAY.weekday())),
    "<その部のセッション名>": "Harness",
    "<このセッションの名前>": "Harness-main",
    "<0 の名前>": "S041-main",
    "<ファイル>": "out.csv",
}

TREE = {
    "TASK.md": f"""# Manager-main: 見本

## タスク
- [ ] HAR-2 スキルを直す → .worktrees/Harness
- [ ] SBI-041 ログイン機能（着手: {md(TODAY)}）→ .worktrees/S041
- [ ] MGR-1 公開の時機（前提: 人の返事）
- [/] MGR-2 告知の文（前提: 人の返事）
""",
    ".worktrees/Harness/TASK.md": f"""# Harness-main: 見本

## タスク
- [x] HAR-2-1 値の表を直す（済: {md(TODAY)}）
- [/] HAR-2-2 スキルを直す
  - 説明: 行の書き方を新しい型に
- [ ] HAR-2-3 フックの案（着手: {md(TODAY + dt.timedelta(1))}）
""",
    ".worktrees/S041/TASK.md": f"""# S041-main: ログイン機能

## タスク
- [ ] SBI-041-1 画面の流れ（着手: {md(TODAY)}）
""",
}


def section_1c():
    m = re.search(r"^## 1c\..*?(?=^## )", SKILL, re.M | re.S)
    assert m, "overview の SKILL.md に 1c の節がない"
    return m.group(0)


def fill(arg):
    for k, v in FILL.items():
        arg = arg.replace(k, v)
    left = re.findall(r"<[^<>]+>", arg)
    assert not left, f"埋めていない置き場所: {left}（{arg}）"
    return arg


def table_args():
    """置き換えの表の「引数」の列の、コードの書き方の中身（--who … などの塊ごと）。"""
    out = []
    for line in section_1c().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 2 and cells[1].startswith("`--"):
            out.extend(re.findall(r"`(--[^`]+)`", cells[1]))
    return out


class OverviewListTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        for rel, text in TREE.items():
            p = Path(self.tmp.name, rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_list(self, args):
        return subprocess.run([sys.executable, str(TASKTREE), os.path.join(self.tmp.name, "TASK.md"), *args],
                              capture_output=True, text=True, cwd=self.tmp.name)

    def test_table_args_run(self):
        """置き換えの表のどの引数も、--list に渡して動く（終わりに「n 件」の行が出る）。"""
        args = table_args()
        self.assertGreaterEqual(len(args), 15, args)
        for a in args:
            with self.subTest(a=a):
                r = self.run_list(["--list", *shlex.split(fill(a))])
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertRegex(r.stdout, r"\d+ 件")

    def test_example_commands_run(self):
        """節のコードブロックの tasktree.py の呼び方が動く。"""
        cmds = re.findall(r"^python3 teamkit/tasktree\.py TASK\.md (--list[^\n#]*)", section_1c(), re.M)
        self.assertTrue(cmds)
        for c in cmds:
            r = self.run_list(shlex.split(fill(c)))
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_formats(self):
        """節に書いた形（md・json・csv）が出る。json の項目は節に書いた名前。"""
        sec = section_1c()
        for f in ("csv", "json"):
            self.assertIn(f"--format {f}", sec)
        r = self.run_list(["--list", "--who", "Harness", "--format", "json"])
        self.assertEqual(r.returncode, 0, r.stderr)
        names = re.findall(r"`(\w+)`", sec[sec.index("項目は"):].split("）", 1)[0])
        for n in names:
            self.assertIn(f'"{n}"', r.stdout)
        out = os.path.join(self.tmp.name, "out.csv")
        r = self.run_list(["--list", "--who", "Harness", "--format", "csv", "-o", out])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(Path(out).read_text(encoding="utf-8-sig").startswith("状態,"))

    def test_words_mean_what_the_skill_says(self):
        """置き換えの例が、見本のツリーで思ったとおりの行を出す。"""
        today = md(TODAY)
        r = self.run_list(["--list", "--who", "Harness", "--from", today, "--to", today])
        self.assertIn("HAR-2-2", r.stdout)        # 進行中は期間によらず入る
        self.assertIn("HAR-2-1", r.stdout)        # 今日済んだ
        self.assertNotIn("HAR-2-3", r.stdout)     # 明日から
        self.assertNotIn("SBI-041-1", r.stdout)   # ほかの持ち手
        r = self.run_list(["--list", "--who", "Manager", "--who-only", "--state", "human,blocked"])
        self.assertIn("MGR-1", r.stdout)
        self.assertNotIn("HAR-2", r.stdout)
        self.assertNotIn("MGR-2", r.stdout)       # [/] で前提が残る行は進行中（スキルに書いたとおり）
        r = self.run_list(["--list", "--who", "Manager", "--state", "doing"])
        self.assertRegex(r.stdout, r"MGR-2 \| 告知の文 \| [^|]*人の返事")
        r = self.run_list(["--list", "--who", "Nobody"])
        self.assertIn("Nobody", r.stderr)         # ツリーにない名前は標準エラーに


if __name__ == "__main__":
    unittest.main()
