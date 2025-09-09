#!/usr/bin/env python3
# polish_relationships_tmdl.py (final-final)

import argparse, re
from pathlib import Path

BLOCK_START = re.compile(r"^\s*relationship\b", re.IGNORECASE)
FROM_LINE   = re.compile(r"^\s*fromColumn:\s*(.+)$", re.IGNORECASE)
TO_LINE     = re.compile(r"^\s*toColumn:\s*(.+)$", re.IGNORECASE)
WRAPPER_LINE= re.compile(r"^\s*relationships\s*:?\s*$", re.IGNORECASE)
REL_NAME_QUOTED = re.compile(r"^(\s*relationship)\s+'([^']+)'\s*", re.IGNORECASE)
REL_HEADER      = re.compile(r"^(\s*relationship\s+)(.+)$", re.IGNORECASE)
SUFFIX_PAREN    = re.compile(r"\s*\([^)]*\)\s*$")

def strip_wrapper_and_fix_headers(text: str) -> str:
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and WRAPPER_LINE.match(lines[0]):
        lines.pop(0)
        if lines and not lines[0].strip():
            lines.pop(0)
    for i, ln in enumerate(lines):
        m = REL_NAME_QUOTED.match(ln)
        if m:
            ln = f"{m.group(1)} {m.group(2)}"
        m2 = REL_HEADER.match(ln)
        if m2:
            prefix, name = m2.group(1), m2.group(2)
            name = re.sub(r"\s+\(", "(", name)  # remove space before '('
            ln = prefix + name
        lines[i] = ln
    return "\n".join(lines)

def parse_blocks(text: str):
    lines = text.splitlines()
    i, n = 0, len(lines)
    while i < n:
        if not BLOCK_START.match(lines[i]):
            i += 1; continue
        start = i; i += 1
        while i < n and not BLOCK_START.match(lines[i]):
            i += 1
        block = "\n".join(lines[start:i]).strip() + "\n"
        from_col = to_col = ""
        for ln in block.splitlines():
            mf = FROM_LINE.match(ln);  mt = TO_LINE.match(ln)
            if mf: from_col = mf.group(1).strip()
            if mt: to_col   = mt.group(1).strip()
        yield block, from_col, to_col

def norm_col(s: str) -> str:
    s = s.strip()
    s = SUFFIX_PAREN.sub("", s)
    if "[" in s and "]" in s:
        table = s.split("[",1)[0].strip()
        col   = s.split("[",1)[1].split("]",1)[0].strip()
        col   = SUFFIX_PAREN.sub("", col)
        return f"{table}.{col}"
    return SUFFIX_PAREN.sub("", s.replace(" ", ""))

def rewrite_block(block: str, from_norm: str, to_norm: str) -> str:
    def fmt(x: str) -> str:
        t, c = x.split(".", 1); return f"{t}.{c}"
    block = re.sub(r"(?m)^\s*fromColumn:\s*.*$", f"  fromColumn: {fmt(from_norm)}", block)
    block = re.sub(r"(?m)^\s*toColumn:\s*.*$",   f"  toColumn: {fmt(to_norm)}",   block)
    block = re.sub(r"(?m)^\s*crossFilteringBehavior:\s*.*$", "  crossFilteringBehavior: oneDirection", block)
    return block

def main():
    ap = argparse.ArgumentParser("Polish relationships.tmdl (exact header + indent)")
    ap.add_argument("--definition-dir", required=True)
    ap.add_argument("--keep", default="", help='Comma list: "Table.Col=Table.Col"')
    ap.add_argument("--drop-localdatetable", action="store_true")
    args = ap.parse_args()

    rel_path = Path(args.definition_dir) / "relationships.tmdl"
    if not rel_path.exists():
        raise SystemExit(f"Not found: {rel_path}")

    wanted = set()
    if args.keep.strip():
        for item in args.keep.split(","):
            if "=" in item:
                a, b = item.split("=", 1)
                a, b = norm_col(a), norm_col(b)
                wanted.add((a, b)); wanted.add((b, a))

    raw = rel_path.read_text(encoding="utf-8")
    raw = strip_wrapper_and_fix_headers(raw)

    detected, out, kept = [], [], []
    for block, fraw, traw in parse_blocks(raw):
        f, t = norm_col(fraw), norm_col(traw)
        detected.append((f, t))
        keep = True
        if wanted: keep = (f, t) in wanted
        if args.drop_localdatetable and ("LocalDateTable" in f or "LocalDateTable" in t):
            keep = False
        if keep:
            out.append(rewrite_block(block.strip(), f, t))
            kept.append((f, t))

    if not out:
        print("[ERROR] All relationships would be removed. Detected:")
        for a,b in detected: print(" ", a, "=", b)
        raise SystemExit(1)

    rel_path.write_text("\n\n".join(out) + "\n", encoding="utf-8")
    print("✅ relationships.tmdl polished")
    for a,b in kept: print(f"  - {a} -> {b}")

if __name__ == "__main__":
    main()
