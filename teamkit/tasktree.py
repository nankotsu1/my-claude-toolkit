#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TASK.md のツリーの部品（型は teamkit/docs/taskmd.md）。

TASK.md を読み（rows）、束の行（`→ <子のフォルダ>`）をたどって入れ子にし（tree）、文字で書き出す（text）。
全体像を見せる道具（スキルや画面）は、どれもこの部品で TASK.md を読む。読むだけで何も書き換えない。
GitHub も読まない。標準ライブラリだけ。頼るのは TASK.md の型（最初の見出し、`## タスク`、束の `→`、前提と日付の
書き方）だけ。

    python3 teamkit/tasktree.py [TASK.md かフォルダ] [--text | --plan | --html | --list] [--all]
                                [--waiting 持ち手 ...] [--root フォルダ] [--issue-url URL] [-o ファイル]
                                [--format md|json|csv|html] [--who 持ち手 ...] [--who-only]
                                [--from 日] [--to 日] [--planned-only] [--state 状態 ...]

既定は --text（Markdown の箇条書き）。済んだ行は「済 n 件」に畳む（--all で全部）。
--plan は作業計画: 前提をツリー全体でたどって、空き・始められる・人待ち・待ちを書き出す。
--html は作業計画の図: 持ち手ごとの帯の図を、1枚の HTML（図のデータと DRAW_JS を埋め込む）で書き出す。
--list は絞った一覧: ツリー全体の行を、持ち手（--who・--who-only）・期間（--from・--to・--planned-only）・状態（--state）で
絞り、--format の形（md 表・json・csv・html）で書き出す（teamkit/docs/views.md の7章）。
束は、子の TASK.md の枝（番号が束と同じか、束の番号に「-」で続く行）だけを指す（teamkit/docs/views.md の2章）。
--waiting は人を待っている持ち手の名前（くり返すか「,」で区切る）。渡さなければ TASK.md だけで求める。
--root は束の相対のパスを数える根（スプリントの写しのフォルダなど。既定はリポジトリ直下、git の外なら渡したフォルダ）。
--issue-url は Issue のリンクの頭（既定は根の git の設定の origin から。GitHub の形のときだけ）。
"""
import argparse
import copy
import datetime
import html
import json
import os
import re
import sys
import threading

VERSION = 5                     # 読み方の版。読んだ結果を控える道具が、版が違えば読み直すのに使う（読み方を変えたら上げる）
LINES_MAX = 80                  # 1つの読む所から読む行の上限
SIZE_MAX = 500_000              # これより大きい TASK.md は読まない
DEPTH = 3                       # 束をたどる深さ（子・孫・ひ孫）

GENERIC = {"task", "tasks", "task.md", "todo", "タスク"}
HOLDER_HEAD = r"([^:：\s（()）「」]{1,30})[:：]"     # 見出しの「<持ち手の名前>:」（名前は空白・括弧を含まない。「画面の直し（案: A）」は名前にしない）
HEADING = re.compile(r"\s{0,3}#{1,3}\s+(.+?)\s*#*\s*$")
HEADING_12 = re.compile(r"\s{0,3}#{1,2}\s")                 # 節の終わり（次の「# 」「## 」の見出し）
TASKS_HEAD = re.compile(r"\s{0,3}##\s+タスク\s*(?:[（(:：].*)?$")   # 「## タスク」（「## タスク（段階1）」も。「## タスクの説明」は別）
FENCE = re.compile(r"\s{0,3}(`{3,}|~{3,})")
ITEM = re.compile(r"(\s*)(?:[-*+]|\d+[.)])\s+\[([ xX/])\]\s*(.*?)\s*$")     # 印は [ ]・[/]（着手）・[x]
DESC = re.compile(r"(\s+)[-*+]\s+説明\s*[:：]\s*(.*?)\s*$")     # 行のすぐ下の「  - 説明: …」（taskmd.md の2章）
# 行の終わりの Issue: #26、#26、#27、（#26）、(#26, #27)。括弧は対で読む（「（前提: #5）」の「#5）」を Issue と取らない）
TRAILING_ISSUES = re.compile(r"(?:[\s,、]*(?:#\d{1,5}|[（(]\s*#\d{1,5}(?:\s*[,、]\s*#\d{1,5})*\s*[)）]))+\s*$")
ISSUE = re.compile(r"(?<![\w&#])#(\d{1,5})\b")
BUNDLE = re.compile(r"^(.*?)\s*(?:→|->)\s*(\S+)\s*$")       # 束の行の終わりの「→ <フォルダ>」（「->」も）
DATE = re.compile(r"[（(]\s*(着手|済)\s*[:：]\s*(\d{1,2})\s*/\s*(\d{1,2})\s*[）)]")     # 「（着手: 11/24）」「（済: 11/25）」
DATE_KEYS = {"着手": "start", "済": "finished"}
PRE = re.compile(r"[（(]\s*前提\s*[:：]\s*([^）)]*)[）)]")    # 行の中の「（前提: SBI-041-1, REQ-2）」
# 番号の形（teamkit/docs/taskmd.md の3章）: 英大文字で始まる語 - 英大文字と数字、- で続けて子の番号。
# 小文字は入れない（「S041-main」「Re-run」を番号と読まない）
NO_FORM = r"[A-Z][A-Z0-9]*-[A-Z0-9]+(?:-[A-Z0-9]+)*"
UNIT_ID = re.compile(r"(?<![0-9A-Za-z-])(" + NO_FORM + r")(?![0-9A-Za-z-])")     # SBI-041、SBI-041-2、REQ-1、I-3-1
LEAD_NO = re.compile(r"\s*(?:" + UNIT_ID.pattern + r"|(\d{1,5})(?![0-9A-Za-z-]))")
MARKS = {"done": "✅", "doing": "🔄", "todo": "⬜", "wait": "✋"}
STATE_MARKS = {"ready": "⬜", "hum": "✋", "blocked": "⏳"}      # 文字では色と濃さが使えないので、未着手の3つを字で分ける
UNIT_NO = re.compile(r"(?:" + NO_FORM + r"|#?\d{1,5})")        # 番号の形（#5 も。これ以外の語は人の作業）
WAITING = "waiting"     # 持ち手の状態（呼び出す側が渡す）: 人を待っている


def mark_of(ch):
    """チェックボックスの印の字から行の印: x → done、/ → doing（着手）、ほか → todo。"""
    return "done" if ch in "xX" else "doing" if ch == "/" else "todo"


def numbered(ln):
    """数える行か: 先頭に番号の形（teamkit/docs/taskmd.md の2章）がある。番号のない行は数えない。"""
    return bool(UNIT_ID.fullmatch(ln.get("no") or ""))


def in_branch(no, bundle_no):
    """番号 no が束 bundle_no の枝か: 同じ番号か、束の番号に「-」で続く。"""
    return bool(no) and bool(bundle_no) and (no == bundle_no or no.startswith(bundle_no + "-"))


def find_no(p, by_no, by_issue):
    """前提に書いた番号 p を索引で引く。#5 は Issue の番号だけ、ほかは先頭の番号、次に Issue の番号。"""
    if p.startswith("#"):
        return by_issue.get(p[1:])
    return by_no.get(p, by_issue.get(p))


def snippet(text, n=70):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def issue_refs(text):
    out = []
    for n in ISSUE.findall(text or ""):
        if n not in out:
            out.append(n)
    return out


def plain_lines(text):
    """コードブロックの外の行（開いたのと同じ印、つまり同じ文字で同じ長さ以上でだけ閉じる）。"""
    fence = ""
    for raw in text.splitlines():
        f = FENCE.match(raw)
        if fence:
            if f and f.group(1)[0] == fence[0] and len(f.group(1)) >= len(fence) and not raw.strip().strip(fence[0]):
                fence = ""
            continue
        if f:
            fence = f.group(1)
            continue
        yield raw


def split_issues(body):
    """行の最後の Issue 番号（#26、（#26）、(#26, #27)）を外して (文面, [番号])。"""
    tail = TRAILING_ISSUES.search(body)
    if not tail:
        return body, []
    return body[:tail.start()].strip(), issue_refs(tail.group(0))


def lead_no(text):
    """行の先頭の番号（作業単位の番号か Issue の番号。前提に書く名前）か ""。"""
    m = LEAD_NO.match(text or "")
    return (m.group(1) or m.group(2)) if m else ""


def read_pre(text):
    """行の中の前提。書いていなければ None、「なし」なら []、ほかは番号の並び。"""
    m = PRE.search(text or "")
    return split_pre(m.group(1)) if m else None


def split_pre(cell):
    """前提の欄（「SBI-041-1, REQ-2」「なし」）を並びにする。空なら None（書いていない）。"""
    cell = (cell or "").strip()
    if not cell or re.fullmatch(r"[-—–ー]+", cell):
        return None
    if cell == "なし":
        return []
    return [p.strip() for p in re.split(r"[,、，・]", cell) if p.strip()]     # #5 は # のまま（Issue の番号で引く）


def near_date(month, day, today=None):
    """月と日から、今日に近い年の日付（"YYYY-MM-DD"）。去年・今年・来年のうち今日にいちばん近いもの
    （teamkit/docs/taskmd.md の2章。年は書かない）。ない日付（2/30 など）は ""。"""
    today = today or datetime.date.today()
    best = None
    for y in (today.year - 1, today.year, today.year + 1):
        try:
            d = datetime.date(y, month, day)
        except ValueError:
            continue
        if best is None or abs((d - today).days) < abs((best - today).days):
            best = d
    return best.isoformat() if best else ""


def read_dates(text, today=None):
    """行の中の日付（着手予定日・済んだ日）。{"start": "YYYY-MM-DD", "finished": …} の書いてあるものだけ。
    文面からは外さない（見せ方は文面のまま。前倒し・遅れの判定と印は作らない）。"""
    out = {}
    for m in DATE.finditer(text or ""):
        got = near_date(int(m.group(2)), int(m.group(3)), today)
        if got:
            out[DATE_KEYS[m.group(1)]] = got
    return out


def is_folder(word):
    """束のフォルダらしいか: 区切り（/ か \\）を含むか、「.」「~」で始まる。「旧 → 新」「a -> b」の後ろの語は束にしない。"""
    return bool(word) and ("/" in word or "\\" in word or word[0] in ".~")


def width(indent):
    return len(indent.expandtabs(4))


def checkboxes(lines):
    """行の並び lines のチェックボックスの行 [(字下げの幅, 印, 中身, 説明)]。説明は、その行のすぐ下の、より深い
    字下げの「- 説明: …」と、それよりさらに深い字下げの続きの行（空行か浅い行で終わる。続きは改行でつなぐ）。
    すぐ下がほかの箇条書きなら、説明はない（""）。"""
    lines = list(lines)
    out = []
    for i, raw in enumerate(lines):
        m = ITEM.match(raw)
        if not m:
            continue
        w, desc = width(m.group(1)), ""
        d = DESC.match(lines[i + 1]) if i + 1 < len(lines) else None
        if d and width(d.group(1)) > w:
            dw, parts = width(d.group(1)), [d.group(2)]
            for nxt in lines[i + 2:]:
                ind = len(nxt) - len(nxt.lstrip())
                if not nxt.strip() or width(nxt[:ind]) <= dw or ITEM.match(nxt):
                    break           # 空行・浅い行・チェックボックスの行（深い字下げの細目）で終わる
                parts.append(nxt.strip())
            desc = "\n".join(x for x in parts if x)
        out.append((w, mark_of(m.group(2)), m.group(3), desc))
    return out


def item(body, mark, desc=""):
    """チェックボックスの行の中身を1行の dict にする。束の `→ <フォルダ>` と行の最後の Issue 番号は文面から外す。
    desc（行の下の説明）があれば "desc" に入れる（文面には入れない）。"""
    name, issues = split_issues(body)
    to = ""
    m = BUNDLE.match(name)
    if m and is_folder(m.group(2)):
        name, to = m.group(1).strip(), m.group(2)
        name, more = split_issues(name)         # 「文面 #12 → フォルダ」
        issues = more + [n for n in issues if n not in more]
    ln = {"text": snippet(name, 200), "mark": mark, "issues": issues, "no": lead_no(name)}
    pre = read_pre(name)
    if pre is not None:
        ln["pre"] = pre
    ln.update(read_dates(name))     # "start"（着手予定日）・"finished"（済んだ日）。書いた行にだけ
    if to:
        ln["to"] = to
    if desc:
        ln["desc"] = desc[:2000]
    return ln


def section_items(text, head, shallowest=False):
    """見出し head（「## …」）の節のチェックボックスの行。節は次の「# 」「## 」の見出しの手前まで。
    読むのは節の最初のチェックボックスと同じ字下げの行だけ（shallowest なら、節の中でいちばん浅い字下げ）。
    節がなければ None、あれば [(印 done・doing・todo, 中身, 説明)]。"""
    found, inside, body = None, False, []
    for raw in plain_lines(text):
        if HEADING_12.match(raw):
            if inside:
                break
            if head.match(raw):
                inside, found = True, []
            continue
        if inside:
            body.append(raw)
    if found is None:
        return None
    rows = checkboxes(body)
    if not rows:
        return found
    if shallowest:
        want = min(r[0] for r in rows)
        return [(mk, b, d) for w, mk, b, d in rows if w == want][:LINES_MAX]
    # 最初のチェックボックスより深い字下げ（細目）は数えない。浅いものは読む（字下げをそろえ忘れた行も落とさない）
    return [(mk, b, d) for w, mk, b, d in rows if w <= rows[0][0]][:LINES_MAX]


def heading(text):
    """最初の見出し（型どおりの「タスク」などは飛ばす）。なければ ""。"""
    for line in text.splitlines():
        m = HEADING.match(line)
        if m and m.group(1).strip().lower() not in GENERIC:
            return m.group(1).strip()
    return ""


def make_rows(text):
    """TASK.md の文章から、タスクの並び。「## タスク」の節があればその行、なければ全体のチェックボックスのうち、
    いちばん浅い字下げのもの。返り値 {"source": "tasks" | "boxes", "title", "head", "lines"}、読めなければ None。
    行は {"text", "mark", "issues", "no"} と、あれば "pre"（前提）・"start"・"finished"（着手予定日・済んだ日。
    "YYYY-MM-DD"。年は今日に近い年。文面にも残る）・"to"（束のフォルダ。書いたまま）・"desc"（行の下の説明）・"kids"。"""
    title = heading(text)
    # head: 見出しの中身（「:」の前の持ち手の名前を除く）
    out = {"title": title, "head": re.sub(HOLDER_HEAD + r"\s*", "", title, count=1) if colon_name(title) else title}
    got = section_items(text, TASKS_HEAD)
    if got is not None:
        return dict(out, source="tasks", lines=[item(body, mk, d) for mk, body, d in got])
    items = checkboxes(plain_lines(text))
    top = min((w for w, *_ in items), default=0)
    found = [item(body, mk, d) for w, mk, body, d in items if w == top]
    return dict(out, source="boxes", lines=found[:LINES_MAX]) if found else None


def repo_base(directory):
    """リポジトリ直下（worktree の中でも、もとのリポジトリ）。git を呼ばずに .git をたどる
    （.git がファイルなら、その gitdir と commondir を読む）。git の外なら directory のまま。"""
    d = os.path.abspath(directory)
    while True:
        dot = os.path.join(d, ".git")
        if os.path.isdir(dot):
            return d
        if os.path.isfile(dot):
            try:
                with open(dot, encoding="utf-8") as f:
                    gitdir = f.read().strip()
                gitdir = gitdir[len("gitdir:"):].strip() if gitdir.startswith("gitdir:") else ""
                gitdir = os.path.normpath(os.path.join(d, gitdir))
                common = gitdir
                cfile = os.path.join(gitdir, "commondir")
                if os.path.isfile(cfile):
                    with open(cfile, encoding="utf-8") as f:
                        common = os.path.normpath(os.path.join(gitdir, f.read().strip()))
                return os.path.dirname(common) if os.path.basename(common) == ".git" else d
            except (OSError, ValueError):
                return d
        up = os.path.dirname(d)
        if up == d:
            return os.path.abspath(directory)
        d = up


def task_path(path):
    """TASK.md かフォルダ（フォルダなら直下の TASK.md）のパス。"""
    return path if os.path.basename(path) == "TASK.md" else os.path.join(path, "TASK.md")


