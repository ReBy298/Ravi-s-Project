#!/usr/bin/env python3
# polish_relationships_tmdl.py (v3)
# - Remove "relationships" wrapper line
# - Unquote relationship names: relationship 'Name' -> relationship Name
# - Normalize columns so People[Region (People)] -> People.Region, Returned[Order_ID (Returned)] -> Returned.Order_ID
# - Keep only desired pairs (--keep) and optionally drop LocalDateTable; prints detected pairs if result would be empty.

import argparse, re
from pathlib import Path

BLOCK_START = re.compile(r"^\s*relationship\b", re.IGNORECASE)
FROM_LINE   = re.compile(r"^\s*fromColumn:\s*(.+)$", re.IGNORECASE)
TO_LINE     = re.compile(r"^\s*toColumn:\s*(.+)$", re.IGNORECASE)
WRAPPER_LINE= re.compile(r"^\s*relationships\s*:?\s*$", re.IGNORECASE)
REL_NAME_QUOTED = re.compile(r"^(\s*relationship)\s+'([^']+)'\s*", re.IGNORECASE)

def strip_wrapper_and_unquote(text: str) -> str:
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
            lines[i] = f"{m.group(1)} {m.group(2)}"
    return "\n".join(lines)

def parse_blocks(text: str):
    lines = text.splitlines()
    i, n = 0, len(lines)
    while i < n:
        if not BLOCK_START.match(lines[i]):
            i += 1
            continue
        start = i
        i += 1
        while i < n and not BLOCK_START.match(lines[i]):
            i += 1
        block = "\n".join(lines[start:i]).strip() + "\n"
        from_col = to_col = ""
        for ln in block.splitlines():
            mf = FROM_LINE.match(ln)
            if mf: from_col = mf.group(1).strip()
            mt = TO_LINE.match(ln)
            if mt: to_col = mt.group(1).strip()
        yield block, from_col, to_col

SUFFIX_PAREN = re.compile(r"\s*\([^)]*\)\s*$")  # trims trailing " (People)" etc.

def norm_col(s: str) -> str:
    s = s.strip()
    # tolerate "(People)" adornments outside brackets too
    s = SUFFIX_PAREN.sub("", s)
    # Accept bracket syntax People[Region (People)]
    if "[" in s and "]" in s:
        table = s.split("[",1)[0].strip()
        col   = s.split("[",1)[1].split("]",1)[0].strip()
        col   = SUFFIX_PAREN.sub("", col)  # drop trailing " (Returned)" etc.
        return f"{table}.{col}"
    # If it already looks like Table.Column, drop trailing adornment
    return SUFFIX_PAREN.sub("", s.replace(" ", ""))

def main():
    ap = argparse.ArgumentParser("Polish relationships.tmdl (remove wrapper, unquote names, filter)")
    ap.add_argument("--definition-dir", required=True, help=".../<Base>.SemanticModel/definition")
    ap.add_argument("--keep", default="", help='Comma list of "Table.Col=Table.Col" to keep')
    ap.add_argument("--drop-localdatetable", action="store_true",
                    help="Drop relationships that reference LocalDateTable (auto date)")
    args = ap.parse_args()

    rel_path = Path(args.definition_dir) / "relationships.tmdl"
    if not rel_path.exists():
        raise SystemExit(f"Not found: {rel_path}")

    wanted_pairs = set()
    if args.keep.strip():
        for item in args.keep.split(","):
            if "=" in item:
                left, right = item.split("=", 1)
                wanted_pairs.add((norm_col(left), norm_col(right)))
                wanted_pairs.add((norm_col(right), norm_col(left)))  # either direction

    raw = rel_path.read_text(encoding="utf-8")
    raw = strip_wrapper_and_unquote(raw)

    kept, dropped, out = [], [], []
    detected = []  # list of all normed pairs we see

    for block, fcol, tcol in parse_blocks(raw):
        f_norm, t_norm = norm_col(fcol), norm_col(tcol)
        detected.append((f_norm, t_norm))
        has_local = "LocalDateTable" in f_norm or "LocalDateTable" in t_norm

        keep = True
        if wanted_pairs:
            keep = (f_norm, t_norm) in wanted_pairs
        if args.drop_localdatetable and has_local:
            keep = False

        if keep:
            out.append(block.strip())
            kept.append((f_norm, t_norm))
        else:
            dropped.append((f_norm, t_norm))

    if not out:
        print("[ERROR] All relationships would be removed.")
        if detected:
            print("Detected pairs in your file (use these in --keep):")
            for a,b in detected:
                print(f"  {a}={b}")
        if wanted_pairs:
            print("Your --keep normalized to:")
            for a,b in sorted(wanted_pairs):
                print(f"  {a}={b}")
        raise SystemExit(1)

    rel_path.write_text("\n\n".join(out) + "\n", encoding="utf-8")

    print("✅ relationships.tmdl polished")
    if kept:
        print(" Kept:")
        for a,b in kept: print(f"  - {a} -> {b}")
    if dropped:
        print(" Dropped:")
        for a,b in dropped: print(f"  - {a} -> {b}")

if __name__ == "__main__":
    main()
