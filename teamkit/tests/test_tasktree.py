# -*- coding: utf-8 -*-
"""TASK.md のツリーの部品 teamkit/tasktree.py のテスト（型は teamkit/docs/taskmd.md、見え方は teamkit/docs/views.md）。

部品は直接読み込んで関数を呼ぶ（TASK.md は一時ディレクトリ）: 読み方（「## タスク」、なければいちばん浅い
チェックボックス。印 [ ]・[/]・[x]）、束の枝（番号が束と同じか、束の番号に「-」で続く行だけ）、束の状態を枝から、
番号のない行を数えない、写した木を読む（ツリーの根）、3段と循環、持ち手の名前、人を待っている持ち手、前提と順番の待ち、
計画、図のデータ（Issue のリンクの頭、ブロッカーの短い形）、文字の書き出し、CLI。

    python3 -m unittest discover -s teamkit/tests -p test_tasktree.py
"""
import datetime
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
PART = HERE.parent / "tasktree.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


T = load(PART, "tasktree_test")
WAITING = T.WAITING

# views.md の5章の例（統括と、部1つ、ライン1本）。--text と --plan は文書の例と同じ字になる
ROOT = """# Manager-main: 会員機能を作る

## タスク
- [ ] REQ-3 認証の要求 → .worktrees/Req
- [ ] REQ-4 通知メールの要求 → .worktrees/Req
- [ ] SBI-041 ログイン機能（前提: REQ-3）→ .worktrees/S041
- [ ] MGR-1 公開の時機を決める（前提: SBI-041, 人の返事）

## 申し送り
- [ ] 申し送りの行は読まない
"""
REQ = """# Req-main: 要求と仕様の受け持ち

## タスク
- [x] REQ-3-1 認証の方式を調べる
- [x] REQ-3-2 要求を書く
- [/] REQ-4-1 通知の文面を詰める
- [ ] REQ-4-2 メール配信サービスを比べる（大きいので部下に任せる）→ .worktrees/REQ-4-2
"""
LINE = """# S041-main: ログイン機能

## タスク
- [x] SBI-041-1 画面の流れを調べる
- [/] SBI-041-2 ログイン画面を作る
- [ ] SBI-041-3 パスワードの再設定

## ラインの作業

| 作業単位 | 状態 |
| --- | --- |
| X-1 表は読まない | **いま** |
"""
TEXT = """# Manager-main: 会員機能を作る
- ✅ 済 1 件
- 🔄 REQ-4 通知メールの要求 0/2
  - （.worktrees/Req/TASK.md）
  - 🔄 REQ-4-1 通知の文面を詰める
  - ⬜ REQ-4-2 メール配信サービスを比べる（大きいので部下に任せる）
    - （.worktrees/REQ-4-2/TASK.md）
    - タスク一覧はありません
- 🔄 SBI-041 ログイン機能（前提: REQ-3） 1/3
  - （.worktrees/S041/TASK.md）
  - ✅ 済 1 件
  - 🔄 SBI-041-2 ログイン画面を作る
  - ⏳ SBI-041-3 パスワードの再設定
- ⏳ MGR-1 公開の時機を決める（前提: SBI-041, 人の返事）
"""
PLAN = """# 計画 — 会員機能を作る
- 始められる: REQ-4-2 メール配信サービスを比べる（大きいので部下に任せる）（REQ-4-2）
- 待ち: SBI-041-3 パスワードの再設定（S041-main） ← SBI-041-2（S041-main 🔄）
- 待ち: MGR-1 公開の時機を決める（Manager-main） ← SBI-041（S041-main 🔄）
"""


def root_plus(*rows):
    """ROOT の「## タスク」の終わりに行を足したもの（申し送りの節の前）。"""
    return ROOT.replace("\n## 申し送り", "".join(r + "\n" for r in rows) + "\n## 申し送り")


class Repo:
    """一時ディレクトリのリポジトリ（.git フォルダだけ）に TASK.md を置く。"""

    def __init__(self, case, git=True):
        self.root = Path(tempfile.mkdtemp(prefix="tasktree-"))
        case.addCleanup(shutil.rmtree, self.root, True)
        if git:
            (self.root / ".git").mkdir()

    def put(self, rel, text):
        p = self.root / rel / "TASK.md" if rel else self.root / "TASK.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def example(self):
        self.put("", ROOT)
        self.put(".worktrees/Req", REQ)
        self.put(".worktrees/S041", LINE)
        return self


def run_cli(*args):
    return subprocess.run([sys.executable, str(PART), *map(str, args)], capture_output=True, timeout=30)


def by_no(t):
    return {ln["no"]: ln for ln, _ in T.walk(t) if ln["no"]}


def lane_of(g, kind, name=None):
    return next(L for L in g["lanes"] if L["kind"] == kind and (name is None or name in (L["name"], L.get("bundle"))))


def nos(g, ids):
    return [g["boxes"][i]["no"] for i in ids]