def bundle_dir(to, where, base=None):
    """束に書いたフォルダの絶対パス。相対は、ツリーの根 base（なければ TASK.md のあるフォルダ where の
    リポジトリ直下）から数える。"""
    to = os.path.expanduser(to)
    if os.path.basename(to) == "TASK.md":
        to = os.path.dirname(to) or "."
    return os.path.normpath(to if os.path.isabs(to) else os.path.join(base or repo_base(where), to))


def tree_base(path):
    """ツリーの根（束の相対のパスを数える所。teamkit/docs/views.md の1章）: ふだんはリポジトリ直下。渡した TASK.md の
    束の相対のパスが、その TASK.md のフォルダから数えて、その下の TASK.md のある所を指すなら（スプリントの写しのように、
    木ごと写したフォルダ）、そのフォルダ。git の外でもそのフォルダ。"""
    p = os.path.abspath(task_path(path))
    here = os.path.dirname(p)
    base = repo_base(here)
    if base == here:
        return base
    r = rows(p)
    for ln in (r or {}).get("lines") or []:
        to = os.path.expanduser(ln.get("to") or "")
        if not to or os.path.isabs(to):
            continue
        d = os.path.normpath(os.path.join(here, to))
        # 自分より下の別のフォルダだけを見る（「→ .」や「../x」で、子のフォルダを根にしない）
        if d.startswith(here + os.sep) and os.path.isfile(task_path(d)):
            return here
    return base


_CACHE = {}     # TASK.md のパス -> ((更新時刻, 大きさ), 読んだ結果)
_CACHE_LOCK = threading.Lock()      # 呼び出す側が複数のスレッドから呼んでもよいように（画面のサーバーなど）


def rows(path):
    """TASK.md（かフォルダ）のタスクの並び（make_rows）。束の行には "dir"（絶対パス）を足す。
    ファイルがない・大きすぎる・読める所がなければ None。更新時刻と大きさが同じ間は読み直さない。
    返すのは控えの写し（呼ぶ側が書き換えてよい）。"""
    path = os.path.abspath(task_path(path))
    try:
        st = os.stat(path)
    except OSError:
        with _CACHE_LOCK:
            _CACHE.pop(path, None)
        return None
    key = (st.st_mtime_ns, st.st_size, datetime.date.today())     # 日付の年は今日から決めるので、日が変われば読み直す
    with _CACHE_LOCK:
        hit = _CACHE.get(path)
    if hit and hit[0] == key:
        return copy.deepcopy(hit[1])
    got = None
    if st.st_size <= SIZE_MAX:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                got = make_rows(f.read())
        except OSError:
            got = None
    if got is not None:
        where = os.path.dirname(path)
        for ln in got["lines"]:
            if ln.get("to"):
                ln["dir"] = bundle_dir(ln["to"], where)
    with _CACHE_LOCK:
        _CACHE[path] = (key, got)
        if len(_CACHE) > 256:
            _CACHE.pop(next(iter(_CACHE)))
    return copy.deepcopy(got)


def count(ln):
    """束の行に、枝の行の済んだ数・全体・いま 🔄 の行の番号を足す（済んだ束も。枝はスプリントの終わりまで残る）。"""
    kids = (ln.get("kids") or {}).get("lines") or []
    ln["done"] = sum(k["mark"] == "done" for k in kids)
    ln["total"] = len(kids)
    ln["now"] = "・".join(k.get("no") or snippet(k["text"], 20) for k in kids if k["mark"] == "doing")


def show_path(to):
    return to if os.path.basename(to) == "TASK.md" else to.rstrip("/\\") + "/TASK.md"


def holder_state(holders, name):
    """持ち手の状態 holders（持ち手の名前 -> WAITING、または {"state": …, ほかの項目}）から、name の
    (状態, ほかの項目)。渡していない・名前がなければ ("", {})。ほかの項目は、その持ち手に任せた束の行にそのまま足す
    （呼び出す側が見せ方に使う。"wait" の並びは、子の束から親の束へ合わせて上げる）。"""
    v = (holders or {}).get(name) if name else None
    if isinstance(v, dict):
        return (v.get("state") or ""), {k: x for k, x in v.items() if k != "state"}
    return (v or ""), {}


def tree(path, holders=None, depth=DEPTH, got=None, _seen=None, _level=0, base=None, branch=None):
    """束をたどって、子の TASK.md の枝を入れ子にしたもの（rows の形に、束の "kids" と数え）。
    数えるのは番号のある行だけ（番号のない行は外して、その数を "unnumbered" に。teamkit/docs/views.md の2章）。
    束の kids は {"path"（束に書いたフォルダ + /TASK.md）, "source", "title", "head", "lines"（枝の行だけ。子の
    TASK.md の順）}。枝は、子の TASK.md の行のうち、番号が束と同じか束の番号に「-」で続く行。同じフォルダを指す束が
    2つ以上あれば、子の行はいちばん長く合う番号の束1つにだけ入る。子の行には子の TASK.md の中の順 "ord" を足す。
    子の TASK.md がないか読める所がなければ lines は空。depth の段まで開き、たどった先がすでにたどった TASK.md なら
    "loop" を真にして開かない。base: 束の相対のパスを数える根（なければ tree_base。写しのフォルダを渡すと、そこを根に）。
    branch: 番号を渡すと、この TASK.md のその枝の行だけを読む（図で束に入るとき）。
    束の印は枝から求める（束の行に書いた印は読まない）: 枝に行があって全部済みなら done、枝に [/] か [x] があれば
    doing、ほかは todo。子の持ち手が人を待っていれば（holders。holder_state）、済んでいない束は wait（✋）。枝に ✋ の
    行（孫の束）があれば束も wait にし、"wait" を合わせる。got: path の rows を呼ぶ側が持っていれば、それを使う。
    TASK.md がなければ None。"""
    me = os.path.realpath(task_path(path))
    r = copy.deepcopy(got) if got is not None else rows(path)
    if r is None:
        return None
    r["path"] = os.path.abspath(task_path(path))        # link が、根の TASK.md を探すのに使う
    base = os.path.abspath(base) if base else tree_base(path)
    r["base"] = base
    keep = [ln for ln in r["lines"] if numbered(ln) and (not branch or in_branch(ln["no"], branch))]
    r["unnumbered"] = 0 if branch else sum(1 for ln in r["lines"] if not numbered(ln))
    r["lines"] = keep
    if branch:
        r["branch"] = branch
    where = os.path.dirname(r["path"])
    for ln in r["lines"]:
        if ln.get("to"):
            ln["dir"] = bundle_dir(ln["to"], where, base)
    seen = (_seen or frozenset()) | {me}
    subs = {}           # 子の TASK.md の実パス -> その tree（同じフォルダの束は1回だけ読み、行を枝に分ける）
    for ln in r["lines"]:
        d = ln.get("dir")
        if not d:
            continue
        child = os.path.realpath(task_path(d))
        if child in seen:
            ln["loop"] = True
        elif _level < depth:
            if child not in subs:
                subs[child] = tree(d, holders, depth, None, seen, _level + 1, base)
            sub = subs[child]
            ln["kids"] = {"path": show_path(ln["to"]), "source": (sub or {}).get("source", ""),
                          "title": (sub or {}).get("title", ""), "head": (sub or {}).get("head", ""), "lines": []}
    for child, sub in subs.items():
        mine = [ln for ln in r["lines"] if ln.get("kids") is not None and not ln.get("loop")
                and os.path.realpath(task_path(ln["dir"])) == child]
        for i, k in enumerate((sub or {}).get("lines") or []):
            k["ord"] = i
            owner = max((ln for ln in mine if in_branch(k["no"], ln["no"])), key=lambda ln: len(ln["no"]), default=None)
            if owner is not None:
                owner["kids"]["lines"].append(k)
    for ln in r["lines"]:
        if not ln.get("dir"):
            continue
        kl = (ln.get("kids") or {}).get("lines") or []
        if kl and all(k["mark"] == "done" for k in kl):
            ln["mark"] = "done"
        else:
            ln["mark"] = "doing" if any(k["mark"] in ("doing", "done") for k in kl) else "todo"
            state, more = holder_state(holders, bundle_name(ln))
            ln.update(more)
            up = [k for k in kl if k["mark"] == "wait"]
            if up:                          # 子の束の ✋ は親の束にも上がる。待っているものの並びも合わせる
                state = WAITING
                waits = list(ln.get("wait") or [])
                for k in up:
                    waits += [w for w in k.get("wait") or [] if w not in waits]
                if waits:
                    ln["wait"] = waits
            if state == WAITING:
                ln["mark"] = "wait"
        if "kids" in ln:
            count(ln)
    return r


FOLD_DONE = False               # 表示の設定: 作業計画の図で、済んだ仕事を帯の左の「済 n」にまとめる（偽なら名前のない点）
NAME_MAX = 20                   # 持ち手の名前の長さ（約20字。図の帯の名前の欄に収まる長さ）
LANE_HOLDER = True              # 表示の設定: 図の帯の名前を持ち手の名前にする（偽なら束の行の文面）


def walk(t, owner=None):
    """ツリーの行を、上から順に、束の子へ入りながら (行, 持ち手) で返す。持ち手は {"name", "dir", "path"}
    （その行が書いてある TASK.md の持ち主。束のフォルダ。いちばん上の TASK.md は dir が TASK.md のフォルダ）。"""
    for ln, who, _ in units(t, owner):
        yield ln, who


def units(t, owner=None, _ctx="unit", _open=None):
    """walk と同じ順で (行, 持ち手, 数え方) を返す。数え方は "unit"（数える行）か "closed"（済んだ束の枝の中）。
    束の行は、その行が書いてある所の数え方。束は自分の枝だけを持つので、同じフォルダを指す束も別に数える。
    束の行の種類は、済んでいない束 "first"・済んだ束 "closed"・たどった先に戻る "loop"
    （束の行の id -> 種類を _open["kind"] に入れる。bundle_kinds）。"""
    if owner is None:
        d = os.path.dirname(t["path"]) if t.get("path") else ""
        owner = {"name": holder(d, t.get("title") or ""), "dir": d, "path": t.get("path") or ""}
    opened = _open if _open is not None else {"kind": {}}
    for ln in t.get("lines") or []:
        yield ln, owner, _ctx
        kids = ln.get("kids")
        d = ln.get("dir") or ""
        if not d:
            continue
        kind = "loop" if ln.get("loop") else "closed" if ln["mark"] == "done" else "first"
        opened["kind"][id(ln)] = kind
        if kids is None or ln.get("loop"):
            continue
        sub = "closed" if kind == "closed" or _ctx == "closed" else "unit"
        who = {"name": holder(d, kids.get("title") or ""), "dir": d, "path": kids.get("path") or ""}
        yield from units(kids, who, sub, opened)


def bundle_kinds(t):
    """(行, 持ち手, 数え方) の並びと、束の行の id -> "first"・"closed"・"loop"。"""
    opened = {"kind": {}}
    got = list(units(t, None, "unit", opened))
    return got, opened["kind"]


def colon_name(title):
    """見出し「# <持ち手の名前>: <中身>」の「:」の前（teamkit/docs/taskmd.md の2章）。「:」のない見出しは ""。"""
    m = re.match(HOLDER_HEAD, (title or "").strip())
    return m.group(1) if m else ""


def holder(d, title=""):
    """持ち手の名前（teamkit/docs/taskmd.md の2章）: TASK.md の見出し title の「:」の前。決まらないとき（見出しがない、
    「:」がない、TASK.md がない）は、TASK.md のあるフォルダ d の名前。約20字で切る。"""
    # フォルダ名は実パスから（リンクや書き方の違う同じフォルダを、同じ名前にする）
    name = colon_name(title) or (os.path.basename(os.path.realpath(d.rstrip("/\\")) or d) if d else "")
    return snippet(name, NAME_MAX)


def holder_of(path):
    """TASK.md（かフォルダ）の持ち手の名前（holder）。呼び出す側が、持ち手の状態を名前で渡すのに使う。"""
    p = os.path.abspath(task_path(path))
    r = rows(p)
    return holder(os.path.dirname(p), (r or {}).get("title") or "")


def bundle_name(ln):
    """束の行の子の持ち手の名前。子を開いていれば子の見出しから、開いていない（深さの上限・循環）ときは子の TASK.md を読む。"""
    d = ln.get("dir") or ""
    kids = ln.get("kids")
    if kids is not None:
        return holder(d, kids.get("title") or "")
    return holder_of(d) if d else ""


def bundle_owner(ln):
    """束の行の持ち手（束の行の仕事は子の持ち手のもの。子がまだ行を書いていなくても。teamkit/docs/taskmd.md の2章）。"""
    kids = ln.get("kids") or {}
    d = ln.get("dir") or ""
    return {"name": bundle_name(ln), "dir": d, "path": kids.get("path") or show_path(ln.get("to") or d)}


def link(t, root=None, holders=None):
    """前提をツリー全体でたどって、行に state・waits・human を足す。t を書き換えて返す。
    state（未着手の行と、枝に印のない束だけ）: "blocked"（前提に書いた番号の行か順番の1つ前の行がまだ済んでいない。
    ツリーにない番号も）→ "hum"（前提に人の作業がある。人を待っている持ち手の束＝ mark が wait もここ）→ "ready"。
    🔄 の行（[/] の行と、枝に印のある束）には state を付けず、残る前提を waits・human に出す（ブロッカー。views.md の2章）。
    waits: 待つ行 [{"no"（書いた番号）, "found", "text", "owner", "mark"（相手の今の印: done・doing・ready・hum・blocked・todo）}]。
    済んだ相手は入れない。human: 前提のうち番号の形でない語（人の作業）。
    順番は、同じ TASK.md で自分でやる行（束でない行）の1つ前の未済の行で、waits に "seq" を真にして入れる（owner は
    同じ持ち手。図の矢印にはしない）。束は順番に入らない。書いた前提と同じ行なら1つだけ。
    番号の索引は root（根の TASK.md のツリー）の全部の行から。root がなければ、t の根（tree の "base"）の TASK.md を
    tree で読み、それもなければ t。先頭の番号、次に Issue の番号で引き、同じ番号はたどった順で最初のもの。root から
    届かない t の行も、root のあとに索引に入れる。済んだ束の枝の中には state を付けない。
    済んでいない束は、束の行に書いた前提で着手不可・人待ちなら、枝の未着手の行に同じ state・waits・human を写し
    "inherit" を真にする（束には "held"）。そうでなく枝に済んでいない行があれば、未着手の束の state を枝から求める
    （ready → hum → blocked。waits・human は枝のものを合わせる）。"""
    if root is None and t.get("path"):
        base = t.get("base") or tree_base(t["path"])
        top = task_path(base)
        if os.path.abspath(top) != t["path"] and os.path.isfile(top):
            root = tree(top, holders, base=base)
    trees = [x for x in (root, t) if x is not None]
    if root is None:
        root = t
    by_no, by_issue = {}, {}
    walked = {}
    for x in [root] + [x for x in trees if x is not root]:      # root が先。root から届かない t の行も引ける
        walked[id(x)] = bundle_kinds(x)
        for ln, owner, ctx in walked[id(x)][0]:
            hit = (ln, bundle_owner(ln) if ln.get("dir") else owner, False)
            for idx, k in ([(by_no, ln["no"])] if ln.get("no") else []) + [(by_issue, n) for n in ln.get("issues") or []]:
                if k not in idx:
                    idx[k] = hit
    prev = {}           # 自分でやる行の id -> 同じ TASK.md の1つ前の未済の自分でやる行（順番の前提）
    for x in trees:
        stack = [x]
        while stack:
            node = stack.pop()
            last = None
            for ln in node.get("lines") or []:
                if ln.get("dir"):       # 任せた行（束）は順番に入らない
                    if ln.get("kids") is not None and not ln.get("loop"):
                        stack.append(ln["kids"])
                    continue
                if last is not None:
                    prev[id(ln)] = last
                if ln["mark"] != "done":
                    last = ln
    todo = []
    for x in trees:
        for ln, owner, ctx in walked[id(x)][0]:
            if ctx != "unit" or ln["mark"] == "done" or "state" in ln or "waits" in ln:
                continue
            waits, human, found = [], [], []
            for p in ln.get("pre") or []:
                if not UNIT_NO.fullmatch(p):
                    human.append(p)
                    continue
                hit = find_no(p, by_no, by_issue)
                if hit is None:
                    waits.append({"no": p, "found": False, "text": "", "owner": "", "mark": ""})
                elif hit[0]["mark"] != "done":
                    waits.append({"no": p, "found": True, "text": hit[0]["text"], "owner": hit[1]["name"], "mark": ""})
                    found.append((waits[-1], hit[0]))
            before = prev.get(id(ln))
            if before is not None and not any(same_row(row, before) for _, row in found):
                # 順番: 1つ前の未済の行を待つ。矢印にはしない（seq）。書いた前提と同じ行なら1つだけ
                no = before.get("no") or ("#" + before["issues"][0] if before.get("issues")
                                          else snippet(DATE.sub("", label(before)).strip(), 20))
                waits.append({"no": no, "found": True, "text": before["text"], "owner": owner["name"], "mark": "", "seq": True})
                found.append((waits[-1], before))
            ln["waits"], ln["human"] = waits, human
            todo.append(found)
            if ln["mark"] == "doing":
                continue                # 🔄 は印のまま。残る前提はブロッカーに出す
            ln["state"] = "blocked" if waits else "hum" if human or ln["mark"] == "wait" else "ready"
            ln["held"] = bool([w for w in waits if not w.get("seq")] or human)    # 書いた前提で待つ（束なら枝へ写す）
    for x in trees:
        got, kinds = walked[id(x)]
        # 上から: 未着手の束が束の前提で待つなら、枝の未着手の行も同じ状態（孫へも続く）
        for ln, _, ctx in got:
            if (ctx == "unit" and kinds.get(id(ln)) == "first" and ln.get("kids") and ln.get("held")
                    and ln.get("state") in ("blocked", "hum")):
                for k in ln["kids"].get("lines") or []:
                    if k["mark"] in ("todo", "wait"):
                        k.update(state=ln["state"], waits=list(ln["waits"]), human=list(ln["human"]),     # 待つ相手の印はあとで同じ dict に入る
                                 inherit=True, held=True)
    for x in trees:
        got, kinds = walked[id(x)]
        bundles = [ln for ln, _, ctx in got if ctx == "unit" and kinds.get(id(ln)) == "first" and ln.get("kids")]
        for ln in reversed(bundles):    # 下から: 未着手の束の四角は、枝の済んでいない行から
            if not ln.get("state") or ln.get("held") or ln["mark"] == "wait":
                continue
            rest = [k for k in ln["kids"].get("lines") or [] if k["mark"] != "done"]
            states = {k.get("state") for k in rest}
            pick = next((s for s in ("ready", "hum", "blocked") if s in states), None)
            if not pick:
                continue
            waits, human = [], []
            for k in rest:      # 枝の中の順番の待ちは、子の中の話なので束には出さない
                waits += [w for w in k.get("waits") or [] if not w.get("seq") and w["no"] not in {v["no"] for v in waits}]
                human += [h for h in k.get("human") or [] if h not in human]
            ln.update(state=pick, waits=waits, human=human)
    for found in todo:                  # 待つ相手の今の印（相手の state が決まってから）
        for w, row in found:
            w["mark"] = row.get("state") or row["mark"]
    t["linked"] = True
    return t


