#!/usr/bin/env bash
# run_all.sh
# One-shot pipeline: venv + requirements, env loading, LLM generation,
# PBIP integration (TMDLs), scaffold final PBIP (.pbip + Report + SemanticModel),
# then TMDL formatting/polishing (correct order).

set -euo pipefail

# -------------------------
# Args (with defaults)
# -------------------------
PROJECT_ROOT="${1:-$(pwd)}"
PROVIDER="${2:-azure}"
MODEL="${3:-gpt-5-mini}"
PBIP_NAME="${4:-SampleTableau.pbip}"
TEMPLATE_NAME="${5:-PBIPTemplate.pbip}"
TABLES="${6:-Orders,People,Returned}"
FORCE="${7:-true}"   # true/false → fresh build

cd "$PROJECT_ROOT"

# -------------------------
# Python env & deps
# -------------------------
if [ -f "requirements.txt" ]; then
  if [ ! -d ".venv" ]; then
    python3 -m venv .venv
  fi
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
  pip install --upgrade pip
  pip install -r "requirements.txt"
fi

# Use venv python if present (allows override via env PYBIN)
if [ -d ".venv" ]; then
  PYBIN="${PYBIN:-$PROJECT_ROOT/.venv/bin/python}"
else
  PYBIN="${PYBIN:-python}"
fi

# -------------------------
# Load env vars from .env (optional)
# -------------------------
if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

# -------------------------
# 1) Generation + integration (intermediate PBIP at OUT_PBIP/<BASE>.pbip/…)
# -------------------------
$PYBIN "run_tableau_to_pbip.py" \
  --project-root "$PROJECT_ROOT" \
  --provider "$PROVIDER" \
  --model "$MODEL" \
  --tables "$TABLES" \
  --pbip-name "$PBIP_NAME" \
  --template-name "$TEMPLATE_NAME" \
  --force

# -------------------------
# 2) Final scaffold: <Base>.pbip (file) + <Base>.Report + <Base>.SemanticModel
# -------------------------
SC_FORCE_FLAG=""
if [ "$FORCE" = "true" ]; then
  SC_FORCE_FLAG="--force"
fi

$PYBIN "scaffold_pbip.py" \
  --project-root "$PROJECT_ROOT" \
  --pbip-name "$PBIP_NAME" \
  $SC_FORCE_FLAG

# -------------------------
# 3) Post-processing (on final SemanticModel/definition)
#    Important order:
#      a) normalize (curly blocks → label style)
#      b) polish tables (drop 'columns:' / 'partitions:', fix M braces, ensure annotation)
#      c) polish relationships (optional rules)
# -------------------------
BASE="${PBIP_NAME%.pbip}"
DEF_DIR="$PROJECT_ROOT/OUT_PBIP/$BASE/$BASE.SemanticModel/definition"

# a) Normalize TMDL style (introduces 'columns:'/'partitions:' labels from braces)
if [ -f "normalize_tmdl_style.py" ]; then
  $PYBIN "normalize_tmdl_style.py" --root "$DEF_DIR"
fi

# b) Polish tables: remove wrappers, fix braces, ensure PBI_ResultType
if [ -f "polish_tables_tmdl.py" ]; then
  $PYBIN "polish_tables_tmdl.py" --definition-dir "$DEF_DIR"
fi

# c) Keep only desired relationships; drop LocalDateTable auto-date (adjust --keep as needed)
if [ -f "polish_relationships_tmdl.py" ]; then
  $PYBIN "polish_relationships_tmdl.py" \
    --definition-dir "$DEF_DIR" \
    --keep "Orders.Region=People.Region,Orders.Order_ID=Returned.Order_ID" \
    --drop-localdatetable
fi

# -------------------------
# Done
# -------------------------
echo
echo "✅ All done."
echo "Open: $PROJECT_ROOT/OUT_PBIP/$BASE/$BASE.pbip in Power BI Desktop."
