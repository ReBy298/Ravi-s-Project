#!/usr/bin/env python3
"""
pbip_integrate.py
-----------------
Integrate AI-generated artifacts into a PBIP project.

What it does for a given table:
1) Copies the PBIP template to an output PBIP folder (if output doesn't exist).
   - If the template path is a directory, it copies it.
   - If it's a file or not a directory, it scaffolds a minimal PBIP project.
2) Reads your columns spec (boss-style YAML-like list or pre-rendered TMDL columns)
   and renders a proper TMDL table file at:
      <pbip_out>/SemanticModel/definition/tables/<Table>.tmdl
3) Wraps the provided Power Query M partition block into a TMDL `partitions { ... }`
   and appends it under the table definition.
4) Ensures `ref table '<Table>'` exists in `model.tmdl`.
5) Regenerates a simple `relationships.tmdl` from the Tableau XML:
   maps object-ids -> captions and expressions -> columns to build
   (fromTable[col]) -> (toTable[col]) relationships.

USAGE:
  python pbip_integrate.py \
    --xml /path/to/datasource_demo_tableau.xml \
    --pbip-template /path/to/PBIPTemplate.pbip \
    --pbip-out /path/to/OUT_PBIP/SampleTableau.pbip \
    --table Orders \
    --columns-file /path/to/out/Orders_columns_boss_style.txt \
    --partition-file /path/to/out/Orders_partition.m
"""
import argparse
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

# --------------------------
# Optional YAML dependency
# --------------------------
try:
    import yaml  # type: ignore
except Exception:
    yaml = None

# --------------------------
# Helpers: filesystem
# --------------------------
def ensure_pbip_scaffold(pbip_out: Path):
    """Create a minimal PBIP scaffold if it doesn't exist."""
    (pbip_out / "SemanticModel" / "definition" / "tables").mkdir(parents=True, exist_ok=True)
    model = pbip_out / "SemanticModel" / "definition" / "model.tmdl"
    if not model.exists():
        model.write_text(
            "model\n"
            "{\n"
            '  culture: "en-US"\n'
            "  tables: {\n"
            "  }\n"
            "}\n", encoding="utf-8"
        )
    rels = pbip_out / "SemanticModel" / "definition" / "relationships.tmdl"
    if not rels.exists():
        rels.write_text(
            "relationships\n"
            "{\n"
            "}\n", encoding="utf-8"
        )

def copy_pbip_template_if_needed(template: Path, pbip_out: Path):
    """Copy PBIP template folder to pbip_out if pbip_out doesn't exist."""
    if pbip_out.exists():
        return
    if template.exists() and template.is_dir():
        shutil.copytree(template, pbip_out)
        # Make sure the essential folders exist even if template lacked them
        ensure_pbip_scaffold(pbip_out)
    else:
        # Template is not a directory → scaffold minimal PBIP
        ensure_pbip_scaffold(pbip_out)

# --------------------------
# Boss-style columns parsing
# --------------------------
def load_columns_from_boss_style(path: Path) -> List[Dict[str, Any]]:
    """
    Reads a boss-style YAML-like list:
      - name: Row_ID
        dataType: int64
        summarizeBy: count
        sourceColumn: Row_ID
        formatString: "0"
    Returns a list of dicts.
    """
    text = path.read_text(encoding="utf-8").strip()
    # Heuristic: if looks like TMDL already (starts with "table" or "column"), return a sentinel
    if re.match(r"^\s*(table|column|columns\s*\{)", text, flags=re.I):
        return [{"__TMDL_RAW__": text}]

    if yaml is None:
        raise RuntimeError(
            f"File '{path}' looks like YAML boss-style, but PyYAML is not installed.\n"
            "Install it with:  python -m pip install pyyaml"
        )
    data = yaml.safe_load(text)
    if not isinstance(data, list):
        raise ValueError("Boss-style columns file must be a YAML list of columns.")
    out: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict) or "name" not in item:
            continue
        out.append(item)
    if not out:
        raise ValueError("No columns parsed from boss-style file.")
    return out

# --------------------------
# TMDL rendering
# --------------------------
def _fmt_ident(name: str) -> str:
    """Format identifiers safely; add single quotes if they contain spaces or special chars."""
    if re.search(r"[^\w]", name):
        return f"'{name}'"
    return name

