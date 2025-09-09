#!/usr/bin/env bash
# run_all.sh
# Wrapper: crea/activa venv (si hay requirements.txt), carga .env
# y ejecuta el orquestador usando SOLO la carpeta del proyecto.

set -euo pipefail

PROJECT_ROOT="${1:-$(pwd)}"
PROVIDER="${2:-azure}"
MODEL="${3:-gpt-5-mini}"
PBIP_NAME="${4:-SampleTableau.pbip}"
TEMPLATE_NAME="${5:-PBIPTemplate.pbip}"

cd "$PROJECT_ROOT"

# Crear/activar venv si hay requirements.txt
if [ -f "requirements.txt" ]; then
  if [ ! -d ".venv" ]; then
    python3 -m venv .venv
  fi
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
  pip install --upgrade pip
  pip install -r "requirements.txt"
fi

# Cargar .env si existe
if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

# Verifica que el orquestador esté junto al proyecto
if [ ! -f "run_tableau_to_pbip.py" ]; then
  echo "ERROR: run_tableau_to_pbip.py no está en $PROJECT_ROOT"
  echo "Colócalo ahí o ajusta esta ruta en el script."
  exit 1
fi

python "run_tableau_to_pbip.py" \
  --project-root "$PROJECT_ROOT" \
  --provider "$PROVIDER" \
  --model "$MODEL" \
  --pbip-name "$PBIP_NAME" \
  --template-name "$TEMPLATE_NAME" \
  --force