def same_row(a, b):
    """同じ TASK.md の行か（root と t で別に読んだ写しどうしも）。書いた前提と順番の待ちを1つにまとめるのに使う。"""
    return a is b or (a["text"] == b["text"] and (a.get("no") or "") == (b.get("no") or "")
                      and (a.get("issues") or []) == (b.get("issues") or []))


def plan(t, holders=None):
    """作業計画。t は link 済み（なければ link する）。
    {"idle": [持ち手], "ready": [行], "hum": [行], "blocked": [行]}。行は {"text", "no", "issues", "owner", "dir", "state",
    "waits", "human"}。持ち手は {"name", "dir", "path"}。数える単位は teamkit/docs/views.md の3章: 済んだ束は数えない。
    済んでいない束は、束の前提で待つなら束の1行（枝の写した行は出さない）、枝に行があれば枝の行（束の行は出さない）、
    枝に行がなければ束の行（持ち手は子）。人を待っている持ち手の束は、束の行も枝の行も出す。
    idle: 束のフォルダのうち、その持ち手の仕事（上で数えるものと、写した行）に 🔄 も始められるもないもの。
    セッションが動いているかでは決めない。道具は、勧めも送りもしない。"""
    if not t.get("linked"):
        link(t, None, holders)
    out = {"idle": [], "ready": [], "hum": [], "blocked": []}
    got, kinds = bundle_kinds(t)
    folders = {}        # 実パス -> {"name", "dir", "path", "work"}

    def put(ln, owner):
        state = ln.get("state")
        if state:
            out[state].append({"text": ln["text"], "no": ln.get("no") or "", "issues": ln.get("issues") or [],
                               "owner": owner["name"], "dir": owner["dir"], "state": state,
                               "waits": ln.get("waits") or [], "human": ln.get("human") or [],
                               **{k: ln[k] for k in ("start", "finished") if ln.get(k)}})

    def folder(d, ln, kids):
        key = os.path.realpath(d)
        if key not in folders:
            folders[key] = {"name": bundle_name(ln), "dir": d, "path": (kids or {}).get("path") or show_path(ln.get("to") or d), "work": []}
        return folders[key]

    top = got[0][1] if got else None
    for ln, owner, ctx in got:
        if ctx != "unit":
            continue
        d = ln.get("dir")
        kind = kinds.get(id(ln)) if d else None
        if kind is None:            # 束でない行（自身の行か、束の枝の行）
            if not ln.get("inherit"):
                put(ln, owner)
            if owner is not top:
                f = folders.get(os.path.realpath(owner["dir"]))
                if f is not None:
                    f["work"].append(ln)
            continue
        if owner is not top and kind != "closed":       # 束の行は、その行を書いた持ち手の仕事でもある（さらに子へ任せた 🔄 など）
            g = folders.get(os.path.realpath(owner["dir"]))
            if g is not None:
                g["work"].append(ln)
        if kind == "loop":
            put(ln, bundle_owner(ln))
            continue
        f = folder(d, ln, ln.get("kids"))
        who = {"name": f["name"], "dir": f["dir"]}     # 束の行の仕事は子の持ち手のもの（teamkit/docs/taskmd.md の2章）
        if kind == "closed":
            continue
        kl = (ln.get("kids") or {}).get("lines") or []
        if ln.get("held") or not kl:
            # 束の前提で待つ束と、枝に行のない束は、束の行を1つの仕事に
            if not ln.get("inherit"):
                put(ln, who)
            f["work"].append(ln)
        elif ln["mark"] == "wait":
            put(ln, who)            # 人を待っている持ち手: 束も出し、枝の行もそのまま数える
        # 枝に行があれば枝の行を数える（上の「束でない行」で）
    for key, f in folders.items():
        if any(r["mark"] == "doing" or r.get("state") == "ready" for r in f["work"]):
            continue
        out["idle"].append({"name": f["name"], "dir": f["dir"], "path": f["path"]})
    return out


def graph(t, holders=None, fold=None, issue_url=None):
    """作業計画の図のデータ。t は tree の結果（link 済みでなければ link する）。JSON にできる dict を返す:
    {"title", "path", "lanes", "boxes", "edges", "seq", "fold", "cycle", "plan", "summary", "list", "issue_url"}。
    lanes: 持ち手ごとの帯 [{"id", "name", "dir", "path", "kind"（"self" t の持ち手自身・"folder" 束のフォルダ・
    "other" ほかの所）, "boxes"（済んでいない箱の id。左から）, "done"（済んだ箱の id。TASK.md の順）, "idle"（空き）}]。
    いちばん上に、待つ行が図にないときだけ「ほかの所」、次に自身（束でない行。なければ出さない）、続いて束のフォルダごと
    （TASK.md の順。同じフォルダの束は1本）。帯の名前は持ち手の名前（LANE_HOLDER が偽なら束の行の文面）。
    boxes: [{"id", "lane", "col"（済んだ箱は -1）, "no", "tag"（番号の短い形）, "text"（前提を外した文面）, "full", "mark",
    "state", "issues", "done"・"total"・"now"（束の箱）, "waits"（"tag" つき）, "human", "wait"（人を待っているもの。
    holders のほかの項目）, "enter"（押すと入る束の子のフォルダ）, "branch"（入る枝の番号）, "found"（ほかの所の箱）}]。
    束の枝に行があれば、枝の行を1つずつ箱にする（済んだ束も）。同じフォルダの束の枝は、子の TASK.md の順に並べ、
    枝に行のない束の箱はそのあと。枝の中の束（孫への束）は "deleg" を真にし、押すと孫の枝に入る。
    col: 同じ帯のすぐ前の箱の列と、待つ箱の列のうち、いちばん右の列の次（0 から）。
    edges: 書いた前提だけ [{"from"（待つ箱）, "to"（待っている箱）, "cycle"}]。循環した矢印は cycle を真にし、列の計算から外す。
    前提に書いた番号が図の中の済んだ箱なら、その点から済んでいない箱へも矢印を引く（fold では引かない）。
    枝を開いた束の番号を待つ行は、その枝の済んでいない最後の箱から（済んだ枝なら最後の箱から）。枝を開いた束の行の前提は、
    その枝の済んでいない最初の箱へ。
    seq: 帯の中の順番の線 [{"from", "to"}]。fold: 済んだ箱を帯の左の「済 n」にまとめるか（なければ FOLD_DONE）。
    plan は plan(t, holders)、summary はその文字（plan_text の見出しを除く行）。帯の idle: plan の空きと同じ。
    issue_url: Issue のリンクの頭（番号を足すと Issue のページ）。None なら根の git の設定の origin から（issue_base）。"""
    if not t.get("linked"):
        link(t, None, holders)
    fold = FOLD_DONE if fold is None else bool(fold)
    p = plan(t, holders)
    idle = {os.path.realpath(i["dir"]) for i in p["idle"]}
    lanes, boxes, pres = [], [], {}
    me = {"id": 0, "name": lane_name(holder(os.path.dirname(t.get("path") or ""), t.get("title") or "")) or "（自身）",
          "dir": os.path.dirname(t.get("path") or ""), "path": t.get("path") or "", "kind": "self",
          "boxes": [], "done": [], "idle": False}
    lanes.append(me)
    by_dir, bundles, opened_no, opened_done, wants = {}, {}, {}, {}, []

    def add(lane, ln, **more):
        b = {"id": len(boxes), "lane": lane["id"], "col": -1, "no": ln.get("no") or "", "text": DATE.sub("", label(ln)).strip(),
             "full": ln.get("text") or "", "mark": ln["mark"], "state": ln.get("state") or "",
             "issues": ln.get("issues") or [], "waits": [dict(w, tag=short_no(w["no"])) for w in ln.get("waits") or []],
             "human": ln.get("human") or [], "wait": ln.get("wait") or []}
        for k in ("done", "total", "now", "start", "finished", "desc"):     # 日付と説明は書いた行にだけ
            if k in ln:
                b[k] = ln[k]
        if ln.get("dir") and b["no"]:
            # 束の待つものは枝から合わせたもの。自分の枝の番号への待ちは図の外の話なので矢印にしない
            b["waits"] = [w for w in b["waits"] if not w["no"].startswith(b["no"] + "-")]
        b.update(more)
        boxes.append(b)
        pres[b["id"]] = [x for x in ln.get("pre") or [] if UNIT_NO.fullmatch(x)]
        lane["done" if ln["mark"] == "done" else "boxes"].append(b["id"])
        return b

    def entry(ln):
        """押すと入る先: 枝に行のある束（循環でない）の子のフォルダと枝の番号。"""
        kk = ln.get("kids")
        if ln.get("dir") and kk is not None and kk.get("lines") and not ln.get("loop"):
            return {"enter": ln["dir"], "branch": ln.get("no") or ""}
        return {"enter": "", "branch": ""}

    for ln in t.get("lines") or []:
        d = ln.get("dir")
        if not d:
            add(me, ln, **entry(ln))
            continue
        key = os.path.realpath(d)
        kids = ln.get("kids")
        lane = by_dir.get(key)
        if lane is None:
            lane = {"id": len(lanes), "name": "", "dir": d, "path": (kids or {}).get("path") or show_path(ln["to"]),
                    "kind": "folder", "boxes": [], "done": [], "idle": False}
            lanes.append(lane)
            by_dir[key] = lane
            bundles[lane["id"]] = []
        bundles[lane["id"]].append(ln)
    for lane in lanes[1:]:
        bl = bundles[lane["id"]]
        opened = [ln for ln in bl if (ln.get("kids") or {}).get("lines") and not ln.get("loop")]
        rows_ = sorted(((k, ln) for ln in opened for k in ln["kids"]["lines"]), key=lambda x: x[0].get("ord", 0))
        made = {}
        for k, ln in rows_:
            # 枝の中の束（部下への束）は枝分かれ（順番の線につながない。子が自分でやる行ではない）
            made.setdefault(id(ln), []).append(add(lane, k, deleg=bool(k.get("dir")), **entry(k)))
        for ln in bl:
            if id(ln) not in made:
                add(lane, ln, **entry(ln))      # 枝に行のない束は、束の行を1つの丸に（plan も1つの仕事に数える）
                continue
            got = made[id(ln)]
            undone = [b for b in got if b["mark"] != "done"]
            mine = [b for b in undone if not b.get("deleg")] or undone
            if ln.get("no"):
                if mine:
                    opened_no[ln["no"]] = mine[-1]["id"]    # この束の番号を待つ行は、この束の枝の最後の丸から
                else:
                    opened_done[ln["no"]] = got[-1]["id"]
            pre = [x for x in ln.get("pre") or [] if UNIT_NO.fullmatch(x)]
            if pre and undone:
                wants.append((undone[0]["id"], pre))        # 束の行の前提は、枝の済んでいない最初の丸へ
        pick = next((b for b in bl if b["mark"] != "done"), bl[-1])
        lane["bundle"] = label(pick)
        # 帯の名前は計画の持ち手の名前（plan と同じ決め方: そのフォルダを指す最初の束の子の見出し）
        lane["name"] = (lane_name(bundle_name(bl[0]))
                        if LANE_HOLDER else lane["bundle"])
        if pick["mark"] != "done" and pick.get("state") in ("blocked", "hum"):
            # 枝を開いた束の行の前提は、箱にならないので帯に持たせる（帯の名前のツールチップ）
            lane.update(state=pick["state"], waits=pick.get("waits") or [], human=pick.get("human") or [])
        lane["idle"] = os.path.realpath(lane["dir"]) in idle     # 計画の空きと同じ

    # 待つ行を箱に結ぶ（先頭の番号、次に Issue の番号。図の中で最初のもの）。図にない行は「ほかの所」の帯の点線の箱
    by_no, by_issue = {}, {}
    for b in boxes:
        if b["mark"] == "done":         # 待つ相手は済んでいない行だけ（済んだ箱は列に置かないので、矢印を引けない）
            continue
        if b["no"]:
            by_no.setdefault(b["no"], b["id"])
        for n in b["issues"]:
            by_issue.setdefault(n, b["id"])
    other = {"id": len(lanes), "name": "ほかの所", "dir": "", "path": "", "kind": "other",
             "boxes": [], "done": [], "idle": False}
    outside, edges = {}, []
    for no, bid in opened_no.items():       # 子の行を開いた束の番号は、その子の行の済んでいない最後の丸
        by_no.setdefault(no, bid)
    for b in list(boxes):
        for w in b["waits"]:
            if w.get("seq"):            # 順番の待ちは矢印にしない（順番の線で見える）
                continue
            src = find_no(w["no"], by_no, by_issue)
            if src is None:
                src = outside.get(w["no"])
            if src is None:
                ob = {"id": len(boxes), "lane": other["id"], "col": -1, "no": w["no"],
                      "text": snippet(w.get("text") or "", 40) if w["found"] else "？", "full": w.get("text") or "",
                      "mark": w.get("mark") if w.get("mark") in MARKS else "todo",
                      "state": w.get("mark") if w.get("mark") in STATE_MARKS else "", "issues": [], "waits": [],
                      "human": [], "wait": [], "found": w["found"], "owner": w.get("owner") or ""}
                boxes.append(ob)
                other["boxes"].append(ob["id"])
                outside[w["no"]] = src = ob["id"]
            if src != b["id"] and {"from": src, "to": b["id"], "cycle": False} not in edges:     # #5 と I-3-1 が同じ行でも1本
                edges.append({"from": src, "to": b["id"], "cycle": False})
    if not fold:                        # 前提の相手が済んだ箱なら、その点から
        dno, dissue = {}, {}
        for b in boxes:
            if b["mark"] == "done":
                if b["no"]:
                    dno.setdefault(b["no"], b["id"])
                for n in b["issues"]:
                    dissue.setdefault(n, b["id"])
        seen = {(e["from"], e["to"]) for e in edges}
        for no, bid in opened_done.items():     # 済んだ枝の束の番号は、その枝の最後の丸
            dno.setdefault(no, bid)
        # 枝を開いた束の行の前提は、枝の済んでいない最初の丸へ（束の行は丸にならない。上の wants）
        wants = [(b["id"], pres.get(b["id"]) or []) for b in boxes if b["mark"] != "done" and b["lane"] != other["id"]] + wants
        for to, pre in wants:
            for x in pre:
                src = find_no(x, dno, dissue)
                if src is None or find_no(x, by_no, by_issue) is not None or src == to or (src, to) in seen:
                    continue            # 済んでいない相手は waits の矢印（上）。済んだ相手だけ点から
                seen.add((src, to))
                edges.append({"from": src, "to": to, "cycle": False})
    if other["boxes"]:
        lanes.insert(0, other)
    if not me["boxes"] and not me["done"]:
        lanes.remove(me)

    # 列: 同じ帯のすぐ前の箱と、待つ箱の列のうち、いちばん右の列の次。帯の中の順番は崩さず、
    # 輪を作る矢印（待っている箱から待つ箱へ、順番と矢印でたどり着ける）を循環として外して数える
    nxt = {b["id"]: [] for b in boxes}
    for lane in lanes:
        for a, b in zip(lane["boxes"], lane["boxes"][1:]):
            nxt[a].append(b)

    def reach(a, z):
        stack, seen = [a], {a}
        while stack:
            i = stack.pop()
            if i == z:
                return True
            for j in nxt[i]:
                if j not in seen:
                    seen.add(j)
                    stack.append(j)
        return False

    for e in edges:
        if boxes[e["from"]]["mark"] == "done":     # 済んだ点からの矢印は列に使わない（点は列に置かない）
            continue
        if reach(e["to"], e["from"]):
            e["cycle"] = True
        else:
            nxt[e["from"]].append(e["to"])
    before = {}
    for a, js in nxt.items():
        for j in js:
            before.setdefault(j, []).append(a)
    col = longest([i for lane in lanes for i in lane["boxes"]], before)
    for i, c in col.items():
        boxes[i]["col"] = c
    # 丸の列: 済んだ仕事も丸にするので、帯の中は済んだ丸 → 済んでいない丸の順で、すぐ前の丸の次と、
    # 待つ丸（済んだ点からの矢印も）の次のうち右のほう。循環の矢印は上と同じく外す
    # （「ほかの所」の丸どうしは順番がないので、つながない）
    # 任せた行（deleg。部下への束）は順番につながず、前提だけで決める。前提がなければ帯の済んだ丸の次
    after = {b["id"]: [] for b in boxes}
    for lane in lanes:
        if lane["kind"] == "other":
            continue
        order = [i for i in lane["done"] + lane["boxes"] if not boxes[i].get("deleg")]
        for a, b in zip(order, order[1:]):
            after[b].append(a)
        for i in lane["boxes"]:
            if boxes[i].get("deleg") and lane["done"]:
                after[i].append(lane["done"][-1])
    for e in edges:
        if not e["cycle"]:
            after[e["to"]].append(e["from"])
    at = longest([i for lane in lanes for i in lane["done"] + lane["boxes"]], after)
    for b in boxes:
        b["at"] = at.get(b["id"], 0)
        b["kind"] = kind_of(b)
    for lane in lanes:                  # 同じ帯で同じ列の丸は縦にずらす（枝。"lift" 0, 1, 2…）
        used = {}
        for i in lane["done"] + lane["boxes"]:
            b = boxes[i]
            # 任せた行はいつも1段下（順番の線の上に乗らないように。枝に見える）
            b["lift"] = max(used.get(b["at"], 0), 1 if b.get("deleg") else 0)
            used[b["at"]] = b["lift"] + 1
        lane["lifts"] = max(used.values(), default=1)
    for i, lane in enumerate(lanes):
        lane["id"] = i
        for bi in lane["boxes"] + lane["done"]:
            boxes[bi]["lane"] = i
    seq = []
    for lane in lanes:
        if lane["kind"] == "other":
            continue
        order = [i for i in (lane["boxes"] if fold else lane["done"] + lane["boxes"]) if not boxes[i].get("deleg")]
        seq += [{"from": a, "to": b} for a, b in zip(order, order[1:])]
    tags(lanes, boxes)
    return {"title": t.get("head") or t.get("title") or "", "path": t.get("path") or "", "lanes": lanes, "boxes": boxes,
            "edges": edges, "seq": seq, "fold": fold, "cycle": any(e["cycle"] for e in edges), "plan": p,
            "summary": plan_text(p).splitlines()[1:], "list": glist(lanes, p),
            "issue_url": issue_base(t.get("base") or tree_base(t.get("path") or ".")) if issue_url is None else issue_url}


