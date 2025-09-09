#!/usr/bin/env python3
# scaffold_pbip.py (v3)
# Produces:
# OUT_PBIP/<BASE>/<BASE>.pbip                ← FILE
# OUT_PBIP/<BASE>/<BASE>.Report/             ← FOLDER (from template)
# OUT_PBIP/<BASE>/<BASE>.SemanticModel/...   ← FOLDER (your TMDLs preferred)

import argparse
import shutil
import sys
from pathlib import Path

def copytree(src: Path, dst: Path):
    if src.exists():
        shutil.copytree(src, dst, dirs_exist_ok=True)

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def must_exist(p: Path, label: str):
    if not p.exists():
        sys.exit(f"[ERROR] Missing {label}: {p}")

def main():
    ap = argparse.ArgumentParser("Scaffold PBIP with user-generated TMDLs preferred")
    ap.add_argument("--project-root", required=True, help="Folder with pbip_template/ and OUT_PBIP/")
    ap.add_argument("--pbip-name", required=True, help="e.g., SampleTableau.pbip or SampleTableau")
    ap.add_argument("--force", action="store_true", help="Remove OUT_PBIP/<BASE> before creating")
    args = ap.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    template_root = project_root / "pbip_template"
    must_exist(template_root, "template root (pbip_template)")

    base = args.pbip_name[:-5] if args.pbip_name.endswith(".pbip") else args.pbip_name
    out_root = project_root / "OUT_PBIP" / base
    if args.force and out_root.exists():
        shutil.rmtree(out_root)
    ensure_dir(out_root)

    # Template assets
    tpl_manifest = template_root / "PBIPTemplate.pbip"
    tpl_report   = template_root / "rtemplate.Report"
    tpl_sem      = template_root / "smtemplate.SemanticModel"
    tpl_enus     = tpl_sem / "definition" / "cultures" / "en-US.tmdl"
    tpl_db       = tpl_sem / "definition" / "database.tmdl"
    tpl_model    = tpl_sem / "definition" / "model.tmdl"
    tpl_rel      = tpl_sem / "definition" / "relationships.tmdl"
    tpl_tables   = tpl_sem / "definition" / "tables"
    tpl_pbism    = tpl_sem / "definition.pbism"
    tpl_layout   = tpl_sem / "diagramLayout.json"

    # Generated (source) — this is exactly where pbip_integrate.py wrote them
    gen_root = project_root / "OUT_PBIP" / f"{base}.pbip" / "SemanticModel" / "definition"
    gen_model = gen_root / "model.tmdl"
    gen_rel   = gen_root / "relationships.tmdl"
    gen_db    = gen_root / "database.tmdl"
    gen_tables= gen_root / "tables"

    # Outputs
    out_manifest = out_root / f"{base}.pbip"
    out_report   = out_root / f"{base}.Report"
    out_sem      = out_root / f"{base}.SemanticModel"
    out_def      = out_sem / "definition"
    out_tables   = out_def / "tables"
    out_cult     = out_def / "cultures"

    # 1) Write manifest file (.pbip)
    must_exist(tpl_manifest, "PBIPTemplate.pbip")
    shutil.copy2(tpl_manifest, out_manifest)
    txt = out_manifest.read_text(encoding="utf-8")
    txt = txt.replace("@@.Report@@", f"{base}.Report").replace("@@.SemanticModel@@", f"{base}.SemanticModel")
    out_manifest.write_text(txt, encoding="utf-8")

    # 2) Report folder
    must_exist(tpl_report, "report template (rtemplate.Report)")
    ensure_dir(out_report)
    copytree(tpl_report, out_report)

    # 3) SemanticModel folder
    ensure_dir(out_sem); ensure_dir(out_def); ensure_dir(out_tables); ensure_dir(out_cult)

    # cultures/en-US.tmdl from template (static)
    must_exist(tpl_enus, "culture file en-US.tmdl")
    shutil.copy2(tpl_enus, out_cult / "en-US.tmdl")

    # Helper: copy preferring generated, fallback to template
    def copy_preferring_generated(gen: Path, tpl: Path, out: Path, label: str):
        src = gen if gen and gen.exists() else tpl
        if not src or not src.exists():
            sys.exit(f"[ERROR] Missing {label}. Looked for: {gen} and {tpl}")
        shutil.copy2(src, out)
        print(f"[OK] {label}: {src} -> {out}")

    # model / relationships / database
    copy_preferring_generated(gen_model, tpl_model, out_def / "model.tmdl", "model.tmdl")
    copy_preferring_generated(gen_rel,   tpl_rel,   out_def / "relationships.tmdl", "relationships.tmdl")
    copy_preferring_generated(gen_db,    tpl_db,    out_def / "database.tmdl", "database.tmdl")

    # tables/*.tmdl — prefer generated directory, otherwise use template tables
    src_tables = gen_tables if (gen_tables.exists() and any(gen_tables.iterdir())) else tpl_tables
    if not src_tables or not src_tables.exists():
        sys.exit(f"[ERROR] Missing tables dir. Looked for: {gen_tables} and {tpl_tables}")
    # Copy each .tmdl file (avoid nested subfolders)
    ensure_dir(out_tables)
    count = 0
    for f in src_tables.glob("*.tmdl"):
        shutil.copy2(f, out_tables / f.name)
        count += 1
    print(f"[OK] tables: copied {count} table TMDLs from {src_tables}")

    # pbism & diagram layout from template
    must_exist(tpl_pbism, "definition.pbism")
    must_exist(tpl_layout, "diagramLayout.json")
    shutil.copy2(tpl_pbism,  out_sem / "definition.pbism")
    shutil.copy2(tpl_layout, out_sem / "diagramLayout.json")

    print("\n✅ PBIP scaffold ready")
    print(f" - {out_manifest}")
    print(f" - {out_report}")
    print(f" - {out_sem}")

if __name__ == "__main__":
    main()
