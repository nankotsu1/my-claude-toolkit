# -*- coding: utf-8 -*-
"""ラインを立てるときの TASK.md の下書きを作るスクリプト（.claude/skills/line-start/draft.py）のテスト。

gh は呼ばない。見本の台帳と、リポジトリのひな形から下書きを作り、部品（teamkit/tasktree.py）で読めることを確かめる。

    python3 -m unittest discover -s teamkit/tests -p test_line_start.py
"""
import contextlib
import importlib.util
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = (ROOT / "teamkit/templates/TASK.template.md").read_text(encoding="utf-8")
# 見本の値の表（.claude/teamkit.md の形。teamkit/templates/teamkit.template.md）
VALUES_MD = """\
| 項目 | 値 |
| :--- | :--- |
| 決まりの文書 | `docs/rules.md` |
| 台帳 | `ledger.md` |
| 報告の写し先 | `docs/records/` |
| 本番（触らない） | `8765`、`~/.app/`（本番のサーバー） |
| ラインのポートの始まり | `18810` |
| ラインのポートの枠の数 | `8` |
| ラインのポートの枠の幅 | `10` |
| 実機確認の基準 | `docs/verify.md` |
| 一時の worktree | `.worktrees/wt/<番号>` |
"""


def load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


LEDGER = """\
# 作業の台帳

## 一覧

| 番号 | 名前 | 持ち手 | もとの番号 | Issue |
| :--- | :--- | :--- | :--- | :--- |
| SBI-041 | ログイン機能 | ライン S041-main | — | — |
| SBI-050 | 子の行のある仕事 | ライン S050-main | — | — |
| HAR-3 | 部の仕事 | Harness-main | — | — |

## SBI-041 ログイン機能

- 作るもの:
  - ログイン画面（`/login`）: メールとパスワードで入れる画面。
    続きの行もある
  - パスワードの再設定: 再設定のメールを送る
- 確かめ方: `python3 -m unittest tests.test_login` が通る。実機確認（人が update して見る）
- 触る所: `app/server.py`（`PAGE` の文字の所）、`tests/test_login.py`

## SBI-050 子の行のある仕事

全体の説明。

| 子の行 | 名前 | 持ち手（見込み） | 依存の事実 |
| :--- | :--- | :--- | :--- |
| SBI-050-1 | 一つめの子 | ライン S050-main | — |
| SBI-050-2 | 二つめの子 | ライン S050-main | SBI-050-1 の形を使う |

### SBI-050-3 注記のある子（2025-06-02、承認）

- 作るもの（基準は 設計書の 4.2。図解 https://example.com/a ）:
  - 不具合: 待ちの行に印を付けない
  - 列の名前を変える
- 確かめ方: テストが通る
- 触る所: `teamkit/z.py`

ファイルが重なる所: SBI-050-1 と HAR-3 は `README.md` で重なる。SBI-041 と SBI-099 は認証の部品で重なる。

### SBI-050-1 一つめの子

- 作るもの: 子の部品を作る
- 確かめ方: テストが通る
- 触る所: `teamkit/x.py`

### SBI-050-2 二つめの子

- 作るもの: 二つめ
- 確かめ方: テスト
- 触る所: `teamkit/y.py`
"""


def values_of(md):
    return load("teamkit_values_t", "teamkit/values.py").load(path=_tmpfile(md))