def longest(starts, before):
    """列を決める: どの id も、before（id -> 前の id の並び。輪はない）のいちばん右の次（なければ 0）。
    starts の順に、前から決める（深い連なりでも再帰しない）。{id: 列}。"""
    col = {}
    for start in starts:
        stack = [start]
        while stack:
            i = stack[-1]
            if i in col:
                stack.pop()
                continue
            todo = [a for a in before.get(i, []) if a not in col]
            if todo:
                stack.extend(todo)
                continue
            col[i] = max((col[a] for a in before.get(i, [])), default=-1) + 1
            stack.pop()
    return col


def kind_of(b):
    """箱の状態のアイコンの種類: done・doing・ready・hum・blocked。未着手で state がなければ、
    人を待っている束（✋）は hum、ほかは ready。"""
    if b["mark"] in ("done", "doing"):
        return b["mark"]
    if b.get("state") in STATE_MARKS:
        return b["state"]
    return "hum" if b["mark"] == "wait" else "ready"


def short_no(no):
    """番号の短い形（teamkit/docs/taskmd.md の3章）: 頭の語の1文字目と残り（SBI-041-2 → S041-2、REQ-2 → R2、
    I-3-1 → I3-1）。番号の形でないもの（数字だけなど）はそのまま。"""
    head, _, rest = (no or "").partition("-")
    if not rest or not head:
        return no or ""
    return head[0] + rest


def lane_name(name):
    """図の帯の名前: 持ち手の名前から末尾の -main を省く（Req-main → Req。帯の名前の欄を狭くする）。"""
    return re.sub(r"-main$", "", name or "") or (name or "")


def tags(lanes, boxes):
    """丸ごとの番号 tag を boxes に入れる: 先頭の番号の短い形（short_no）→ Issue の番号（「#」つき）→「?」。
    数える行には全部番号があるので、ほかの付け方は持たない（teamkit/docs/views.md の4章）。"""
    for b in boxes:
        b["tag"] = short_no(b["no"]) if b["no"] else "#" + str(b["issues"][0]) if b["issues"] else "?"


GITHUB = re.compile(r"^(?:https?://(?:[^@/]+@)?github\.com/|ssh://git@github\.com/|git@github\.com:)([\w.-]+/[\w.-]+?)(?:\.git)?/?$")


def issue_base(base):
    """Issue のリンクの頭（https://github.com/<持ち主>/<リポジトリ>/issues/）を、base の git の設定の origin から求める。
    git を呼ばず、ネットにもつながない。GitHub の形でないか、読めなければ ""。"""
    d = os.path.join(base or ".", ".git")
    try:
        if os.path.isfile(d):
            with open(d, encoding="utf-8") as f:
                g = f.read().strip()
            if not g.startswith("gitdir:"):
                return ""
            d = os.path.normpath(os.path.join(base, g[len("gitdir:"):].strip()))
            c = os.path.join(d, "commondir")
            if os.path.isfile(c):
                with open(c, encoding="utf-8") as f:
                    d = os.path.normpath(os.path.join(d, f.read().strip()))
        with open(os.path.join(d, "config"), encoding="utf-8", errors="replace") as f:
            text = f.read()
    except (OSError, ValueError):
        return ""
    inside = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("["):
            inside = bool(re.fullmatch(r'\[\s*remote\s+"origin"\s*\]', line))
            continue
        m = re.fullmatch(r"url\s*=\s*(\S+)", line) if inside else None
        if m:
            g = GITHUB.match(m.group(1))
            return f"https://github.com/{g.group(1)}/issues/" if g else ""
    return ""


def glist(lanes, p):
    """図の下の一覧のデータ: {"idle": [空きの持ち手の名前（plan の空きと同じ。表示の設定 TG_LIST_IDLE のときだけ出す）], "lanes": [{"lane"（帯の id）,
    "name", "rows"（済んでいない丸の id。左から）, "done"（済んだ丸の id）, "all"（済んだ丸も済んでいない丸も、TASK.md の順。
    済んだ行も混ぜる一覧の並びに使う）}]}。行の中身（番号・名前・状態・進み・ブロッカー（待つもの）・人の作業）は boxes の
    tag・text・kind・done/total・waits・human。"""
    return {"idle": [lane_name(i["name"]) for i in p["idle"]],
            "lanes": [{"lane": L["id"], "name": L["name"], "rows": list(L["boxes"]), "done": list(L["done"]),
                       # 丸の id は graph() の add() が TASK.md を読んだ順に振る（帯の中では読んだ順に増える）
                       "all": sorted(L["done"] + L["boxes"])}
                      for L in lanes if L["boxes"] or L["done"]]}

DRAW_CSS = r"""
:root{--tg-card:#1F1F1F;--tg-fg:#CCCCCC;--tg-mut:#8A8A8A;--tg-line:#3C3C3C;--tg-lane:#1C1C1C;--tg-lane2:#232323;
--tg-blue:#4DAAFC;--tg-ready:#2F6AA3;--tg-edge:#A8D4FF;--tg-blocked:#1E3247;--tg-arrow:#8AA4BD;--tg-ng:#F85149;--tg-link:#4DAAFC;
--tg-ok:#3FB950;--tg-seq:#5A5A5A;
--tg-i-done:#4CC07C;--tg-i-blue:#6C9CF0;--tg-i-hum:#F0A040;--tg-i-gray:#6B7385;--tg-i-in:#FFFFFF;--tg-hl:#4A4320}
:root[data-theme=light]{--tg-card:#FFFFFF;--tg-fg:#3B3B3B;--tg-mut:#8A8A8A;--tg-line:#CECECE;--tg-lane:#FAFAFA;--tg-lane2:#F0F0F0;
--tg-blue:#005FB8;--tg-ready:#8FBBE6;--tg-edge:#0B4F91;--tg-blocked:#E1ECF7;--tg-arrow:#6B8199;--tg-ng:#C4312B;--tg-link:#005FB8;
--tg-ok:#1A7F37;--tg-seq:#B4B4B4;
--tg-i-done:#2F9E5B;--tg-i-blue:#2F6FD6;--tg-i-hum:#E08A1E;--tg-i-gray:#A3AAB8;--tg-i-in:#FFFFFF;--tg-hl:#FFF1C2}
.tg-svg{display:block;font:12px/1.3 -apple-system,BlinkMacSystemFont,"Segoe UI","Yu Gothic UI","Meiryo",system-ui,sans-serif}
.tg-lane{fill:var(--tg-lane)}.tg-lane.alt{fill:var(--tg-lane2)}
.tg-name{fill:var(--tg-fg);font-weight:600}
.tg-box rect{fill:var(--tg-card);stroke:var(--tg-line);stroke-width:1}
.tg-box text{fill:var(--tg-fg)}.tg-box .tg-no{font-weight:600}.tg-box .tg-pg{fill:var(--tg-mut);font-size:11px}
.tg-doing rect{stroke:var(--tg-blue);stroke-width:2.5}
.tg-ready rect{fill:var(--tg-ready);stroke:var(--tg-ready)}
.tg-hum rect{fill:var(--tg-ready);stroke:var(--tg-edge);stroke-width:2.5}
.tg-blocked rect{fill:var(--tg-blocked);stroke:var(--tg-blocked)}.tg-blocked text{fill:var(--tg-mut)}
.tg-done rect{fill:var(--tg-lane2);stroke:var(--tg-line)}.tg-done text{fill:var(--tg-mut);font-size:11px}
.tg-other rect{fill:none;stroke:var(--tg-mut);stroke-dasharray:4 3;stroke-width:1.2}.tg-other text{fill:var(--tg-mut)}
.tg-edge{fill:none;stroke:var(--tg-arrow);stroke-width:1.5}
.tg-svg[data-icons="1"] .tg-edge{opacity:.3;stroke-width:1}.tg-svg[data-icons="1"] .tg-edge.on{opacity:1;stroke-width:1.8}.tg-edge.cycle{stroke:var(--tg-ng);stroke-dasharray:5 4}
.tg-seq{fill:none;stroke:var(--tg-seq);stroke-width:1}
.tg-dot circle{fill:var(--tg-ok)}.tg-dot:hover circle{stroke:var(--tg-link);stroke-width:2}
.tg-ahead{fill:var(--tg-arrow)}.tg-ahead-x{fill:var(--tg-ng)}
.tg-idle{fill:var(--tg-mut);font-style:italic}
.tg-fold{cursor:pointer}.tg-fold rect{fill:transparent;stroke:var(--tg-line)}.tg-fold text{fill:var(--tg-mut);font-size:11px}
.tg-go{cursor:pointer;outline:none}.tg-go:hover rect,.tg-go:focus-visible rect,.tg-fold:hover rect,.tg-fold:focus-visible rect{stroke:var(--tg-link);stroke-width:2}
.tg-wrap{overflow-x:auto;overflow-y:hidden}
.tg-err{color:var(--tg-ng);font-size:12px;margin:0 0 6px}
/* 状態のアイコン: 済＝緑にチェック、進行中＝青に ▶、始められる＝青の輪、人待ち＝橙に人、着手不可＝灰に砂時計 */
.tg-ic{display:inline-block;vertical-align:-3px;flex:none}
.tg-ic .tg-ib,.tg-node .tg-ib{fill:var(--tg-i-gray)}
.tg-ic.done .tg-ib,.tg-node.done .tg-ib{fill:var(--tg-i-done)}
.tg-ic.doing .tg-ib,.tg-node.doing .tg-ib{fill:var(--tg-i-blue)}
.tg-ic.hum .tg-ib,.tg-node.hum .tg-ib{fill:var(--tg-i-hum)}
.tg-ic.ready .tg-ib,.tg-node.ready .tg-ib{fill:var(--tg-card);stroke:var(--tg-i-blue)}
.tg-ig{fill:var(--tg-i-in)}.tg-ig.line{fill:none;stroke:var(--tg-i-in);stroke-linecap:round;stroke-linejoin:round}
.tg-node{outline:none}.tg-node .tg-halo{fill:var(--tg-hl);opacity:0}.tg-node.hl .tg-halo{opacity:1}
.tg-node:focus-visible .tg-halo{opacity:1;stroke:var(--tg-link);stroke-width:1.5}
.tg-node.tg-go{cursor:pointer}.tg-node.tg-other{opacity:.75}
/* 押せる丸（中に入る束・待っている持ち手を選ぶ）の見た目（TG_GO_LOOK）と、一覧の押せる行のタイトルの後ろの「›」 */
.tg-gor{fill:none;stroke:var(--tg-link);stroke-width:1.3;stroke-dasharray:2.6 2.2}
.tg-gor.solid{stroke:var(--tg-mut);stroke-dasharray:none;stroke-width:1.2}
.tg-gob{fill:var(--tg-link);stroke:var(--tg-card);stroke-width:1.2}.tg-gobt{fill:var(--tg-i-in);font:700 7px system-ui,sans-serif}
.tg-row .tg-gom{color:var(--tg-link);font-weight:700;margin-left:2px;padding:0 4px;border-radius:3px;cursor:pointer;outline:none}
.tg-row .tg-gom:hover,.tg-row .tg-gom:focus-visible{background:var(--tg-lane2);box-shadow:0 0 0 1px var(--tg-link)}
/* 説明のある行の名前（押すと下に説明が開く）と、開いた説明 */
.tg-nm.has{cursor:pointer;text-decoration:underline dotted var(--tg-mut);text-underline-offset:3px;outline:none;border-radius:2px}
.tg-nm.has:hover{text-decoration-color:var(--tg-fg)}.tg-nm.has:focus-visible{box-shadow:0 0 0 1px var(--tg-link)}
.tg-row.tg-dsc{padding:0 4px 4px}.tg-dsc>.tg-dt{grid-column:5/-1;color:var(--tg-mut);font-size:11.5px;white-space:pre-wrap;overflow-wrap:anywhere}
.tg-tag{fill:var(--tg-fg);font:600 10px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}.tg-node.blocked .tg-tag{fill:var(--tg-mut)}
.tg-list{margin:10px 0 0;font-size:12px;color:var(--tg-fg)}
.tg-list .tg-lidle{color:var(--tg-mut);margin:0 0 6px}
.tg-lrows{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:16px 2.6em 2.6em minmax(3.5em,auto) fit-content(40em) fit-content(30%) minmax(2.5em,auto) 1fr;column-gap:6px}
.tg-lrows>li{grid-column:1/-1}
.tg-list.narrow .tg-lrows{grid-template-columns:16px 2.6em 2.6em minmax(3.5em,auto) minmax(6em,1fr)}
/* 1列の表: 状態｜着手｜済｜番号｜タイトル｜ブロッカー｜Issue｜余り。タイトルは中身の幅で約40字まで（6字分より狭くしない）、
   余りは右の端へ（ブロッカーと Issue をタイトルの近くに）。ブロッカーは幅の3割まで */
.tg-row{display:grid;grid-template-columns:subgrid;gap:0 6px;align-items:center;padding:1px 4px;border-radius:3px;outline:none}
.tg-list.narrow .tg-row>.tg-rs{grid-row:2;grid-column:5}.tg-list.narrow .tg-row>.tg-ri{grid-row:2;grid-column:4;text-align:left}
.tg-list.narrow .tg-lhead>.tg-rs,.tg-list.narrow .tg-lhead>.tg-ri{display:none}
.tg-row.tg-lhead{color:var(--tg-mut);font-size:11px}
.tg-row.hl,.tg-row:focus-visible{background:var(--tg-hl)}.tg-row:focus-visible{box-shadow:0 0 0 1px var(--tg-link)}
.tg-row .tg-rt{font:600 11px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:nowrap}
.tg-row .tg-rd{color:var(--tg-mut);font-size:11px;font-variant-numeric:tabular-nums;white-space:nowrap}
.tg-row .tg-rn{min-width:6em;overflow-wrap:anywhere}.tg-row.done .tg-rn,.tg-row.blocked .tg-rn{color:var(--tg-mut)}
.tg-row .tg-ri{color:var(--tg-mut);font-size:11px;white-space:nowrap;text-align:right}.tg-ri a{color:var(--tg-link);text-decoration:none}.tg-ri a:hover,.tg-ri a:focus-visible{text-decoration:underline}
.tg-row .tg-rs{color:var(--tg-mut);font-size:11px;overflow-wrap:anywhere}
.tg-dn{padding:1px 4px;margin:0;border:0;background:none;color:var(--tg-mut);font:inherit;font-size:11px;cursor:pointer}
.tg-dn:hover,.tg-dn:focus-visible{color:var(--tg-fg);outline:1px solid var(--tg-link);border-radius:3px}
.tg-sum{margin:10px 0 0;padding:0 0 0 18px;font-size:12px;color:var(--tg-fg)}.tg-sum li{margin:1px 0;overflow-wrap:anywhere}
"""

