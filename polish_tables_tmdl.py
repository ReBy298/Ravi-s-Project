#!/usr/bin/env python3
# polish_tables_tmdl.py
# Formatea TMDL de tablas para que cumpla con:
#   - Sin etiquetas "columns:" / "partitions:"
#   - Indentación consistente:
#       table-level            -> 0
#       lineageTag (table)     -> 2
#       column <Name>          -> 2
#       props de columna       -> 4  (dataType, formatString, lineageTag, summarizeBy, sourceColumn)
#       annotation (col)       -> 4
#       variation Variation    -> 4
#           props de variation -> 6
#       partition … = m        -> 2
#           mode:, source =    -> 4
#           let / in           -> 6
#           líneas M           -> 8
#   - Asegura "annotation PBI_ResultType = Table" al final (indent 2)

import argparse
import re
from pathlib import Path

RE_COL_LABEL  = re.compile(r"^\s*columns\s*:\s*$", re.IGNORECASE)
RE_PART_LABEL = re.compile(r"^\s*partitions\s*:\s*$", re.IGNORECASE)

RE_TABLE      = re.compile(r"^\s*table\b", re.IGNORECASE)
RE_T_LINEAGE  = re.compile(r"^\s*lineageTag\s*:\s*", re.IGNORECASE)

RE_COLUMN     = re.compile(r"^\s*column\b", re.IGNORECASE)
RE_COL_PROP   = re.compile(r"^\s*(dataType|formatString|lineageTag|summarizeBy|sourceColumn)\s*:\s*", re.IGNORECASE)
RE_COL_ANN    = re.compile(r"^\s*annotation\b", re.IGNORECASE)

RE_VARIATION  = re.compile(r"^\s*variation\b", re.IGNORECASE)
RE_VAR_PROP   = re.compile(r"^\s*(isDefault|relationship\s*:|defaultHierarchy\s*:)", re.IGNORECASE)

RE_PARTITION  = re.compile(r"^\s*partition\b.*=\s*m\s*$", re.IGNORECASE)
RE_MODE       = re.compile(r"^\s*mode\s*:\s*", re.IGNORECASE)
RE_SOURCE     = re.compile(r"^\s*source\s*=", re.IGNORECASE)
RE_LET        = re.compile(r"^\s*let\s*$", re.IGNORECASE)
RE_IN         = re.compile(r"^\s*in\s*$", re.IGNORECASE)
RE_MLINE      = re.compile(r"^\s*(Source\s*=|srcSource\s*=|[A-Za-z0-9_]+_object\s*=)", re.IGNORECASE)

def indent(level: int, s: str) -> str:
    return (" " * level) + s.strip()

def polish_file(p: Path) -> None:
    text = p.read_text(encoding="utf-8")
    lines = text.splitlines()

    out = []
    state = "root"          # root | in_column | in_variation | in_partition | in_let
    skip_next_blank = False

    for raw in lines:
        ln = raw.rstrip()

        # Elimina labels
        if RE_COL_LABEL.match(ln) or RE_PART_LABEL.match(ln):
            skip_next_blank = True
            continue
        if skip_next_blank and not ln.strip():
            continue
        skip_next_blank = False

        s = ln.strip()
        if not s:
            out.append("")   # conservar líneas en blanco
            continue

        # Transiciones de estado
        if RE_TABLE.match(s):
            state = "root"
            out.append(s)  # "table X" sin indent extra
            continue

        if state == "root" and RE_T_LINEAGE.match(s):
            out.append(indent(2, s))
            continue

        if RE_COLUMN.match(s):
            state = "in_column"
            out.append(indent(2, s))
            continue

        if RE_PARTITION.match(s):
            state = "in_partition"
            out.append(indent(2, s))
            continue

        # ---- dentro de columna ----
        if state == "in_column":
            if RE_VARIATION.match(s):
                state = "in_variation"
                out.append(indent(4, s))
                continue
            if RE_COL_PROP.match(s):
                # dataType, formatString, lineageTag, summarizeBy, sourceColumn -> 4 espacios
                out.append(indent(4, s))
                continue
            if RE_COL_ANN.match(s):
                out.append(indent(4, s))
                continue
            # cualquier otra cosa en columna, deja a 4 por seguridad
            out.append(indent(4, s))
            continue

        # ---- dentro de variation ----
        if state == "in_variation":
            if RE_VAR_PROP.match(s):
                out.append(indent(6, s))
                continue
            # línea en blanco u otra cosa -> mantén 6 si parece prop; si no, baja a columna
            if s:  # algo no reconocido, trátalo como prop
                out.append(indent(6, s))
                continue

        # ---- dentro de partición ----
        if state == "in_partition":
            if RE_MODE.match(s) or RE_SOURCE.match(s):
                # normaliza "source =" y su indent
                s = s.replace("  ", " ")
                s = s.replace("=  ", "= ")
                out.append(indent(4, s))
                continue
            if RE_LET.match(s) or RE_IN.match(s):
                out.append(indent(6, s))
                # cuando vemos "in", seguimos en in_partition (el bloque M sigue)
                continue
            if RE_MLINE.match(s):
                out.append(indent(8, s))
                continue
            if RE_COL_ANN.match(s):
                # annotation PBI_ResultType (aunque suele ir fuera, toleramos aquí)
                out.append(indent(2, s))
                continue
            # fallback dentro de partición
            out.append(indent(6, s))
            continue

        # ---- fuera de bloques: annotations de nivel tabla, etc. ----
        if RE_COL_ANN.match(s):
            out.append(indent(2, s))
            continue

        # fallback general
        out.append(s)

        # Heurística de salida de estados:
        if RE_TABLE.match(s) or RE_PARTITION.match(s) or RE_COLUMN.match(s):
            # el próximo ciclo ajustará state
            pass

    # Asegura annotation final
    body = "\n".join(out).rstrip()
    if "annotation PBI_ResultType = Table" not in body:
        body += "\n\n  annotation PBI_ResultType = Table"

    p.write_text(body + "\n", encoding="utf-8")

def main():
    ap = argparse.ArgumentParser("Polish TMDL tables (indent exacto y sin labels)")
    ap.add_argument("--definition-dir", required=True, help=".../<Base>.SemanticModel/definition")
    args = ap.parse_args()

    tables_dir = Path(args.definition_dir) / "tables"
    if not tables_dir.exists():
        raise SystemExit(f"Not found tables dir: {tables_dir}")

    for f in sorted(tables_dir.glob("*.tmdl")):
        polish_file(f)

    print("✅ TMDL tables polished (indent exacto y sin labels).")

if __name__ == "__main__":
    main()
