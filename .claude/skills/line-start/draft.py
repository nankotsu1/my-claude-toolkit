#!/usr/bin/env python3
"""ラインを立てるときの TASK.md の下書きを作る（line-start スキル）。

統括（Manager-main）が、前提の済んだ作業単位（SBI）にラインを立てるとき、リポジトリ直下で動かす。
台帳のその番号の節と、ひな形（teamkit/templates/TASK.template.md）から埋める。台帳の場所・報告の写し先・
ポートの枠・決まりの文書・本番は、導入したリポジトリの値の表（.claude/teamkit.md。teamkit/values.py で読む）から。
値の表にない値は <…> のまま残し、注意に出す。

    python3 .claude/skills/line-start/draft.py SBI-041              # 下書きを標準出力に（書かない）。注意は標準エラーに
    python3 .claude/skills/line-start/draft.py SBI-041 --write      # 置き場所 .worktrees/S041/ を作り、TASK.md を書く（無いときだけ）
    python3 .claude/skills/line-start/draft.py SBI-041-1 --write    # 子の行を1本のラインにするときも同じ（フォルダは S041）

台帳とひな形は origin/main から読む（無ければ手元のファイル）。--ledger・--template・--values で別のファイルも読める（試す用）。

ラインの置き場所（.worktrees/S<番号>）は TASK.md だけを置くフォルダで、git の worktree にしない。--write は置き場所を作り、
git がそこで止まるように空を指す .git ファイルを置く。作業はラインが作業の場所（値の表の「作業の場所」。`直下` が既定で、
リポジトリ直下でブランチを切る。`worktree` か直下が塞がっていれば、仕事ごとの一時の worktree）でする。

埋めるもの: 見出し（# S<番号>-main: <名前>）、## タスク の行（台帳の子の行の表か、作るものの箇条書きから
<番号>-<連番> を振る。最後に「テスト・レビュー・PR」の行。名前は20字まで、作るものと確かめ方の要点は行の下の
「- 説明: …」に）、持ち場（触る所）、材料（台帳の節の作るもの・確かめ方）、
この作業単位の値（ブランチ・フォルダ・ポートの枠・PR のタイトル・報告の写し先・実機確認）、並行して動いているもの
（台帳の「ファイルが重なる所」でこの番号に触れる文）。

ラインの TASK.md には前提を書かない（前提を書くのは親の TASK.md だけで、持ち手をまたぐ待ち合わせは
統括の行の前提で表し、済んだら統括がラインに知らせる）。着手予定日も書かない（中の行の日付はラインが書く）。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import os
import re
import subprocess
import sys

TEMPLATE = "teamkit/templates/TASK.template.md"
VALUES = ".claude/teamkit.md"
UNIT_RE = re.compile(r"^SBI-(\d{3,4})((?:-\d+)*)$")
LAST_ROW = "テスト・レビュー・PR"
LAST_DESC = "全部のテストを流し、セルフレビューをして PR を出す（実機確認が要れば手順を PR に）"
NAME_MAX = 20       # 行の名前の目安（teamkit/docs/taskmd.md の2章）。超えたら切って、もとの文は説明に回す
DESC_MAX = 120      # 説明に写す要点の長さ。全文は材料の節にある
# 置き場所に置く .git ファイル。gitdir が無い所を指すので、置き場所で使った git は「not a git repository」で止まる
# （止めないと、git は上へたどってリポジトリ直下の main に当たる）。
GUARD = "gitdir: TASK.md だけの置き場所。git は作業の場所で使う\n"


def _run(cmd: list[str], cwd: str | None = None) -> str:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True).stdout


# ---------------------------------------------------------------- 台帳を読む

def unit_names(unit_id: str) -> dict[str, str]:
    """SBI-041-1 → {folder: S041, session: S041-main, branch: SBI-041-1, number: 41}。"""
    m = UNIT_RE.match(unit_id)
    if not m:
        raise ValueError(f"作業単位の番号の形ではない: {unit_id}（SBI-041、SBI-041-2 の形。部の仕事 REQ-・HAR- はラインにしない）")
    num = m.group(1)
    return {"folder": f"S{num}", "session": f"S{num}-main", "branch": unit_id, "number": int(num)}


def _num(values: dict, key: str) -> int | None:
    v = (values.get(key) or [None])[0]
    return int(v) if v and v.isdigit() else None


def port_range(number: int, values: dict, slot: int | None = None) -> str | None:
    """ラインの模擬環境のポートの枠（値の表の始まり・枠の数・幅から）。値の表になければ None。"""
    base, slots, width = (_num(values, k) for k in ("ラインのポートの始まり", "ラインのポートの枠の数", "ラインのポートの枠の幅"))
    if base is None or not slots or not width:
        return None
    k = number % slots if slot is None else slot
    lo = base + width * k
    return f"{lo}〜{lo + width - 1}"


def _codes(vals: list[str]) -> str:
    return "・".join(f"`{v}`" for v in vals)


def section(ledger_md: str, unit_id: str) -> tuple[str, str]:
    """(見出しの名前, 節の本文)。「## <番号> <名前>」か「### <番号> <名前>」から、同じか浅い見出しの手前まで。"""
    m = re.search(rf"^(#{{2,4}}) {re.escape(unit_id)}(?:[ \t]+([^\n]*))?\n", ledger_md, re.M)
    if not m:
        raise ValueError(f"台帳に {unit_id} の節（## {unit_id} <名前>）がない。要求分析部に作業計画を頼む")
    level = len(m.group(1))
    rest = ledger_md[m.end():]
    end = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return (m.group(2) or "").strip(), (rest[:end.start()] if end else rest).strip("\n")