def render_columns_tmdl_block(columns: List[Dict[str, Any]]) -> str:
    """
    Render a TMDL columns block from boss-style columns list.
    If the list contains a single dict with __TMDL_RAW__, returns that raw content
    (assuming it's already valid TMDL snippet for columns).
    """
    if len(columns) == 1 and "__TMDL_RAW__" in columns[0]:
        raw = columns[0]["__TMDL_RAW__"]
        # If raw is a full table file, caller will embed it differently.
        # If raw contains "column " entries, we just return it.
        return str(raw).strip()

    lines: List[str] = []
    lines.append("  columns {")
    for col in columns:
        name = str(col.get("name", "")).strip()
        if not name:
            continue
        dt = str(col.get("dataType", "string")).strip()
        summ = str(col.get("summarizeBy", "") or "").strip()
        src = str(col.get("sourceColumn", name)).strip()
        fmt = col.get("formatString", None)
        lines.append(f"    column {_fmt_ident(name)}")
        lines.append("    {")
        lines.append(f"      dataType: {dt}")
        if summ and summ.lower() != "none":
            lines.append(f"      summarizeBy: {summ}")
        lines.append(f"      sourceColumn: {_fmt_ident(src)}")
        if fmt is not None and str(fmt).strip() != "":
            # if it's purely digits, no quotes; else quote
            fmt_str = str(fmt)
            if re.fullmatch(r"\d+", fmt_str):
                lines.append(f"      formatString: {fmt_str}")
            else:
                lines.append(f'      formatString: "{fmt_str}"')
        lines.append("    }")
    lines.append("  }")
    return "\n".join(lines)

def render_partition_block_tmdl(partition_text: str, table: str) -> str:
    """
    Wrap the provided 'partition <table> = m ...' into:
      partitions {
        partition <table> = m
          ...
      }
    """
    body = partition_text.strip()
    # Normalize indentation to 2 spaces inside partitions { ... }
    indented = []
    for ln in body.splitlines():
        indented.append("  " + ln.rstrip())
    return "  partitions {\n" + "\n".join(indented) + "\n  }"

def render_table_tmdl(table: str, columns_block_or_list, partition_text: str) -> str:
    """Render a full table TMDL file."""
    # If columns list is a raw TMDL (single dict __TMDL_RAW__), drop into place
    if isinstance(columns_block_or_list, list) and len(columns_block_or_list) == 1 and "__TMDL_RAW__" in columns_block_or_list[0]:
        # Is this a full table or only "column" entries?
        raw = columns_block_or_list[0]["__TMDL_RAW__"].strip()
        if re.search(r"^\s*table\s", raw, flags=re.I):
            # Already a full table file, but we still need to append partitions
            core = raw.rstrip()
            parts_block = render_partition_block_tmdl(partition_text, table)
            # If raw already has partitions, you may want to replace them; here we just append
            return core + "\n" + parts_block + "\n"
        else:
            # It's a columns-only snippet → wrap into a full table
            cols_block_text = raw
    else:
        cols_block_text = render_columns_tmdl_block(columns_block_or_list)

    parts_block = render_partition_block_tmdl(partition_text, table)

    lines: List[str] = []
    lines.append(f"table {_fmt_ident(table)}")
    lines.append("{")
    lines.append(cols_block_text)
    lines.append(parts_block)
    lines.append("}")
    return "\n".join(lines) + "\n"

# --------------------------
# Model.tmdl update
# --------------------------
def ensure_ref_table(model_path: Path, table: str):
    """
    Ensure model.tmdl contains:
      model { ... tables: { ref table '<Table>' } }
    """
    if not model_path.exists():
        model_path.parent.mkdir(parents=True, exist_ok=True)
        model_path.write_text(
            "model\n{\n  culture: \"en-US\"\n  tables: {\n  }\n}\n", encoding="utf-8"
        )

    text = model_path.read_text(encoding="utf-8")
    ref_line = f"ref table {_fmt_ident(table)}"
    if ref_line in text:
        return

    # Find or create tables block
    m = re.search(r"(tables\s*:\s*\{\s*)(.*?)(\s*\})", text, flags=re.S)
    if m:
        start, body, end = m.groups()
        new_body = (body + f"\n    {ref_line}").rstrip()
        new_text = text[:m.start(1)] + start + new_body + end + text[m.end(3):]
        model_path.write_text(new_text, encoding="utf-8")
    else:
        # inject a basic tables block near the top of model
        new_text = re.sub(
            r"model\s*\{",
            "model\n{\n  tables: {\n    " + ref_line + "\n  }",
            text,
            count=1,
            flags=re.S,
        )
        if new_text == text:
            # fallback: overwrite with a minimal model including the ref
            new_text = (
                "model\n{\n"
                '  culture: "en-US"\n'
                "  tables: {\n"
                f"    {ref_line}\n"
                "  }\n"
                "}\n"
            )
        model_path.write_text(new_text, encoding="utf-8")

