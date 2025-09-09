#!/usr/bin/env python3
# polish_relationships_tmdl.py (final)
# Purpose:
#   - Remove the top "relationships" / "relationships:" wrapper line (if present)
#   - Unquote relationship names:  relationship 'Name' -> relationship Name
#   - Normalize column refs so:
#         People[Region (People)]  -> People.Region
#         Returned[Order_ID (Returned)] -> Returned.Order_ID
#   - Keep only the relationships you specify via --keep "Table.Col=Table.Col"
#   - Optionally drop LocalDateTable auto-date relationships
#   - Rewrite fromColumn/toColumn to EXACTLY "Table.Column" style
#
# Usage example:
#   python polish_relationships_tmdl.py \
#     --definition-dir "/path/OUT_PBIP/SampleTableau/SampleTableau.SemanticModel/definition" \
#     --keep "Orders.Region=People.Region,Orders.Order_ID=Returned.Order_ID" \
#     --drop-localdatetable

import argparse
import re
from pathlib import Path

# --- Regexes ---
BLOCK_START = re.compile(r"^\s*relationship\b", re.IGNORECASE)
FROM_LINE   = re.compile(r"^\s*fromColumn:\s*(.+)$", re.IGNORECASE)
TO_LINE     = re.compile(r"^\s*toColumn:\s*(.+)$", re.IGNORECASE)
WRAPPER_LINE= re.compile(r"^\s*relationships\s*:?\s*$", re.IGNORECASE)
REL_NAME_QUOTED = re.compile(r"^(\s*relationship)\s+'([^']+)'\s*", re.IGNORECASE)
SUFFIX_PAREN = re.compile(r"\s*\([^)]*\)\s*$")  # trims trailing " (People)" etc.


def strip_wrapper_and_unquote(text: str) -> str:
    """Remove top 'relationships' wrapper and unquote relationship names."""
    lines = text.splitlines()

    # Drop leading blanks
    while lines and not lines[0].strip():
        lines.pop(0)

    # Remove wrapper if present
    if lines and WRAPPER_LINE.match(lines[0]):
        lines.pop(0)
        if lines and not lines[0].strip():
            lines.pop(0)

    # Unquote 'relationship "Name"' -> relationship Name
    for i, ln in enumerate(lines):
        m = REL_NAME_QUOTED.match(ln)
        if m:
            lines[i] = f"{m.group(1)} {m.group(2)}"

    return "\n".join(lines)


def parse_blocks(text: str):
    """Yield (block_text, from_col_raw, to_col_raw) for each relationship block."""
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
            if mf:
                from_col = mf.group(1).strip()
            mt = TO_LINE.match(ln)
            if mt:
                to_col = mt.group(1).strip()

        yield block, from_col, to_col


def norm_col(s: str) -> str:
    """
    Normalize a column reference to 'Table.Column'.
    Handles:
      - People[Region (People)]  -> People.Region
      - Orders.Order_ID          -> Orders.Order_ID
      - Trims spaces and trailing parenthetical adornments.
    """
    s = s.strip()
    s = SUFFIX_PAREN.sub("", s)  # drop trailing " (People)" if outside brackets

    if "[" in s and "]" in s:
        table = s.split("[", 1)[0].strip()
        col   = s.split("[", 1)[1].split("]", 1)[0].strip()
        col   = SUFFIX_PAREN.sub("", col)  # drop trailing adornments inside brackets
        return f"{table}.{col}"

    # Already looks like Table.Column → ensure no spaces and no adornments
    return SUFFIX_PAREN.sub("", s.replace(" ", ""))


def rewrite_from_to(block: str, from_norm: str, to_norm: str, style: str = "dot") -> str:
    """
    Rewrite fromColumn/toColumn lines to the desired style.
    style="dot" → Table.Column    style="bracket" → Table[Column]
    """
    def fmt(x: str) -> str:
        table, col = x.split(".", 1)
        return f"{table}.{col}" if style == "dot" else f"{table}[{col}]"

    block = re.sub(r"(?m)^\s*fromColumn:\s*.*$", f"  fromColumn: {fmt(from_norm)}", block)
    block = re.sub(r"(?m)^\s*toColumn:\s*.*$",   f"  toColumn: {fmt(to_norm)}",   block)
    return block


def main():
    ap = argparse.ArgumentParser("Polish relationships.tmdl (remove wrapper, normalize, filter, rewrite)")
    ap.add_argument("--definition-dir", required=True, help=".../<Base>.SemanticModel/definition")
    ap.add_argument("--keep", default="", help='Comma list of "Table.Col=Table.Col" to keep')
    ap.add_argument("--drop-localdatetable", action="store_true",
                    help="Drop relationships that reference LocalDateTable (auto date)")
    ap.add_argument("--style", choices=["dot", "bracket"], default="dot",
                    help="Output style for column refs (default: dot → Table.Column)")
    args = ap.parse_args()

    rel_path = Path(args.definition_dir) / "relationships.tmdl"
    if not rel_path.exists():
        raise SystemExit(f"Not found: {rel_path}")

    # Parse desired pairs
    wanted_pairs = set()
    if args.keep.strip():
        for item in args.keep.split(","):
            if "=" in item:
                left, right = item.split("=", 1)
                wanted_pairs.add((norm_col(left), norm_col(right)))
                wanted_pairs.add((norm_col(right), norm_col(left)))  # either direction

    raw = rel_path.read_text(encoding="utf-8")
    raw = strip_wrapper_and_unquote(raw)

    kept, dropped, out_blocks, detected = [], [], [], []

    for block, from_raw, to_raw in parse_blocks(raw):
        f_norm, t_norm = norm_col(from_raw), norm_col(to_raw)
        detected.append((f_norm, t_norm))

        has_local = "LocalDateTable" in f_norm or "LocalDateTable" in t_norm

        keep = True
        if wanted_pairs:
            keep = (f_norm, t_norm) in wanted_pairs
        if args.drop_localdatetable and has_local:
            keep = False

        if keep:
            cleaned = rewrite_from_to(block.strip(), f_norm, t_norm, style=args.style)
            out_blocks.append(cleaned)
            kept.append((f_norm, t_norm))
        else:
            dropped.append((f_norm, t_norm))

    if not out_blocks:
        print("[ERROR] All relationships would be removed.")
        if detected:
            print("Detected pairs in your file (use these in --keep):")
            for a, b in detected:
                print(f"  {a}={b}")
        if wanted_pairs:
            print("Your --keep normalized to:")
            for a, b in sorted(wanted_pairs):
                print(f"  {a}={b}")
        raise SystemExit(1)

    rel_path.write_text("\n\n".join(out_blocks) + "\n", encoding="utf-8")

    print("✅ relationships.tmdl polished")
    if kept:
        print(" Kept:")
        for a, b in kept:
            print(f"  - {a} -> {b}")
    if dropped:
        print(" Dropped:")
        for a, b in dropped:
            print(f"  - {a} -> {b}")


if __name__ == "__main__":
    main()