# ---- 読み方（rows / make_rows） ----
class RowsTest(unittest.TestCase):
    def test_marks_bundles_issues_and_numbers(self):
        r = T.make_rows("# Manager-main: 試し\n\n## タスク\n- [x] A-1 済み\n- [/] A-2 着手 #12\n- [ ] A-3 束 → .worktrees/a #13\n"
                        "- [X] A-4 大文字\n- [ ] 番号なし\n")
        self.assertEqual((r["source"], r["title"], r["head"]), ("tasks", "Manager-main: 試し", "試し"))
        self.assertEqual([(ln["no"], ln["mark"]) for ln in r["lines"]],
                         [("A-1", "done"), ("A-2", "doing"), ("A-3", "todo"), ("A-4", "done"), ("", "todo")])
        self.assertEqual([ln["issues"] for ln in r["lines"]], [[], ["12"], ["13"], [], []])
        self.assertEqual(r["lines"][2]["to"], ".worktrees/a")

    def test_only_tasks_section_or_boxes(self):
        """読むのは「## タスク」の節だけ。なければ全体のチェックボックスのいちばん浅いもの。表の行は行にならない。"""
        r = T.make_rows(LINE)
        self.assertEqual((r["source"], [ln["no"] for ln in r["lines"]]), ("tasks", ["SBI-041-1", "SBI-041-2", "SBI-041-3"]))
        r = T.make_rows("# 統括\n## タスクライン\n- [ ] A-1 甲 → .worktrees/a #3\n  - [ ] 細目\n- [/] B-1 乙\n")
        self.assertEqual(r["source"], "boxes")
        self.assertEqual([(ln["no"], ln["mark"], ln.get("to")) for ln in r["lines"]],
                         [("A-1", "todo", ".worktrees/a"), ("B-1", "doing", None)])
        self.assertIsNone(T.make_rows("# 表だけ\n\n| 作業単位 | 状態 |\n| --- | --- |\n| SBI-031 甲 | いま |\n"))
        self.assertEqual(T.make_rows("## タスク一覧\n- [ ] A\n")["source"], "boxes")
        self.assertEqual(T.make_rows("## タスク（統括）\n- [ ] A\n")["source"], "tasks")
        self.assertIsNone(T.make_rows("# 本文だけ\n```\n- [ ] 囲みの中\n```\n"))

    def test_arrow_needs_a_folder_and_shallow_rows(self):
        r = T.make_rows("## タスク\n- [ ] 名前を旧 → 新\n- [ ] 変換 a -> b\n- [ ] 上 → .\n- [ ] 家 → ~/work\n")
        self.assertEqual([(ln["text"], ln.get("to")) for ln in r["lines"]],
                         [("名前を旧 → 新", None), ("変換 a -> b", None), ("上", "."), ("家", "~/work")])
        r = T.make_rows("## タスク\n  - [ ] A\n    - [ ] 細目\n- [ ] B\n")
        self.assertEqual([ln["text"] for ln in r["lines"]], ["A", "B"])

    def test_rows_reads_file_or_folder_and_resolves_from_repo_root(self):
        repo = Repo(self).example()
        for arg in (repo.root / "TASK.md", repo.root):
            self.assertEqual(T.rows(str(arg))["lines"][0]["dir"], str(repo.root / ".worktrees/Req"))
        # 子のフォルダの TASK.md の束も、そのフォルダではなくリポジトリ直下から数える
        self.assertEqual(T.rows(str(repo.root / ".worktrees/Req"))["lines"][3]["dir"], str(repo.root / ".worktrees/REQ-4-2"))
        self.assertIsNone(T.rows(str(repo.root / "nope")))
        T.rows(str(repo.root))["lines"].clear()             # 控えは写しを返す
        self.assertEqual(len(T.rows(str(repo.root))["lines"]), 4)

    def test_repo_base_in_git_worktree(self):
        repo = Repo(self)
        wt = repo.root / ".worktrees" / "line-1b"
        gitdir = repo.root / ".git" / "worktrees" / "line-1b"
        gitdir.mkdir(parents=True)
        (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
        wt.mkdir(parents=True)
        (wt / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
        self.assertEqual(T.repo_base(str(wt / "tools")), str(repo.root))
        self.assertEqual(T.bundle_dir(".worktrees/a", str(wt)), str(repo.root / ".worktrees/a"))
        self.assertEqual(T.bundle_dir("/abs/where/TASK.md", str(wt)), "/abs/where")
        self.assertEqual(T.bundle_dir("a/b", str(wt), "/base"), "/base/a/b")
        outside = Path(tempfile.mkdtemp(prefix="tasktree-nogit-"))
        self.addCleanup(shutil.rmtree, outside, True)
        self.assertEqual(T.repo_base(str(outside)), str(outside))

    def test_number_form(self):
        """番号: 英大文字で始まる語 - 英大文字と数字、- で続く子の番号。数字で始まる語・小文字・日付は番号にしない。"""
        for text, no in [("SBI-041 a", "SBI-041"), ("SBI-041-2 b", "SBI-041-2"), ("X-9 c", "X-9"), ("5-A d", ""),
                         ("1-E e", ""), ("H-9", "H-9"), ("ABC1-2-3 e", "ABC1-2-3"), ("REQ-1 部の仕事", "REQ-1"),
                         ("HAR-42-3 細目", "HAR-42-3"), ("I-3-1 子", "I-3-1"), ("S041-main f", ""), ("Re-run g", ""),
                         ("2026-11-22 h", ""), ("SBI-041a i", ""), ("12 番", "12"), ("UTF-8 で書く", "UTF-8")]:
            self.assertEqual(T.lead_no(text), no, text)
        self.assertEqual(T.read_pre("（前提: SBI-040, SBI-039-2, update）"), ["SBI-040", "SBI-039-2", "update"])
        self.assertEqual([bool(T.UNIT_NO.fullmatch(p)) for p in ["SBI-040", "SBI-039-2", "12", "update", "S033-main", "5-A"]],
                         [True, True, True, False, False, False])
        self.assertEqual([T.in_branch(n, "REQ-4") for n in ("REQ-4", "REQ-4-1", "REQ-4-2-1", "REQ-41", "REQ-3-1", "")],
                         [True, True, True, False, False, False])

    def test_version(self):
        self.assertEqual(T.VERSION, 5)


# ---- 束の枝（views.md の2章「束の枝」） ----
class BranchTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self).example()

    def test_doc_example_text_and_plan(self):
        """views.md の5章の例: --text と --plan が文書の例と同じ字になる（CLI も）。"""
        t = T.link(T.tree(str(self.repo.root)))
        self.assertEqual(T.text(t), TEXT)
        self.assertEqual(T.plan_text(T.plan(t), t["head"]), PLAN)
        self.assertEqual(run_cli(self.repo.root).stdout.decode("utf-8"), TEXT)
        self.assertEqual(run_cli(self.repo.root / "TASK.md", "--plan").stdout.decode("utf-8"), PLAN)

    def test_two_bundles_to_one_folder_have_own_branch(self):
        """同じフォルダを指す束は、それぞれ自分の枝だけを持つ。どの束にも当たらない子の行は出ない。"""
        self.repo.put(".worktrees/Req", REQ + "- [ ] REQ-9-1 束のない仕事\n")
        t = T.tree(str(self.repo.root))
        r3, r4 = t["lines"][:2]
        self.assertEqual([k["no"] for k in r3["kids"]["lines"]], ["REQ-3-1", "REQ-3-2"])
        self.assertEqual([k["no"] for k in r4["kids"]["lines"]], ["REQ-4-1", "REQ-4-2"])
        self.assertNotIn("REQ-9-1", by_no(t))
        self.assertEqual([k["ord"] for k in r4["kids"]["lines"]], [2, 3])        # 子の TASK.md の中の順
        # 束と同じ番号の行1つでもよい。束の番号に「-」で続かない行（REQ-41）は枝に入らない
        self.repo.put(".worktrees/Req", "# Req-main: 受け持ち\n\n## タスク\n- [x] REQ-3 そのまま1行\n- [ ] REQ-41 別の依頼\n")
        r3, r4 = T.tree(str(self.repo.root))["lines"][:2]
        self.assertEqual(([k["no"] for k in r3["kids"]["lines"]], r3["mark"]), (["REQ-3"], "done"))
        self.assertEqual((r4["kids"]["lines"], r4["mark"]), ([], "todo"))

    def test_nested_bundle_numbers_take_the_longest(self):
        """束 REQ-4 と REQ-4-2 が同じフォルダを指すなら、REQ-4-2-1 は長く合う REQ-4-2 の枝だけに入る。"""
        self.repo.put("", "# Manager-main: 試し\n\n## タスク\n- [ ] REQ-4 甲 → .worktrees/Req\n- [ ] REQ-4-2 乙 → .worktrees/Req\n")
        self.repo.put(".worktrees/Req", "# Req-main: 受け持ち\n\n## タスク\n- [x] REQ-4-1 一\n- [ ] REQ-4-2-1 二\n")
        a, b = T.tree(str(self.repo.root))["lines"]
        self.assertEqual(([k["no"] for k in a["kids"]["lines"]], [k["no"] for k in b["kids"]["lines"]]),
                         (["REQ-4-1"], ["REQ-4-2-1"]))
        self.assertEqual((a["mark"], b["mark"]), ("done", "todo"))

    def test_bundle_state_from_branch(self):
        """束の状態は枝から: 全部 [x] で済み、[/] か [x] があれば 🔄、印がなければ前提から。束の行に書いた印は読まない。"""
        self.repo.put("", ROOT.replace("- [ ] REQ-4", "- [x] REQ-4").replace("- [ ] REQ-3", "- [/] REQ-3"))
        t = T.link(T.tree(str(self.repo.root)))
        by = by_no(t)
        self.assertEqual((by["REQ-3"]["mark"], by["REQ-3"]["done"], by["REQ-3"]["total"]), ("done", 2, 2))
        self.assertEqual((by["REQ-4"]["mark"], by["REQ-4"]["now"]), ("doing", "REQ-4-1"))
        self.assertNotIn("⚠", T.text(t, all=True))
        self.repo.put(".worktrees/S041", "# S041-main: ログイン機能\n\n## タスク\n- [ ] SBI-041-1 調べる\n")
        t = T.link(T.tree(str(self.repo.root)))
        self.assertEqual((by_no(t)["SBI-041"]["mark"], by_no(t)["SBI-041"]["state"]), ("todo", "ready"))   # REQ-3 は済み

    def test_done_bundle_is_opened(self):
        """済んだ束も枝を開く（--all の文字と、図の済んだ丸）。"""
        t = T.link(T.tree(str(self.repo.root)))
        out = T.text(t, all=True)
        self.assertIn("- ✅ REQ-3 認証の要求 2/2\n  - （.worktrees/Req/TASK.md）\n  - ✅ REQ-3-1", out)
        g = T.graph(T.tree(str(self.repo.root)))
        req = lane_of(g, "folder", "Req")
        self.assertEqual(nos(g, req["done"]), ["REQ-3-1", "REQ-3-2"])
        self.assertEqual(nos(g, req["boxes"]), ["REQ-4-1", "REQ-4-2"])

    def test_unnumbered_rows_are_not_counted(self):
        """「## タスク」の番号のない行は数えない: 計画と図には出さず、文字の全体像の終わりに件数だけ。番号のない束も
        同じで、子は開かない（番号のない行の短い形は作らない）。"""
        self.repo.put("", ROOT.replace("- [ ] MGR-1", "- [ ] 覚え書きの行\n- [ ] 番号のない束 → .worktrees/S041\n- [ ] MGR-1"))
        t = T.link(T.tree(str(self.repo.root)))
        self.assertEqual((t["unnumbered"], len(t["lines"])), (2, 4))
        self.assertEqual(T.text(t), TEXT + "- 番号のない行 2 件（数えない）\n")
        self.assertEqual(T.plan_text(T.plan(t), t["head"]), PLAN)
        g = T.graph(T.tree(str(self.repo.root)))
        self.assertTrue(all(b["no"] for b in g["boxes"]))
        self.assertEqual(sorted(b["tag"] for b in g["boxes"] if b["lane"] == lane_of(g, "self")["id"]), ["M1"])
        self.assertEqual(len(lane_of(g, "folder", "S041")["done"] + lane_of(g, "folder", "S041")["boxes"]), 3)  # 束は1つだけ

    def test_rows_outside_bundles_are_counted(self):
        """子が束の番号に続けずに足した済んでいない行は、束に入れず、文字の全体像の終わりに子の TASK.md ごとの件数と
        場所だけ（孫の分も根まで上げる。済んだ行は数えない）。計画には出さない。"""
        self.repo.put(".worktrees/Req", REQ + "- [ ] REQ-9 部が足した仕事\n- [x] REQ-8 済んだ別の依頼\n")
        self.repo.put(".worktrees/REQ-4-2", "# REQ-4-2: 比べる\n\n## タスク\n- [ ] REQ-4-2-1 候補を出す\n"
                      "- [ ] X-1 部下が足した仕事\n- [/] X-2 もう1つ\n")
        t = T.link(T.tree(str(self.repo.root)))
        self.assertEqual(t["outside"], [{"path": ".worktrees/Req/TASK.md", "count": 1},
                                        {"path": ".worktrees/REQ-4-2/TASK.md", "count": 2}])
        out = T.text(t)
        self.assertTrue(out.endswith("- ⚠ 束の外の行 1 件（.worktrees/Req/TASK.md）\n"
                                     "- ⚠ 束の外の行 2 件（.worktrees/REQ-4-2/TASK.md）\n"), out)
        self.assertNotIn("REQ-9", out)
        self.assertNotIn("X-1", T.plan_text(T.plan(t), t["head"]))

    def test_branch_option_reads_one_branch(self):
        """branch を渡すと、その TASK.md のその枝の行だけ（図で束に入るとき）。"""
        t = T.tree(str(self.repo.root / ".worktrees/Req"), branch="REQ-4")
        self.assertEqual(([ln["no"] for ln in t["lines"]], t["branch"]), (["REQ-4-1", "REQ-4-2"], "REQ-4"))
        g = T.graph(T.tree(str(self.repo.root)))
        box = next(b for b in g["boxes"] if b["no"] == "REQ-4-2")
        self.assertEqual((box["enter"], box["branch"]), ("", ""))     # 子の TASK.md がない束には入れない
        self.repo.put(".worktrees/REQ-4-2", "# REQ-4-2: 比べる\n\n## タスク\n- [ ] REQ-4-2-1 候補を出す\n- [ ] REQ-9 ほかの依頼\n")
        g = T.graph(T.tree(str(self.repo.root)))
        box = next(b for b in g["boxes"] if b["no"] == "REQ-4-2")
        self.assertEqual((box["enter"], box["branch"]), (str(self.repo.root / ".worktrees/REQ-4-2"), "REQ-4-2"))
        sub = T.graph(T.tree(box["enter"], branch=box["branch"]))
        self.assertEqual([b["no"] for b in sub["boxes"] if b["lane"] == lane_of(sub, "self")["id"]], ["REQ-4-2-1"])

    def test_depth_and_loop(self):
        r = self.repo.root
        self.repo.put(".worktrees/REQ-4-2", "# 孫: 比べる\n\n## タスク\n- [ ] REQ-4-2-1 ひ孫へ → .worktrees/deep\n"
                                            "- [ ] REQ-4-2-2 上へ戻る → .\n")
        self.repo.put(".worktrees/deep", "# ひ孫: 深い\n\n## タスク\n- [ ] REQ-4-2-1-1 さらに → .worktrees/more\n")
        self.repo.put(".worktrees/more", "# 4段目\n\n## タスク\n- [ ] REQ-4-2-1-1-1 出ない\n")
        sub = T.tree(str(r))["lines"][1]["kids"]["lines"][1]
        self.assertEqual(sub["kids"]["path"], ".worktrees/REQ-4-2/TASK.md")
        deep, back = sub["kids"]["lines"]
        self.assertTrue(back.get("loop"))             # 統括の TASK.md へ戻る
        self.assertNotIn("kids", back)
        more = deep["kids"]["lines"][0]
        self.assertNotIn("kids", more)                # 3段まで
        self.assertNotIn("loop", more)
        self.assertNotIn("kids", T.tree(str(r), depth=1)["lines"][1]["kids"]["lines"][1])

    def test_tree_uses_given_rows(self):
        got = T.make_rows(ROOT)
        t = T.tree(str(self.repo.root / "elsewhere"), got=got, base=str(self.repo.root))
        self.assertEqual(t["lines"][1]["total"], 2)
        self.assertNotIn("kids", got["lines"][1])     # 渡したものは書き換えない


# ---- 進行中（views.md の2章「進行中」） ----
class DoingTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self).example()

    def test_doing_row_keeps_remaining_prerequisites_as_blockers(self):
        """[/] の行は、前提が残っていても 🔄。残る前提（見つからない番号も）はブロッカーに出す。計画には数えない。"""
        self.repo.put(".worktrees/S041", LINE.replace("- [/] SBI-041-2 ログイン画面を作る",
                                                      "- [/] SBI-041-2 ログイン画面を作る（前提: SBI-041-9, update）"))
        t = T.link(T.tree(str(self.repo.root)))
        s2 = by_no(t)["SBI-041-2"]
        self.assertEqual((s2["mark"], "state" in s2), ("doing", False))
        self.assertEqual(([(w["no"], w["found"]) for w in s2["waits"]], s2["human"]), ([("SBI-041-9", False)], ["update"]))
        p = T.plan(t)
        self.assertNotIn("SBI-041-2", [r["no"] for k in ("ready", "hum", "blocked") for r in p[k]])
        g = T.graph(T.tree(str(self.repo.root)))
        box = next(b for b in g["boxes"] if b["no"] == "SBI-041-2")
        self.assertEqual((box["kind"], [(w["tag"], w["found"]) for w in box["waits"]], box["human"]),
                         ("doing", [("S041-9", False)], ["update"]))

    def test_doing_row_after_unfinished_row_waits_in_order(self):
        """[/] の行も、順番の1つ前の未済の行をブロッカーに出す（🔄 のまま）。"""
        self.repo.put(".worktrees/S041", LINE.replace("- [ ] SBI-041-3", "- [/] SBI-041-3"))
        s3 = by_no(T.link(T.tree(str(self.repo.root))))["SBI-041-3"]
        self.assertEqual((s3["mark"], [(w["no"], w["seq"]) for w in s3["waits"]]), ("doing", [("SBI-041-2", True)]))


