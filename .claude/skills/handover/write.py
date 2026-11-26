#!/usr/bin/env python3
"""TASK.md の申し送りの節だけを、安全に差し替える（handover スキル）。

    python3 .claude/skills/handover/write.py TASK.md < 新しい申し送り.md
    python3 .claude/skills/handover/write.py TASK.md --from 新しい申し送り.md

- 新しい申し送りは「## 申し送り」の見出しの行から書く（見出しがなければ足す）
- 差し替えるのは、行頭が「## 申し送り」の見出しの行から、次の「# 」か「## 」の見出しの手前（なければ末尾）まで
  だけ。本文の途中にある「## 申し送り」という文字列（「下の『## 申し送り』を更新する」など）や、
  コードブロックの中の見出しには当たらない
- 見出しの節がなければ、末尾に足す
- 書く前に、差し替えたあとの「## 」の見出しの数と並びが、申し送りの節を除いて変わっていないかを確かめる。
  変わっていたら書かずに止める（本文の文字列に当たると、そこから最後までを消してしまうため）
"""
from __future__ import annotations

import argparse
import os
import re
import sys

HEAD_RE = re.compile(r"^##\s+申し送り\s*$")


def headings(lines: list[str]) -> list[tuple[int, str]]:
    """コードブロックの外の「# 」「## 」の見出し（行番号, 行）。"""
    out, fence = [], False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if not fence and re.match(r"^#{1,2} ", line):
            out.append((i, line.rstrip()))
    return out


def odd_headings(lines: list[str]) -> list[tuple[int, str]]:
    """見出しとして不自然な「## 」の行（本文の折り返しが行頭に来たもの）。

    括弧（「（…）」「(…)」）の中を除いて、句点「。」を含む、または 40 文字を超える「## 」の見出し
    （最初の「# 」の見出しは長くてよいので見ない）。書くのは止めず、警告だけ出す（本文の折り返しの行が
    「## 申し送り…」で始まると、TASK.md を読む道具と後の書き換えで節が重なるため）。
    """
    out = []
    for i, l in headings(lines):
        if not l.startswith("## "):
            continue
        bare = re.sub(r"（[^（）]*）|\([^()]*\)", "", l[3:]).strip()
        if "。" in bare or len(bare) > 40:
            out.append((i, l))
    return out


def replace_handover(text: str, new: str) -> str:
    lines = text.splitlines()
    new_lines = new.strip("\n").splitlines()
    if not new_lines or not HEAD_RE.match(new_lines[0]):
        new_lines = ["## 申し送り", ""] + new_lines
    if any(re.match(r"^#{1,2} ", l) for l in new_lines[1:]):
        raise ValueError("新しい申し送りの中に「# 」「## 」の見出しがある（中は「### 」までにする）")
    hs = headings(lines)
    starts = [i for i, l in hs if HEAD_RE.match(l)]
    if len(starts) > 1:
        raise ValueError(f"申し送りの見出しが {len(starts)} つある（{', '.join(str(i + 1) for i in starts)} 行目）。手で1つにする")
    if starts:
        s = starts[0]
        e = next((i for i, _ in hs if i > s), len(lines))
        before, after = lines[:s], lines[e:]
    else:
        before, after = lines, []
    while before and not before[-1].strip():
        before.pop()
    result = before + ([""] if before else []) + new_lines + ([""] if after else []) + after
    # 申し送りの節を除いた見出しの並びが変わっていないか
    keep = lambda hl: [l for _, l in hl if not HEAD_RE.match(l)]
    if keep(headings(result)) != keep(hs):
        raise ValueError("差し替えると、申し送り以外の見出しが変わる。書かずに止めた")
    return "\n".join(result) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="TASK.md の申し送りの節だけを差し替える")
    ap.add_argument("task", help="TASK.md のパス")
    ap.add_argument("--from", dest="src", help="新しい申し送りのファイル（なければ標準入力）")
    a = ap.parse_args(argv)
    new = open(a.src, encoding="utf-8").read() if a.src else sys.stdin.read()
    try:
        old = open(a.task, encoding="utf-8").read()
    except FileNotFoundError:
        old = ""
    try:
        out = replace_handover(old, new)
    except ValueError as e:
        print(f"書いていません: {e}", file=sys.stderr)
        return 1
    tmp = a.task + ".handover-tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(out)
    os.replace(tmp, a.task)
    n_old, n_new = len(headings(old.splitlines())), len(headings(out.splitlines()))
    print(f"{a.task} の申し送りを書きました（見出し {n_old} → {n_new}）")
    for i, l in odd_headings(out.splitlines()):
        print(f"注意: {i + 1} 行目は見出しとして不自然（本文の折り返しが行頭に来た？）: {l[:60]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
