#!/usr/bin/env python3
# polish_tables_tmdl.py
# - Remove 'columns:' / 'partitions:' labels
# - Normalize indent:
#     'column' lines → 2 spaces
#     'partition … = m' → 2 spaces
#     'mode:' / 'source =' → 4 spaces
#     'let' / 'in' / M-lines → 6+ spaces
# - Ensure trailing 'annotation PBI_ResultType = Table' at 2 spaces

import argparse, re
from pathlib import Path

COL_LABEL = re.compile(r"^\s*columns\s*:\s*$", re.IGNORECASE)
PART_LABEL= re.compile(r"^\s*partitions\s*:\s*$", re.IGNORECASE)
IS_COLUMN = re.compile(r"^\s*column\b", re.IGNORECASE)
IS_PART   = re.compile(r"^\s*partition\b", re.IGNORECASE)

def polish_file(p: Path) -> None:
    txt = p.read_text(encoding="utf-8")
    lines = txt.splitlines()

    out = []
    skip_next_blank = False
    for ln in lines:
        if COL_LABEL.match(ln) or PART_LABEL.match(ln):
            # drop labels entirely
            skip_next_blank = True
            continue
        if skip_next_blank and not ln.strip():
            # drop blank line right after the removed label
            continue
        skip_next_blank = False

        s = ln.rstrip()

        # columns
        if IS_COLUMN.match(s):
            s = "  " + s.strip()  # exactly 2 spaces
            out.append(s); continue

        # partition block and inner lines
        if IS_PART.match(s):
            s = "  " + s.strip()
            out.append(s); continue

        if s.strip().startswith("mode:"):
            out.append("    " + s.strip()); continue

        if s.strip().startswith("source"):
            # normalize "source =" spacing and indent
            s0 = s.strip().replace("  ", " ")
            s0 = s0.replace("= ", "= ")
            out.append("    " + s0); continue

        if s.strip().startswith("let"):
            out.append("      " + s.strip()); continue
        if s.strip().startswith("in"):
            out.append("      " + s.strip()); continue

        # M lines inside let/in (heuristic)
        if s.strip().startswith(("Source =", "srcSource", "Orders_object", "People_object", "Returned_object")):
            out.append("        " + s.strip()); continue

        out.append(s)

    # ensure annotation at end (2 spaces indent)
    body = "\n".join(out).rstrip()
    if "annotation PBI_ResultType = Table" not in body:
        body += "\n\n  annotation PBI_ResultType = Table"

    p.write_text(body + "\n", encoding="utf-8")

def main():
    ap = argparse.ArgumentParser("Polish TMDL table files (indent + wrappers)")
    ap.add_argument("--definition-dir", required=True, help=".../<Base>.SemanticModel/definition")
    args = ap.parse_args()

    tables_dir = Path(args.definition_dir) / "tables"
    if not tables_dir.exists():
        raise SystemExit(f"Not found tables dir: {tables_dir}")

    for f in sorted(tables_dir.glob("*.tmdl")):
        polish_file(f)

    print("✅ TMDL tables polished (indent, no labels, annotation ensured).")

if __name__ == "__main__":
    main()