# ---- 人を待っている持ち手 ----
class WaitingTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self).example()

    def test_waiting_holder_bundle_is_human_even_with_marks(self):
        """人を待っている持ち手に任せた束は、枝に印があっても ✋（人待ち）。ほかの項目は束にそのまま足す。
        計画には束も枝の行も出す。"""
        w = [{"name": "Req-main", "state": "確認待ち"}]
        holders = {"Req-main": {"state": WAITING, "wait": w}}
        t = T.link(T.tree(str(self.repo.root), holders), None, holders)
        r4 = by_no(t)["REQ-4"]
        self.assertEqual((r4["mark"], r4["state"], r4["wait"]), ("wait", "hum", w))
        self.assertEqual(by_no(t)["REQ-3"]["mark"], "done")           # 済んだ束はそのまま
        self.assertIn("- ✋ REQ-4 通知メールの要求 0/2", T.text(t))
        p = T.plan(t, holders)
        self.assertEqual([r["no"] for r in p["hum"]], ["REQ-4"])
        self.assertEqual([r["no"] for r in p["ready"]], ["REQ-4-2"])
        g = T.graph(T.tree(str(self.repo.root), holders), holders)
        self.assertEqual(lane_of(g, "folder", "Req").get("state"), "hum")
        self.assertEqual(T.holder_state(holders, "Req-main"), (WAITING, {"wait": w}))
        self.assertEqual(T.holder_state(None, "x"), ("", {}))

    def test_wait_climbs_to_parent_bundle(self):
        """孫の持ち手が人を待っていれば、孫の束も、その上の束も ✋。見出しに「:」がなければフォルダ名で渡す。"""
        self.repo.put(".worktrees/REQ-4-2", "# 孫\n\n## タスク\n- [ ] REQ-4-2-1 葉\n")
        w = {"name": "部下", "state": "確認待ち"}
        t = T.tree(str(self.repo.root), {"REQ-4-2": {"state": WAITING, "wait": [w]}})
        r4 = t["lines"][1]
        self.assertEqual((r4["mark"], r4["wait"]), ("wait", [w]))
        self.assertEqual(r4["kids"]["lines"][1]["mark"], "wait")

    def test_unopened_bundle_still_uses_child_heading(self):
        """深さの上限で開かない束も、子の TASK.md の見出しの名前で持ち手の状態を引く。"""
        self.repo.put(".worktrees/REQ-4-2", "# Leaf-main: 葉\n\n## タスク\n- [ ] REQ-4-2-1 調べる\n")
        t = T.tree(str(self.repo.root), {"Leaf-main": WAITING}, depth=1)
        leaf = t["lines"][1]["kids"]["lines"][1]
        self.assertNotIn("kids", leaf)
        self.assertEqual((leaf["mark"], t["lines"][1]["mark"]), ("wait", "wait"))
        self.assertEqual(T.bundle_owner(leaf)["name"], "Leaf-main")

    def test_cli_waiting(self):
        """CLI の --waiting は持ち手の名前（くり返すか「,」「、」で区切る）。部品に渡すのと同じ結果。"""
        holders = {"Req-main": WAITING, "S041-main": WAITING}
        want = T.plan_text(T.plan(T.link(T.tree(str(self.repo.root), holders), None, holders), holders), "会員機能を作る")
        for args in (["--waiting", "Req-main,S041-main"], ["--waiting", "Req-main", "--waiting", "S041-main"],
                     ["--waiting", "Req-main、S041-main"]):
            r = run_cli("--plan", self.repo.root, *args)
            self.assertEqual((r.returncode, r.stdout.decode("utf-8")), (0, want), args)
        self.assertIn("- 人待ち: REQ-4 通知メールの要求（Req-main）", want)
        self.assertEqual(T.cli_holders(["b"]), {"b": WAITING})
        self.assertIsNone(T.cli_holders([" , "]))


