#!/usr/bin/env python3
"""
run_tableau_to_pbip.py
Orchestrates the existing scripts (tableau_xml_to_bossstyle_ai.py + pbip_integrate.py)
so you can pass just a project folder and it runs end-to-end without editing variables.

Folder convention under --project-root (defaults shown):
  ├── datasource_demo_tableau.xml
  ├── prompt.txt
  ├── pbip_template/
  │   └── PBIPTemplate.pbip         (default template name; can be changed with --template-name)
  ├── out/                          (will be created if missing)
  └── OUT_PBIP/                     (will be created; contains the final PBIP folder)

Environment:
  - Reads standard env vars (AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_VERSION)
  - If a ".env" file exists in --project-root, loads KEY=VALUE pairs into the environment (no dependency on python-dotenv).

Usage examples:
  python run_tableau_to_pbip.py --project-root "/Users/rebeca.mendoza/Desktop/Ravi" \
    --provider azure --model "gpt-5-mini" --tables ALL \
    --pbip-name "SampleTableau.pbip"

  python run_tableau_to_pbip.py --project-root "/Users/rebeca.mendoza/Desktop/Ravi" \
    --provider azure --model "gpt-5-mini" --tables Orders,People,Returned

Notes:
  - This script *does not* change your existing scripts. It calls them via subprocess.
  - It auto-discovers table names from the XML when --tables ALL (default).
  - It removes the existing PBIP output folder if --force is specified (fresh run).
"""

import argparse
import os
import re
import sys
import json
import shutil
import subprocess
from pathlib import Path


def load_dotenv_if_exists(project_root: Path):
    env_file = project_root / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        os.environ[key] = val


def discover_tables_from_xml(xml_path: Path):
    """
    Heuristic discovery of table names from a Tableau datasource XML.
    Looks for patterns like [schema].[TableName] or attributes table="[schema].[TableName]".
    Returns a sorted list of unique table names (without schema).
    """
    if not xml_path.exists():
        raise FileNotFoundError(f"XML not found: {xml_path}")
    text = xml_path.read_text(encoding="utf-8", errors="ignore")
    # Matches [schema].[TableName]
    matches = re.findall(r"\[([^\]]+)\]\.\[([^\]]+)\]", text)
    tables = {tbl for (_schema, tbl) in matches}
    # Also try to get direct 'table="TableName"' (no schema) occurrences
    matches2 = re.findall(r'table\s*=\s*"([^"]+)"', text, flags=re.IGNORECASE)
    for m in matches2:
        # if it's already schema-qualified, split to get the last chunk
        if m.startswith("[") and "].[" in m:
            m2 = re.findall(r"\[([^\]]+)\]\.\[([^\]]+)\]", m)
            if m2:
                tables.add(m2[0][1])
        else:
            # plain name
            tables.add(m)
    out = sorted(tables)
    return out


def run_cmd(cmd, cwd=None):
    print("\n$ " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=cwd)
    if proc.returncode != 0:
        raise SystemExit(f"Command failed with exit code {proc.returncode}: {' '.join(cmd)}")


