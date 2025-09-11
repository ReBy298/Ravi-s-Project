#!/usr/bin/env python3
"""
pbip_integrate.py

Integrate a single table into a PBIP (TMDL) model:
- Creates/updates OUT_PBIP/<Name>.pbip/SemanticModel/definition/tables/<Table>.tmdl
- Ensures model.tmdl & relationships.tmdl exist
- Emits relationships in TMDL using Table.'Column'
- Normalizes columns like "Region(People)" -> "Region" before emitting

Usage example:
  python pbip_integrate.py \
    --xml /path/to/datasource_demo_tableau.xml \
    --pbip-template /path/to/PBIPTemplate.pbip \
    --pbip-out /path/to/OUT_PBIP/SampleTableau.pbip \
    --table Orders \
    --columns-file /path/to/out/Orders_columns_boss_style.txt \
    --partition-file /path/to/out/Orders_partition.m
"""

import argparse
import csv
import os
import re
import shutil
from pathlib import Path
from typing import List, Optional, Tuple, Dict

# --------------------------
# Helpers
# --------------------------

def _find_sem_model_dir(pbip_out_dir: Path) -> Path:
    """
    Return the semantic model root inside the copied template.
    Prefer placeholder dirs shipped in the template (smtemplate.SemanticModel),
    otherwise use 'SemanticModel' (create it if missing).
    """
    for name in ("smtemplate.SemanticModel", "SemanticModel", "template.SemanticModel"):
        cand = pbip_out_dir / name
        if cand.exists() and cand.is_dir():
            return cand
    # nothing found → create canonical path
    cand = pbip_out_dir / "SemanticModel"
    cand.mkdir(parents=True, exist_ok=True)
    return cand

def _strip_table_suffix(col: str, table: str) -> str:
    """
    Normalize column names that carry a trailing '(Table)' suffix.
    Example: 'Region(People)' or 'Region (People)' -> 'Region' when table == 'People'.
    """
    col = (col or "").strip().strip("'").strip('"')
    m = re.match(r"^(.*?)[ ]*\(([^\)]+)\)$", col)
    if m and m.group(2).strip().lower() == (table or "").strip().lower():
        return m.group(1).strip()
    return col

def _fmt_table_ident(table_name: str) -> str:
    """Return table identifier as it should appear in TMDL (adjust if you ever need quoting)."""
    return table_name

def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def _copy_template_if_missing(template_input: Path, pbip_out_dir: Path) -> None:
    """
    Accept either:
      - template_input = /path/to/pbip_template          (directory), or
      - template_input = /path/to/pbip_template/Name.pbip (file in that directory)

    If the output dir doesn't exist, copy the whole template directory tree there.
    """
    template_dir = template_input
    if template_dir.is_file():
        # If they gave us /path/.../PBIPTemplate.pbip, use its parent folder.
        template_dir = template_dir.parent

    if not template_dir.exists() or not template_dir.is_dir():
        raise FileNotFoundError(f"PBIP template directory not found: {template_input}")

    if pbip_out_dir.exists():
        # Already scaffolded for this run; nothing to do
        return

    shutil.copytree(template_dir, pbip_out_dir)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")

def _indent_block(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line.strip() else line for line in text.splitlines())

def _looks_like_tmdl_columns_block(text: str) -> bool:
    # Heuristic: if it already contains "column <name>" lines, treat as TMDL-ready
    return bool(re.search(r"(?m)^\s*column\s+[A-Za-z0-9_]+", text))

