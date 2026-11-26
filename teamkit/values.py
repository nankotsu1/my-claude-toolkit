#!/usr/bin/env python3
r"""導入したリポジトリの値の表（`.claude/teamkit.md`）を読む。標準ライブラリだけ。

値の表は Markdown の表で、見出しの行の1列目が「項目」のもの。1列目が項目、2列目が値（3列目からは説明で、読まない）。
見出しの1列目が「項目」でない表（持ち手と置き場所の一覧など、そのリポジトリが足した表）は読まない。
項目の名前と意味は `teamkit/templates/teamkit.template.md`。

- 値はコードの書き方（`…`）で囲む。いくつもあるときは「、」で並べる（`a`、`b`）。コードの外の文と、全角の括弧（…）の中は説明として読み飛ばす
- 値の中の「|」は「\|」と書く（表の区切りと見分けるため）
- コードの書き方がひとつもないセルは、セルの文をそのまま1つの値とする（文で書く項目のため）
- 空のセルと「—」は、値がないものとする（スキルは、その値を使う所を飛ばすか、`<…>` のまま残す）

    python3 teamkit/values.py                 # 全部の項目と値
    python3 teamkit/values.py 台帳            # その項目の値（1行に1つ）。ないときは何も出さず終了コード 1
    python3 teamkit/values.py 台帳 --root <リポジトリ直下>
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

PATH = ".claude/teamkit.md"
_CODE = re.compile(r"`([^`]+)`")


def _cells(line: str) -> list[str]:
    """表の行のセル。「\\|」はセルの中の「|」。"""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.replace("\\|", "|").strip() for c in re.split(r"(?<!\\)\|", s)]


def _drop_notes(cell: str) -> str:
    """全角の括弧（…）の中（説明）を外す。入れ子も外側ごと。コードの書き方の中の括弧は残す。"""
    out, depth, code = [], 0, False
    for ch in cell:
        if ch == "`" and depth == 0:
            code = not code
        if not code and ch == "（":
            depth += 1
            continue
        if not code and ch == "）" and depth:
            depth -= 1
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out)


def parse(md: str) -> dict[str, str]:
    """項目 → 値のセル（生の文字）。見出しの1列目が「項目」の表だけを読む（見出しの行と区切りの行は除く）。
    表の外の行、コードブロックの中、ほかの見出しの表は読まない。同じ項目は最初のもの。
    新しい表は「見出しの行のすぐ下に区切りの行（| :--- |）」で始まる。区切りの行がない表の行（表の途中の空行のあと
    など）は、その前の表の続きとして読む。"""
    out: dict[str, str] = {}
    lines = md.splitlines()
    fence = False
    inside = False          # いまの表が値の表か
    sep = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
    skip = -1
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence or not line.lstrip().startswith("|") or i == skip:
            continue
        cells = _cells(line)
        if i + 1 < len(lines) and sep.match(lines[i + 1]):     # 新しい表の見出しの行
            inside = bool(cells) and cells[0].strip("* ") == "項目"
            skip = i + 1
            continue
        if not inside or len(cells) < 2:
            continue
        key, val = cells[0].strip("* "), cells[1]
        if not key or re.fullmatch(r":?-{2,}:?", key):
            continue
        out.setdefault(key, val)
    return out


def items(cell: str | None) -> list[str]:
    """セルの値の並び。コードの書き方があればその中身、なければセルの文1つ。空と「—」は []。"""
    if cell is None:
        return []
    bare = _drop_notes(cell)
    codes = _CODE.findall(bare)
    if codes:
        return [c.strip() for c in codes if c.strip()]
    if bare.strip() in ("", "—", "-"):           # 説明（括弧）だけのセルと「—（…）」も、値なし
        return []
    return [cell.strip()]                         # 文の項目は、添え書きの括弧ごと1つの値


def repo_root(start: str = ".") -> str:
    """値の表を探すリポジトリ直下（git の作業ツリーの直下。git の外なら start）。"""
    try:
        return subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start,
                              capture_output=True, text=True, check=True).stdout.strip() or start
    except (OSError, subprocess.CalledProcessError):
        return start


def load(root: str | None = None, path: str | None = None) -> dict[str, list[str]]:
    """値の表を読んで、項目 → 値の並び。値の表がなければ空。"""
    p = path or os.path.join(root or repo_root(), PATH)
    try:
        with open(p, encoding="utf-8") as fh:
            md = fh.read()
    except OSError:
        return {}
    return {k: items(v) for k, v in parse(md).items() if items(v)}


def first(values: dict[str, list[str]], key: str, default: str | None = None) -> str | None:
    """その項目の最初の値（なければ default）。"""
    got = values.get(key) or []
    return got[0] if got else default


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="導入したリポジトリの値の表（.claude/teamkit.md）を読む")
    ap.add_argument("key", nargs="?", help="項目（なければ全部）")
    ap.add_argument("--root", help="リポジトリ直下（既定: いまの git の作業ツリーの直下）")
    ap.add_argument("--file", help=f"値の表のファイル（既定: <リポジトリ直下>/{PATH}）")
    a = ap.parse_args(argv)
    values = load(a.root, a.file)
    if a.key:
        got = values.get(a.key) or []
        for v in got:
            print(v)
        return 0 if got else 1
    for k, vs in values.items():
        print(f"{k}: {'、'.join(vs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