def table_name(ledger_md: str, unit_id: str) -> str:
    """一覧や子の行の表で、その番号の行の2列目（名前）。"""
    m = re.search(rf"^\|\s*{re.escape(unit_id)}\s*\|\s*([^|]+?)\s*\|", ledger_md, re.M)
    return m.group(1) if m else ""


def field(body: str, name: str, *, note: bool = False) -> str:
    """節の「- <name>: …」の中身（続く字下げの行も）。

    名前の直後の括弧の注記（「- 作るもの（spec の …。図解 …）:」）も読む。中身が字下げの入れ子の
    箇条書きだけでもよい。note=True なら注記を中身の頭に付けて返す（材料の写し用）。
    """
    m = re.search(rf"^- {re.escape(name)}[ \t]*(（[^（）\n]*）)?[:：][ \t]*(.*?)(?=^- [^\n]*[:：]|^\S|\Z)",
                  body + "\n", re.M | re.S)
    if not m:
        return ""
    val = m.group(2).rstrip()
    if note and m.group(1):
        val = f"{m.group(1)}{val if val.startswith(chr(10)) else ' ' + val}".rstrip()
    return val.strip("\n") if not note else val


def _short(text: str) -> str:
    """行の名前のもとにする形: 最初の「: 」の前（あれば）、改行と行頭の記号を外す。終わりの（…）は外す。"""
    t = re.sub(r"\s+", " ", text).strip()
    m = re.match(r"^(.+?)[:：]\s", t)
    if m and len(m.group(1)) >= 2:
        t = m.group(1)
    m = re.match(r"^(.{2,}?)（[^（）]*）$", t)      # 終わりの（…）は材料の写しにあるので外す
    if m:
        t = m.group(1)
    return t


def name_of(text: str, limit: int = NAME_MAX) -> tuple[str, bool]:
    """(行の名前, 縮めたか)。_short の形が長ければ、括弧の中を外し、それでも長ければ区切り（、・）で切る。なければ「…」で切る。"""
    t = _short(text)
    if len(t) <= limit:
        return t, False
    u = re.sub(r"（[^（）]*）|\([^()]*\)", "", t).strip()
    if len(u) < 2:              # 括弧を外すと何も残らないときは、そのまま切る
        u = t
    if 2 <= len(u) <= limit:
        return u, True
    head = u[:limit]
    cut = max(head.rfind(c) for c in "、・")
    return (head[:cut] if cut >= 4 else u[:limit - 1] + "…"), True


def gist(text: str, limit: int = DESC_MAX) -> str:
    """説明に写す要点: 改行と行頭の記号を外し、文（。で終わる）を limit まで。1文目から長ければ切る。"""
    t = re.sub(r"\s+", " ", re.sub(r"^\s*-\s+", "", text, flags=re.M)).strip()
    out = ""
    for sent in _sentences(t):
        if not sent.strip():
            continue
        if len(out) + len(sent) > limit:
            break
        out += sent
    return (out or (t if len(t) <= limit else t[:limit - 1] + "…")).strip()