# ---- 計画（views.md の3章） ----
class PlanTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self).example()

    def plan(self, holders=None):
        return T.plan(T.link(T.tree(str(self.repo.root), holders), None, holders), holders)

    def test_bundle_prerequisite_holds_branch(self):
        """束の前提で待つ束は、束の1行を数え、枝の未着手の行も同じ状態にする（計画には束の1行だけ）。"""
        self.repo.put("", ROOT.replace("- [ ] REQ-4 通知メールの要求", "- [ ] REQ-4 通知メールの要求（前提: MGR-2）")
                      .replace("\n## 申し送り", "- [ ] MGR-2 予算を決める\n\n## 申し送り"))
        self.repo.put(".worktrees/Req", REQ.replace("- [/] REQ-4-1", "- [ ] REQ-4-1"))
        t = T.link(T.tree(str(self.repo.root)))
        by = by_no(t)
        self.assertEqual((by["REQ-4"]["state"], by["REQ-4-1"]["state"], by["REQ-4-1"]["inherit"]), ("blocked", "blocked", True))
        p = T.plan(t)
        self.assertIn("REQ-4", [r["no"] for r in p["blocked"]])
        self.assertNotIn("REQ-4-1", [r["no"] for r in p["blocked"]])
        self.assertEqual([i["name"] for i in p["idle"]], ["Req-main", "REQ-4-2"])

    def test_bundle_without_branch_belongs_to_child(self):
        """枝に行のない束は、束の行を子の持ち手の仕事として数える（その持ち手は空きでない）。"""
        self.repo.put(".worktrees/S041", "# S041-main: ログイン機能\n\n## タスク\n- [x] SBI-040-1 前の依頼\n")
        self.repo.put("", ROOT.replace("（前提: REQ-3）", ""))
        p = self.plan()
        self.assertIn(("SBI-041", "S041-main"), [(r["no"], r["owner"]) for r in p["ready"]])
        self.assertNotIn("S041-main", [i["name"] for i in p["idle"]])

    def test_idle_is_not_from_sessions(self):
        """空きは、数えた仕事に 🔄 も始められるもない持ち手。渡した持ち手の状態では絞らない。"""
        self.repo.put(".worktrees/Req", REQ.replace("- [/] REQ-4-1", "- [x] REQ-4-1").replace(
            "- [ ] REQ-4-2 メール配信サービスを比べる（大きいので部下に任せる）→ .worktrees/REQ-4-2", "- [ ] REQ-4-2 比べる（前提: update）"))
        for holders in (None, {"S041-main": WAITING}):
            self.assertEqual([i["name"] for i in self.plan(holders)["idle"]], ["Req-main"])
        g = T.graph(T.tree(str(self.repo.root)))
        self.assertTrue(lane_of(g, "folder", "Req")["idle"])
        self.assertEqual(g["list"]["idle"], ["Req"])

    def test_missing_human_and_hash_prerequisites(self):
        self.repo.put("", root_plus("- [ ] MGR-2 見つからない（前提: SBI-099）", "- [ ] MGR-3 Issue で引く（前提: #77）"))
        self.repo.put(".worktrees/S041", LINE.replace("- [ ] SBI-041-3 パスワードの再設定", "- [ ] SBI-041-3 パスワードの再設定 #77"))
        by = by_no(T.link(T.tree(str(self.repo.root))))
        self.assertEqual([(w["no"], w["found"]) for w in by["MGR-2"]["waits"]], [("SBI-099", False), ("MGR-1", True)])
        self.assertEqual([(w["no"], w["owner"]) for w in by["MGR-3"]["waits"]][0], ("#77", "S041-main"))
        self.assertEqual((by["MGR-1"]["state"], by["MGR-1"]["human"]), ("blocked", ["人の返事"]))
        self.assertEqual(T.wait_label(by["MGR-2"]["waits"][0]), "SBI-099（見つからない）")

    def test_trailing_issues_still_read(self):
        for body, want in (("仕事 #26", ("仕事", ["26"])), ("仕事（#26）", ("仕事", ["26"])),
                           ("仕事 (#26, #27)", ("仕事", ["26", "27"])), ("仕事 #26、#27", ("仕事", ["26", "27"])),
                           ("仕事（前提: #5）", ("仕事（前提: #5）", [])), ("仕事（前提: X-1, #5）#9", ("仕事（前提: X-1, #5）", ["9"]))):
            self.assertEqual(T.split_issues(body), want, body)

    def test_plan_text_omits_empty_kinds(self):
        self.assertEqual(T.plan_text({"idle": [], "ready": [], "hum": [], "blocked": []}, "x"), "# 計画 — x\n- 計画に出すものはありません\n")


# ---- 順番 ----
SEQ_ROOT = """# Manager-main: 順番

## タスク
- [ ] D1-1 一
- [ ] REQ-5 見直し → ./req
- [ ] D1-2 二（前提: なし）
- [ ] D1-3 三
"""
SEQ_REQ = "# Req-main: 見直し\n\n## タスク\n- [ ] REQ-5-1 調べる\n- [ ] REQ-5-2 書く\n"


class SequenceTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self)
        self.repo.put("", SEQ_ROOT)
        self.repo.put("req", SEQ_REQ)

    def test_only_first_is_ready_rest_wait_for_previous(self):
        t = T.link(T.tree(str(self.repo.root)))
        by = by_no(t)
        self.assertEqual(by["D1-1"]["state"], "ready")
        for a, b in (("D1-1", "D1-2"), ("D1-2", "D1-3"), ("REQ-5-1", "REQ-5-2")):
            self.assertEqual((by[b]["state"], [(w["no"], w["seq"]) for w in by[b]["waits"]]), ("blocked", [(a, True)]), b)
        self.assertEqual((by["REQ-5"]["state"], by["REQ-5"]["waits"]), ("ready", []))      # 束は順番に入らない
        self.assertIn("- 待ち: D1-3 三（Manager-main） ← D1-2（Manager-main ⏳）", T.plan_text(T.plan(t)))
        g = T.graph(T.tree(str(self.repo.root)))
        self.assertFalse([e for e in g["edges"] if g["boxes"][e["from"]]["lane"] == g["boxes"][e["to"]]["lane"]])

    def test_written_prerequisite_and_sequence_are_one_wait(self):
        self.repo.put("req", "# Req-main: 下\n\n## タスク\n- [ ] REQ-5-1 画面の直し #12\n- [ ] REQ-5-2 次（前提: 12）\n")
        t = T.link(T.tree(str(self.repo.root / "req")))
        self.assertEqual([(w["no"], bool(w.get("seq"))) for w in t["lines"][1]["waits"]], [("12", False)])

    def test_plan_and_graph_count_the_same(self):
        for holders in (None, {"Req-main": WAITING}):
            g = T.graph(T.tree(str(self.repo.root), holders), holders)
            p = T.plan(T.link(T.tree(str(self.repo.root), holders), None, holders), holders)
            for k in ("ready", "hum", "blocked"):
                self.assertEqual(sorted(r["no"] for r in g["plan"][k]), sorted(r["no"] for r in p[k]), k)
            kinds = {b["no"]: b["kind"] for b in g["boxes"]}
            for k in ("ready", "hum", "blocked"):
                for r in p[k]:
                    if r["no"] in kinds:
                        self.assertEqual(kinds[r["no"]], k, r["no"])
            self.assertEqual([i["name"] for i in g["plan"]["idle"]], [i["name"] for i in p["idle"]])


