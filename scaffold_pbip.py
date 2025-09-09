#!/usr/bin/env python3
# scaffold_pbip.py (final, with .pbir patch using ../ and optional .pbidataset)

import argparse
import shutil
import sys
from pathlib import Path

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def must(p: Path, label: str) -> None:
    if not p.exists():
        sys.exit(f"[ERROR] Missing {label}: {p}")

def copytree(src: Path, dst: Path) -> None:
    if src.exists():
        shutil.copytree(src, dst, dirs_exist_ok=True)

def is_json_like(p: Path) -> bool:
    try:
        s = p.read_text(encoding="utf-8").lstrip()
        return s.startswith("{") or s.startswith("[")
    except Exception:
        return False

def table_names_from_dir(tables_dir: Path) -> list[str]:
    return sorted([f.stem for f in tables_dir.glob("*.tmdl")])

def fill_model_placeholders(model_path: Path, tables_dir: Path) -> None:
    if not model_path.exists():
        return
    names = table_names_from_dir(tables_dir)
    text = model_path.read_text(encoding="utf-8")
    changed = False
    if "@@tablenamelist@@" in text:
        list_lit = "[" + ", ".join(f"'{t}'" for t in names) + "]"
        text = text.replace("@@tablenamelist@@", list_lit)
        changed = True
    if "@@reftable@@" in text:
        refs = "\n".join(f"ref table {t}" for t in names)
        text = text.replace("@@reftable@@", refs)
        changed = True
    if changed:
        model_path.write_text(text, encoding="utf-8")

def write_lightweight_pbidataset(sem_root: Path) -> None:
    pbid = sem_root / "definition.pbidataset"
    if not pbid.exists():
        pbid.write_text('{"version":"1.0","storageMode":"tmdl","path":"definition"}\n', encoding="utf-8")

def main():
    ap = argparse.ArgumentParser("PBIP scaffold (template model + generated TMDLs preferred)")
    ap.add_argument("--project-root", required=True)
    ap.add_argument("--pbip-name", required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    root = Path(args.project_root).expanduser().resolve()
    tpl_root = root / "pbip_template"
    must(tpl_root, "template root (pbip_template)")

    base = args.pbip_name[:-5] if args.pbip_name.endswith(".pbip") else args.pbip_name
    out_root = root / "OUT_PBIP" / base
    if args.force and out_root.exists():
        shutil.rmtree(out_root)
    ensure_dir(out_root)

    # Template assets
    tpl_manifest = tpl_root / "PBIPTemplate.pbip"
    tpl_report   = tpl_root / "rtemplate.Report"
    tpl_sem      = tpl_root / "smtemplate.SemanticModel"
    tpl_enus     = tpl_sem / "definition" / "cultures" / "en-US.tmdl"
    tpl_db       = tpl_sem / "definition" / "database.tmdl"
    tpl_model    = tpl_sem / "definition" / "model.tmdl"
    tpl_rel      = tpl_sem / "definition" / "relationships.tmdl"
    tpl_tables   = tpl_sem / "definition" / "tables"
    tpl_pbism    = tpl_sem / "definition.pbism"
    tpl_layout   = tpl_sem / "diagramLayout.json"

    # Generated intermediates
    gen_def      = root / "OUT_PBIP" / f"{base}.pbip" / "SemanticModel" / "definition"
    gen_rel      = gen_def / "relationships.tmdl"
    gen_db       = gen_def / "database.tmdl"
    gen_tables   = gen_def / "tables"

    # Outputs
    out_manifest = out_root / f"{base}.pbip"
    out_report   = out_root / f"{base}.Report"
    out_sem      = out_root / f"{base}.SemanticModel"
    out_def      = out_sem / "definition"
    out_tables   = out_def / "tables"
    out_cult     = out_def / "cultures"
    for d in (out_report, out_sem, out_def, out_tables, out_cult):
        ensure_dir(d)

    # 1) Manifest (.pbip)
    must(tpl_manifest, "PBIPTemplate.pbip")
    shutil.copy2(tpl_manifest, out_manifest)
    mtxt = out_manifest.read_text(encoding="utf-8")
    mtxt = (mtxt
            .replace("@@.Report@@", f"{base}.Report")
            .replace("@@.SemanticModel@@", f"{base}.SemanticModel"))
    out_manifest.write_text(mtxt, encoding="utf-8")

    # 2) Report + patch .pbir (relative path ../ to the semantic model)
    must(tpl_report, "rtemplate.Report")
    copytree(tpl_report, out_report)

    report_def = out_report / "definition.pbir"
    if report_def.exists():
        rtxt = report_def.read_text(encoding="utf-8")
        # Replace placeholder with a path relative to the Report folder:
        #   SampleTableau.Report/definition.pbir  ->  ../SampleTableau.SemanticModel
        rtxt = rtxt.replace("@@.SemanticModel@@", f"../{base}.SemanticModel")
        if "definition.pbidataset" in rtxt and (tpl_pbism.exists()):
            rtxt = rtxt.replace("definition.pbidataset", "definition.pbism")
        report_def.write_text(rtxt, encoding="utf-8")

    # 3) SemanticModel
    for src, dst in [(tpl_enus, out_cult / "en-US.tmdl"),
                     (tpl_pbism, out_sem / "definition.pbism"),
                     (tpl_layout, out_sem / "diagramLayout.json")]:
        must(src, src.name)
        shutil.copy2(src, dst)

    rel_src = gen_rel if (gen_rel.exists() and not is_json_like(gen_rel)) else tpl_rel
    must(rel_src, "relationships.tmdl (generated/template)")
    shutil.copy2(rel_src, out_def / "relationships.tmdl")

    db_src = gen_db if (gen_db.exists() and not is_json_like(gen_db)) else tpl_db
    must(db_src, "database.tmdl (generated/template)")
    shutil.copy2(db_src, out_def / "database.tmdl")

    copied_tables = 0
    if gen_tables.exists():
        for f in sorted(gen_tables.glob("*.tmdl")):
            if not is_json_like(f):
                shutil.copy2(f, out_tables / f.name)
                copied_tables += 1
    if copied_tables == 0 and tpl_tables.exists():
        for f in sorted(tpl_tables.glob("*.tmdl")):
            shutil.copy2(f, out_tables / f.name)
            copied_tables += 1
    if copied_tables == 0:
        sys.exit("[ERROR] No table TMDLs found to copy.")

    shutil.copy2(tpl_model, out_def / "model.tmdl")
    fill_model_placeholders(out_def / "model.tmdl", out_tables)

    # Optional .pbidataset alias (keeps Desktop happy in both modes)
    write_lightweight_pbidataset(out_sem)

    print("✅ PBIP scaffold ready")
    print(f" - Manifest:      {out_manifest}")
    print(f" - Report folder: {out_report}")
    print(f" - SemanticModel: {out_sem}")

if __name__ == "__main__":
    main()