DRAW_JS = r"""
// 未着手の印の字と、待つ相手の書き方（図と、呼び出す側の画面のツールチップで同じに使う）
const TG_SYM={done:"✅",doing:"🔄",todo:"⬜",ready:"⬜",hum:"✋",blocked:"⏳",wait:"✋"};
const TG_STATE={done:"済",doing:"進行中",todo:"未着手",ready:"始められる",hum:"人待ち",blocked:"着手不可",wait:"人待ち"};
// words: 印の字の代わりに状態の名前（図の下の一覧。アイコンの図に絵文字を混ぜない）
function tgWaitLabel(w,words){return !w.found?w.no+"（見つからない）":w.no+"（"+(w.owner?w.owner+" ":"")+((words?TG_STATE:TG_SYM)[w.mark]||"")+"）"}
// 作業計画の図を描く。g: tasktree.graph の dict、root: 描く先の要素。
// opt: {open: 「済 n」を開いた帯の id の Set, redraw()（開け閉めのあと描き直す）, onEnter(dir, 文面, 枝の番号)（束の箱。
// 入った先は、dir の TASK.md の、その番号の枝だけを描く）,
// onWait(w)（人待ちの箱を押したとき。box.wait[0] をそのまま渡す。図が読むのは w.name と w.state だけで、ほかの項目は呼び出す側が決める）,
// width（描く幅。なければ root の幅）}
// 済んだ仕事: g.fold が偽なら、帯の左に名前のない小さな点で詰めて並べ（列の幅を取らない）、そのあとに列が続く。
// 帯の中の順番（g.seq）は矢じりのない細い線、前提（g.edges）は帯をまたぐ曲がった矢印。真なら帯の左の「済 n」
// 大きさ: 描く所の幅いっぱいに描く。帯の名前の欄は幅の約6分の1（156〜312）、残りを列の数で分けて列の幅に
// （158 より狭くなるなら 158 のまま。横にスクロール）。箱と帯の名前は2行まで折り返し、入らないときだけ「…」
// 表示の設定: 図の下の一覧のいちばん上に「空き: …」の1行を出す（帯の「空き」だけでは足りないとき。teamkit/docs/views.md の6章）
let TG_LIST_IDLE=false;     // let: 画面のテストが前の形も確かめる
// 表示の設定: 一覧のブロッカーの番号に、待つ相手の持ち手と状態を括弧で添え、束の進みも出す（前の見せ方）
let TG_LIST_WAIT_DETAIL=false;
// 表示の設定: 押せる丸の見た目。"ring" 外に点線の輪、"badge" 右上に小さな丸の印、"double" 外に細い実線の輪、"" 印なし
let TG_GO_LOOK="ring";
// 表示の設定: 状態のアイコンと番号で描く。false なら、名前と進みを書いた箱で描く（drawTaskGraphBoxes）
let TG_ICONS=true;     // let: 画面のテストが箱の描き方も確かめる（TG_ICONS=false）
// 表示の設定: 図の下の一覧で、済んだ行をいちばん下の「▸ 済 n 件」に畳む。false なら畳まずに着手日の順へ混ぜる
let TG_LIST_FOLD_DONE=false;     // let: 画面のテストが畳む形も確かめる
// アイコンの形を p（svg の g）に描く。中心 (x, y)、半径 r。色は CSS（.tg-ib 地・.tg-ig 中の形。親の class が状態）
function tgShape(p,k,x,y,r){
  const NS="http://www.w3.org/2000/svg",u=r/10;
  const sv=(t,a)=>{const n=document.createElementNS(NS,t);for(const q in a)n.setAttribute(q,a[q]);p.appendChild(n);return n};
  const P=a=>a.map(([px,py])=>(x+px*u)+","+(y+py*u)).join(" ");
  if(k==="ready"){sv("circle",{cx:x,cy:y,r:r-1.2*u,class:"tg-ib","stroke-width":2.4*u});return}
  sv("circle",{cx:x,cy:y,r,class:"tg-ib"});
  if(k==="done")sv("polyline",{points:P([[-4.6,0.2],[-1.3,3.6],[4.8,-3.4]]),class:"tg-ig line","stroke-width":2.4*u});
  else if(k==="doing")sv("polygon",{points:P([[-2.6,-4.4],[4.6,0],[-2.6,4.4]]),class:"tg-ig"});
  else if(k==="hum"){sv("circle",{cx:x,cy:y-2.6*u,r:2.4*u,class:"tg-ig"});
    sv("path",{d:`M${x-4.6*u},${y+5.4*u} Q${x-4.6*u},${y+0.6*u} ${x},${y+0.6*u} Q${x+4.6*u},${y+0.6*u} ${x+4.6*u},${y+5.4*u} Z`,class:"tg-ig"})}
  else sv("path",{d:`M${x-3.6*u},${y-4.6*u} H${x+3.6*u} L${x},${y} L${x+3.6*u},${y+4.6*u} H${x-3.6*u} L${x},${y} Z`,class:"tg-ig line","stroke-width":1.6*u});
}
// 1つのアイコンの svg（一覧の行と、呼び出す側の画面の印）。k: done・doing・ready・hum・blocked
function tgIcon(k,size){
  const NS="http://www.w3.org/2000/svg",n=size||14,s=document.createElementNS(NS,"svg");
  s.setAttribute("width",n);s.setAttribute("height",n);s.setAttribute("viewBox","-10 -10 20 20");
  s.setAttribute("class","tg-ic "+k);s.setAttribute("aria-hidden","true");s.dataset.icon=k;
  const g=document.createElementNS(NS,"g");s.append(g);tgShape(g,k,0,0,9.4);return s;
}
function tgIconsOn(){return TG_ICONS}
function drawTaskGraph(g,root,opt){return TG_ICONS?drawTaskGraphIcons(g,root,opt):drawTaskGraphBoxes(g,root,opt)}
// 丸と番号の図: 全部の仕事を同じ大きさの状態のアイコンと、その下の番号（box.tag）だけで描く。列は box.at
// （済んだ丸も列を取る）。丸の中心の間 34px・帯の高さ 46px に詰め、幅いっぱいには広げない。収まらなければ横スクロールで、
// 初めは右端（今の所）。図の下に一覧（全部の行を着手日の順に1つの表で）。丸と行は、乗せると互いに光る
// （フォーカスでも）。opt は drawTaskGraphBoxes と同じ（open は済みを開いた帯の id）
function drawTaskGraphIcons(g,root,opt){
  opt=opt||{};const open=opt.open||new Set();
  const NS="http://www.w3.org/2000/svg",LH=46,R=9,PAD=6,FS=12;
  // 丸の中心の間: 約34px。番号が長ければ（S041-1 など）、隣の番号と重ならない所まで広げる（番号は 10px の等幅）
  const CW=Math.max(34,Math.ceil(Math.max(0,...(g.boxes||[]).map(b=>String(b.tag||"").length))*6.2)+6);
  const sv=(t,a,p)=>{const n=document.createElementNS(NS,t);for(const k in a||{})n.setAttribute(k,a[k]);if(p)p.appendChild(n);return n};
  const el=(t,c,x)=>{const n=document.createElement(t);if(c)n.className=c;if(x!=null)n.textContent=x;return n};
  const cw=ch=>/[\x00-\xff]/.test(ch)?0.56:1;
  const wrap=(s,w,n)=>{const L=[];let o="",u=0;
    for(const ch of String(s||"")){
      if(u+cw(ch)>w){L.push(o);o="";u=0;
        if(L.length===n){const x=[...L[n-1]];let v=x.reduce((a,c)=>a+cw(c),0);while(x.length&&v+1>w)v-=cw(x.pop());L[n-1]=x.join("")+"…";return {lines:L,cut:true}}}
      o+=ch;u+=cw(ch)}
    if(o||!L.length)L.push(o);return {lines:L,cut:false}};
  const B=g.boxes||[],lanes=g.lanes||[],wl=w=>tgWaitLabel(w,true);
  const pw=root.querySelector(".tg-wrap"),px=pw?pw.scrollLeft:null;
  const fa=document.activeElement,fk=fa&&root.contains(fa)&&fa.dataset?[fa.dataset.ui,fa.dataset.box||fa.dataset.lane||""]:null;
  root.replaceChildren();
  if(g.cycle){const e=el("div","tg-err","前提が循環しています");e.dataset.ui="taskgraph-cycle";root.append(e)}
  const cs=getComputedStyle(root),inner=root.clientWidth-(parseFloat(cs.paddingLeft)||0)-(parseFloat(cs.paddingRight)||0);
  const AW=Math.max(280,Math.floor(opt.width||inner||900));
  const LW=AW<520?96:132,LNW=(LW-14)/FS,X0=LW+18;
  let maxa=0;for(const L of lanes)for(const bi of L.done.concat(L.boxes))maxa=Math.max(maxa,B[bi].at||0);
  // 帯の高さ: 同じ列に縦にずらした丸（任せた行の枝。box.lift）があれば、その段の分だけ高く
  const LS=30,ly={},lh={};let yy=PAD;lanes.forEach(L=>{ly[L.id]=yy;lh[L.id]=LH+((L.lifts||1)-1)*LS;yy+=lh[L.id]});
  const W=X0+(maxa+1)*CW+40,H=yy+PAD;
  const svg=sv("svg",{width:W,height:H,viewBox:"0 0 "+W+" "+H,class:"tg-svg",role:"img","aria-label":"作業計画の図"});
  svg.dataset.ui="taskgraph-svg";svg.dataset.lw=LW;svg.dataset.cw=CW;svg.dataset.icons="1";
  const defs=sv("defs",{},svg);
  for(const [id,c] of [["tg-ah","tg-ahead"],["tg-ahx","tg-ahead-x"]]){
    const m=sv("marker",{id,viewBox:"0 0 8 8",refX:"7",refY:"4",markerWidth:"7",markerHeight:"7",orient:"auto"},defs);sv("path",{d:"M0,0 L8,4 L0,8 z",class:c},m)}
  const pos=b=>({x:X0+(b.at||0)*CW,y:ly[b.lane]+LH/2-5+(b.lift||0)*LS});
  const act=(n,f,label)=>{n.setAttribute("role","button");if(label)n.setAttribute("aria-label",label);
    n.addEventListener("click",f);n.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();f()}})};
  const goOf=b=>b.enter&&opt.onEnter?[()=>opt.onEnter(b.enter,b.text,b.branch||""),b.text+" の図に入る"]
    :b.wait&&b.wait.length&&opt.onWait?[()=>opt.onWait(b.wait[0]),b.wait[0].name+" を選ぶ"]:null;
  const nameOf=b=>{let s=b.text||"";if(b.no&&s.startsWith(b.no))s=s.slice(b.no.length).trim();return b.found===false?"？":s};
  // ツールチップ（と前の見せ方の一覧）: 待つ相手の持ち手と状態、束の進みも
  const subOf=b=>[b.total?b.done+"/"+b.total:"",b.waits&&b.waits.length?"← "+b.waits.map(wl).join("、"):"",
    b.human&&b.human.length?"人の作業: "+b.human.join("、"):"",...(b.wait||[]).map(w=>w.name+"が"+w.state)].filter(Boolean).join("　");
  // 一覧のブロッカー: 待つものの番号の短い形だけ（見つからない番号は「?」）、人の作業の語、待っているものの説明
  const blockOf=b=>TG_LIST_WAIT_DETAIL?subOf(b):[...(b.waits||[]).map(w=>(w.tag||w.no)+(w.found===false?"?":"")),
    ...(b.human||[]),...(b.wait||[]).map(w=>w.name+"が"+w.state)].join(", ");
  const tipOf=b=>[b.tag+" "+nameOf(b)+"（"+(TG_STATE[b.kind]||"")+"）",subOf(b),b.now?"いま: "+b.now:"",b.owner?"持ち手: "+b.owner:"",
    b.issues&&b.issues.length?b.issues.map(n=>"#"+n).join(" "):""].filter(Boolean).join("\n");
  // 光らせる: 丸と一覧の行。前提の矢印は、その丸が待つ丸とその丸を待つ丸へのものだけ濃く（全部を濃くすると込み合う）
  const hl=(id,f)=>{root.querySelectorAll('[data-box="'+id+'"]').forEach(n=>n.classList.toggle("hl",f));
    root.querySelectorAll('[data-ui="taskgraph-edge"][data-from="'+id+'"],[data-ui="taskgraph-edge"][data-to="'+id+'"]').forEach(n=>n.classList.toggle("on",f))};
  const hover=(n,id)=>{for(const [e,f] of [["mouseenter",1],["mouseleave",0],["focus",1],["blur",0]])n.addEventListener(e,()=>hl(id,!!f))};
  // 帯（地と名前。名前は2行まで折り返し）と「空き」
  lanes.forEach((L,i)=>{
    const y=ly[L.id],gl=sv("g",{class:"tg-lanes"},svg);gl.dataset.ui="taskgraph-lane";gl.dataset.kind=L.kind;
    sv("rect",{x:0,y,width:W,height:lh[L.id],class:"tg-lane"+(i%2?" alt":"")},gl);
    const nw=wrap(L.name,LNW,2),nm=sv("g",{class:"tg-names"},gl);nm.dataset.ui="taskgraph-name";
    nw.lines.forEach((s,k)=>{const t=sv("text",{x:8,y:y+lh[L.id]/2+4-(nw.lines.length-1)*7+k*14,class:"tg-name"},nm);t.textContent=s});
    const tp=[nw.cut?L.name:"",L.bundle&&L.bundle!==L.name?L.bundle:"",L.waits&&L.waits.length?"待ち: "+L.waits.map(wl).join("、"):"",
      L.human&&L.human.length?"人の作業: "+L.human.join("、"):""].filter(Boolean).join("\n");
    if(tp)sv("title",{},nm).textContent=tp;
    if(L.idle){const all=L.done.concat(L.boxes),last=all.length?Math.max(...all.map(bi=>B[bi].at||0))+1:0;
      const t=sv("text",{x:X0+last*CW-R+4,y:y+LH/2-1,class:"tg-idle"},gl);t.textContent="空き";t.dataset.ui="taskgraph-idle"}
  });
  // 帯の中の順番（中心どうしの細い線。丸の下に隠れる）と、前提の矢印（帯をまたぐ曲線）
  // 順番の線は g.seq（持ち手が自分でやる行どうしだけ。任せた行は線につながない）
  const ek=new Set((g.edges||[]).map(e=>e.from+">"+e.to));
  for(const s of g.seq||[]){if(ek.has(s.from+">"+s.to))continue;const a=pos(B[s.from]),b=pos(B[s.to]);
    const l=sv("path",{d:`M${a.x},${a.y} L${b.x},${b.y}`,class:"tg-seq"},svg);l.dataset.ui="taskgraph-seq"}
  for(const e of g.edges||[]){
    const a=pos(B[e.from]),b=pos(B[e.to]),x1=a.x+R,y1=a.y,x2=b.x-R-1,y2=b.y,dx=Math.max(16,Math.abs(x2-x1)/2);
    const p=sv("path",{d:`M${x1},${y1} C${x1+dx},${y1} ${x2-dx},${y2} ${x2},${y2}`,class:"tg-edge"+(e.cycle?" cycle":""),"marker-end":e.cycle?"url(#tg-ahx)":"url(#tg-ah)"},svg);
    p.dataset.ui="taskgraph-edge";p.dataset.from=e.from;p.dataset.to=e.to;if(e.cycle)p.dataset.cycle="1"}
  // 丸: アイコンと、下に番号。名前はツールチップと一覧
  for(const L of lanes)for(const bi of L.done.concat(L.boxes)){
    const b=B[bi],{x,y}=pos(b),k=b.kind||"ready";
    const gn=sv("g",{class:"tg-node "+k+(L.kind==="other"?" tg-other":""),tabindex:"0"},svg);
    gn.dataset.ui="taskgraph-node";gn.dataset.state=k;gn.dataset.box=b.id;
    sv("circle",{cx:x,cy:y,r:R+5,class:"tg-halo"},gn);tgShape(gn,k,x,y,R);
    const t=sv("text",{x,y:y+R+11,"text-anchor":"middle",class:"tg-tag"},gn);t.textContent=b.tag||"";
    sv("title",{},gn).textContent=tipOf(b);
    const go=goOf(b);if(go){gn.classList.add("tg-go");act(gn,go[0],go[1]);gn.dataset.go=TG_GO_LOOK||"none";
      if(TG_GO_LOOK==="ring"||TG_GO_LOOK==="double")sv("circle",{cx:x,cy:y,r:R+3.2,class:"tg-gor"+(TG_GO_LOOK==="double"?" solid":"")},gn);
      else if(TG_GO_LOOK==="badge"){const bx=x+R*0.78,by=y-R*0.78;sv("circle",{cx:bx,cy:by,r:4.2,class:"tg-gob"},gn);
        const t2=sv("text",{x:bx,y:by+2.4,"text-anchor":"middle",class:"tg-gobt"},gn);t2.textContent="›"}}
    hover(gn,b.id);
  }
  // 帯の名前の欄は左に留める（狭い画面では留めない）
  const pin=sv("g",{class:"tg-pin"},svg);
  lanes.forEach((L,i)=>sv("rect",{x:0,y:ly[L.id],width:LW,height:lh[L.id],class:"tg-lane"+(i%2?" alt":"")},pin));
  for(const n of svg.querySelectorAll(".tg-lanes > .tg-names"))pin.append(n);
  const gw=el("div","tg-wrap");gw.dataset.ui="taskgraph-wrap";gw.append(svg);root.append(gw);
  const pinned=AW>=LW*3,keep=()=>pin.setAttribute("transform","translate("+(pinned?gw.scrollLeft:0)+",0)");
  if(pinned)gw.dataset.pin="1";
  gw.addEventListener("scroll",keep,{passive:true});
  gw.scrollLeft=px==null?gw.scrollWidth:px;keep();requestAnimationFrame(keep);
  // 図の下の一覧: 1列の表「状態｜着手｜済｜番号｜タイトル｜ブロッカー｜Issue」（TG_LIST_IDLE なら上に「空き」の1行）。
  // 並びは状態によらず着手日の順（同じ日と日付のない行は帯と TASK.md の順。日付のない行はあと）。済んだ行も畳まずに
  // 混ぜる（予定に対して前倒し・遅れが並んで見える）。TG_LIST_FOLD_DONE が真なら、済んだ行は
  // いちばん下の「▸ 済 n 件」に畳み（済の日の順）、押すと開く（open の "done"）。狭い幅ではブロッカーと Issue を2行目に
  const ls=el("div","tg-list"+(AW<520?" narrow":""));ls.dataset.ui="taskgraph-list";
  const gl=g.list||{idle:[],lanes:lanes.map(L=>({lane:L.id,name:L.name,rows:L.boxes,done:L.done}))};
  if(TG_LIST_IDLE&&(gl.idle||[]).length){const p=el("p","tg-lidle","空き: "+gl.idle.join("、"));p.dataset.ui="taskgraph-list-idle";ls.append(p)}
  const md=d=>d?(+d.slice(5,7))+"/"+(+d.slice(8,10)):"";
  const row=bi=>{const b=B[bi],li=el("li","tg-row "+(b.kind||"ready"));li.dataset.ui="taskgraph-row";li.dataset.box=b.id;li.tabIndex=0;
    const no=el("span","tg-rt",b.tag||"");if(b.no&&b.no!==b.tag)no.title=b.no;
    // Issue: リンクの頭（g.issue_url）があれば、新しいタブで開くリンク
    const is=el("span","tg-ri");(b.issues||[]).forEach((n,k)=>{if(k)is.append(" ");
      if(!g.issue_url){is.append("#"+n);return}
      const a=el("a","","#"+n);a.href=g.issue_url+n;a.target="_blank";a.rel="noopener noreferrer";a.dataset.ui="taskgraph-issue";
      a.addEventListener("click",e=>e.stopPropagation());is.append(a)});
    // 名前: 説明があれば押すと下に開く（もう一度で閉じる。開いた行は open に "d<番号>" で覚える）
    const rn=el("span","tg-rn"),nm=el("span","tg-nm",nameOf(b));rn.append(nm);
    li.append(tgIcon(b.kind||"ready",14),el("span","tg-rd",md(b.start)),el("span","tg-rd",md(b.finished)),no,
      rn,el("span","tg-rs",blockOf(b)),is);
    if(b.desc){nm.classList.add("has");nm.dataset.ui="taskgraph-name-desc";nm.dataset.box=b.id;nm.tabIndex=0;nm.setAttribute("role","button");
      const k="d"+(b.no||b.id),set=o=>{nm.setAttribute("aria-expanded",o?"true":"false");
        const nx=li.nextElementSibling;if(nx&&nx.dataset.ui==="taskgraph-desc")nx.remove();
        if(o){const d=el("li","tg-row tg-dsc");d.dataset.ui="taskgraph-desc";d.dataset.box=b.id;d.append(el("div","tg-dt",b.desc));li.after(d)}};
      const flip=e=>{e.stopPropagation();if(open.has(k))open.delete(k);else open.add(k);set(open.has(k))};
      nm.addEventListener("click",flip);nm.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();flip(e)}});
      li._desc=()=>set(open.has(k))}
    // 束に入る・持ち手を選ぶは「›」を押したときだけ（行のほかの所では入らない）
    const go=goOf(b);if(go){li.classList.add("tg-go");const m=el("span","tg-gom","›");m.dataset.ui="taskgraph-go";m.dataset.box=b.id;m.tabIndex=0;
      act(m,e=>{if(e&&e.stopPropagation)e.stopPropagation();go[0]()},go[1]);rn.append(m)}
    hover(li,b.id);return li};
  const put=bi=>{const li=row(bi);ul.append(li);if(li._desc)li._desc()};
  // 帯の順に、帯の中は TASK.md の順（glist の "all"）。日付で並べ、同じ日と日付のない行はこの順のまま
  const fold=TG_LIST_FOLD_DONE,order=[],dones=[];
  for(const r of gl.lanes||[]){if(fold){order.push(...r.rows);dones.push(...r.done)}else order.push(...(r.all||r.done.concat(r.rows)))}
  const byDate=key=>(p,q)=>{const x=B[p[0]][key]||"",y=B[q[0]][key]||"";return (x&&y?(x<y?-1:x>y?1:0):x?-1:y?1:0)||p[1]-q[1]};
  const rows=order.map((bi,k)=>[bi,k]).sort(byDate("start")).map(p=>p[0]);
  const fin=dones.map((bi,k)=>[bi,k]).sort(byDate("finished")).map(p=>p[0]);
  const ul=el("ul","tg-lrows");ul.dataset.ui="taskgraph-list-rows";
  const hd=el("li","tg-row tg-lhead");hd.setAttribute("aria-hidden","true");
  for(const [c,x] of [["",""],["tg-rd","着手"],["tg-rd","済"],["tg-rt","番号"],["tg-rn","タイトル"],["tg-rs","ブロッカー"],["tg-ri","Issue"]])hd.append(el("span",c,x));
  ul.append(hd);for(const bi of rows)put(bi);
  if(fin.length){const o=open.has("done"),li=el("li"),bt=el("button","tg-dn",(o?"▾":"▸")+" 済 "+fin.length+" 件");
    bt.type="button";bt.dataset.ui="taskgraph-done";bt.setAttribute("aria-expanded",o?"true":"false");
    bt.addEventListener("click",()=>{if(open.has("done"))open.delete("done");else open.add("done");if(opt.redraw)opt.redraw()});
    li.append(bt);ul.append(li);if(o)for(const bi of fin)put(bi)}
  ls.append(ul);root.append(ls);
  // 描き直しても、押していた所（済の畳み・丸・行）にフォーカスを戻す
  if(fk&&fk[0]){const n=[...root.querySelectorAll('[data-ui="'+fk[0]+'"]')].find(x=>(x.dataset.box||x.dataset.lane||"")===fk[1]);if(n)n.focus()}
}
// 箱の描き方。TG_ICONS が false のとき
function drawTaskGraphBoxes(g,root,opt){
  opt=opt||{};const open=opt.open||new Set();
  const NS="http://www.w3.org/2000/svg",BH=52,LH=72,DW=96,DH=30,PAD=8,FS=12,DS=14,DR=4.5,fold=!!g.fold;
  const sv=(t,a,p)=>{const n=document.createElementNS(NS,t);for(const k in a||{})n.setAttribute(k,a[k]);if(p)p.appendChild(n);return n};
  const el=(t,c,x)=>{const n=document.createElement(t);if(c)n.className=c;if(x!=null)n.textContent=x;return n};
  const cw=ch=>/[\x00-\xff]/.test(ch)?0.56:1;
  // 文面を、字の数の見積もり w（全角1、半角0.56）で n 行まで折り返す。入らなければ最後の行の終わりを「…」に
  const wrap=(s,w,n)=>{const L=[];let o="",u=0;
    for(const ch of String(s||"")){
      if(u+cw(ch)>w){L.push(o);o="";u=0;
        if(L.length===n){const x=[...L[n-1]];let v=x.reduce((a,c)=>a+cw(c),0);while(x.length&&v+1>w)v-=cw(x.pop());L[n-1]=x.join("")+"…";return {lines:L,cut:true}}}
      o+=ch;u+=cw(ch)}
    if(o||!L.length)L.push(o);return {lines:L,cut:false}};
  const txt=(p,x,y,s,c)=>{const n=sv("text",{x,y,class:c||""},p);n.textContent=s;return n};
  const lines=(p,x,y,w,c)=>{w.lines.forEach((s,i)=>txt(p,x,y+i*14,s,c))};
  const wl=tgWaitLabel;
  const B=g.boxes||[],lanes=g.lanes||[];
  const pw=root.querySelector(".tg-wrap"),px=pw?pw.scrollLeft:null;    // 描き直す前の横の位置（開け閉め・大きさの変化では保つ）
  root.replaceChildren();
  if(g.cycle){const e=el("div","tg-err","前提が循環しています");e.dataset.ui="taskgraph-cycle";root.append(e)}
  let maxc=0,maxd=0;for(const b of B)maxc=Math.max(maxc,b.col);
  const ndot=fold?0:Math.max(0,...lanes.map(L=>L.done.length)),DA=ndot?ndot*DS+12:0;     // 点を並べる幅（全部の帯で同じ。列をそろえる）
  const cs=getComputedStyle(root),inner=root.clientWidth-(parseFloat(cs.paddingLeft)||0)-(parseFloat(cs.paddingRight)||0);
  const AW=Math.max(320,Math.floor(opt.width||inner||900));
  const LW=Math.round(Math.min(312,Math.max(156,AW/6))),CW=Math.max(158,Math.floor((AW-LW-DA-48)/(maxc+1))),X0=LW+DA;
  const BW=Math.min(CW-20,320),NW=(BW-14)/FS,LNW=(LW-16)/FS;
  let y=PAD;const ly={};
  for(const L of lanes){const o=fold&&open.has(L.id)&&L.done.length>0;ly[L.id]={y,o};y+=LH+(o?DH+6:0);if(o)maxd=Math.max(maxd,L.done.length)}
  const W=Math.max(AW,X0+(maxc+1)*CW+48,LW+maxd*(DW+6)+PAD),H=y+PAD;
  const svg=sv("svg",{width:W,height:H,viewBox:"0 0 "+W+" "+H,class:"tg-svg",role:"img"});svg.dataset.ui="taskgraph-svg";
  svg.dataset.lw=LW;svg.dataset.cw=CW;
  const defs=sv("defs",{},svg);
  for(const [id,c] of [["tg-ah","tg-ahead"],["tg-ahx","tg-ahead-x"]]){
    const m=sv("marker",{id,viewBox:"0 0 8 8",refX:"7",refY:"4",markerWidth:"7",markerHeight:"7",orient:"auto"},defs);sv("path",{d:"M0,0 L8,4 L0,8 z",class:c},m)}
  const at=b=>({x:X0+b.col*CW+(CW-BW)/2,y:ly[b.lane].y+(LH-BH)/2});
  const dotk=new Map();if(!fold)for(const L of lanes)L.done.forEach((bi,k)=>dotk.set(bi,k));
  const isDot=b=>dotk.has(b.id);
  const dotAt=b=>({x:LW+8+dotk.get(b.id)*DS+DR,y:ly[b.lane].y+LH/2});
  // 線のつなぎ目: 点は円の端、箱は左右の辺の真ん中
  const rightOf=b=>{if(isDot(b)){const d=dotAt(b);return {x:d.x+DR,y:d.y}}const a=at(b);return {x:a.x+BW,y:a.y+BH/2}};
  const leftOf=b=>{if(isDot(b)){const d=dotAt(b);return {x:d.x-DR,y:d.y}}const a=at(b);return {x:a.x,y:a.y+BH/2}};
  const act=(n,f,label)=>{n.setAttribute("tabindex","0");n.setAttribute("role","button");if(label)n.setAttribute("aria-label",label);
    n.addEventListener("click",f);n.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();f()}})};
  // ツールチップは画面に出ていない情報だけ: 切れた文面の全文、待つ相手と人の作業、人を待っているもの、いまの 🔄
  const tipOf=(cut,full,b)=>[cut?full:"",b.waits&&b.waits.length?"待ち: "+b.waits.map(wl).join("、"):"",
    b.human&&b.human.length?"人の作業: "+b.human.join("、"):"",...(b.wait||[]).map(w=>w.name+"が"+w.state),
    b.now?"いま: "+b.now:"",b.owner?"持ち手: "+b.owner:"",b.found===false?"ツリーに見つからない番号":"",
    b.issues&&b.issues.length?b.issues.map(n=>"#"+n).join(" "):""].filter(Boolean).join("\n");     // 箱には Issue を出さないので
  const tip=(n,s)=>{if(s)sv("title",{},n).textContent=s};
  lanes.forEach((L,i)=>{
    const {y,o}=ly[L.id],h=LH+(o?DH+6:0),gl=sv("g",{class:"tg-lanes"},svg);gl.dataset.ui="taskgraph-lane";gl.dataset.kind=L.kind;
    sv("rect",{x:0,y,width:W,height:h,class:"tg-lane"+(i%2?" alt":"")},gl);
    const nw=wrap(L.name,LNW,2),nm=sv("g",{class:"tg-names"},gl);nm.dataset.ui="taskgraph-name";
    lines(nm,8,y+18,nw,"tg-name");tip(nm,tipOf(nw.cut,L.name,L));
    if(fold&&L.done.length){
      const f=sv("g",{class:"tg-fold"},gl);f.dataset.ui="taskgraph-done";f.dataset.lane=L.id;
      sv("rect",{x:8,y:y+44,width:50,height:18,rx:9},f);txt(f,16,y+57,"済 "+L.done.length+(o?" ▾":" ▸"));
      f.setAttribute("aria-expanded",o?"true":"false");
      act(f,()=>{if(open.has(L.id))open.delete(L.id);else open.add(L.id);if(opt.redraw)opt.redraw()},"済 "+L.done.length+" 件を"+(o?"閉じる":"開く"));
      if(o)L.done.forEach((bi,k)=>{const b=B[bi],x=LW+k*(DW+6),gb=sv("g",{class:"tg-box tg-done"},gl);gb.dataset.ui="taskgraph-donebox";
        const s=(b.no&&!b.text.startsWith(b.no)?b.no+" ":"")+b.text,f1=wrap(s,7.5,1);
        sv("rect",{x,y:y+LH,width:DW,height:DH-6,rx:4},gb);txt(gb,x+6,y+LH+16,f1.lines[0]);tip(gb,f1.cut?b.full||s:"")})}
    if(!fold)L.done.forEach(bi=>{const b=B[bi],d=dotAt(b),gd=sv("g",{class:"tg-dot"},gl);gd.dataset.ui="taskgraph-dot";
      sv("circle",{cx:d.x,cy:d.y,r:DR},gd);        // 押す所ではないので Tab では止まらない（中身はツールチップ）
      const s=(b.no&&!b.text.startsWith(b.no)?b.no+" ":"")+b.text;tip(gd,"✅ "+s+(b.issues&&b.issues.length?"\n"+b.issues.map(n=>"#"+n).join(" "):""))});
    if(L.idle){const last=L.boxes.length?Math.max(...L.boxes.map(bi=>B[bi].col))+1:0;const t=txt(gl,X0+last*CW+10,y+LH/2+4,"空き","tg-idle");t.dataset.ui="taskgraph-idle"}
  });
  const ek=new Set((g.edges||[]).map(e=>e.from+">"+e.to));
  for(const s of g.seq||[]){     // 帯の中の順番（矢じりなし。待ちではない）。同じ2つを前提の矢印が結ぶなら矢印だけ
    const a=B[s.from],b=B[s.to];if(!a||!b||ek.has(s.from+">"+s.to)||(a.col<0&&!isDot(a))||(b.col<0&&!isDot(b)))continue;
    const p=rightOf(a),q=leftOf(b);if(q.x<=p.x)continue;
    const l=sv("path",{d:`M${p.x},${p.y} L${q.x},${q.y}`,class:"tg-seq"},svg);l.dataset.ui="taskgraph-seq"}
  for(const e of g.edges||[]){
    const fa=B[e.from],fb=B[e.to];if(fa.col<0&&!isDot(fa))continue;
    const a=rightOf(fa),b=leftOf(fb),x1=a.x,y1=a.y,x2=b.x,y2=b.y,dx=Math.max(30,Math.abs(x2-x1)/2);
    const p=sv("path",{d:`M${x1},${y1} C${x1+dx},${y1} ${x2-dx},${y2} ${x2-2},${y2}`,class:"tg-edge"+(e.cycle?" cycle":""),"marker-end":e.cycle?"url(#tg-ahx)":"url(#tg-ah)"},svg);
    p.dataset.ui="taskgraph-edge";p.dataset.from=e.from;p.dataset.to=e.to;if(e.cycle)p.dataset.cycle="1"}
  for(const L of lanes)for(const bi of L.boxes){
    const b=B[bi],{x,y}=at(b),k=b.mark==="done"?"done":b.mark==="doing"?"doing":(b.state||"ready");
    const gb=sv("g",{class:"tg-box tg-"+k+(L.kind==="other"?" tg-other":"")},svg);gb.dataset.ui="taskgraph-box";gb.dataset.state=k;
    sv("rect",{x,y,width:BW,height:BH,rx:5},gb);
    const pg=b.total?b.done+"/"+b.total:"";
    if(b.no)txt(gb,x+7,y+16,b.no,"tg-no");
    if(pg){const t=txt(gb,x+BW-6,y+16,pg,"tg-pg");t.setAttribute("text-anchor","end")}
    let name=b.text||"";if(b.no&&name.startsWith(b.no))name=name.slice(b.no.length).trim();
    if(L.kind==="other"&&b.found===false)name="？";
    const nw=wrap(name,NW,2);lines(gb,x+7,b.no||pg?y+31:y+21,nw);
    tip(gb,tipOf(nw.cut,b.full||b.text,b));
    if(b.enter&&opt.onEnter){gb.classList.add("tg-go");gb.dataset.enter="1";act(gb,()=>opt.onEnter(b.enter,b.text,b.branch||""),b.text+" の図に入る")}
    else if(b.wait&&b.wait.length&&opt.onWait){gb.classList.add("tg-go");act(gb,()=>opt.onWait(b.wait[0]),b.wait[0].name+" を選ぶ")}
  }
  // 帯の名前の欄は左に留める（横にスクロールしても、どの帯か分かる）: 名前と「済 n」を、帯の地の色の板ごといちばん上へ。
  // 狭い画面（幅が名前の欄の3倍より狭い）では留めない（留めると図の見える所が半分ほどになる）
  const pin=sv("g",{class:"tg-pin"},svg);
  lanes.forEach((L,i)=>{const {y,o}=ly[L.id];sv("rect",{x:0,y,width:LW,height:LH+(o?DH+6:0),class:"tg-lane"+(i%2?" alt":"")},pin)});
  for(const n of svg.querySelectorAll(".tg-lanes > .tg-names, .tg-lanes > .tg-fold"))pin.append(n);
  // 横のスクロールは図だけ（まとめの欄はいつも見える）。初めて描くときは右端（今の所）に合わせる
  const gw=el("div","tg-wrap");gw.dataset.ui="taskgraph-wrap";gw.append(svg);root.append(gw);
  const pinned=AW>=LW*3,keep=()=>pin.setAttribute("transform","translate("+(pinned?gw.scrollLeft:0)+",0)");
  if(pinned)gw.dataset.pin="1";
  gw.addEventListener("scroll",keep,{passive:true});
  gw.scrollLeft=px==null?gw.scrollWidth:px;keep();requestAnimationFrame(keep);     // 大きさが落ち着いたあとにも
  const sum=el("ul","tg-sum");sum.dataset.ui="taskgraph-summary";
  for(const s of g.summary||[])sum.append(el("li","",s.replace(/^- /,"")));
  root.append(sum);
}
"""