def _sentences(t: str) -> list[str]:
    """括弧の外の「。」で文に分ける（括弧の中の「。」では切らない）。"""
    out, cur, depth = [], "", 0
    for ch in t:
        cur += ch
        depth += ch in "（(「" and 1 or 0
        depth -= ch in "）)」" and 1 or 0
        if ch == "。" and depth <= 0:
            out.append(cur)
            cur, depth = "", 0
    return out + ([cur] if cur else [])


def _rest(text: str) -> str:
    """箇条書き1つの、名前（最初の「: 」の前）より後ろ。区切りがなければ全文。"""
    t = re.sub(r"\s+", " ", text).strip()
    m = re.match(r"^(.+?)[:：]\s+(.*)$", t)
    return m.group(2) if m and len(m.group(1)) >= 2 else t


def rows(ledger_md: str, body: str, unit_id: str, check: str = "") -> tuple[list[tuple[str, str]], bool]:
    """## タスク の行の (「<番号> <名前>」, 説明)、名前を縮めた行があったか。

    子の行の表があればそれ（説明は子の節の作るもの・確かめ方の要点）、なければ作るものの箇条書きから
    （説明は箇条書きの名前より後ろ）。説明が名前と同じなら空。最後の行の説明に、確かめ方の要点。
    """
    out: list[tuple[str, str]] = []
    cut_any = False
    kids = re.findall(rf"^\|\s*({re.escape(unit_id)}-\d+)\s*\|\s*([^|]+?)\s*\|", body, re.M)
    if kids:
        for n, full in kids:
            name, cut = name_of(full)
            try:
                _, sub = section(ledger_md, n)
            except ValueError:
                sub = ""
            own = re.split(r"^#{2,4} ", sub, maxsplit=1, flags=re.M)[0]
            mk, ck = field(own, "作るもの"), field(own, "確かめ方")
            parts = ([full.rstrip("。") + "。"] if cut else []) + ([gist(mk, 100)] if mk else [])   # 縮めた名前のもとの文は説明の頭に
            if ck:
                parts.append("確かめ方: " + gist(ck, 60))
            out.append((f"{n} {name}", " ".join(parts)))
            cut_any |= cut
    else:
        make = field(body, "作るもの")
        items = re.findall(r"^  - (.+(?:\n {4,}.+)*)", make, re.M)
        texts = items or ([make] if make.strip() else [])
        for i, t in enumerate(texts, 1):
            name, cut = name_of(t)
            desc = gist(_rest(t))
            out.append((f"{unit_id}-{i} {name}", "" if desc == name else desc))
            cut_any |= cut
    last = LAST_DESC + ("。確かめ方: " + gist(check) if check else "")
    used = [int(row.split(" ", 1)[0].rsplit("-", 1)[1]) for row, _ in out]
    out.append((f"{unit_id}-{max(used, default=0) + 1} {LAST_ROW}", last))
    return out, cut_any


def task_lines(items: list[tuple[str, str]]) -> str:
    """行と、その下に1段字下げした「- 説明: …」（説明があれば）。"""
    lines = []
    for row, desc in items:
        lines.append(f"- [ ] {row}")
        if desc:
            lines.append(f"  - 説明: {desc}")
    return "\n".join(lines)


def overlaps(ledger_md: str, unit_id: str, parent: str | None) -> list[str]:
    """「ファイルが重なる所:」の文のうち、この番号（か親の番号ちょうど）に触れるもの。"""
    out = []
    for m in re.finditer(r"^ファイルが重なる所[:：]\s*(.+)$", ledger_md, re.M):
        for sent in re.split(r"(?<=。)", m.group(1)):
            s = sent.strip()
            if s and (re.search(rf"{re.escape(unit_id)}(?:-\d+)*(?![-\d])", s)
                      or (parent and re.search(rf"{re.escape(parent)}(?![-\d])", s))):
                out.append(s)
    return out


# ---------------------------------------------------------------- 下書き