def _tmpfile(text):
    fd, path = tempfile.mkstemp(suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


class DraftTest(unittest.TestCase):
    def setUp(self):
        self.m = load("line_start_draft", ".claude/skills/line-start/draft.py")
        self.values = values_of(VALUES_MD)

    def draft(self, unit, **kw):
        kw.setdefault("values", self.values)
        return self.m.build_draft(ledger_md=LEDGER, template_md=TEMPLATE, unit_id=unit, now="2026-11-22 10:00", **kw)

    def tasks(self, text):
        body = text.split("## タスク\n", 1)[1].split("\n## ", 1)[0]
        return [l for l in body.splitlines() if l.startswith("- [")]

    def descs(self, text):
        """行ごとの説明（行の下の「  - 説明: …」。なければ空）。"""
        body = text.split("## タスク\n", 1)[1].split("\n## ", 1)[0]
        out = {}
        row = None
        for l in body.splitlines():
            if l.startswith("- ["):
                row = l.split(" ")[3]
                out[row] = ""
            elif l.startswith("  - 説明: ") and row:
                out[row] = l[len("  - 説明: "):]
        return out

    def test_names_and_ports(self):
        m = self.m
        self.assertEqual(m.unit_names("SBI-041"),
                         {"folder": "S041", "session": "S041-main", "branch": "SBI-041", "number": 41})
        self.assertEqual(m.unit_names("SBI-012-1")["folder"], "S012")
        self.assertEqual(m.unit_names("SBI-012-1")["branch"], "SBI-012-1")
        v = self.values
        self.assertEqual(m.port_range(3, v), "18840〜18849")     # 枠 ＝ 番号を枠の数で割った余り
        self.assertEqual(m.port_range(8, v), "18810〜18819")
        self.assertEqual(m.port_range(41, v), "18820〜18829")
        self.assertEqual(m.port_range(41, v, slot=7), "18880〜18889")
        self.assertIsNone(m.port_range(41, {}))                   # 値の表になければ出さない
        for bad in ("HAR-1", "REQ-2", "X-9", "SBI-41"):
            with self.assertRaises(ValueError):
                m.unit_names(bad)

    def test_rows_from_make_items(self):
        t, notes = self.draft("SBI-041")
        self.assertEqual(t.splitlines()[0], "# S041-main: SBI-041 ログイン機能")
        self.assertEqual(self.tasks(t), [
            "- [ ] SBI-041-1 ログイン画面",
            "- [ ] SBI-041-2 パスワードの再設定",
            "- [ ] SBI-041-3 " + self.m.LAST_ROW,
        ])
        d = self.descs(t)
        self.assertEqual(d["SBI-041-1"], "メールとパスワードで入れる画面。 続きの行もある")   # 名前より後ろが説明
        self.assertEqual(d["SBI-041-2"], "再設定のメールを送る")
        self.assertTrue(d["SBI-041-3"].startswith(self.m.LAST_DESC + "。確かめ方: `python3 -m unittest"), d)
        self.assertFalse(any("20字" in n for n in notes), notes)
        self.assertIn("18820〜18829", t)
        self.assertIn("`SBI-041: ログイン機能`", t)
        self.assertIn("`docs/records/SBI-041.md`", t)
        self.assertIn("実機確認: あり", t)
        self.assertIn("`app/server.py`（`PAGE` の文字の所）", t)
        self.assertIn("SBI-041 と SBI-099 は認証の部品で重なる。", t)
        self.assertIn("続きの行もある", t)                    # 作るものの写しは字下げの続きも
        self.assertIn("`docs/rules.md` と値の表 `.claude/teamkit.md`", t)
        self.assertIn("台帳 `ledger.md` の「SBI-041」の節", t)
        self.assertIn("本番（`8765`・`~/.app/`）には触れない", t)
        self.assertIn("`docs/verify.md`", t)
        self.assertNotIn("本番のサーバー", t)                # 値の表の説明（括弧の中）は書かない

    def test_values_change_the_draft(self):
        """値の表の値を変えると、下書きの値が変わる（スクリプトに固定の値を持たない）。"""
        other = values_of(VALUES_MD.replace("`docs/records/`", "`notes/done/`").replace("`18810`", "`20000`")
                          .replace("`8` |", "`4` |").replace("`10` |", "`5` |").replace("`docs/rules.md`", "`RULES.md`")
                          .replace("`8765`、`~/.app/`", "`9000`"))
        t, _ = self.draft("SBI-041", values=other)
        self.assertIn("`notes/done/SBI-041.md`", t)
        self.assertIn("20005〜20009", t)                            # 41 を 4 で割った余り 1、幅 5
        self.assertIn("`RULES.md` と値の表", t)
        self.assertIn("本番（`9000`）には触れない", t)
        t, notes = self.draft("SBI-041", values={})                 # 値の表がない
        self.assertIn("<ポートの範囲。", t)
        self.assertIn("<報告の写し先>", t)
        self.assertIn("本番には触れない", t)
        self.assertTrue(any("ポートの枠がない" in n for n in notes), notes)

    def test_rows_from_child_table(self):
        t, _ = self.draft("SBI-050")
        self.assertEqual(self.tasks(t), ["- [ ] SBI-050-1 一つめの子", "- [ ] SBI-050-2 二つめの子",
                                         "- [ ] SBI-050-3 " + self.m.LAST_ROW])
        d = self.descs(t)
        self.assertEqual(d["SBI-050-1"], "子の部品を作る 確かめ方: テストが通る")   # 子の節の作るもの・確かめ方の要点
        self.assertEqual(d["SBI-050-2"], "二つめ 確かめ方: テスト")
        self.assertIn("SBI-050-1 と HAR-3 は `README.md` で重なる。", t)   # 子の番号に触れる文も

    def test_child_unit_as_a_line(self):
        t, notes = self.draft("SBI-050-1")
        self.assertEqual(t.splitlines()[0], "# S050-main: SBI-050-1 一つめの子")
        self.assertEqual(self.tasks(t), ["- [ ] SBI-050-1-1 子の部品を作る", "- [ ] SBI-050-1-2 " + self.m.LAST_ROW])
        self.assertEqual(self.descs(t)["SBI-050-1-1"], "")                 # 名前と同じなら説明を書かない
        self.assertIn("`.worktrees/S050`", t)
        self.assertIn("ブランチ: `SBI-050-1`", t)
        self.assertIn("一時の worktree `.worktrees/wt/SBI-050-1`", t)
        self.assertIn("SBI-050-1 と HAR-3", t)
        self.assertNotIn("SBI-041 と SBI-099", t)
        self.assertTrue(any("実機確認" in n for n in notes))     # 台帳に無いので埋める

    def test_make_with_note_and_nested_items(self):
        """「- 作るもの（注記）:」で中身が字下げの入れ子だけの形も読む。"""
        t, notes = self.draft("SBI-050-3")
        self.assertEqual(t.splitlines()[0], "# S050-main: SBI-050-3 注記のある子")   # 見出しの終わりの日付の注記は外す
        self.assertEqual(self.tasks(t), [
            "- [ ] SBI-050-3-1 不具合",
            "- [ ] SBI-050-3-2 列の名前を変える",
            "- [ ] SBI-050-3-3 " + self.m.LAST_ROW,
        ])
        self.assertFalse(any("作るもの" in n for n in notes))
        self.assertNotIn("<作るもの>", t)
        self.assertIn("作るもの（写し）: （基準は 設計書の 4.2。図解 https://example.com/a ）\n  - 不具合: 待ちの行に印を付けない", t)
        self.assertEqual(self.m.field("- 作るもの（注記）: 一行\n- 確かめ方: x\n", "作るもの"), "一行")
        self.assertEqual(self.m.field("- 作るもの（注記）: 一行\n", "作るもの", note=True), "（注記） 一行")

    def test_work_place(self):
        """値の表の「作業の場所」に合わせて、下書きの作業の場所が変わる（既定は直下。line_rules.md の2章の 0）。"""
        t, notes = self.draft("SBI-041")                                  # 見本の値の表には項目がない → 直下
        self.assertIn("- 作業の場所: 直下（値の表）", t)
        self.assertIn("`git fetch origin && git switch -c SBI-041 origin/main`", t)
        self.assertIn("塞がっていれば一時の worktree `.worktrees/wt/SBI-041`", t)
        self.assertIn("ラインが直下（塞がっていれば一時の worktree .worktrees/wt/SBI-041）で origin/main から切る", t)
        self.assertFalse([n for n in notes if "作業の場所" in n or "直下" in n], notes)
        here = values_of(VALUES_MD + "| 作業の場所 | `直下` |\n")
        self.assertEqual(self.draft("SBI-041", values=here)[0], t)
        wt = values_of(VALUES_MD + "| 作業の場所 | `worktree` |\n")
        t, notes = self.draft("SBI-041", values=wt)
        self.assertIn("- 作業の場所: 一時の worktree `.worktrees/wt/SBI-041`（値の表が worktree。", t)
        self.assertIn("`git fetch origin && git worktree add .worktrees/wt/SBI-041 -b SBI-041 origin/main`", t)
        self.assertNotIn("git switch -c", t)
        self.assertIn("ラインが一時の worktree .worktrees/wt/SBI-041 を origin/main から作って切る", t)
        bad = values_of(VALUES_MD + "| 作業の場所 | `どこか` |\n")
        t, notes = self.draft("SBI-041", values=bad)
        self.assertIn("- 作業の場所: 直下（値の表）", t)
        self.assertTrue(any("作業の場所" in n for n in notes), notes)

    def test_long_names_go_to_desc(self):
        """名前は20字まで。長い名前は縮め、もとの文は説明に回して注意に出す（teamkit/docs/taskmd.md の2章）。"""
        m = self.m
        self.assertEqual(m.name_of("ログイン画面（`/login`）: 画面"), ("ログイン画面", False))
        self.assertEqual(m.name_of("部品を teamkit/ に移し、新しい型で読む"), ("部品を teamkit/ に移し", True))
        self.assertEqual(m.name_of("あいうえおかきくけこさしすせそたちつてとなにぬ"),
                         ("あいうえおかきくけこさしすせそたちつて…", True))
        self.assertEqual(m.name_of("短い名前（とても長い括弧の注記がここにずっと続いている）の行です"), ("短い名前の行です", True))
        self.assertEqual(m.name_of("（括弧だけの、とても長い名前がここに続いていく）")[0], "（括弧だけの")
        self.assertEqual(m.gist("一つめ（括弧の中。ここ）の文。二つめ。"), "一つめ（括弧の中。ここ）の文。二つめ。")
        self.assertEqual(m.gist("一つめ。二つめの長い文", limit=6), "一つめ。")
        self.assertEqual(m.gist("切れない長い一つの文", limit=5), "切れない…")
        long = LEDGER.replace("| SBI-050-2 | 二つめの子 |", "| SBI-050-2 | 二つめの子で、とても長い名前の仕事をまとめて書いた行 |")
        t, notes = m.build_draft(ledger_md=long, template_md=TEMPLATE, unit_id="SBI-050", now="x", values=self.values)
        row = self.tasks(t)[1]
        self.assertEqual(row, "- [ ] SBI-050-2 二つめの子で")             # 「、」の手前で切る
        self.assertTrue(self.descs(t)["SBI-050-2"].startswith("二つめの子で、とても長い名前の仕事をまとめて書いた行。 二つめ"))
        self.assertTrue(any("20字" in n for n in notes), notes)
        for r in self.tasks(t):                                     # どの行の名前も20字まで
            self.assertLessEqual(len(r.split(" ", 4)[4]), m.NAME_MAX, r)

    def test_no_prereqs_no_dates_in_rows(self):
        """ラインの TASK.md の行には前提も着手予定日も書かない（前提は親の TASK.md だけ）。"""
        for unit in ("SBI-041", "SBI-050", "SBI-050-2"):
            t, _ = self.draft(unit)
            for row in self.tasks(t):
                self.assertNotIn("前提", row)
                self.assertNotIn("着手", row)

    def test_template_sections_kept(self):
        t, _ = self.draft("SBI-041")
        heads = [l for l in t.splitlines() if l.startswith("## ")]
        self.assertEqual(heads, ["## タスク", "## 持ち場", "## 材料", "## この作業単位の値",
                                 "## 並行して動いているもの", "## メモ", "## 報告", "## 申し送り"])
        self.assertIn("フェーズ: 実装", t)
        self.assertIn("理由: 立ち上げ", t)

    def test_tasktree_reads_draft(self):
        t, _ = self.draft("SBI-041")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "TASK.md")
            Path(p).write_text(t, encoding="utf-8")
            text = subprocess.run([sys.executable, str(ROOT / "teamkit/tasktree.py"), p, "--text", "--all"],
                                  capture_output=True, text=True, check=True).stdout
        self.assertIn("S041-main", text)
        self.assertIn("SBI-041-1 ログイン画面", text)
        self.assertIn("SBI-041-3", text)

    def test_errors(self):
        with self.assertRaises(ValueError):
            self.draft("SBI-099")                 # 節がない
        with self.assertRaises(ValueError):
            self.draft("HAR-3")                   # 部の仕事はラインにしない

    def test_repo_ledger(self):
        """導入したリポジトリの台帳（値の表の「台帳」）のどの SBI の節からも、下書きが作れる（名前は20字まで）。"""
        values = self.m.load_values(str(ROOT))
        path = (values.get("台帳") or [None])[0]
        if not path or not (ROOT / path).is_file():
            self.skipTest("値の表に台帳がない")
        ledger = (ROOT / path).read_text(encoding="utf-8")
        units = re.findall(r"^#{2,4} (SBI-\d{3,4}(?:-\d+)*)(?:[ \t]|$)", ledger, re.M)
        if not units:
            self.skipTest("台帳に SBI の節がない")
        for unit in units:
            t, notes = self.m.build_draft(ledger_md=ledger, template_md=TEMPLATE, unit_id=unit, now="x", values=values)
            self.assertFalse([n for n in notes if "作るもの" in n], unit)
            self.assertTrue(all(len(r.split(" ", 4)[4]) <= self.m.NAME_MAX for r in self.tasks(t)), (unit, self.tasks(t)))


