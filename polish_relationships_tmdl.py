#!/usr/bin/env python3
# polish_relationships_tmdl.py
import argparse
import re
from pathlib import Path
from typing import List, Tuple, Dict, Optional

REL_FILE = "relationships.tmdl"

REL_START_RE = re.compile(r"^\s*relationship\s+(?P<name>[^\s].*)\s*$")
FROM_RE = re.compile(r"^\s*fromColumn:\s+(?P<table>[A-Za-z0-9_]+)\.\'(?P<col>.+)\'\s*$")
TO_RE   = re.compile(r"^\s*toColumn:\s+(?P<table>[A-Za-z0-9_]+)\.\'(?P<col>.+)\'\s*$")
XFB_RE  = re.compile(r"^\s*crossFilteringBehavior:\s+(?P<xfb>\S+)\s*$")

def _strip_table_suffix(col: str, table: str) -> str:
    """
    Normalize column names that may carry '(Table)' suffix (with optional spaces).
    Examples:
      Region(People)     -> Region
      Region (People)    -> Region
    """
    col = (col or "").strip().strip("'").strip('"')
    m = re.match(r"^(.*?)[ ]*\(([^\)]+)\)$", col)
    if m and m.group(2).strip().lower() == (table or "").strip().lower():
        return m.group(1).strip()
    return col

def _parse_keep_list(keep_arg: Optional[str]) -> List[Tuple[str, str, str, str]]:
    """
    --keep accepts comma-separated entries like:
      "Orders.Region=People.Region,Orders.Order_ID=Returned.Order_ID"
    We also allow 'Region(People)' forms and normalize them away.
    Returns list of (lt, lc_norm, rt, rc_norm).
    """
    if not keep_arg:
        return []
    parts = [p.strip() for p in keep_arg.split(",") if p.strip()]
    keep = []
    for part in parts:
        if "=" not in part or "." not in part:
            continue
        left, right = part.split("=", 1)
        lt, lc = left.split(".", 1)
        rt, rc = right.split(".", 1)
        lc = _strip_table_suffix(lc, lt)
        rc = _strip_table_suffix(rc, rt)
        keep.append((lt.strip(), lc, rt.strip(), rc))
    return keep

def _read_relationships(path: Path) -> List[Dict[str, str]]:
    """
    Very small TMDL reader for relationship blocks we emit.
    """
    if not path.exists():
        return []

    rows = path.read_text(encoding="utf-8").splitlines()
    rels: List[Dict[str, str]] = []
    cur: Dict[str, str] = {}
    in_block = False

    for line in rows:
        m = REL_START_RE.match(line)
        if m:
            if in_block and cur:
                rels.append(cur)
            cur = {"name": m.group("name")}
            in_block = True
            continue

        if not in_block:
            continue

        m = FROM_RE.match(line)
        if m:
            cur["from_table"] = m.group("table")
            cur["from_column_raw"] = m.group("col")
            continue

        m = TO_RE.match(line)
        if m:
            cur["to_table"] = m.group("table")
            cur["to_column_raw"] = m.group("col")
            continue

        m = XFB_RE.match(line)
        if m:
            cur["crossFilteringBehavior"] = m.group("xfb")
            continue

        # blank or unrelated lines end the block (when we hit a new relationship, handled above)

    if in_block and cur:
        rels.append(cur)

    # Normalize column names now
    for r in rels:
        lt = r.get("from_table") or ""
        rt = r.get("to_table") or ""
        r["from_column"] = _strip_table_suffix(r.get("from_column_raw", ""), lt)
        r["to_column"]   = _strip_table_suffix(r.get("to_column_raw", ""), rt)

    return rels

def _write_relationships(path: Path, rels: List[Dict[str, str]]) -> None:
    lines: List[str] = []
    for r in rels:
        name = r.get("name", "relationship")
        lt   = r.get("from_table")
        lc   = r.get("from_column")
        rt   = r.get("to_table")
        rc   = r.get("to_column")
        xfb  = r.get("crossFilteringBehavior")

        if not (lt and lc and rt and rc):
            continue

        lines.append(f"relationship {name}")
        lines.append(f"  fromColumn: {lt}.'{lc}'")
        lines.append(f"  toColumn: {rt}.'{rc}'")
        if xfb:
            lines.append(f"  crossFilteringBehavior: {xfb}")
        lines.append("")  # blank line

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

def _should_drop_local_date_table(rel: Dict[str, str]) -> bool:
    # drop relationships that involve LocalDateTable_*
    lt = (rel.get("from_table") or "").lower()
    rt = (rel.get("to_table") or "").lower()
    return lt.startswith("localdatetable_") or rt.startswith("localdatetable_")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--definition-dir", required=True, help=".../SemanticModel/definition")
    ap.add_argument("--keep", default="", help="Comma-separated keep list: A.Col=B.Col, ...")
    ap.add_argument("--drop-localdatetable", action="store_true")
    args = ap.parse_args()

    rel_path = Path(args.definition_dir) / REL_FILE
    rels = _read_relationships(rel_path)

    # Normalize & filter
    keep_pairs = _parse_keep_list(args.keep)
    keep_set = {f"{lt}.{lc}={rt}.{rc}" for (lt, lc, rt, rc) in keep_pairs}

    filtered: List[Dict[str, str]] = []
    for r in rels:
        if args.drop_localdatetable and _should_drop_local_date_table(r):
            continue

        # Build normalized key for matching
        lt = r.get("from_table") or ""
        lc = r.get("from_column") or ""
        rt = r.get("to_table") or ""
        rc = r.get("to_column") or ""
        key = f"{lt}.{lc}={rt}.{rc}"

        if keep_set:
            # keep only those explicitly allowed
            if key in keep_set:
                filtered.append(r)
        else:
            # keep everything (minus LocalDateTable if requested)
            filtered.append(r)

    if keep_set and not filtered:
        # Show what we detected to help caller adjust --keep
        detected = []
        for r in rels:
            lt = r.get("from_table") or ""
            lc = r.get("from_column") or ""
            rt = r.get("to_table") or ""
            rc = r.get("to_column") or ""
            detected.append(f"{lt}.'{lc}' = {rt}.'{rc}'")
        print("[ERROR] All relationships would be removed. Detected:")
        for d in detected:
            print(f"  {d}")
        raise SystemExit(1)

    _write_relationships(rel_path, filtered)

if __name__ == "__main__":
    main()