def html_page(g):
    """図のデータ g（graph の結果）を、1枚の HTML（データと DRAW_JS を埋め込む）にする。CLI の --html。"""
    data = json.dumps(g, ensure_ascii=False).replace("</", "<\\/")
    title = html.escape("作業計画 — " + (g.get("title") or "TASK.md"))
    return ("<!doctype html>\n<html lang=\"ja\"><head><meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
            f"<title>{title}</title>\n<style>{DRAW_CSS}\n"
            ":root{color-scheme:dark;--bg:#181818}:root[data-theme=light]{color-scheme:light;--bg:#F8F8F8}\n"
            "body{margin:0;padding:12px 16px;background:var(--bg);color:var(--tg-fg);font:13px/1.5 system-ui,sans-serif}\n"
            "h1{font-size:14px;margin:0 0 8px}#g{overflow:auto;scrollbar-gutter:stable}</style>\n"
            "<script>if(matchMedia(\"(prefers-color-scheme: light)\").matches)"
            "document.documentElement.dataset.theme=\"light\"</script>\n"
            f"</head><body><h1>{title}</h1><div id=\"g\"></div>\n<script>{DRAW_JS}\n"
            f"const G={data};const open=new Set();\n"
            "function draw(){drawTaskGraph(G,document.getElementById(\"g\"),{open,redraw:draw})}\ndraw();\n"
            "addEventListener(\"resize\",draw);\n"
            "</script></body></html>\n")