class WriteTest(unittest.TestCase):
    def setUp(self):
        self.m = load("line_start_draft", ".claude/skills/line-start/draft.py")
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.ledger = os.path.join(self.root, "ledger.md")
        Path(self.ledger).write_text(LEDGER, encoding="utf-8")
        self.tmpl = os.path.join(self.root, "tmpl.md")
        Path(self.tmpl).write_text(TEMPLATE, encoding="utf-8")
        os.makedirs(os.path.join(self.root, ".claude"))
        Path(self.root, ".claude", "teamkit.md").write_text(VALUES_MD, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.m.main(["SBI-041", "--root", self.root, "--ledger", self.ledger,
                                "--template", self.tmpl, *args])
        return code, out.getvalue(), err.getvalue()

    def test_print_only(self):
        code, out, err = self.run_main()
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("# S041-main: "))
        self.assertFalse(os.path.exists(os.path.join(self.root, ".worktrees")))
        self.assertIn("18820〜18829", out)                             # リポジトリ直下の値の表を読んだ

    def test_ledger_from_values(self):
        """--ledger がなければ、値の表の「台帳」を読む。値の表に台帳がなければ止まる。"""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.m.main(["SBI-041", "--root", self.root, "--template", self.tmpl])
        self.assertEqual(code, 0, err.getvalue())                       # git の外なので手元の ledger.md
        self.assertIn("# S041-main: SBI-041 ログイン機能", out.getvalue())
        Path(self.root, ".claude", "teamkit.md").write_text(VALUES_MD.replace("| 台帳 | `ledger.md` |\n", ""), encoding="utf-8")
        code, _, err = self.run_main_without_ledger()
        self.assertEqual(code, 2)
        self.assertIn("「台帳」がない", err)
        Path(self.root, ".claude", "teamkit.md").write_text(VALUES_MD.replace("| ラインのポートの枠の数 | `8` |\n", ""), encoding="utf-8")
        code, _, err = self.run_main("--port-slot", "1")
        self.assertEqual(code, 2)
        self.assertIn("枠の数がないので、--port-slot は使えない", err)
        Path(self.root, ".claude", "teamkit.md").write_text(VALUES_MD, encoding="utf-8")
        code, _, err = self.run_main("--port-slot", "8")
        self.assertIn("--port-slot は 0〜7", err)
        Path(self.root, ".claude", "teamkit.md").write_text(VALUES_MD.replace("| 台帳 | `ledger.md` |\n", ""), encoding="utf-8")
        code, _, err = self.run_main_without_ledger()
        self.assertEqual(code, 2)
        self.assertIn("「台帳」がない", err)

    def run_main_without_ledger(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.m.main(["SBI-041", "--root", self.root, "--template", self.tmpl])
        return code, out.getvalue(), err.getvalue()

    def test_write_makes_placement_and_no_task(self):
        wt = os.path.join(self.root, ".worktrees", "S041")
        code, out, _ = self.run_main("--write")
        self.assertEqual(code, 0)                                       # 置き場所は draft.py が作る（git の worktree にしない）
        path = os.path.join(wt, "TASK.md")
        self.assertTrue(Path(path).read_text(encoding="utf-8").startswith("# S041-main: "))
        self.assertEqual(Path(wt, ".git").read_text(encoding="utf-8"), self.m.GUARD)   # 置き場所で git を止める
        self.assertIn("git worktree add .worktrees/wt/SBI-041 -b SBI-041 origin/main", Path(path).read_text(encoding="utf-8"))
        Path(path).write_text("# S041-main: 動いている\n", encoding="utf-8")
        code, _, err = self.run_main("--write")
        self.assertEqual(code, 1)                                       # 動いているラインを上書きしない
        self.assertEqual(Path(path).read_text(encoding="utf-8"), "# S041-main: 動いている\n")
        code, _, _ = self.run_main("--write", "--force", "--port-slot", "5")
        self.assertEqual(code, 0)
        self.assertIn("18860〜18869", Path(path).read_text(encoding="utf-8"))

    def test_guard_stops_git(self):
        subprocess.run(["git", "init", "-q", self.root], check=True)
        self.assertEqual(self.run_main("--write")[0], 0)
        wt = os.path.join(self.root, ".worktrees", "S041")
        r = subprocess.run(["git", "status"], cwd=wt, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)                           # 上へたどって直下の main に当たらない
        self.assertIn("fatal:", r.stderr)                               # 文言は git の版で違う（not a git repository / gitfile does not point …）

    def test_write_keeps_old_worktree_git(self):
        wt = os.path.join(self.root, ".worktrees", "S041")
        os.makedirs(wt)
        Path(wt, ".git").write_text("gitdir: /somewhere/.git/worktrees/S041\n", encoding="utf-8")
        self.assertEqual(self.run_main("--write")[0], 0)
        self.assertEqual(Path(wt, ".git").read_text(encoding="utf-8"), "gitdir: /somewhere/.git/worktrees/S041\n")


if __name__ == "__main__":
    unittest.main()