# ---- 写した木（views.md の1章「写しの根」） ----
class SnapshotTest(unittest.TestCase):
    def copy(self, src, dst):
        for p in list(src.rglob("TASK.md")):
            q = dst / p.relative_to(src)
            q.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(p, q)

    def test_copied_tree_reads_from_its_own_root(self):
        """木ごと写したフォルダを渡すと、そこを根に束の相対のパスを数える（git の外でも、リポジトリの中の写しでも）。
        今の TASK.md が書き換わっていても、写しの全体像・計画・図が出る。"""
        repo = Repo(self).example()
        out = Repo(self, git=False)
        self.copy(repo.root, out.root)
        inside = repo.root / ".worktrees" / "snapshots" / "2026-11-25"
        self.copy(repo.root, inside)
        repo.put(".worktrees/Req", "# Req-main: 次の依頼\n\n## タスク\n- [ ] REQ-7-1 別の仕事\n")      # 今は書き換わった
        repo.put(".worktrees/S041", "# S041-main: ログイン機能\n\n## タスク\n")
        for snap in (out.root, inside):
            self.assertEqual(T.tree_base(str(snap)), str(snap))
            t = T.link(T.tree(str(snap)))
            self.assertEqual(T.text(t), TEXT, snap)
            self.assertEqual(T.plan_text(T.plan(t), t["head"]), PLAN)
            self.assertEqual(run_cli(snap).stdout.decode("utf-8"), TEXT)
            g = T.graph(T.tree(str(snap)))
            self.assertEqual(nos(g, lane_of(g, "folder", "Req")["boxes"]), ["REQ-4-1", "REQ-4-2"])
        self.assertNotEqual(T.text(T.link(T.tree(str(repo.root)))), TEXT)       # 今の木は今の中身
        self.assertEqual(T.tree_base(str(repo.root / ".worktrees/Req")), str(repo.root))     # 子のフォルダはリポジトリ直下から
        repo.put(".worktrees/loop", "# 輪: 戻る\n\n## タスク\n- [ ] L-1 戻る → .\n- [ ] L-2 上へ → ../Req\n")
        self.assertEqual(T.tree_base(str(repo.root / ".worktrees/loop")), str(repo.root))    # 自分や上を指す束では根にしない

    def test_root_option(self):
        """根を渡すこともできる（--root）。"""
        repo = Repo(self).example()
        snap = repo.root / "snap"
        self.copy(repo.root, snap)
        (snap / ".worktrees/S041/TASK.md").unlink()
        os.rmdir(snap / ".worktrees/S041")
        shutil.rmtree(snap / ".worktrees/Req")
        shutil.copytree(repo.root / ".worktrees/Req", snap / "Req2")
        (snap / "TASK.md").write_text(ROOT.replace(".worktrees/Req", "./Req2").replace(".worktrees/S041", "./nope"), encoding="utf-8")
        t = T.tree(str(snap), base=str(snap))
        self.assertEqual(t["lines"][0]["dir"], str(snap / "Req2"))
        r = run_cli(snap, "--root", snap)
        self.assertIn("- 🔄 REQ-4 通知メールの要求 0/2", r.stdout.decode("utf-8"))