def plan_text(p, title=""):
    """計画（plan の結果）を Markdown の箇条書きにする。空き・始められる・人待ち・待ちの順で、
    値のないものは行ごと出さない。始められる行には持ち手、人待ちには人の作業、待ちの行には「← 待つ行（持ち手と印）」を添える。"""
    out = ["# 計画 — " + (title or "TASK.md")]
    if p["idle"]:
        out.append("- 空き: " + "、".join(i["name"] for i in p["idle"]))
    for r in p["ready"]:
        out.append(f"- 始められる: {label(r)}" + (f"（{r['owner']}）" if r["owner"] else ""))
    for r in p["hum"]:
        out.append(f"- 人待ち: {label(r)}" + (f"（{r['owner']}）" if r["owner"] else "") +
                   (" — 人の作業: " + "、".join(r["human"]) if r["human"] else ""))
    for r in p["blocked"]:
        waits = "、".join(wait_label(w) for w in r["waits"])
        out.append(f"- 待ち: {label(r)}" + (f"（{r['owner']}）" if r["owner"] else "") + f" ← {waits}")
    if len(out) == 1:
        out.append("- 計画に出すものはありません")
    return "\n".join(out) + "\n"


def label(r):
    return PRE.sub("", r["text"]).strip() or "（文面なし）"        # 前提は「←」や人の作業のほうに出す


def wait_label(w):
    if not w["found"]:
        return w["no"] + "（見つからない）"
    mark = STATE_MARKS.get(w["mark"]) or MARKS.get(w["mark"], "")
    return f"{w['no']}（{w['owner']} {mark}）" if w["owner"] else f"{w['no']}（{mark}）"


LIST_STATES = {"done": "done", "doing": "doing", "ready": "ready", "human": "hum", "blocked": "blocked"}    # --state の語 -> 行の種類（kind_of）
LIST_WORDS = {"done": "済み", "doing": "進行中", "ready": "始められる", "human": "人待ち", "blocked": "着手不可", "open": "未済"}
LIST_COLS = ["状態", "着手", "済", "番号", "名前", "ブロッカー", "Issue"]
ISO_DATE = re.compile(r"\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*$")
MD_DATE = re.compile(r"\s*(\d{1,2})\s*/\s*(\d{1,2})\s*$")


def list_date(word, today=None):
    """--from・--to の日（`11/25` か `2026-11-25`。年がなければ今日に近い年）を "YYYY-MM-DD" に。読めなければ ValueError。"""
    m = ISO_DATE.match(word or "")
    if m:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    m = MD_DATE.match(word or "")
    got = near_date(int(m.group(1)), int(m.group(2)), today) if m else ""
    if not got:
        raise ValueError(word)
    return got


def list_span(start, end, today=None):
    """--from・--to の語から期間 (始まり, 終わり)（"YYYY-MM-DD" か None）。年のない日は今日に近い年で、両方を渡したときは
    年のないほうを、もう片方と同じ年にそろえる（12/28〜1/3 のように、半年より大きく逆になるなら年をまたぐ）。"""
    def same_year(word, other, later):
        m = MD_DATE.match(word or "")
        o = datetime.date.fromisoformat(other)
        for y in (o.year, o.year + (1 if later else -1)):
            try:
                d = datetime.date(y, int(m.group(1)), int(m.group(2)))
            except ValueError:
                continue
            if (d >= o if later else d <= o) or abs((d - o).days) <= 183:
                return d.isoformat()
        raise ValueError(word)
    lo = list_date(start, today) if start else None
    hi = list_date(end, today) if end else None
    if lo and hi:
        if not ISO_DATE.match(end):
            hi = same_year(end, lo, True)
        elif not ISO_DATE.match(start):
            lo = same_year(start, hi, False)
    return lo, hi


def split_words(values):
    """くり返しと「,」「、」で区切った語の並び（空は外す）。"""
    return [w.strip() for v in values or [] for w in re.split(r"[,、]", v) if w.strip()]


def list_kind(ln):
    """行の状態の種類（done・doing・ready・hum・blocked。図の丸と同じ決め方）。"""
    return kind_of({"mark": ln["mark"], "state": ln.get("state") or ""})


def listing(t, holders=None, who=None, who_only=False, start=None, end=None, planned_only=False, states=None):
    """絞った一覧（teamkit/docs/views.md の7章）。t は tree の結果（link 済みでなければ link する）。
    一覧に入るのは、ツリー全体の自分でやる行と、枝に行のない束の行（枝のある束の行は出さず、枝の行で出る）。済んだ行も。
    who: 持ち手の名前の並び（末尾の -main は省いてよい）。既定は、その持ち手が任せた先（束をたどった子孫）の行も入れる。
    who_only なら、その持ち手の TASK.md に書いた行と、その持ち手の行（束の行の持ち手は子）だけ。
    start・end: 期間（"YYYY-MM-DD"。片方だけでもよい）。既定は期間に掛かる行: 未着手は着手予定日が期間の終わりまで
    （期間の前なら遅れ）、進行中は全部、済んだ行は済んだ日が期間の中。planned_only なら着手予定日が期間の中の行だけ。
    どちらでも、日付のない未着手の行と、済んだ日のない済んだ行は入らない。
    states: --state の語（done・doing・ready・human・blocked・open）の並び。
    返すのは着手日の順（同じ日と日付のない行はツリーの順。日付のない行はあと）の
    [{"ln"（行）, "kind", "holder"（持ち手の名前）, "path"（行を書いた TASK.md。根からの相対）}]。"""
    if not t.get("linked"):
        link(t, None, holders)
    base = t.get("base") or tree_base(t.get("path") or ".")
    want = {lane_name(snippet(x, NAME_MAX)) for w in who or [] for x in (w, w + "-main")}     # 持ち手の名前は約20字で切る（holder）
    got = []

    def rel(p):
        p = p if os.path.isabs(p) else os.path.join(base, p)
        return os.path.relpath(p, base).replace(os.sep, "/")

    def visit(node, name, path, chain):
        for ln in node.get("lines") or []:
            kids = ln.get("kids")
            if ln.get("dir") and kids is not None and kids.get("lines") and not ln.get("loop"):
                sub = holder(ln["dir"], kids.get("title") or "")
                visit(kids, sub, os.path.join(ln["dir"], "TASK.md"), chain + [sub])
                continue
            mine = bundle_name(ln) if ln.get("dir") else name
            got.append({"ln": ln, "kind": list_kind(ln), "holder": mine, "path": rel(path),
                        "_who": {name, mine} if who_only else set(chain) | {mine}})

    top = holder(os.path.dirname(t.get("path") or ""), t.get("title") or "")
    visit(t, top, t.get("path") or "TASK.md", [top])
    out = []
    for r in got:
        ln, kind = r.pop("ln"), r["kind"]
        if want and not {lane_name(n) for n in r.pop("_who")} & want:
            continue
        r.pop("_who", None)
        if states and not any(s == "open" and kind != "done" or LIST_STATES.get(s) == kind for s in states):
            continue
        if start or end:
            lo, hi = start or "0000-00-00", end or "9999-99-99"
            s, f = ln.get("start") or "", ln.get("finished") or ""
            if planned_only:
                hit = bool(s) and lo <= s <= hi and (kind != "done" or bool(f))
            elif kind == "done":
                hit = bool(f) and lo <= f <= hi
            elif kind == "doing":
                hit = True
            else:
                hit = bool(s) and s <= hi
            if not hit:
                continue
        r["ln"] = ln
        out.append(r)
    order = {id(r): i for i, r in enumerate(out)}
    return sorted(out, key=lambda r: (0 if r["ln"].get("start") else 1, r["ln"].get("start") or "", order[id(r)]))


