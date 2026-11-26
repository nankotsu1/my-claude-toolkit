# -*- coding: utf-8 -*-
"""スプリントの終わりの写しと片付けのスクリプト（.claude/skills/sprint-end/sprint.py）のテスト。

一時の git リポジトリに、根と持ち手の TASK.md を作って流す。

    python3 -m unittest discover -s teamkit/tests -p test_sprint_end.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".claude/skills/sprint-end/sprint.py"

MANAGER = """\
# Manager-main: 目標

## タスク

- [x] REQ-1 済んだ束 → .worktrees/Req
- [ ] REQ-2 枝が全部済んだ束 → .worktrees/Req
- [ ] REQ-3 枝が残る束 → .worktrees/Req
- [ ] SBI-004 子の行がまだない束 → .worktrees/S004
- [x] 番号のない済んだ行
  - 細目の行
- [ ] MGR-1 自分でやる行

## 申し送り

- [x] 申し送りの中のチェックボックスは消さない
"""

REQ = """\
# Req-main: 依頼

## タスク

- [x] REQ-2-1 済み
- [x] REQ-2-2 済み
- [x] REQ-3-1 済み
- [/] REQ-3-2 やりかけ

## 申し送り

更新: 11/25
"""

VALUES = """\
| 項目 | 値 |
| :--- | :--- |
| 部の置き場所 | `.worktrees/Req`、`.worktrees/Test` |
| 写しの置き場 | `.worktrees/snapshots/` |
"""


class SprintEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = Path(self.tmp)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        (self.repo / "teamkit").mkdir()
        shutil.copy(ROOT / "teamkit/values.py", self.repo / "teamkit/values.py")
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude/teamkit.md").write_text(VALUES, encoding="utf-8")
        self.write("TASK.md", MANAGER)
        self.write(".worktrees/Req/TASK.md", REQ)
        self.write(".worktrees/Test/TASK.md", "# Test-main: なし\n\n## タスク\n\n- [x] TST-1 済み\n")
        self.write(".worktrees/S004/TASK.md", "# S004-main: ライン\n\n## タスク\n\n- [ ] SBI-004-1 まだ\n")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, rel, text):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def read(self, rel):
        return (self.repo / rel).read_text(encoding="utf-8")

    def run_it(self, *args):
        r = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.repo, capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr

    def snapshot(self):
        rc, out, _ = self.run_it("snapshot", "--name", "s1")
        self.assertEqual(rc, 0)
        return out.splitlines()[0]

    def test_files_follow_bundles_and_holders(self):
        rc, out, _ = self.run_it("files")
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(out.split()), sorted(["TASK.md", ".worktrees/Req/TASK.md",
                                                      ".worktrees/S004/TASK.md", ".worktrees/Test/TASK.md"]))

    def test_snapshot_keeps_layout_and_never_overwrites(self):
        dest = self.snapshot()
        self.assertEqual(Path(dest), self.repo / ".worktrees/snapshots/s1")
        self.assertEqual((Path(dest) / ".worktrees/Req/TASK.md").read_text(encoding="utf-8"), REQ)
        self.assertEqual((Path(dest) / "TASK.md").read_text(encoding="utf-8"), MANAGER)
        rc, out, _ = self.run_it("snapshot", "--name", "s1")
        self.assertTrue(out.splitlines()[0].endswith("s1-2"))

    def test_clean_without_write_changes_nothing(self):
        dest = self.snapshot()
        rc, out, _ = self.run_it("clean", "--snapshot", dest)
        self.assertEqual(rc, 0)
        self.assertEqual(self.read("TASK.md"), MANAGER)
        self.assertIn("消す行 3", out.splitlines()[0])

    def test_clean_removes_done_rows_and_done_bundles_only(self):
        dest = self.snapshot()
        rc, _, err = self.run_it("clean", "--snapshot", dest, "--write", "TASK.md", ".worktrees/Req/TASK.md")
        self.assertEqual(rc, 0, err)
        m = self.read("TASK.md")
        for gone in ("REQ-1 ", "REQ-2 ", "番号のない済んだ行", "細目の行"):
            self.assertNotIn(gone, m.split("## 申し送り")[0])
        for kept in ("REQ-3 ", "SBI-004 ", "MGR-1 ", "申し送りの中のチェックボックスは消さない"):
            self.assertIn(kept, m)
        r = self.read(".worktrees/Req/TASK.md")
        self.assertNotIn("REQ-2-1", r)
        self.assertNotIn("REQ-3-1", r)
        self.assertIn("[/] REQ-3-2", r)
        self.assertIn("更新: 11/25", r)
        self.assertIn("[x] TST-1", self.read(".worktrees/Test/TASK.md"))     # 挙げていない TASK.md は書かない

    def test_clean_refuses_file_changed_after_snapshot(self):
        dest = self.snapshot()
        self.write("TASK.md", MANAGER + "\n")
        rc, _, err = self.run_it("clean", "--snapshot", dest, "--write", "TASK.md")
        self.assertEqual(rc, 1)
        self.assertIn("書かない", err)
        self.assertEqual(self.read("TASK.md"), MANAGER + "\n")

    def test_orphan_folder_is_listed_not_removed(self):
        self.write("TASK.md", MANAGER.replace("- [ ] MGR-1", "- [x] REQ-5 部下の束 → .worktrees/REQ-5\n- [ ] MGR-1"))
        self.write(".worktrees/REQ-5/TASK.md", "# REQ-5: 部下\n\n## タスク\n\n- [x] REQ-5-1 済み\n")
        dest = self.snapshot()
        rc, out, _ = self.run_it("clean", "--snapshot", dest)
        tail = out.split("どの束からも指されなくなるフォルダ")[1]
        self.assertIn(".worktrees/REQ-5", tail)
        self.assertNotIn(".worktrees/Req\n", tail)       # 持ち手の置き場所は出さない
        self.assertTrue((self.repo / ".worktrees/REQ-5").is_dir())


if __name__ == "__main__":
    unittest.main()