# ---- 図（views.md の6章） ----
class GraphTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self).example()

    def graph(self, rel="", holders=None, **kw):
        return T.graph(T.tree(str(self.repo.root / rel) if rel else str(self.repo.root), holders), holders, **kw)

    def test_lanes_boxes_and_tags(self):
        """帯は自身 → 束のフォルダの順。同じフォルダの束は1本の帯に、それぞれの枝を子の TASK.md の順で。
        丸の番号は短い形だけ。"""
        g = self.graph()
        self.assertEqual([(L["kind"], L["name"]) for L in g["lanes"]], [("self", "Manager"), ("folder", "Req"), ("folder", "S041")])
        req = lane_of(g, "folder", "Req")
        self.assertEqual((nos(g, req["done"]), nos(g, req["boxes"])), (["REQ-3-1", "REQ-3-2"], ["REQ-4-1", "REQ-4-2"]))
        self.assertEqual(req["bundle"], "REQ-4 通知メールの要求")
        tag = {b["no"]: b["tag"] for b in g["boxes"]}
        self.assertEqual((tag["REQ-4-2"], tag["SBI-041-3"], tag["MGR-1"]), ("R4-2", "S041-3", "M1"))
        kind = {b["no"]: b["kind"] for b in g["boxes"]}
        self.assertEqual((kind["REQ-3-1"], kind["REQ-4-1"], kind["REQ-4-2"], kind["SBI-041-3"], kind["MGR-1"]),
                         ("done", "doing", "ready", "blocked", "blocked"))
        self.assertTrue(next(b for b in g["boxes"] if b["no"] == "REQ-4-2")["deleg"])      # 枝の中の束は枝分かれ
        json.dumps(g)

    def test_arrows_from_bundle_branches(self):
        """束の番号を待つ行は、その枝の済んでいない最後の丸から。済んだ枝の束を待つ行は、済んだ最後の丸から点の矢印。"""
        g = self.graph()
        name = lambda i: g["boxes"][i]["no"]      # noqa: E731
        edges = sorted((name(e["from"]), name(e["to"])) for e in g["edges"])
        self.assertIn(("SBI-041-3", "MGR-1"), edges)                 # SBI-041 を待つ: 枝の最後の済んでいない丸から
        self.assertIn(("REQ-3-2", "SBI-041-2"), edges)               # 済んだ REQ-3 は、その枝の最後の丸（点）から
        self.assertFalse(g["cycle"])

    def test_list_blockers_are_short_numbers(self):
        """一覧のブロッカーは番号の短い形（waits の tag）。見つからない番号は found が偽（画面は「?」を足す）。"""
        self.repo.put("", root_plus("- [ ] MGR-2 見つからない（前提: SBI-099）"))
        g = self.graph()
        m2 = next(b for b in g["boxes"] if b["no"] == "MGR-2")
        self.assertEqual([(w["tag"], w["found"]) for w in m2["waits"]], [("S099", False), ("M1", True)])
        js = T.DRAW_JS
        self.assertIn("let TG_LIST_WAIT_DETAIL=false;", js)
        self.assertIn("let TG_LIST_IDLE=false;", js)
        self.assertIn('(w.tag||w.no)+(w.found===false?"?":"")', js)
        self.assertIn('let TG_GO_LOOK="ring";', js)         # 押せる丸は外に点線の輪（既定）

    def test_issue_link_head(self):
        """Issue のリンクの頭は、呼び出す側が渡すか、根の git の設定の origin から（GitHub の形のときだけ）。"""
        self.repo.put("", ROOT.replace("- [ ] MGR-1 公開の時機を決める（前提: SBI-041, 人の返事）",
                                       "- [ ] MGR-1 公開の時機を決める（前提: SBI-041, 人の返事） #210"))
        self.assertEqual(self.graph()["issue_url"], "")
        (self.repo.root / ".git" / "config").write_text(
            '[core]\n\tbare = false\n[remote "upstream"]\n\turl = git@github.com:x/y.git\n'
            '[remote "origin"]\n\turl = git@github.com:owner/repo.git\n', encoding="utf-8")
        self.assertEqual(self.graph()["issue_url"], "https://github.com/owner/repo/issues/")
        self.assertEqual(self.graph(issue_url="https://example.test/i/")["issue_url"], "https://example.test/i/")
        self.assertEqual(self.graph(issue_url="")["issue_url"], "")
        for url, want in (("https://github.com/o/r", "https://github.com/o/r/issues/"),
                          ("https://user@github.com/o/r.git", "https://github.com/o/r/issues/"),
                          ("ssh://git@github.com/o/r.git", "https://github.com/o/r/issues/"),
                          ("https://gitlab.com/o/r.git", "")):
            (self.repo.root / ".git" / "config").write_text(f'[remote "origin"]\n\turl = {url}\n', encoding="utf-8")
            self.assertEqual(T.issue_base(str(self.repo.root)), want, url)
        self.assertIn("g.issue_url+n", T.DRAW_JS)
        r = run_cli(self.repo.root, "--html", "--issue-url", "https://example.test/i/")
        self.assertIn('"issue_url": "https://example.test/i/"', r.stdout.decode("utf-8"))

    def test_cycle_is_marked_and_columns_stay_finite(self):
        self.repo.put("", "# Manager-main: 全体\n\n## タスク\n- [ ] P-1 甲（前提: P-2）\n- [ ] P-2 乙（前提: P-1）\n- [ ] P-3 丙\n")
        g = self.graph()
        self.assertTrue(g["cycle"])
        self.assertEqual([e["cycle"] for e in g["edges"]].count(True), 1)

    def test_missing_goes_to_other_lane(self):
        self.repo.put("", root_plus("- [ ] MGR-2 見つからない（前提: SBI-099）"))
        g = self.graph()
        ob = g["boxes"][lane_of(g, "other")["boxes"][0]]
        self.assertEqual((ob["no"], ob["found"], ob["text"], ob["tag"]), ("SBI-099", False, "？", "S099"))

    def test_fold_switch(self):
        g = self.graph(fold=True)
        self.assertTrue(g["fold"])
        with mock.patch.object(T, "FOLD_DONE", True):
            self.assertTrue(self.graph()["fold"])

    def test_list_all_keeps_taskmd_order(self):
        g = self.graph()
        for r in g["list"]["lanes"]:
            self.assertEqual(sorted(r["all"]), sorted(r["rows"] + r["done"]))
        req = next(r for r in g["list"]["lanes"] if r["name"] == "Req")
        self.assertEqual(nos(g, req["all"]), ["REQ-3-1", "REQ-3-2", "REQ-4-1", "REQ-4-2"])

    def test_cli_html(self):
        """--html は1枚の HTML。データの中の </script> で切れない。読むだけ。"""
        self.repo.put("", root_plus("- [ ] MGR-9 危ない </script><b> 文字"))
        out = self.repo.root / "out" / "図.html"
        out.parent.mkdir()
        before = (self.repo.root / "TASK.md").read_bytes()
        r = run_cli(self.repo.root, "--html", "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        page = out.read_text(encoding="utf-8")
        self.assertTrue(page.startswith("<!doctype html>"))
        self.assertIn("function drawTaskGraph(", page)
        self.assertEqual(page.count("</script>"), 2)
        data = page.split("const G=", 1)[1].split(";const open=", 1)[0]
        self.assertEqual(json.loads(data.replace("<\\/", "</")), json.loads(json.dumps(self.graph())))
        self.assertEqual((self.repo.root / "TASK.md").read_bytes(), before)
        r = run_cli(self.repo.root / "nope", "--html")
        self.assertEqual(r.returncode, 0)
        self.assertIn("タスク一覧はありません", r.stdout.decode("utf-8"))


# ---- 持ち手の名前 ----
class HolderTest(unittest.TestCase):
    def test_owner_names(self):
        repo = Repo(self)
        repo.put("", "# 見出しだけ\n\n## タスク\n- [ ] A-1 甲 → ./s5\n")
        repo.put("s5", "# 見出しだけ\n\n## タスク\n- [ ] A-1-1 乙\n")
        self.assertEqual(T.holder_of(str(repo.root / "s5")), "s5")
        self.assertEqual(T.holder("x", "Req-main: 受け持ち"), "Req-main")
        self.assertEqual(T.holder("/a/b", "画面の直し（案: A）"), "b")
        self.assertEqual(T.lane_name("Req-main"), "Req")

    @unittest.skipIf(os.name == "nt", "リンクを作れないことがある")
    def test_folder_name_from_real_path(self):
        repo = Repo(self)
        repo.put("s5", "# 見出しだけ\n\n- [ ] 甲\n")
        link = repo.root.parent / (repo.root.name + "-link")
        os.symlink(repo.root / "s5", link)
        self.addCleanup(os.remove, link)
        self.assertEqual(T.holder_of(str(link)), "s5")


# ---- 行の説明（taskmd.md の2章「説明」） ----
class DescTest(unittest.TestCase):
    def test_reads_description_and_continuation(self):
        """行のすぐ下の1段字下げの「- 説明: …」と、さらに字下げした続きの行を、その行の説明として読む。"""
        r = T.make_rows("# Manager-main: 試し\n\n## タスク\n"
                        "- [ ] A-1 画面を直す #3\n  - 説明: メールで入れるように。\n    見本のアカウントで入れれば済み\n      - 箇条の続きも\n"
                        "- [x] A-2 説明なし\n"
                        "- [ ] A-3 ほかの箇条書き\n  - 細目は説明ではない\n  - 説明: すぐ下でないので読まない\n"
                        "- [/] A-4 全角のコロン → .worktrees/a\n\t- 説明：束の説明\n"
                        "- [ ] A-5 空行で終わる\n  - 説明: 一\n\n    二は続きでない\n")
        got = {ln["no"]: ln.get("desc") for ln in r["lines"]}
        self.assertEqual(got, {"A-1": "メールで入れるように。\n見本のアカウントで入れれば済み\n- 箇条の続きも", "A-2": None, "A-3": None,
                               "A-4": "束の説明", "A-5": "一"})
        self.assertEqual([ln["text"] for ln in r["lines"]][0], "A-1 画面を直す")      # 説明は文面に入らない
        self.assertEqual(r["lines"][3]["to"], ".worktrees/a")
        self.assertEqual(len(r["lines"]), 5)                                          # 説明の行と細目は行にならない
        # 「## タスク」のない TASK.md でも同じ。説明の行と同じ字下げの「- 説明:」は説明でない
        r = T.make_rows("# 部下\n- [ ] B-1 甲\n  - 説明: 甲の説明\n- [ ] B-2 乙\n- 説明: 字下げがない\n")
        self.assertEqual([(ln["no"], ln.get("desc")) for ln in r["lines"]], [("B-1", "甲の説明"), ("B-2", None)])
        # 説明の続きは、深い字下げのチェックボックスの行（細目）で終わる
        r = T.make_rows("## タスク\n- [ ] C-1 甲\n  - 説明: 一\n    続き\n    - [ ] C-1-1 細目\n      あと\n")
        self.assertEqual(r["lines"][0]["desc"], "一\n続き")

    def test_description_goes_to_graph_not_text_or_plan(self):
        """説明は図のデータ（丸の "desc"）に入れ、文字の全体像と計画には出さない（今と同じ字）。"""
        repo = Repo(self).example()
        repo.put("", ROOT.replace("- [ ] MGR-1 公開の時機を決める（前提: SBI-041, 人の返事）",
                                  "- [ ] MGR-1 公開の時機を決める（前提: SBI-041, 人の返事）\n  - 説明: 告知の日を決める。\n    人の返事で済み"))
        repo.put(".worktrees/S041", LINE.replace("- [ ] SBI-041-3 パスワードの再設定", "- [ ] SBI-041-3 パスワードの再設定\n  - 説明: 再設定のリンクを直す"))
        t = T.link(T.tree(str(repo.root)))
        self.assertEqual(T.text(t), TEXT)
        self.assertEqual(T.plan_text(T.plan(t), t["head"]), PLAN)
        self.assertEqual(run_cli(repo.root).stdout.decode("utf-8"), TEXT)
        g = T.graph(T.tree(str(repo.root)))
        desc = {b["no"]: b.get("desc") for b in g["boxes"]}
        self.assertEqual((desc["MGR-1"], desc["SBI-041-3"], desc["SBI-041-2"]), ("告知の日を決める。\n人の返事で済み", "再設定のリンクを直す", None))
        self.assertIn("taskgraph-name-desc", T.DRAW_JS)


class DateTest(unittest.TestCase):
    """日付: 「（着手: 11/24）」「（済: 11/25）」を読み、年は今日に近い年。文面に残し、前提や番号と読み違えない。"""

    def test_near_year(self):
        today = datetime.date(2026, 11, 22)
        self.assertEqual(T.near_date(11, 24, today), "2026-11-24")
        self.assertEqual(T.near_date(1, 5, today), "2027-01-05")
        self.assertEqual(T.near_date(3, 1, today), "2027-03-01")
        self.assertEqual(T.near_date(6, 1, today), "2026-06-01")
        self.assertEqual(T.near_date(12, 28, datetime.date(2027, 1, 3)), "2026-12-28")
        self.assertEqual(T.near_date(2, 30, today), "")
        self.assertEqual(T.near_date(2, 29, today), "")
        self.assertEqual(T.near_date(2, 29, datetime.date(2027, 11, 22)), "2028-02-29")

    def test_rows_keep_text_and_dates(self):
        repo = Repo(self)
        today = datetime.date.today()
        repo.put("", "# Manager-main: 日付\n\n## タスク\n"
                     "- [ ] SBI-010 着手だけ（着手: 11/24）\n"
                     "- [x] SBI-011 着手と済（前提: SBI-010）（着手: 11/24）（済: 11/25） #7\n"
                     "- [ ] SBI-012 半角と全角（前提:SBI-011）(着手：1/5)\n"
                     "- [ ] SBI-013 日付なし\n")
        t = T.link(T.tree(str(repo.root)))
        ln = t["lines"]
        y = lambda m, d: T.near_date(m, d, today)       # noqa: E731
        self.assertEqual((ln[0].get("start"), ln[0].get("finished")), (y(11, 24), None))
        self.assertEqual((ln[1]["start"], ln[1]["finished"], ln[1]["pre"], ln[1]["issues"]), (y(11, 24), y(11, 25), ["SBI-010"], ["7"]))
        self.assertEqual((ln[2]["start"], ln[2]["pre"], ln[2]["no"]), (y(1, 5), ["SBI-011"], "SBI-012"))
        self.assertNotIn("start", ln[3])
        self.assertEqual(ln[1]["text"], "SBI-011 着手と済（前提: SBI-010）（着手: 11/24）（済: 11/25）")
        self.assertEqual((ln[2]["state"], [w["no"] for w in ln[2]["waits"]]), ("blocked", ["SBI-010"]))
        p = T.plan(t)
        self.assertEqual([(r["no"], r.get("start")) for r in p["ready"]], [("SBI-010", y(11, 24))])
        box = next(b for b in T.graph(t)["boxes"] if b["no"] == "SBI-011")
        self.assertEqual((box["start"], box["finished"]), (y(11, 24), y(11, 25)))


# ---- 絞った一覧（--list。views.md の7章） ----
LIST_ROOT = """# Manager-main: 絞り込みの見本

## タスク
- [ ] MGR-1 公開の時機を決める（着手: 11/20）
- [ ] SBI-041 ログイン機能 → .worktrees/S041
- [ ] REQ-4 通知メールの要求 → .worktrees/Req
- [ ] HAR-90 ひな形の見直し（着手: 11/26） → .worktrees/Har #40
"""
LIST_LINE = """# S041-main: ログイン機能

## タスク
- [x] SBI-041-1 画面の流れを調べる（着手: 11/23）（済: 11/24）
- [/] SBI-041-2 ログイン画面を作る（着手: 11/24）
- [ ] SBI-041-3 パスワードの再設定（着手: 11/25）
  - 説明: 再設定のメールが届く
    新しいパスワードで入れる
- [ ] SBI-041-4 日付のない行
"""
LIST_REQ = """# Req-main: 要求

## タスク
- [x] REQ-4-1 通知の文面を詰める（済: 11/26）
- [/] REQ-4-3 日付のない進行中
- [ ] REQ-4-2 候補を比べる → .worktrees/Sub
"""
LIST_SUB = """# Sub-main: 候補

## タスク
- [ ] REQ-4-2-1 候補を出す（前提: 人の返事）（着手: 11/27）
"""
# views.md の7章の例と同じ字
LIST_MD = """| 状態 | 着手 | 済 | 番号 | 名前 | ブロッカー | Issue |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 🔄 | 11/24 |  | SBI-041-2 | ログイン画面を作る |  |  |
| ⏳ | 11/25 |  | SBI-041-3 | パスワードの再設定 | SBI-041-2 |  |

2 件（持ち手: S041-main と任せた先、期間: 11/25〜11/27 に掛かる行）
"""


class ListTest(unittest.TestCase):
    """絞った一覧: 入る行（自分でやる行と枝のない束の行）、持ち手と任せた先・その持ち手だけ、期間に掛かる行と予定だけ、
    遅れと進行中、日付のない行、状態と open、着手日の順、4つの形、7章の例と同じ字。文字の全体像と計画は変えない。"""

    def setUp(self):
        self.repo = Repo(self)
        self.repo.put("", LIST_ROOT)
        self.repo.put(".worktrees/S041", LIST_LINE)
        self.repo.put(".worktrees/Req", LIST_REQ)
        self.repo.put(".worktrees/Sub", LIST_SUB)
        self.y = lambda m, d: T.near_date(m, d)     # noqa: E731

    def got(self, **kw):
        t = T.tree(str(self.repo.root))
        return [r["ln"]["no"] for r in T.listing(t, **kw)]

    def span(self, a, b):
        return {"start": self.y(*a), "end": self.y(*b)}

    def test_rows_in_the_list(self):
        # 枝のある束（SBI-041・REQ-4・REQ-4-2）は出ず、枝の行で出る。枝のない束 HAR-90 は束の行で。着手日の順、日付のない行はあと
        self.assertEqual(self.got(), ["MGR-1", "SBI-041-1", "SBI-041-2", "SBI-041-3", "HAR-90", "REQ-4-2-1",
                                      "SBI-041-4", "REQ-4-1", "REQ-4-3"])
        t = T.tree(str(self.repo.root))
        r = {x["ln"]["no"]: x for x in T.listing(t)}
        self.assertEqual((r["HAR-90"]["holder"], r["HAR-90"]["path"]), ("Har", "TASK.md"))   # 束の行の持ち手は子
        self.assertEqual((r["REQ-4-2-1"]["holder"], r["REQ-4-2-1"]["path"]), ("Sub-main", ".worktrees/Sub/TASK.md"))
        self.assertEqual({k: r[k]["kind"] for k in ("SBI-041-1", "SBI-041-2", "SBI-041-3", "MGR-1", "REQ-4-2-1")},
                         {"SBI-041-1": "done", "SBI-041-2": "doing", "SBI-041-3": "blocked", "MGR-1": "ready", "REQ-4-2-1": "hum"})

    def test_who(self):
        self.assertEqual(self.got(who=["Req-main"]), ["REQ-4-2-1", "REQ-4-1", "REQ-4-3"])       # 任せた先も
        self.assertEqual(self.got(who=["Req"]), ["REQ-4-2-1", "REQ-4-1", "REQ-4-3"])            # -main は省いてよい
        self.assertEqual(self.got(who=["Req"], who_only=True), ["REQ-4-1", "REQ-4-3"])
        self.assertEqual(self.got(who=["Manager"], who_only=True), ["MGR-1", "HAR-90"])         # 書いた束の行も
        self.assertEqual(self.got(who=["Har"], who_only=True), ["HAR-90"])                      # 束の行の持ち手（子）
        self.assertEqual(len(self.got(who=["Manager-main"])), 9)
        self.assertEqual(self.got(who=["S041", "Sub"]), ["SBI-041-1", "SBI-041-2", "SBI-041-3", "REQ-4-2-1", "SBI-041-4"])
        self.assertEqual(self.got(who=["だれでもない"]), [])

    def test_period(self):
        # 掛かる行: 遅れ（MGR-1）、進行中は日付がなくても（REQ-4-3）、済んだ日が期間の中（REQ-4-1）。日付のない未着手と
        # 期間の前に済んだ行は入らない
        self.assertEqual(self.got(**self.span((11, 25), (11, 27))),
                         ["MGR-1", "SBI-041-2", "SBI-041-3", "HAR-90", "REQ-4-2-1", "REQ-4-1", "REQ-4-3"])
        self.assertEqual(self.got(planned_only=True, **self.span((11, 25), (11, 27))), ["SBI-041-3", "HAR-90", "REQ-4-2-1"])
        self.assertEqual(self.got(**self.span((11, 26), (11, 26))), ["MGR-1", "SBI-041-2", "SBI-041-3", "HAR-90", "REQ-4-1", "REQ-4-3"])
        self.assertEqual(self.got(planned_only=True, **self.span((11, 26), (11, 26))), ["HAR-90"])
        self.assertEqual(self.got(start=self.y(11, 24)), ["MGR-1", "SBI-041-1", "SBI-041-2", "SBI-041-3", "HAR-90", "REQ-4-2-1",
                                                          "REQ-4-1", "REQ-4-3"])
        self.assertEqual(self.got(end=self.y(11, 21), planned_only=True), ["MGR-1"])

    def test_state(self):
        self.assertEqual(self.got(states=["done"]), ["SBI-041-1", "REQ-4-1"])
        self.assertEqual(self.got(states=["doing"]), ["SBI-041-2", "REQ-4-3"])
        self.assertEqual(self.got(states=["human"]), ["REQ-4-2-1"])
        self.assertEqual(self.got(states=["ready", "blocked"]), ["MGR-1", "SBI-041-3", "HAR-90", "SBI-041-4"])
        self.assertEqual(self.got(states=["open"]), [n for n in self.got() if n not in ("SBI-041-1", "REQ-4-1")])
        self.assertEqual(self.got(states=["open"], who=["S041"], **self.span((11, 25), (11, 27))), ["SBI-041-2", "SBI-041-3"])

    def test_md_same_as_views(self):
        r = run_cli(self.repo.root, "--list", "--who", "S041-main", "--from", "11/25", "--to", "11/27")
        self.assertEqual((r.returncode, r.stdout.decode("utf-8")), (0, LIST_MD))
        r = run_cli(self.repo.root, "--list", "--state", "human,done", "--who", "Req", "--who-only")
        self.assertTrue(r.stdout.decode("utf-8").endswith("\n1 件（持ち手: Req だけ、状態: 人待ち・済み）\n"), r.stdout)
        r = run_cli(self.repo.root, "--list", "--from", "11/26", "--to", self.y(11, 26), "--planned-only")
        self.assertIn("| HAR-90 | ひな形の見直し |  | #40 |", r.stdout.decode("utf-8"))
        self.assertTrue(r.stdout.decode("utf-8").endswith("1 件（期間: 11/26 に予定の行）\n"))
        self.assertTrue(run_cli(self.repo.root, "--list").stdout.decode("utf-8").endswith("\n\n9 件\n"))

    def test_json(self):
        r = run_cli(self.repo.root, "--list", "--format", "json", "--who", "S041")
        out = r.stdout.decode("utf-8")
        self.assertEqual(len(out.strip().splitlines()), 2 + 4)        # 1件1行
        got = json.loads(out)
        self.assertEqual([x["no"] for x in got], ["SBI-041-1", "SBI-041-2", "SBI-041-3", "SBI-041-4"])
        self.assertEqual(got[2], {"no": "SBI-041-3", "name": "パスワードの再設定", "desc": "再設定のメールが届く\n新しいパスワードで入れる",
                                  "state": "blocked", "holder": "S041-main", "path": ".worktrees/S041/TASK.md",
                                  "start": self.y(11, 25), "finished": "", "blockers": ["SBI-041-2"], "human": [], "issues": []})
        h = json.loads(run_cli(self.repo.root, "--list", "--format", "json", "--state", "human").stdout)
        self.assertEqual((h[0]["state"], h[0]["human"]), ("human", ["人の返事"]))
        self.assertEqual(json.loads(run_cli(self.repo.root, "--list", "--format", "json", "--who", "x").stdout), [])

    def test_csv(self):
        import csv
        import io
        raw = run_cli(self.repo.root, "--list", "--format", "csv", "--who", "Har").stdout
        self.assertTrue(raw.startswith("\ufeff".encode("utf-8")))
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        self.assertEqual(rows, [["状態", "着手", "済", "番号", "名前", "ブロッカー", "Issue", "持ち手"],
                                ["⬜", self.y(11, 26), "", "HAR-90", "ひな形の見直し", "", "#40", "Har"]])
        out = self.repo.root / "a.csv"
        run_cli(self.repo.root, "--list", "--format", "csv", "-o", out)
        self.assertEqual(out.read_bytes().count(b"\r\n"), 10)

    def test_html(self):
        page = run_cli(self.repo.root, "--list", "--format", "html", "--who", "S041", "--issue-url", "https://x/issues/").stdout.decode("utf-8")
        self.assertIn("drawTaskList(", page)
        self.assertIn('"desc": "再設定のメールが届く\\n新しいパスワードで入れる"', page)
        self.assertIn('"blk": "S041-2"', page)          # ブロッカーは図の下の一覧と同じ短い形
        self.assertIn('"terms": "持ち手: S041 と任せた先"', page)
        self.assertIn("https://x/issues/", page)
        self.assertNotIn("drawTaskGraph(G", page)        # 帯と丸は描かない
        self.assertIn("tasklist-name-desc", T.LIST_JS)

    def test_text_and_plan_unchanged(self):
        repo = Repo(self).example()
        self.assertEqual(run_cli(repo.root, "--text").stdout.decode("utf-8"), TEXT)
        self.assertEqual(run_cli(repo.root, "--plan").stdout.decode("utf-8"), PLAN)

    def test_done_without_finished(self):
        # 済んだ日のない済んだ行は、予定だけでも入らない
        self.repo.put(".worktrees/Har", "# Har-main: h\n\n## タスク\n- [x] HAR-90-1 済の日なし（着手: 11/26）\n- [ ] HAR-90-2 予定（着手: 11/26）\n")
        self.assertEqual(self.got(planned_only=True, **self.span((11, 26), (11, 26))), ["HAR-90-2"])
        self.assertEqual(self.got(states=["done"], who=["Har"]), ["HAR-90-1"])

    def test_span_years(self):
        d = datetime.date(2026, 11, 25)
        self.assertEqual(T.list_span("5/1", "6/1", d), ("2027-05-01", "2027-06-01"))      # 片方ずつ近い年にしない
        self.assertEqual(T.list_span("12/28", "1/3", d), ("2026-12-28", "2027-01-03"))    # 年をまたぐ
        self.assertEqual(T.list_span("11/27", "11/25", d), ("2026-11-27", "2026-11-25"))  # 逆に書いたのは逆のまま（CLI がエラー）
        self.assertEqual(T.list_span("1/3", "2026-12-28", d), ("2026-01-03", "2026-12-28"))
        self.assertEqual(T.list_span("11/25", None, d), ("2026-11-25", None))
        self.assertRaises(ValueError, T.list_span, "2/30", None, d)

    def test_long_holder_name(self):
        self.repo.put(".worktrees/Har", "# VeryLongHolderNameOver20-main: h\n\n## タスク\n- [ ] HAR-90-1 長い名前\n")
        self.assertEqual(self.got(who=["VeryLongHolderNameOver20"]), ["HAR-90-1"])
        self.assertEqual(self.got(who=["VeryLongHolderNameOver20-main"]), ["HAR-90-1"])

    def test_narrow(self):
        self.assertIn('" narrow"', T.LIST_JS)

    def test_cli_errors(self):
        for args in (["--who", "S041"], ["--from", "11/25"], ["--format", "json"], ["--state", "done"], ["--list", "--plan"]):
            r = run_cli(self.repo.root, *args)
            self.assertEqual(r.returncode, 2, args)
        r = run_cli(self.repo.root, "--list", "--who", "S014,S041")
        self.assertEqual(r.returncode, 0)
        self.assertIn("S014", r.stderr.decode("utf-8"))
        self.assertNotIn("S041", r.stderr.decode("utf-8"))
        self.assertEqual(run_cli(self.repo.root, "--list", "--who", "Req,Manager").stderr, b"")     # 束だけの持ち手も
        for args in (["--state", "later"], ["--from", "13/40"], ["--from", "11/27", "--to", "11/25"]):
            r = run_cli(self.repo.root, "--list", *args)
            self.assertEqual(r.returncode, 2, args)
        r = run_cli(self.repo.root / "nothing", "--list")
        self.assertEqual((r.returncode, r.stdout.decode("utf-8").splitlines()[-1]), (0, "0 件"))


if __name__ == "__main__":
    unittest.main()