def _parse_simple_columns_rows(text: str) -> List[Tuple[str, str, Optional[str]]]:
    """
    Parse very simple inputs like:
      Row_ID,int64,count
      Discount,double,sum
      Customer_ID,string,none
    or "name | type | summarize"
    Returns list of (name, type, summarizeBy or None)
    """
    out: List[Tuple[str, str, Optional[str]]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # split by comma or pipe
        if "," in line:
            parts = [p.strip() for p in line.split(",")]
        elif "|" in line:
            parts = [p.strip() for p in line.split("|")]
        else:
            # fallback: if it's just a name, default string/none
            parts = [line]

        name = parts[0]
        dtype = (parts[1] if len(parts) > 1 else "string").lower()
        agg = parts[2] if len(parts) > 2 else None
        # normalize a few common dtype aliases
        if dtype in ("integer", "int", "int64", "long"):
            dtype = "int64"
        elif dtype in ("double", "real", "float", "decimal"):
            dtype = "double"
        elif dtype in ("datetime", "date", "timestamp"):
            dtype = "dateTime"
        else:
            dtype = "string"
        out.append((name, dtype, agg))
    return out

def _render_columns_from_rows(rows: List[Tuple[str, str, Optional[str]]]) -> str:
    """
    Render TMDL column blocks from parsed rows.
    """
    lines: List[str] = []
    for name, dtype, agg in rows:
        lines.append(f"  column {name}")
        lines.append(f"    dataType: {dtype}")
        if agg and agg.lower() not in ("none", "default"):
            lines.append(f"    summarizeBy: {agg}")
        lines.append(f"    sourceColumn: {name}")
    return "\n".join(lines)

def _load_columns_block(columns_file: Path) -> str:
    """
    Load columns spec; if it's already TMDL 'column ...' blocks, return as-is.
    Otherwise, treat as a simple CSV-like list and render.
    """
    raw = _read_text(columns_file)
    if _looks_like_tmdl_columns_block(raw):
        # Clean up any top-level 'table' wrapper if the file accidentally contains it
        if raw.lstrip().startswith("table "):
            # Extract only the 'column ...' blocks
            cols = re.findall(r"(?ms)(^\s*column\s+.*?(?=^\s*(?:column\s+|partition\s+|annotation\s+|$)))", raw)
            return "\n".join(c.rstrip() for c in cols)
        return raw.strip()
    # Parse simple rows
    rows = _parse_simple_columns_rows(raw)
    return _render_columns_from_rows(rows)

def _wrap_partition_block(table: str, m_text: str) -> str:
    """
    Take a raw M block (let...in...) and wrap as TMDL partition with canonical indentation.
    Also ensure single braces (sometimes LLMs print '{{' / '}}').
    """
    m_text = m_text.replace("{{", "{").replace("}}", "}")

    # Trim and indent the M lines under "source ="
    m_text = m_text.strip("\n")
    # canonical 2/4/6 indentation pattern:
    #   partition <T> = m
    #     mode: import
    #     source =
    #       let
    #         ...
    #       in
    #         Return
    lines = []
    lines.append(f"  partition {table} = m")
    lines.append(f"    mode: import")
    lines.append(f"    source =")
    # if user-supplied block includes its own 'let', reindent; otherwise trust it
    # We force 6 spaces for 'let' / 'in' and 8 for body
    # Attempt a lightweight normalization:
    # Put a newline before 'in' to ensure we can indent the return nicely
    m_text_norm = re.sub(r"\n\s*in\s*\n", "\n      in\n", m_text, flags=re.IGNORECASE)
    if not re.search(r"(?m)^\s*let\s*$", m_text_norm):
        # If it doesn't seem to contain a line with exactly 'let', just indent raw
        lines.append(_indent_block(m_text_norm, 6))
    else:
        # Reindent line-by-line:
        out_m = []
        for raw in m_text_norm.splitlines():
            s = raw.strip()
            if not s:
                continue
            if s.lower() == "let":
                out_m.append("      let")
            elif s.lower() == "in":
                out_m.append("      in")
            else:
                out_m.append("        " + s)
        lines.extend(out_m)
    return "\n".join(lines)

def _ensure_model_file(model_path: Path) -> None:
    if not model_path.exists():
        _write_text(model_path, "model\n")

def _ensure_relationships_file(rel_path: Path) -> None:
    if not rel_path.exists():
        _write_text(rel_path, "")

def _read_existing_tables(tables_dir: Path) -> List[str]:
    names = []
    if tables_dir.exists():
        for p in tables_dir.glob("*.tmdl"):
            names.append(p.stem)
    return names

def _append_or_update_relationships(rel_path: Path, rels: List[Tuple[str,str,str,str]], behavior: Optional[str] = None) -> None:
    """
    rels: list of (left_table, left_col, right_table, right_col)
    Emits TMDL blocks; normalizes col suffixes.
    """
    existing = _read_text(rel_path) if rel_path.exists() else ""
    blocks: List[str] = []
    if existing.strip():
        blocks.append(existing.rstrip() + "\n")

    for (lt, lc, rt, rc) in rels:
        lc_n = _strip_table_suffix(lc, lt)
        rc_n = _strip_table_suffix(rc, rt)
        name = f"{lt}_{lc_n}_{rt}_{rc_n}"
        blocks.append(f"relationship {name}")
        blocks.append(f"  fromColumn: {_fmt_table_ident(lt)}.'{lc_n}'")
        blocks.append(f"  toColumn: {_fmt_table_ident(rt)}.'{rc_n}'")
        if behavior:
            blocks.append(f"  crossFilteringBehavior: {behavior}")
        blocks.append("")  # blank line

    _write_text(rel_path, "\n".join(blocks).rstrip() + "\n")

# --------------------------
# Core integrate
# --------------------------

def integrate_table(xml_path: Path,
                    template_dir: Path,
                    pbip_out_dir: Path,
                    table_name: str,
                    columns_file: Path,
                    partition_file: Path) -> None:
    # 0) Ensure OUT PBIP exists (copy template if needed)
    _copy_template_if_missing(template_dir, pbip_out_dir)

    # 1) Paths
    sem_model_dir = _find_sem_model_dir(pbip_out_dir)
    def_dir = sem_model_dir / "definition"
    tables_dir = def_dir / "tables"
    model_path = def_dir / "model.tmdl"
    rel_path = def_dir / "relationships.tmdl"
    table_tmdl = tables_dir / f"{table_name}.tmdl"

    _ensure_dir(tables_dir)
    _ensure_model_file(model_path)
    _ensure_relationships_file(rel_path)

    # 2) Build TMDL for the table
    cols_block = _load_columns_block(columns_file)
    m_raw = _read_text(partition_file)

    # Compose the table file
    parts: List[str] = []
    parts.append(f"table {table_name}")
    # columns (already indented or we indent if needed)
    if not cols_block.startswith("  "):
        cols_block = _indent_block(cols_block, 2)
    parts.append(cols_block)
    # partition block (wrapped)
    parts.append(_wrap_partition_block(table_name, m_raw))
    # annotation (Power BI likes this)
    parts.append("  annotation PBI_ResultType = Table")

    tmdl_text = "\n".join(parts).rstrip() + "\n"
    _write_text(table_tmdl, tmdl_text)

    # 3) Optionally add “obvious” relationships if both sides exist:
    #    - Orders.Region = People.Region
    #    - Orders.Order_ID = Returned.Order_ID
    #    This mirrors the sample Ravi asked to preserve.
    existing_tables = set(_read_existing_tables(tables_dir))
    auto_rels: List[Tuple[str,str,str,str]] = []
    if table_name in ("Orders", "People") and {"Orders", "People"}.issubset(existing_tables):
        auto_rels.append(("Orders", "Region", "People", "Region"))
    if table_name in ("Orders", "Returned") and {"Orders", "Returned"}.issubset(existing_tables):
        auto_rels.append(("Orders", "Order_ID", "Returned", "Order_ID"))

    if auto_rels:
        _append_or_update_relationships(rel_path, auto_rels, behavior=None)

    # 4) Log
    print("✅ Integrated table:", table_name)
    print("  -", table_tmdl)
    print("  -", model_path)
    print("  -", rel_path)

# --------------------------
# CLI
# --------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml", required=True, help="Source Tableau XML (not strictly required to parse)")
    ap.add_argument("--pbip-template", required=True, help="Path to PBIP template (.pbip folder)")
    ap.add_argument("--pbip-out", required=True, help="Output PBIP folder (will be created from template if missing)")
    ap.add_argument("--table", required=True, help="Table name to integrate (e.g., Orders)")
    ap.add_argument("--columns-file", required=True, help="Columns spec (TMDL-style blocks or simple CSV-like lines)")
    ap.add_argument("--partition-file", required=True, help="M block (let...in) for this table")
    args = ap.parse_args()

    xml_path = Path(args.xml)
    template_dir = Path(args.pbip_template)
    pbip_out_dir = Path(args.pbip_out)
    table_name = args.table
    cols_file = Path(args.columns_file)
    part_file = Path(args.partition_file)

    if not cols_file.exists():
        raise FileNotFoundError(f"Columns file not found: {cols_file}")
    if not part_file.exists():
        raise FileNotFoundError(f"Partition file not found: {part_file}")

    integrate_table(
        xml_path=xml_path,
        template_dir=template_dir,
        pbip_out_dir=pbip_out_dir,
        table_name=table_name,
        columns_file=cols_file,
        partition_file=part_file,
    )

if __name__ == "__main__":
    main()
