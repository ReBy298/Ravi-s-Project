#!/usr/bin/env python3
# scaffold_pbip.py — robust scaffold that understands placeholder template folders
# - Supports smtemplate.SemanticModel / rtemplate.Report (template placeholders)
# - Produces final OUT_PBIP/<Base>/<Base>.SemanticModel and <Base>.Report
# - Copies all definition files and the tables/*.tmdl
# - Writes a minimal <Base>.pbip manifest
#
# Usage (as your run_all.sh does):
#   python scaffold_pbip.py --project-root /path/to/project --pbip-name SampleTableau.pbip --force

import argparse
import json
import shutil
import sys
from pathlib import Path

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def rm_tree(p: Path) -> None:
    if p.exists():
        shutil.rmtree(p)

def _find_sem_model_dir(pbip_dir: Path) -> Path:
    """Inside the intermediate PBIP folder (<Base>.pbip), find the semantic model root."""
    for name in ("SemanticModel", "smtemplate.SemanticModel", "template.SemanticModel"):
        cand = pbip_dir / name
        if cand.exists() and cand.is_dir():
            return cand
    raise FileNotFoundError(f"No SemanticModel folder found under {pbip_dir}")

def _find_report_dir(pbip_dir: Path) -> Path:
    """Inside the intermediate PBIP folder (<Base>.pbip), find the report root."""
    for name in ("Report", "rtemplate.Report", "template.Report"):
        cand = pbip_dir / name
        if cand.exists() and cand.is_dir():
            return cand
    raise FileNotFoundError(f"No Report folder found under {pbip_dir}")

def _copy_definition(src_sem: Path, dst_sem: Path) -> None:
    """Copy 'definition' (and .pbi if present) from src_sem to dst_sem."""
    src_def = src_sem / "definition"
    if not src_def.exists():
        raise SystemExit(f"[ERROR] Source definition folder not found: {src_def}")

    # Copy definition root files
    dst_def = dst_sem / "definition"
    ensure_dir(dst_def)

    # subfolder: tables
    ensure_dir(dst_def / "tables")
    tables_src = src_def / "tables"
    if tables_src.exists():
        for tmdl in tables_src.glob("*.tmdl"):
            (dst_def / "tables" / tmdl.name).write_text(tmdl.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        print(f"[WARN] No 'tables' folder in {src_def}; continuing")

    # other files in definition (database.tmdl, model.tmdl, relationships.tmdl, cultures/, etc.)
    for item in src_def.iterdir():
        if item.name == "tables":
            continue
        if item.is_file():
            (dst_def / item.name).write_text(item.read_text(encoding="utf-8"), encoding="utf-8")
        elif item.is_dir():
            # shallow copy directories like cultures/
            dst_sub = dst_def / item.name
            ensure_dir(dst_sub)
            for f in item.rglob("*"):
                rel = f.relative_to(item)
                dst_f = dst_sub / rel
                if f.is_dir():
                    ensure_dir(dst_f)
                else:
                    ensure_dir(dst_f.parent)
                    dst_f.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

    # optional .pbi folder (editorSettings.json, etc.)
    src_pbi = src_sem / ".pbi"
    if src_pbi.exists():
        for f in src_pbi.rglob("*"):
            rel = f.relative_to(src_pbi)
            dst_f = dst_sem / ".pbi" / rel
            if f.is_dir():
                ensure_dir(dst_f)
            else:
                ensure_dir(dst_f.parent)
                try:
                    dst_f.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
                except UnicodeDecodeError:
                    # binary or unknown encoding; copy raw
                    ensure_dir(dst_f.parent)
                    shutil.copy2(f, dst_f)

def _copy_report(src_report: Path, dst_report: Path) -> None:
    """Copy the report folder (definition.pbir, etc.)."""
    ensure_dir(dst_report)
    for f in src_report.rglob("*"):
        rel = f.relative_to(src_report)
        dst_f = dst_report / rel
        if f.is_dir():
            ensure_dir(dst_f)
        else:
            ensure_dir(dst_f.parent)
            try:
                dst_f.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
            except UnicodeDecodeError:
                shutil.copy2(f, dst_f)

def _patch_pbir_to_relative(dst_report: Path) -> None:
    """
    Optional quality-of-life: if definition.pbir exists and contains absolute dataset paths,
    nudge them to use relative paths (../<Base>.SemanticModel/definition).
    This is best-effort; if the structure doesn't match JSON, we leave it as-is.
    """
    pbir = dst_report / "definition.pbir"
    if not pbir.exists():
        return
    try:
        data = json.loads(pbir.read_text(encoding="utf-8"))
    except Exception:
        return

    # Very light patch: prefer relativeReferences if present in schema
    # We just write back the same JSON to normalize formatting; custom patches can be added here
    pbir.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def _write_manifest(final_root: Path, base: str) -> None:
    """
    Write a minimal <Base>.pbip manifest that points to <Base>.Report and <Base>.SemanticModel.
    Power BI Desktop accepts a simple JSON with 'artifacts'.
    """
    manifest_path = final_root / f"{base}.pbip"
    manifest = {
        "version": "1.0",
        "artifacts": [
            {"location": f"{base}.Report", "type": "Report"},
            {"location": f"{base}.SemanticModel", "type": "SemanticModel"}
        ]
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

def main():
    ap = argparse.ArgumentParser("PBIP scaffold (template model + generated TMDLs)")
    ap.add_argument("--project-root", required=True)
    ap.add_argument("--pbip-name", required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    root = Path(args.project_root)
    base = args.pbip_name[:-5] if args.pbip_name.endswith(".pbip") else args.pbip_name

    intermediate_pbip = root / "OUT_PBIP" / f"{base}.pbip"
    if not intermediate_pbip.exists():
        sys.exit(f"[ERROR] Intermediate PBIP not found: {intermediate_pbip}")

    # final output root (directory that will contain <Base>.pbip + folders)
    final_root = root / "OUT_PBIP" / base
    if args.force and final_root.exists():
        rm_tree(final_root)
    ensure_dir(final_root)

    # Find source folders (placeholder-friendly)
    src_sem = _find_sem_model_dir(intermediate_pbip)
    src_report = _find_report_dir(intermediate_pbip)

    # Dest folders
    dst_sem = final_root / f"{base}.SemanticModel"
    dst_report = final_root / f"{base}.Report"

    # Copy
    _copy_definition(src_sem, dst_sem)
    _copy_report(src_report, dst_report)
    _patch_pbir_to_relative(dst_report)

    # Manifest
    _write_manifest(final_root, base)

    print("✅ PBIP scaffold ready")
    print(f" - Manifest:      {final_root / (base + '.pbip')}")
    print(f" - Report folder: {dst_report}")
    print(f" - SemanticModel: {dst_sem}")

if __name__ == "__main__":
    main()