def main():
    ap = argparse.ArgumentParser(description="Run Tableau→BossStyle→PBIP pipeline with one command.")
    ap.add_argument("--project-root", required=True, help="Folder containing datasource_demo_tableau.xml, prompt.txt, pbip_template/, etc.")
    ap.add_argument("--provider", default="azure", choices=["azure","openai"], help="LLM provider (default: azure)")
    ap.add_argument("--model", default="gpt-5-mini", help="Model or (for Azure) the *deployment name*")
    ap.add_argument("--tables", default="ALL", help="Comma-separated list (e.g., Orders,People,Returned) or ALL to auto-discover from XML")
    ap.add_argument("--template-name", default="PBIPTemplate.pbip", help="Template file name inside pbip_template/ (default: PBIPTemplate.pbip)")
    ap.add_argument("--pbip-name", default="SampleTableau.pbip", help="Name of the output PBIP folder (default: SampleTableau.pbip)")
    ap.add_argument("--force", action="store_true", help="If set, deletes OUT_PBIP/<pbip-name> before building (fresh run).")
    ap.add_argument("--python-bin", default=sys.executable, help="Python interpreter to use (default: current python).")
    args = ap.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    load_dotenv_if_exists(project_root)

    xml_path = project_root / "datasource_demo_tableau.xml"
    prompt_path = project_root / "prompt.txt"
    out_dir = project_root / "out"
    tmdl_template = project_root / "pbip_template" / args.template_name
    pbip_out_dir = project_root / "OUT_PBIP"
    pbip_out = pbip_out_dir / args.pbip_name

    # Sanity checks
    if not xml_path.exists():
        raise SystemExit(f"Missing XML: {xml_path}")
    if not prompt_path.exists():
        raise SystemExit(f"Missing prompt.txt: {prompt_path}")
    if not tmdl_template.exists():
        raise SystemExit(f"Missing template PBIP: {tmdl_template}")

    out_dir.mkdir(parents=True, exist_ok=True)
    pbip_out_dir.mkdir(parents=True, exist_ok=True)
    if args.force and pbip_out.exists():
        shutil.rmtree(pbip_out, ignore_errors=True)

    # Determine tables
    if args.tables.strip().upper() == "ALL":
        tables = discover_tables_from_xml(xml_path)
        if not tables:
            # Fallback to the known trio
            tables = ["Orders","People","Returned"]
    else:
        tables = [t.strip() for t in args.tables.split(",") if t.strip()]

    print(f"Using tables: {tables}")

    # Paths to the existing scripts (assumed to live in the same folder or project root)
    # Try to resolve them under project root first; otherwise fallback to current working dir.
    t2b = project_root / "tableau_xml_to_bossstyle_ai.py"
    if not t2b.exists():
        t2b = Path("tableau_xml_to_bossstyle_ai.py").resolve()
    pbi_int = project_root / "pbip_integrate.py"
    if not pbi_int.exists():
        pbi_int = Path("pbip_integrate.py").resolve()

    if not t2b.exists():
        raise SystemExit(f"Cannot find tableau_xml_to_bossstyle_ai.py in {project_root} or CWD.")
    if not pbi_int.exists():
        raise SystemExit(f"Cannot find pbip_integrate.py in {project_root} or CWD.")

    # Step 1: Generate boss-style columns and M partitions for each table
    for tbl in tables:
        cols_file = out_dir / f"{tbl}_columns_boss_style.txt"
        part_file = out_dir / f"{tbl}_partition.m"

        cmd_gen = [
            args.python_bin, str(t2b),
            "--input", str(xml_path),
            "--out-dir", str(out_dir),
            "--provider", args.provider,
            "--model", args.model,
            "--prompt-file", str(prompt_path),
            "--table", tbl
        ]
        run_cmd(cmd_gen)

    # Step 2: Integrate into PBIP for each table
    # The first call creates the PBIP from the template. Subsequent calls add tables into the same PBIP.
    for idx, tbl in enumerate(tables):
        cols_file = out_dir / f"{tbl}_columns_boss_style.txt"
        part_file = out_dir / f"{tbl}_partition.m"
        if not cols_file.exists():
            raise SystemExit(f"Missing columns file for {tbl}: {cols_file}")
        if not part_file.exists():
            raise SystemExit(f"Missing partition file for {tbl}: {part_file}")

        cmd_pbi = [
            args.python_bin, str(pbi_int),
            "--xml", str(xml_path),
            "--pbip-template", str(tmdl_template),
            "--pbip-out", str(pbip_out),
            "--table", tbl,
            "--columns-file", str(cols_file),
            "--partition-file", str(part_file)
        ]
        run_cmd(cmd_pbi)

    print("\n✅ Done!")
    print(f"PBIP created at: {pbip_out}")
    print("Open it with Power BI to verify tables, columns, relationships and partitions.")
    

if __name__ == "__main__":
    main()
