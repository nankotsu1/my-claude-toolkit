#!/usr/bin/env python3
r"""スプリントの終わりの写しと片付け（teamkit/docs/taskmd.md の4章）。標準ライブラリだけ。

    python3 .claude/skills/sprint-end/sprint.py files                    # 木の TASK.md（根と、束をたどった先）
    python3 .claude/skills/sprint-end/sprint.py snapshot                 # 木ごと写しの置き場へ写す（写した先を出す）
    python3 .claude/skills/sprint-end/sprint.py clean --snapshot <写し>  # 消す行を見る（書かない）
    python3 .claude/skills/sprint-end/sprint.py clean --snapshot <写し> --write <TASK.md> ...   # 消す

- 根は、リポジトリ直下の TASK.md（`--root` で変えられる）。束（行の終わりの `→ <フォルダ>`）をたどって、木の TASK.md を
  集める。値の表の「持ち手の置き場所」（前の名前「部の置き場所」）の TASK.md も、束から指されていなくても入れる
- 写しの置き場は、値の表の「写しの置き場」。なければ `.worktrees/snapshots/`。その下にスプリントのフォルダ
  `YYYY-MM-DD`（同じ日に2回目なら `YYYY-MM-DD-2`）を作り、リポジトリ直下からの相対の位置のまま全文を写す
- 消すのは `## タスク` の節の、済んだ行だけ: `[x]` の行と、枝（子の TASK.md の、番号が束と同じか束の番号に `-` で
  続く行）が全部 `[x]` の束。行の下の深い字下げの行（細目）も一緒に消す。ほかの節（申し送りなど）には触れない
- `--write` は、名前を挙げた TASK.md だけを書き換える（持ち手が止まっているものだけを挙げる）。写しと中身が違う
  TASK.md は書き換えない（写したあとに変わった。写し直す）
- どの束からも指されなくなるフォルダ（部下の置き場所の候補。持ち手の置き場所は除く）は、出すだけで消さない
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import shutil
import subprocess
import sys

DEFAULT_PLACE = ".worktrees/snapshots/"
HEAD_12 = re.compile(r"\s{0,3}#{1,2}\s")
TASKS_HEAD = re.compile(r"\s{0,3}##\s+タスク\s*(?:[（(:：].*)?$")
FENCE = re.compile(r"\s{0,3}(`{3,}|~{3,})")
ITEM = re.compile(r"(\s*)(?:[-*+]|\d+[.)])\s+\[([ xX/])\]\s*(.*?)\s*$")
BUNDLE = re.compile(r"^(.*?)\s*(?:→|->)\s*(\S+?)\s*(?:#\d{1,5}\s*)*$")
NO = re.compile(r"\s*([A-Z]{1,5}(?:-\d+)+)(?![0-9A-Za-z-])")


def repo_base(start: str) -> str:
    """リポジトリ直下（worktree の中なら、もとのリポジトリ）。"""
    try:
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=start,
                                capture_output=True, text=True, check=True).stdout.strip()
        return os.path.dirname(common) if os.path.basename(common) == ".git" else os.path.abspath(start)
    except (OSError, subprocess.CalledProcessError):
        return os.path.abspath(start)


def table(base: str) -> dict:
    """値の表（teamkit/values.py）。読めなければ空。"""
    sys.path.insert(0, os.path.join(base, "teamkit"))
    try:
        import values  # type: ignore
        return values.load(base)
    except Exception:
        return {}


def holders(base: str) -> list[str]:
    """値の表の「持ち手の置き場所」（前の名前「部の置き場所」も）の TASK.md。束がなくても木に入れる。"""
    t = table(base)
    dirs = t.get("持ち手の置き場所") or t.get("部の置き場所") or []
    return [child_path(d, base) for d in dirs]


def place(base: str) -> str:
    """値の表の「写しの置き場」（なければ既定）の絶対パス。"""
    got = (table(base).get("写しの置き場") or [None])[0]
    p = os.path.expanduser(got or DEFAULT_PLACE)
    return os.path.normpath(p if os.path.isabs(p) else os.path.join(base, p))


def task_lines(text: str):
    """`## タスク` の節の行。[(行の番号, 字下げ, 印, 中身)]。節の最初の行と同じか浅い字下げの行だけ。"""
    out, inside, fence = [], False, False
    for i, raw in enumerate(text.splitlines()):
        if FENCE.match(raw):
            fence = not fence
            continue
        if fence:
            continue
        if HEAD_12.match(raw):
            if inside:
                break
            inside = bool(TASKS_HEAD.match(raw))
            continue
        m = ITEM.match(raw) if inside else None
        if m:
            out.append((i, len(m.group(1).expandtabs(4)), m.group(2).lower(), m.group(3)))
    if not out:
        return []
    top = out[0][1]
    return [r for r in out if r[1] <= top]


def lead_no(body: str) -> str:
    m = NO.match(body)
    return m.group(1) if m else ""


def bundle_to(body: str) -> str:
    m = BUNDLE.match(body)
    return m.group(2) if m and not m.group(2).startswith("#") else ""


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def child_path(to: str, base: str) -> str:
    to = os.path.expanduser(to)
    if os.path.basename(to) == "TASK.md":
        to = os.path.dirname(to)
    return os.path.normpath(os.path.join(to if os.path.isabs(to) else os.path.join(base, to), "TASK.md"))


def collect(root: str, base: str, extra=()) -> dict:
    """木の TASK.md → {"text", "rows": [{"i", "indent", "mark", "body", "no", "to"(子の TASK.md の絶対パス)}]}。
    extra: 束から指されていなくても読む TASK.md（持ち手の置き場所）。根と束をたどったあとに足す。"""
    out, todo = {}, [os.path.abspath(root)]
    while todo:
        p = todo.pop(0)
        if p in out or not os.path.isfile(p):
            continue
        text = read(p)
        rows = []
        for i, ind, mark, body in task_lines(text):
            to = bundle_to(body)
            r = {"i": i, "indent": ind, "mark": mark, "body": body, "no": lead_no(body),
                 "to": child_path(to, base) if to else ""}
            rows.append(r)
            if r["to"]:
                todo.append(r["to"])
        out[p] = {"text": text, "rows": rows}
        if not todo and extra:
            todo, extra = list(extra), ()
    return out


def branches(r: dict, nodes: dict) -> list:
    kid = nodes.get(r["to"])
    if not kid or not r["no"]:
        return []
    return [k for k in kid["rows"] if k["no"] == r["no"] or k["no"].startswith(r["no"] + "-")]


def is_done(r: dict, nodes: dict, _seen=frozenset()) -> bool:
    if r["mark"] == "x":
        return True
    if not r["to"] or r["to"] in _seen:
        return False
    br = branches(r, nodes)
    return bool(br) and all(is_done(k, nodes, _seen | {r["to"]}) for k in br)


def done_lines(path: str, nodes: dict) -> list[int]:
    """消す行の番号（細目の行も）。"""
    text_lines = nodes[path]["text"].splitlines()
    out = []
    for r in nodes[path]["rows"]:
        if not is_done(r, nodes):
            continue
        out.append(r["i"])
        j = r["i"] + 1
        while j < len(text_lines):
            s = text_lines[j]
            if not s.strip() or len(s) - len(s.lstrip()) <= r["indent"] or HEAD_12.match(s):
                break
            out.append(j)
            j += 1
    return out


def rel(p: str, base: str) -> str:
    return os.path.relpath(p, base)


def cmd_files(nodes, base, _a):
    for p in nodes:
        print(rel(p, base))
    return 0


def cmd_snapshot(nodes, base, a):
    top = os.path.abspath(a.to) if a.to else place(base)
    name = a.name or _dt.date.today().isoformat()
    dest, n = os.path.join(top, name), 1
    while os.path.exists(dest):
        n += 1
        dest = os.path.join(top, f"{name}-{n}")
    for p in nodes:
        q = os.path.join(dest, rel(p, base))
        os.makedirs(os.path.dirname(q), exist_ok=True)
        shutil.copy2(p, q)
    print(dest)
    for p in nodes:
        print(f"  {rel(p, base)}")
    return 0


def cmd_clean(nodes, base, a):
    snap = os.path.abspath(a.snapshot)
    write = {os.path.abspath(w) for w in (a.write or [])}
    bad = [w for w in write if w not in nodes]
    if bad:
        print("木にない TASK.md: " + ", ".join(rel(w, base) for w in bad), file=sys.stderr)
        return 2
    gone, rc = set(), 0
    for p, node in nodes.items():
        drop = done_lines(p, nodes)
        lines = node["text"].splitlines(keepends=True)
        print(f"== {rel(p, base)}: 消す行 {sum(1 for r in node['rows'] if r['i'] in drop)}")
        for r in node["rows"]:
            if r["i"] in drop:
                print(f"  - [{r['mark']}] {r['body'][:80]}")
                if r["to"]:
                    gone.add(r["to"])
        if p not in write or not drop:
            continue
        copy = os.path.join(snap, rel(p, base))
        if not os.path.isfile(copy) or read(copy) != node["text"]:
            print(f"  書かない: 写し {copy} がないか、写したあとに変わった（写し直す）", file=sys.stderr)
            rc = 1
            continue
        with open(p, "w", encoding="utf-8") as f:
            f.write("".join(l for k, l in enumerate(lines) if k not in drop))
        print("  書いた")
    kept = {r["to"] for p, node in nodes.items() for r in node["rows"]
            if r["to"] and r["i"] not in done_lines(p, nodes)}
    orphans = sorted(os.path.dirname(g) for g in gone - kept - set(a.holders) if os.path.isdir(os.path.dirname(g)))
    if orphans:
        print("どの束からも指されなくなるフォルダ（部下の置き場所なら片付ける。消すのは人の許可で）:")
        for d in orphans:
            print(f"  {rel(d, base)}")
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="スプリントの終わりの写しと片付け")
    ap.add_argument("--root", help="根の TASK.md（既定はリポジトリ直下の TASK.md）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("files", help="木の TASK.md を出す")
    s = sub.add_parser("snapshot", help="木ごと写す")
    s.add_argument("--to", help="写しの置き場（既定は値の表の「写しの置き場」）")
    s.add_argument("--name", help="スプリントのフォルダの名前（既定は今日の日付）")
    c = sub.add_parser("clean", help="済んだ行を消す（--write がなければ見るだけ）")
    c.add_argument("--snapshot", required=True, help="写したスプリントのフォルダ")
    c.add_argument("--write", nargs="+", metavar="TASK.md", help="書き換える TASK.md（止まっている持ち手のもの）")
    a = ap.parse_args(argv)
    base = repo_base(os.getcwd())
    root = os.path.abspath(a.root) if a.root else os.path.join(base, "TASK.md")
    if not os.path.isfile(root):
        print(f"根の TASK.md がない: {root}", file=sys.stderr)
        return 2
    a.holders = holders(base)
    nodes = collect(root, base, a.holders)
    return {"files": cmd_files, "snapshot": cmd_snapshot, "clean": cmd_clean}[a.cmd](nodes, base, a)


if __name__ == "__main__":
    sys.exit(main())