def list_name(ln):
    """一覧の名前: 文面から日付・前提・束・Issue と、頭の番号を外したもの（図の下の一覧と同じ）。"""
    s = DATE.sub("", label(ln)).strip()
    no = ln.get("no") or ""
    if no and s.startswith(no):
        s = s[len(no):].strip()
    return s


def list_blockers(ln, short=False):
    """ブロッカー: まだ済んでいない待つものの番号（short なら短い形。見つからない番号は「?」を足す）、人の作業の語、
    呼び出す側が添えた待っているもの。束の行は、自分の枝の番号への待ちを出さない（図と同じ）。"""
    no = ln.get("no") or ""
    ws = [w for w in ln.get("waits") or [] if not (ln.get("dir") and no and w["no"].startswith(no + "-"))]
    return ([(short_no(w["no"]) if short else w["no"]) + ("" if w["found"] else "?") for w in ws]
            + list(ln.get("human") or []) + [f"{w.get('name', '')}が{w.get('state', '')}" for w in ln.get("wait") or []])


def short_md(d):
    return f"{int(d[5:7])}/{int(d[8:10])}" if d else ""


def list_terms(who=None, who_only=False, start=None, end=None, planned_only=False, states=None):
    """絞り込みの条件の1行の中身（「持ち手: S041-main と任せた先、期間: 11/25〜11/27 に掛かる行」）。条件がなければ ""。"""
    out = []
    if who:
        out.append("持ち手: " + "・".join(who) + (" だけ" if who_only else " と任せた先"))
    if start or end:
        span = short_md(start) if start == end else f"{short_md(start)}〜{short_md(end)}"
        out.append(f"期間: {span} " + ("に予定の行" if planned_only else "に掛かる行"))
    if states:
        out.append("状態: " + "・".join(LIST_WORDS.get(s, s) for s in states))
    return "、".join(out)


def list_cells(r):
    ln = r["ln"]
    return [STATE_MARKS.get(r["kind"]) or MARKS.get(r["kind"], "⬜"), short_md(ln.get("start")), short_md(ln.get("finished")),
            ln.get("no") or "", list_name(ln), ", ".join(list_blockers(ln)), " ".join("#" + n for n in ln.get("issues") or [])]


def list_md(got, terms=""):
    """絞った一覧を Markdown の表に（views.md の7章）。終わりに件数と条件の1行。"""
    cell = lambda s: str(s).replace("|", "\\|").replace("\n", " ")
    out = ["| " + " | ".join(LIST_COLS) + " |", "| " + " | ".join([":---"] * len(LIST_COLS)) + " |"]
    out += ["| " + " | ".join(cell(c) for c in list_cells(r)) + " |" for r in got]
    return "\n".join(out) + f"\n\n{len(got)} 件" + (f"（{terms}）" if terms else "") + "\n"


def list_json(got):
    """絞った一覧を JSON の配列（1件1行）に。項目の名前は英字。"""
    word = {v: k for k, v in LIST_STATES.items()}
    items = []
    for r in got:
        ln = r["ln"]
        items.append(json.dumps({"no": ln.get("no") or "", "name": list_name(ln), "desc": ln.get("desc") or "",
                                 "state": word.get(r["kind"], r["kind"]), "holder": r["holder"], "path": r["path"],
                                 "start": ln.get("start") or "", "finished": ln.get("finished") or "",
                                 "blockers": [w["no"] for w in ln.get("waits") or []
                                              if not (ln.get("dir") and ln.get("no") and w["no"].startswith(ln["no"] + "-"))],
                                 "human": list(ln.get("human") or []), "issues": [int(n) for n in ln.get("issues") or []]},
                                ensure_ascii=False))
    return "[\n" + ",\n".join(items) + "\n]\n" if items else "[]\n"


def list_csv(got):
    """絞った一覧を CSV に（UTF-8、BOM 付き、1行目は列の名前。列は md と同じに持ち手を足す。日付は YYYY-MM-DD）。"""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(LIST_COLS + ["持ち手"])
    for r in got:
        c = list_cells(r)
        c[1], c[2] = r["ln"].get("start") or "", r["ln"].get("finished") or ""
        w.writerow(c + [r["holder"]])
    return "\ufeff" + buf.getvalue()


LIST_JS = r"""
// 絞った一覧の1枚（tasktree.py --list --format html）。図の下の一覧と同じ見た目の表だけを描く（帯と丸は描かない）。
// L: {title, terms, issue_url, rows: [{kind, start, finished, no, tag, name, desc, blk, issues}]}
function drawTaskList(L,root){
  const el=(t,c,x)=>{const n=document.createElement(t);if(c)n.className=c;if(x!=null)n.textContent=x;return n};
  const md=d=>d?(+d.slice(5,7))+"/"+(+d.slice(8,10)):"";
  const ls=el("div","tg-list"+((root.clientWidth||innerWidth)<520?" narrow":""));ls.dataset.ui="tasklist";const ul=el("ul","tg-lrows");
  const hd=el("li","tg-row tg-lhead");hd.setAttribute("aria-hidden","true");
  for(const [c,x] of [["",""],["tg-rd","着手"],["tg-rd","済"],["tg-rt","番号"],["tg-rn","名前"],["tg-rs","ブロッカー"],["tg-ri","Issue"]])hd.append(el("span",c,x));
  ul.append(hd);
  L.rows.forEach((b,i)=>{const li=el("li","tg-row "+b.kind);li.dataset.ui="tasklist-row";
    const no=el("span","tg-rt",b.tag);if(b.no!==b.tag)no.title=b.no;
    const is=el("span","tg-ri");(b.issues||[]).forEach((n,k)=>{if(k)is.append(" ");
      if(!L.issue_url){is.append("#"+n);return}
      const a=el("a","","#"+n);a.href=L.issue_url+n;a.target="_blank";a.rel="noopener noreferrer";is.append(a)});
    const rn=el("span","tg-rn"),nm=el("span","tg-nm",b.name);rn.append(nm);
    li.append(tgIcon(b.kind,14),el("span","tg-rd",md(b.start)),el("span","tg-rd",md(b.finished)),no,rn,el("span","tg-rs",b.blk),is);
    ul.append(li);
    if(b.desc){nm.classList.add("has");nm.dataset.ui="tasklist-name-desc";nm.tabIndex=0;nm.setAttribute("role","button");nm.setAttribute("aria-expanded","false");
      const flip=()=>{const nx=li.nextElementSibling,o=!(nx&&nx.dataset.ui==="tasklist-desc");
        if(!o)nx.remove();else{const d=el("li","tg-row tg-dsc");d.dataset.ui="tasklist-desc";d.append(el("div","tg-dt",b.desc));li.after(d)}
        nm.setAttribute("aria-expanded",o?"true":"false")};
      nm.addEventListener("click",flip);nm.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();flip()}})}});
  ls.append(ul);const f=el("p","tg-lidle",L.rows.length+" 件"+(L.terms?"（"+L.terms+"）":""));f.dataset.ui="tasklist-count";
  ls.append(f);root.append(ls);
}
"""


def list_html(got, title="", terms="", issue_url=""):
    """絞った一覧を、図の下の一覧と同じ見た目の表1枚の HTML に（名前を押すと説明が開く）。"""
    data = {"title": title, "terms": terms, "issue_url": issue_url or "",
            "rows": [{"kind": r["kind"], "start": r["ln"].get("start") or "", "finished": r["ln"].get("finished") or "",
                      "no": r["ln"].get("no") or "", "tag": short_no(r["ln"].get("no") or ""), "name": list_name(r["ln"]),
                      "desc": r["ln"].get("desc") or "", "blk": ", ".join(list_blockers(r["ln"], short=True)),
                      "issues": list(r["ln"].get("issues") or [])} for r in got]}
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    head = html.escape("一覧 — " + (title or "TASK.md"))
    return ("<!doctype html>\n<html lang=\"ja\"><head><meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
            f"<title>{head}</title>\n<style>{DRAW_CSS}\n"
            ":root{color-scheme:dark;--bg:#181818}:root[data-theme=light]{color-scheme:light;--bg:#F8F8F8}\n"
            "body{margin:0;padding:12px 16px;background:var(--bg);color:var(--tg-fg);font:13px/1.5 system-ui,sans-serif}\n"
            "h1{font-size:14px;margin:0 0 8px}</style>\n"
            "<script>if(matchMedia(\"(prefers-color-scheme: light)\").matches)"
            "document.documentElement.dataset.theme=\"light\"</script>\n"
            f"</head><body><h1>{head}</h1><div id=\"g\"></div>\n<script>{DRAW_JS}\n{LIST_JS}\n"
            f"drawTaskList({blob},document.getElementById(\"g\"));\n"
            "</script></body></html>\n")


def text(t, all=False, title=True):
    """ツリー（tree の結果）を Markdown の箇条書きにする。1行目は TASK.md の見出し、続いて行ごとに
    印・文面・進み・Issue。束は枝の行を字下げする。済んだ行は「済 n 件」の1行にまとめる（all なら全部）。
    番号のない行があれば、終わりに「番号のない行 n 件（数えない）」。"""
    out = []
    if title:
        out.append("# " + (t.get("title") or t.get("head") or "TASK.md"))
    block(t.get("lines") or [], 0, all, out)
    if t.get("unnumbered"):
        out.append(f"- 番号のない行 {t['unnumbered']} 件（数えない）")
    return "\n".join(out) + "\n"


def block(lines, level, all, out):
    pad = "  " * level
    if not lines:
        out.append(pad + "- タスク一覧はありません")
        return
    done = [ln for ln in lines if ln["mark"] == "done"]
    if done and not all:
        out.append(f"{pad}- ✅ 済 {len(done)} 件")
    for ln in lines:
        if ln["mark"] == "done" and not all:
            continue
        mark = STATE_MARKS.get(ln.get("state")) or MARKS.get(ln["mark"], "⬜")      # link 済みなら、未着手は ⬜・✋・⏳
        parts = [mark, ln["text"] or "（文面なし）"]
        if "total" in ln and ln["total"]:
            parts.append(f"{ln['done']}/{ln['total']}")
        parts += ["#" + n for n in ln.get("issues") or []]
        if ln.get("loop"):
            parts.append("（上で開いている TASK.md）")
        out.append(pad + "- " + " ".join(parts))
        kids = ln.get("kids")
        if kids is not None:     # 済んだ行は上の「済 n 件」に畳むので、ここに来るのは済んでいないか all のとき
            if kids.get("path"):
                out.append(f"{pad}  - （{kids['path']}）")
            block(kids.get("lines") or [], level + 1, all, out)


def cli_holders(waiting):
    """--waiting の名前（くり返し・「,」「、」区切り）を、持ち手の状態の dict にする。なければ None。"""
    out = {}
    for v in waiting or []:
        for n in re.split(r"[,、]", v):
            if n.strip():
                out[n.strip()] = WAITING
    return out or None


def main(argv=None):
    ap = argparse.ArgumentParser(description="TASK.md のツリーを、束をたどって文字で書き出す（読むだけ）")
    ap.add_argument("path", nargs="?", default=".", help="TASK.md かフォルダ（既定: いまのフォルダ）")
    ap.add_argument("--text", action="store_true", help="Markdown の箇条書きで書き出す（既定）")
    ap.add_argument("--all", action="store_true", help="済んだ行も畳まずに出す")
    ap.add_argument("--plan", action="store_true", help="作業計画（空き・始められる・人待ち・待ち）を書き出す")
    ap.add_argument("--html", action="store_true", help="作業計画の図を1枚の HTML で書き出す（-o で書き出し先）")
    ap.add_argument("--waiting", action="append", default=[], metavar="持ち手",
                    help="人を待っている持ち手の名前（くり返すか「,」で区切る）。その持ち手に任せた束が人待ち")
    ap.add_argument("--root", metavar="フォルダ",
                    help="束の相対のパスを数える根（スプリントの写しのフォルダなど。既定: リポジトリ直下か、木ごと写したフォルダ）")
    ap.add_argument("--issue-url", metavar="URL",
                    help="Issue のリンクの頭（番号を足すと Issue のページ。既定: 根の git の設定の origin から）")
    ap.add_argument("--list", action="store_true", help="持ち手・期間・状態で絞った行の一覧を書き出す（--format で形）")
    ap.add_argument("--format", choices=["md", "json", "csv", "html"], default="md", help="--list の形（既定: md）")
    ap.add_argument("--who", action="append", default=[], metavar="持ち手",
                    help="--list: 持ち手の名前（くり返すか「,」で区切る。末尾の -main は省いてよい）。既定は任せた先の行も")
    ap.add_argument("--who-only", action="store_true", help="--list: その持ち手の TASK.md の行だけ（任せた先を入れない）")
    ap.add_argument("--from", dest="start", metavar="日", help="--list: 期間の始まり（11/25 か 2026-11-25）")
    ap.add_argument("--to", dest="end", metavar="日", help="--list: 期間の終わり（同じ日なら1日）")
    ap.add_argument("--planned-only", action="store_true", help="--list: 着手予定日が期間の中の行だけ（既定は期間に掛かる行）")
    ap.add_argument("--state", action="append", default=[], metavar="状態",
                    help="--list: done・doing・ready・human・blocked・open（くり返すか「,」で区切る）")
    ap.add_argument("-o", dest="out", help="書き出すファイル（既定: 標準出力）")
    a = ap.parse_args(argv)
    holders = cli_holders(a.waiting)
    used = [n for n, v in (("--who", a.who), ("--who-only", a.who_only), ("--from", a.start), ("--to", a.end),
                           ("--planned-only", a.planned_only), ("--state", a.state), ("--format", a.format != "md")) if v]
    if not a.list and used:
        ap.error(", ".join(used) + " は --list と使う")
    if a.list and (a.plan or a.html or a.text):
        ap.error("--list は --text・--plan・--html と一緒に使えない")
    if a.list:
        who, states = split_words(a.who), split_words(a.state)
        bad = [x for x in states if x not in LIST_WORDS]
        if bad:
            ap.error("--state に使えない語: " + ", ".join(bad) + "（" + "・".join(LIST_WORDS) + "）")
        try:
            start, end = list_span(a.start, a.end)
        except ValueError as e:
            ap.error(f"日付が読めません: {e}（11/25 か 2026-11-25）")
        if start and end and start > end:
            ap.error("--from が --to よりあとです")
        t = tree(a.path, holders, base=a.root)
        got = listing(t, holders, who, a.who_only, start, end, a.planned_only, states) if t is not None else []
        if who and t is not None:      # 見つからない持ち手の名前は、0 件と見分けられるように知らせる
            names = {lane_name(who_["name"]) for _, who_ in walk(t)}
            names |= {lane_name(bundle_name(ln)) for ln, _ in walk(t) if ln.get("dir")}
            for w in who:
                if not {lane_name(snippet(x, NAME_MAX)) for x in (w, w + "-main")} & names:
                    sys.stderr.write(f"tasktree.py: 持ち手 {w} はツリーにありません\n")
        terms = list_terms(who, a.who_only, start, end, a.planned_only, states)
        if a.format == "json":
            body = list_json(got)
        elif a.format == "csv":
            body = list_csv(got)
        elif a.format == "html":
            url = a.issue_url
            if url is None and t is not None:
                url = issue_base(t.get("base") or tree_base(t.get("path") or "."))
            title = (t.get("head") or t.get("title") or "") if t is not None else show_path(a.path)
            body = list_html(got, title, terms, url or "")
        else:
            body = list_md(got, terms)
        if a.out:
            with open(a.out, "w", encoding="utf-8", newline="") as f:
                f.write(body)
        else:
            sys.stdout.buffer.write(body.encode("utf-8"))
        return 0
    t = tree(a.path, holders, base=a.root)
    if t is None:
        body = f"# {show_path(a.path)}\n- タスク一覧はありません\n"
        if a.html:
            body = html_page({"title": show_path(a.path), "lanes": [], "boxes": [], "edges": [], "cycle": False,
                              "summary": ["タスク一覧はありません"]})
    elif a.html:
        body = html_page(graph(t, holders, issue_url=a.issue_url))
    elif a.plan:
        body = plan_text(plan(t, holders), t.get("head") or t.get("title") or "")
    else:
        link(t, None, holders)      # ⏳・✋ は前提から、🔄 は [/] と枝の印から求める（--plan・--html と同じ）
        body = text(t, all=a.all)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(body)
    else:
        sys.stdout.buffer.write(body.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
