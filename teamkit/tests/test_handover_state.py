# -*- coding: utf-8 -*-
"""申し送りの状態を集めるスクリプト（.claude/skills/handover/state.sh）が、値の表（.claude/teamkit.md）を読むことのテスト。

一時の git リポジトリに値の表と部品（teamkit/values.py）を置き、眠るだけの模擬サーバーを立てて数えさせる。
gh は呼ばない（PATH から外す）。本番のサーバーには触れない。

    python3 -m unittest discover -s teamkit/tests -p test_handover_state.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".claude/skills/handover/state.sh"

VALUES = """\
| 項目 | 値 |
| :--- | :--- |
| 本番（触らない） | `8765`、`{prod}/` |
| 模擬サーバーのコマンド | `{name}` |
| 模擬環境のポートの範囲 | `18770〜18899` |
"""


class StateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name, "repo")
        self.prod = Path(self.tmp.name, "prod")
        self.repo.mkdir()
        self.prod.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        (self.repo / "teamkit").mkdir()
        shutil.copy(ROOT / "teamkit/values.py", self.repo / "teamkit/values.py")
        (self.repo / ".claude").mkdir()
        self.name = f"fakesrv_{os.getpid()}.py"
        for d in (self.repo, self.prod):
            (d / self.name).write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            p.kill()
            p.wait()
        self.tmp.cleanup()

    def values(self, name):
        (self.repo / ".claude/teamkit.md").write_text(VALUES.format(prod=self.prod, name=name), encoding="utf-8")

    def serve(self, where):
        p = subprocess.Popen([sys.executable, str(where / self.name)], cwd=where)
        self.procs.append(p)
        return p

    def state(self, *args):
        env = dict(os.environ, PATH="/usr/bin:/bin")       # gh を呼ばない
        r = subprocess.run(["bash", str(STATE), str(self.repo), *args], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def wait_up(self):
        time.sleep(0.3)

    def test_counts_mock_server_from_values(self):
        self.values(self.name)
        mine = self.serve(self.repo)
        prod = self.serve(self.prod)              # 本番の置き場所から動いているもの
        self.wait_up()
        out = self.state("--all")
        self.assertIn(f"  {mine.pid} ", out)
        self.assertNotIn(f"  {prod.pid} ", out)    # 本番は数えない
        out = self.state()
        self.assertIn(f"  {mine.pid} ", out)       # 自分の作業フォルダのもの

    def test_other_name_is_not_counted(self):
        """値の表の模擬サーバーのコマンドを変えると、数えるものが変わる。"""
        self.values("other_server.py")
        mine = self.serve(self.repo)
        self.wait_up()
        out = self.state("--all")
        self.assertNotIn(f"  {mine.pid} ", out)
        self.assertIn("動かしているもの（全部の作業フォルダの模擬サーバー。本番は除く）:\n  なし", out)

    def test_shell_wrapper_is_not_counted(self):
        """sh -c の文の中に名前が出るだけのものは数えない。"""
        self.values(self.name)
        sh = subprocess.Popen(["sh", "-c", f"sleep 30; echo {self.name}"], cwd=self.repo)
        self.procs.append(sh)
        self.wait_up()
        self.assertNotIn(f"  {sh.pid} ", self.state("--all"))

    def test_editor_is_not_counted_but_python_options_are(self):
        """エディタで開いているだけのものは数えず、python にオプションを付けて立てたものは数える。"""
        self.values(self.name)
        viewer = subprocess.Popen(["tail", "-f", str(self.repo / self.name)], cwd=self.repo,
                                  stdout=subprocess.DEVNULL)   # vim x.py の代わり
        opt = subprocess.Popen([sys.executable, "-u", "-X", "dev", str(self.repo / self.name)], cwd=self.repo)
        self.procs += [viewer, opt]
        self.wait_up()
        out = self.state("--all")
        self.assertNotIn(f"  {viewer.pid} ", out)
        self.assertIn(f"  {opt.pid} ", out)

    def test_name_is_not_regex(self):
        """名前の記号は、語として探す（正規表現にしない）。"""
        name = f"srv(dev)_{os.getpid()}.py"
        (self.repo / name).write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        self.values(name)
        p = subprocess.Popen([sys.executable, str(self.repo / name)], cwd=self.repo)
        self.procs.append(p)
        self.wait_up()
        self.assertIn(f"  {p.pid} ", self.state("--all"))

    def test_worktree_without_values_reads_main(self):
        """値の表のない worktree を指しても、もとのリポジトリの直下の値の表を読む。"""
        self.values(self.name)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x"],
                       cwd=self.repo, check=True)
        wt = Path(self.tmp.name, "wt")
        subprocess.run(["git", "worktree", "add", "-q", str(wt)], cwd=self.repo, check=True)
        (wt / self.name).write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        p = self.serve(wt)                         # 名前は、もとのリポジトリの値の表にだけある
        self.wait_up()
        env = dict(os.environ, PATH="/usr/bin:/bin")
        r = subprocess.run(["bash", str(STATE), str(wt)], capture_output=True, text=True, env=env)
        self.assertIn(f"  {p.pid} ", r.stdout)

    def test_without_values(self):
        """値の表がどこにもなければ、模擬サーバーは数えないと書いて、ほかは出す。

        state.sh は、このスクリプトのあるリポジトリの値の表までさかのぼるので、写した state.sh を動かす。"""
        sk = self.repo / ".claude/skills/handover"
        sk.mkdir(parents=True)
        shutil.copy(STATE, sk / "state.sh")
        env = dict(os.environ, PATH="/usr/bin:/bin")
        r = subprocess.run(["bash", str(sk / "state.sh"), str(self.repo)], capture_output=True, text=True, env=env)
        out = r.stdout
        self.assertIn("値の表に「模擬サーバーのコマンド」がないので数えない", out)
        self.assertIn("作業フォルダ:", out)


if __name__ == "__main__":
    unittest.main()