def replace_section(text: str, name: str, body: str) -> str:
    """ひな形の「## <name>」の中身を body に置き換える（見出しは残す）。"""
    m = re.search(rf"^## {re.escape(name)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not m:
        raise ValueError(f"ひな形に {name} の節がない")
    return text[:m.start(1)] + "\n" + body.strip("\n") + "\n\n" + text[m.end(1):]


def build_draft(*, ledger_md: str, template_md: str, unit_id: str, now: str, values: dict | None = None,
                port_slot: int | None = None) -> tuple[str, list[str]]:
    """(下書き, 注意)。values は値の表（項目 → 値の並び。teamkit/values.py の load）。"""
    values = values or {}
    nm = unit_names(unit_id)
    title, body = section(ledger_md, unit_id)
    title = title or table_name(ledger_md, unit_id)
    title = re.sub(r"\s*（[^（）]*\d{4}-\d{1,2}-\d{1,2}[^（）]*）$", "", title)   # 見出しの終わりの日付の注記（「（2025-06-02、承認）」）は外す
    notes: list[str] = []
    if not title:
        notes.append("作業単位の名前が台帳から取れない。見出しの <名前> を埋める")
        title = "<名前>"
    parent = unit_id.rsplit("-", 1)[0] if unit_id.count("-") >= 2 else None
    own = re.split(r"^#{2,4} ", body, maxsplit=1, flags=re.M)[0]     # 子の節（### SBI-xxx-n）の手前まで
    make, check, touch = field(own, "作るもの"), field(own, "確かめ方"), field(own, "触る所")
    if re.search(rf"^\|\s*{re.escape(unit_id)}-\d+\s*\|", own, re.M):      # 子の行の表がある
        see = f"子の行の節（台帳の `### {unit_id}-<連番>`）を読む"
        make, check, touch = make or see, check or see, touch or see
    for label, val in (("作るもの", make), ("確かめ方", check), ("触る所", touch)):
        if not val:
            notes.append(f"台帳の節に「{label}」がない。要求分析部に作業計画を頼むか、手で埋める")
    ledger = (values.get("台帳") or ["<台帳>"])[0]
    rules = values.get("決まりの文書") or []
    verify = (values.get("実機確認の基準") or ["teamkit/docs/verify.md"])[0]
    records = (values.get("報告の写し先") or [None])[0]
    prod = values.get("本番（触らない）") or []
    live = "実機確認" in own
    if not live:
        notes.append(f"実機確認が要るかを決めて、この作業単位の値に書く（{verify} の基準）")
    work = (values.get("一時の worktree") or [None])[0]
    work = work.replace("<番号>", nm["branch"]) if work else "<一時の worktree>"
    place = (values.get("作業の場所") or ["直下"])[0]
    if place not in ("直下", "worktree"):
        notes.append(f"値の表の「作業の場所」が `{place}`。`直下` か `worktree` にする（下書きは直下で書いた）")
        place = "直下"
    br = nm["branch"]
    add = f"`git fetch origin && git worktree add {work} -b {br} origin/main`"
    if place == "直下":
        place_line = (f"- 作業の場所: 直下（値の表）。直下が空いているか（ブランチが既定のブランチで、コミットしていない変更がない）を、"
                      f"リポジトリ直下で `git branch --show-current`・`git status --porcelain`（何も出なければ空き。git に入っていない新しいファイルも数える）で見る。空いていれば直下で "
                      f"`git fetch origin && git switch -c {br} origin/main`。塞がっていれば一時の worktree "
                      f"`{work}` を作る（リポジトリ直下から {add}）。どちらで作業しているかを申し送りに書く")
        branch_note = f"まだない。ラインが直下（塞がっていれば一時の worktree {work}）で origin/main から切る"
    else:
        place_line = (f"- 作業の場所: 一時の worktree `{work}`（値の表が worktree。リポジトリ直下から {add}。"
                      "作業とコミットはこの中で。直下ではブランチを切らない）")
        branch_note = f"まだない。ラインが一時の worktree {work} を origin/main から作って切る"
    ports = port_range(nm["number"], values, port_slot)
    if ports is None:
        notes.append("値の表にラインのポートの枠がない。模擬環境を使うなら手で埋める")

    t = template_md
    t = re.sub(r"^# [^\n]*", f"# {nm['session']}: {unit_id} {title}", t, count=1, flags=re.M)
    intro = (f"あなたは「{nm['session']}」。作業単位 {unit_id} を1つだけ受け持つライン（済んだら閉じる）。"
             "統括（Manager-main）から立ち上げられ、【完了】【質問】は統括へ送る。"
             f"決まりは `teamkit/docs/line_rules.md`{'・' + _codes(rules) if rules else ''} と値の表 `{VALUES}`（セッションの始めに1回読む）。")
    t = re.sub(r"^あなたは「[^\n]*", intro, t, count=1, flags=re.M)
    t = re.sub(r"^フェーズ: [^\n]*", "フェーズ: 実装", t, count=1, flags=re.M)
    items, cut = rows(ledger_md, own, unit_id, check if not check.startswith("子の行の節") else "")
    if cut:
        notes.append(f"名前が{NAME_MAX}字を超えた行を縮めた（もとの文は説明か材料に）。名前を見直す")
    t = replace_section(t, "タスク", task_lines(items))
    t = replace_section(t, "持ち場", "\n".join([
        f"- 台帳の触る所: {touch or '<触る所>'}",
        "- **触らない**: 上に書いていない所。並行して動いているものの持ち場",
    ]))
    t = replace_section(t, "材料", "\n".join([
        f"- 作業計画の正: 台帳 `{ledger}` の「{unit_id}」の節（作るもの・確かめ方・触る所）。食い違うときは台帳に従う",
        f"- 作るもの（写し）: {field(own, '作るもの', note=True) or make or '<作るもの>'}",
        f"- 確かめ方（写し）: {check or '<確かめ方>'}",
        "- 大きな文書は節だけ読む（`teamkit/docs/line_rules.md` の6章）",
    ]))
    values = "\n".join([
        f"- 置き場所: `.worktrees/{nm['folder']}`（TASK.md だけ。git を使わない）",
        f"- ブランチ: `{br}`",
        place_line,
        f"- 模擬環境のポート: {ports or '<ポートの範囲。使わなければこの行を消す>'}（番号で決まる枠。重なるときは統括がここを書き換える）",
        f"- PR のタイトル: `{unit_id}: {title}`。本文に Issue があれば `Closes #<Issue>`、なければ書かない",
        f"- 報告の写し先: `{records.rstrip('/') + '/' + unit_id + '.md'}`" if records else "- 報告の写し先: <報告の写し先>",
        f"- 【完了】の1行目: `【完了】{unit_id} をマージしました`（最後に「人が判断すること:」「止まっている:」）",
        "- 実機確認: " + (f"あり（台帳に書いてある。手順と要るかは `{verify}`）" if live
                       else f"<要るか。`{verify}` の基準で決める>"),
    ])
    over = overlaps(ledger_md, unit_id, parent)
    para = "\n".join(f"- {s}" for s in over) if over else "- <並行して動いているラインや部と、ぶつかる所。統括が書き足す>"
    extra = f"## この作業単位の値\n\n{values}\n\n## 並行して動いているもの\n\n{para}\n\n"
    if re.search(r"^## メモ\n", t, re.M):
        t = replace_section(t, "メモ", "- なし（番号を付けない覚え書き。道具は読まない）")
    m = re.search(r"^## (?:メモ|報告)\n", t, re.M)     # この作業単位の値は、メモ（なければ報告）の手前に
    if not m:
        raise ValueError("ひな形に 報告 の節がない")
    t = t[:m.start()] + extra + t[m.start():]
    handover = "\n".join([
        f"更新: {now} ・ {nm['session']}（統括が下書き） ・ 理由: 立ち上げ",
        "",
        "### いまの状態",
        f"- 作業: まだ始めていない。統括が line-start で {unit_id} の下書きを作った",
        f"- ブランチ: {br}（{branch_note}）",
        "- 未コミット: なし",
        "- 動かしているもの: なし",
        "",
        "### 次にやること",
        "1. 残った <…> を台帳と Issue から埋める",
        f"2. `teamkit/docs/line_rules.md` の進め方の 0 から（作業の場所を用意する。止まったら「"
        f".worktrees/{nm['folder']}/TASK.md を読んで再開して」）",
        "",
        "### 待っている返事",
        "- なし",
        "",
        "### 注意",
        (f"- 本番（{_codes(prod)}）には触れない" if prod else "- 本番には触れない（入れる・更新するのは人だけ）"),
        "- この TASK.md の行には、ほかの持ち手の番号を前提に書かない（待ち合わせは統括の行の前提。済んだら統括が知らせる）",
    ])
    t = replace_section(t, "申し送り", handover)
    left = sorted(set(re.findall(r"<[^<>\n]{1,40}>", t)) - {"<Issue>", "<…>"})
    if left:
        notes.append("まだ埋めていない: " + "、".join(left))
    return t.rstrip("\n") + "\n", notes


# ---------------------------------------------------------------- 入出力

def repo_root() -> str:
    first = _run(["git", "worktree", "list", "--porcelain"]).splitlines()[0]
    return first.removeprefix("worktree ")


def load_values(root: str, given: str | None = None) -> dict:
    """値の表（teamkit/values.py の load）。部品は、リポジトリ直下の teamkit/ か、このスクリプトのあるリポジトリのもの。"""
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "teamkit")
    for d in (os.path.join(root, "teamkit"), here):
        path = os.path.join(d, "values.py")
        if os.path.exists(path):
            spec = importlib.util.spec_from_file_location("teamkit_values", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.load(root, given)
    return {}


def read_doc(path: str, given: str | None, root: str) -> str:
    if given:
        with open(given, encoding="utf-8") as fh:
            return fh.read()
    try:
        return _run(["git", "show", f"origin/main:{path}"], root)
    except subprocess.CalledProcessError:
        with open(os.path.join(root, path), encoding="utf-8") as fh:
            return fh.read()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ラインを立てるときの TASK.md の下書きを作る（統括が、リポジトリ直下で使う）")
    ap.add_argument("unit", help="作業単位の番号（SBI-041、子の行を1本にするなら SBI-041-1）")
    ap.add_argument("--write", action="store_true", help="置き場所 .worktrees/S<番号>/ を作り、TASK.md を書く（無いときだけ）")
    ap.add_argument("--force", action="store_true", help="TASK.md があっても書く")
    ap.add_argument("--port-slot", type=int, help="ポートの枠（0 から、値の表の枠の数より小さい数。同じ枠のラインが動いているとき）")
    ap.add_argument("--root", help="リポジトリ直下（既定: git worktree list の最初）")
    ap.add_argument("--ledger", help="台帳のファイル（既定: origin/main の、値の表の「台帳」）")
    ap.add_argument("--values", help=f"値の表のファイル（既定: <リポジトリ直下>/{VALUES}）")
    ap.add_argument("--template", help=f"ひな形のファイル（既定: origin/main の {TEMPLATE}）")
    a = ap.parse_args(argv)
    try:
        root = a.root or repo_root()
        nm = unit_names(a.unit)
        values = load_values(root, a.values)
        ledger = (values.get("台帳") or [None])[0]
        if not a.ledger and not ledger:
            raise ValueError(f"値の表（{VALUES}）に「台帳」がない。値の表に台帳の場所を書くか、--ledger で渡す")
        slots = _num(values, "ラインのポートの枠の数")
        if a.port_slot is not None and not slots:
            raise ValueError("値の表にラインのポートの枠の数がないので、--port-slot は使えない")
        if a.port_slot is not None and not 0 <= a.port_slot < slots:
            raise ValueError(f"--port-slot は 0〜{slots - 1}")
        draft, notes = build_draft(ledger_md=read_doc(ledger or "", a.ledger, root), values=values,
                                   template_md=read_doc(TEMPLATE, a.template, root),
                                   unit_id=a.unit, now=_dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                                   port_slot=a.port_slot)
    except (ValueError, OSError, subprocess.CalledProcessError) as e:
        print(f"下書きを作れません: {e}", file=sys.stderr)
        return 2
    if a.write:
        wt = os.path.join(root, ".worktrees", nm["folder"])
        path = os.path.join(wt, "TASK.md")
        if os.path.exists(path) and not a.force:
            print(f"書いていません: {path} がもうある（前のラインの TASK.md？）。置き換えるなら --force", file=sys.stderr)
            return 1
        os.makedirs(wt, exist_ok=True)
        guard = os.path.join(wt, ".git")
        if not os.path.lexists(guard):          # .git がもうある置き場所（git の worktree にした置き場所など）は触らない
            with open(guard, "w", encoding="utf-8") as fh:
                fh.write(GUARD)
        tmp = path + ".draft-tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(draft)
        os.replace(tmp, path)
        print(f"{path} を {a.unit} の下書きにしました")
    else:
        print(draft, end="")
    for n in notes:
        print("注意: " + n, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
