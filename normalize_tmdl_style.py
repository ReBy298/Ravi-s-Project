#!/usr/bin/env python3
# normalize_tmdl_style.py
# Cosmetic TMDL rewriter:
# - Removes curly-brace block style and converts known openers to "label:" lines
# - Keeps semantics intact (NO JSON). Purely formatting.

import argparse, re
from pathlib import Path

BLOCK_OPENERS = [
    r"columns", r"measures", r"hierarchies", r"partitions", r"annotations",
    r"calculationGroups?", r"dataAccessOptions", r"legacyRedirects",
    r"formatStringDefinition", r"displayFolders", r"roles", r"tables"
]

# Regexes
RE_OPEN_BRACE_LINE = re.compile(r"^\s*\{\s*$")
RE_CLOSE_BRACE_LINE = re.compile(r"^\s*\}\s*$")
RE_TABLE_HEADER = re.compile(r"^(?P<indent>\s*)(table\s+[^\{\n]+)\s*\{\s*$")
RE_MODEL_HEADER = re.compile(r"^(?P<indent>\s*)(model\s+[^\{\n]*)\s*\{\s*$")
RE_REL_HEADER   = re.compile(r"^(?P<indent>\s*)(relationship\s+[^\{\n]+)\s*\{\s*$")
RE_BLOCK_LABELS = re.compile(rf"^(?P<indent>\s*)\b(?P<label>{'|'.join(BLOCK_OPENERS)})\b\s*\{{\s*$")
RE_EMPTY_LINES  = re.compile(r"\n{3,}")

def transform_text(t: str) -> str:
    out_lines = []
    for line in t.splitlines():
        # Convert headers "table X {" → "table X"
        m = RE_TABLE_HEADER.match(line)
        if m:
            out_lines.append(f"{m.group('indent')}{m.group(2)}")
            continue
        m = RE_MODEL_HEADER.match(line)
        if m:
            out_lines.append(f"{m.group('indent')}{m.group(2)}")
            continue
        m = RE_REL_HEADER.match(line)
        if m:
            out_lines.append(f"{m.group('indent')}{m.group(2)}")
            continue

        # Convert known block openers "columns {" → "columns:"
        m = RE_BLOCK_LABELS.match(line)
        if m:
            out_lines.append(f"{m.group('indent')}{m.group('label')}:")
            continue

        # Drop pure "{" / "}" lines
        if RE_OPEN_BRACE_LINE.match(line) or RE_CLOSE_BRACE_LINE.match(line):
            continue

        out_lines.append(line)

    text = "\n".join(out_lines)
    # Collapse excessive blank lines
    text = RE_EMPTY_LINES.sub("\n\n", text)
    return text.strip() + "\n"

def is_json_like(path: Path) -> bool:
    try:
        s = path.read_text(encoding="utf-8").lstrip()
        return s.startswith("{") or s.startswith("[")
    except Exception:
        return False

def process_file(p: Path):
    if p.suffix.lower() != ".tmdl":
        return
    if is_json_like(p):
        # Don't try to “prettify” actual JSON; upstream guard should avoid this case anyway.
        return
    original = p.read_text(encoding="utf-8")
    transformed = transform_text(original)
    if transformed != original:
        p.write_text(transformed, encoding="utf-8")

def main():
    ap = argparse.ArgumentParser("Normalize TMDL style (remove curly-brace blocks)")
    ap.add_argument("--root", required=True, help="Path to SemanticModel/definition directory")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.exists():
        raise SystemExit(f"Not found: {root}")
    for f in list(root.glob("*.tmdl")) + list((root / "tables").glob("*.tmdl")):
        process_file(f)
    print("TMDL files normalized (cosmetic formatting only).")

if __name__ == "__main__":
    main()