# --------------------------
# Relationships from Tableau XML
# --------------------------
def parse_relationships_from_xml(xml_path: Path) -> List[Dict[str, str]]:
    """
    Read <object-graph><objects> to map id -> caption (table),
    and <relationships> to obtain pairs (table.col) = (table.col).
    Returns list of dicts: {left_table,left_column,right_table,right_column}
    """
    tree = ET.parse(str(xml_path))
    root = tree.getroot()

    id2cap: Dict[str, str] = {}
    for obj in root.findall(".//object-graph/objects/object"):
        obj_id = obj.attrib.get("id")
        cap = obj.attrib.get("caption")
        if obj_id and cap:
            id2cap[obj_id] = cap

    rels_out: List[Dict[str, str]] = []
    for rel in root.findall(".//object-graph/relationships/relationship"):
        eq = rel.find("./expression[@op='=']")
        if eq is None:
            continue
        parts = eq.findall("./expression")
        if len(parts) != 2:
            continue

        # columns in expressions (e.g., "[Region]")
        def _col(op_node):
            col = op_node.attrib.get("op") if op_node is not None else None
            return (col or "").strip("[]")

        left_col = _col(parts[0])
        right_col = _col(parts[1])

        left_ep = rel.find("./first-end-point")
        right_ep = rel.find("./second-end-point")
        left_tab = id2cap.get(left_ep.attrib.get("object-id")) if left_ep is not None else None
        right_tab = id2cap.get(right_ep.attrib.get("object-id")) if right_ep is not None else None
        if not left_tab or not right_tab or not left_col or not right_col:
            continue

        rels_out.append({
            "left_table": left_tab,
            "left_column": left_col,
            "right_table": right_tab,
            "right_column": right_col,
        })

    # dedupe
    uniq = []
    seen = set()
    for r in rels_out:
        key = (r["left_table"], r["left_column"], r["right_table"], r["right_column"])
        if key not in seen:
            uniq.append(r)
            seen.add(key)
    return uniq

def render_relationships_tmdl(rels: List[Dict[str, str]]) -> str:
    """
    Generate a simple relationships.tmdl.
    NOTE: If your template already ships a more elaborate one, you can swap this render.
    """
    lines: List[str] = []
    lines.append("relationships")
    lines.append("{")
    for r in rels:
        lt, lc, rt, rc = r["left_table"], r["left_column"], r["right_table"], r["right_column"]
        name = f"{lt}_{lc}__{rt}_{rc}"
        lines.append(f"  relationship '{name}'")
        lines.append("  {")
        lines.append(f"    fromColumn: {_fmt_ident(lt)}.'{lc}'")
        lines.append(f"    toColumn: {_fmt_ident(rt)}.'{rc}'")
        lines.append("    crossFilteringBehavior: oneDirection")
        lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"

# --------------------------
# Main
# --------------------------
def main():
    ap = argparse.ArgumentParser(description="Copy PBIP template → output, write table TMDL (columns + partition), ensure ref in model, and generate relationships.")
    ap.add_argument("--xml", required=True, help="Path to Tableau datasource XML")
    ap.add_argument("--pbip-template", required=True, help="PBIP template folder (.pbip as directory). If not a directory, a minimal scaffold will be created.")
    ap.add_argument("--pbip-out", required=True, help="Output PBIP folder")
    ap.add_argument("--table", required=True, help="Table name (e.g., Orders)")
    ap.add_argument("--columns-file", required=True, help="Boss-style columns file (YAML-like list) OR pre-rendered TMDL snippet")
    ap.add_argument("--partition-file", required=True, help="Power Query M partition block file (starting with 'partition <table> = m')")
    args = ap.parse_args()

    tpl = Path(args.pbip_template)
    out = Path(args.pbip_out)
    xml_path = Path(args.xml)
    columns_file = Path(args.columns_file)
    partition_file = Path(args.partition_file)
    table = args.table

    # 1) Copy/Scaffold PBIP
    copy_pbip_template_if_needed(tpl, out)

    # 2) Load columns
    cols = load_columns_from_boss_style(columns_file)

    # 3) Load partition text
    part_text = partition_file.read_text(encoding="utf-8")

    # 4) Render table TMDL
    table_tmdl = render_table_tmdl(table, cols, part_text)

    # 5) Write table file
    tables_dir = out / "SemanticModel" / "definition" / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    (tables_dir / f"{table}.tmdl").write_text(table_tmdl, encoding="utf-8")

    # 6) Ensure model.tmdl has ref table
    model_path = out / "SemanticModel" / "definition" / "model.tmdl"
    ensure_ref_table(model_path, table)

    # 7) Generate relationships.tmdl from XML (complete set)
    rels = parse_relationships_from_xml(xml_path)
    rels_text = render_relationships_tmdl(rels)
    (out / "SemanticModel" / "definition" / "relationships.tmdl").write_text(rels_text, encoding="utf-8")

    print("✅ Integrated table:", table)
    print("  -", tables_dir / f"{table}.tmdl")
    print("  -", model_path)
    print("  -", out / "SemanticModel" / "definition" / "relationships.tmdl")

if __name__ == "__main__":
    main()
