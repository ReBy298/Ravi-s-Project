#!/usr/bin/env python3
# polish_tables_tmdl.py
# Remove "columns:" and "partitions:" lines from table TMDLs,
# fix accidental double braces in M, and ensure PBI_ResultType annotation.

import argparse, re
from pathlib import Path

RE_COLUMNS_LINE    = re.compile(r"(?m)^\s*columns:\s*\n")
RE_PARTITIONS_LINE = re.compile(r"(?m)^\s*partitions:\s*\n")

def polish_table_file(p: Path) -> None:
    if p.suffix.lower() != ".tmdl":
        return
    text = p.read_text(encoding="utf-8")

    # 1) Drop wrapper labels
    text = RE_COLUMNS_LINE.sub("", text)
    text = RE_PARTITIONS_LINE.sub("", text)

    # 2) Fix accidental double braces in M queries (if any)
    text = text.replace("{{", "{").replace("}}", "}")

    # 3) Ensure result-type annotation (if missing)
    if "annotation PBI_ResultType" not in text:
        text = text.rstrip() + "\n\nannotation PBI_ResultType = Table\n"

    p.write_text(text, encoding="utf-8")

def main():
    ap = argparse.ArgumentParser("Polish table TMDL files")
    ap.add_argument("--definition-dir", required=True,
                    help="Path to .../<Base>.SemanticModel/definition")
    args = ap.parse_args()

    root = Path(args.definition_dir).expanduser().resolve()
    tables_dir = root / "tables"
    if not tables_dir.exists():
        raise SystemExit(f"Tables folder not found: {tables_dir}")

    # Process each table TMDL
    for f in sorted(tables_dir.glob("*.tmdl")):
        polish_table_file(f)

    print("✅ TMDL tables polished (removed 'columns:'/'partitions:', fixed braces, ensured annotation).")

if __name__ == "__main__":
    main()
