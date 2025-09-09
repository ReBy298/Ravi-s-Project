#!/usr/bin/env bash
# run_all.sh
# One-shot pipeline: venv + requirements, env loading, LLM generation,
# PBIP integration (TMDLs), and final PBIP scaffold (.pbip + Report + SemanticModel)

set -euo pipefail

PROJECT_ROOT="${1:-$(pwd)}"
PROVIDER="${2:-azure}"
MODEL="${3:-gpt-5-mini}"
PBIP_NAME="${4:-SampleTableau.pbip}"
TEMPLATE_NAME="${5:-PBIPTemplate.pbip}"
TABLES="${6:-Orders,People,Returned}"
FORCE="${7:-true}"   # true/false → fresh build

cd "$PROJECT_ROOT"

# 0) venv + requirements (optional)
if [ -f "requirements.txt" ]; then
  if [ ! -d ".venv" ]; then
    python3 -m venv .venv
  fi
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
  pip install --upgrade pip
  pip install -r "requirements.txt"
fi

# 1) load .env if present (so Ravi only needs the folder)
if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

PYBIN="${PYBIN:-python}"   # allow override if needed

# 2) LLM + integration (this generates columns/partitions and TMDLs)
$PYBIN "run_tableau_to_pbip.py" \
  --project-root "$PROJECT_ROOT" \
  --provider "$PROVIDER" \
  --model "$MODEL" \
  --tables "$TABLES" \
  --pbip-name "$PBIP_NAME" \
  --template-name "$TEMPLATE_NAME" \
  --force

# 3) Final scaffold: write <Base>.pbip (file) + <Base>.Report + <Base>.SemanticModel
SC_FORCE_FLAG=""
if [ "$FORCE" = "true" ]; then
  SC_FORCE_FLAG="--force"
fi

$PYBIN "scaffold_pbip.py" \
  --project-root "$PROJECT_ROOT" \
  --pbip-name "$PBIP_NAME" \
  $SC_FORCE_FLAG

echo
echo "✅ All done."
BASE="${PBIP_NAME%.pbip}"
echo "Open: $PROJECT_ROOT/OUT_PBIP/$BASE/$BASE.pbip in Power BI Desktop."
