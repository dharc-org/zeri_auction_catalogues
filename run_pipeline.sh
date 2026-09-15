#!/usr/bin/env bash
# ZAC catalogues pipeline orchestrator
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"   # richiesto: enrich_artist_school.py e i default di
                      # extract_collections_periods.py / assign_entities_via_title_match.py
                      # sono path relativi alla cwd

COLLECTIONS_CSV="${PROJECT_ROOT}/extracted_collections.csv"
PERIODS_CSV="${PROJECT_ROOT}/extracted_periods.csv"
RUN_ALL=false
SKIP_REVIEW_CHECK=false

usage() {
  cat <<EOF
Usage: $(basename "$0") [--all] [--skip-review-check]

  --all                 Passa --all a app/generate_rdf.py (tutti i cataloghi, non solo reviewed=1)
  --skip-review-check   Salta il controllo sulle righe new=True in extracted_collections/periods.csv
EOF
  exit 1
}

for arg in "$@"; do
  case "$arg" in
    --all) RUN_ALL=true ;;
    --skip-review-check) SKIP_REVIEW_CHECK=true ;;
    -h|--help) usage ;;
    *) echo "Argomento sconosciuto: $arg"; usage ;;
  esac
done

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1"; }

# ritorna 1 se il csv contiene almeno una riga con new == True
has_pending_review() {
  local file="$1"
  python3 - "$file" <<'PY'
import csv, sys
path = sys.argv[1]
try:
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if str(row.get("new", "")).strip().lower() == "true":
                sys.exit(1)
except FileNotFoundError:
    pass
sys.exit(0)
PY
}

# ---- 1. extract_collections_periods.py -----------------------------------
log "STEP 1/4: extract_collections_periods.py"
python3 "${PROJECT_ROOT}/extract_collections_periods.py"

if [[ "$SKIP_REVIEW_CHECK" == false ]]; then
  pending=false
  has_pending_review "$COLLECTIONS_CSV" || pending=true
  has_pending_review "$PERIODS_CSV" || pending=true
  if [[ "$pending" == true ]]; then
    log "Righe new=True presenti in extracted_collections.csv / extracted_periods.csv."
    log "Copiale nello spreadsheet ZERI_NER per la revisione, poi rilancia con --skip-review-check."
    exit 2
  fi
fi

# ---- 2. assign_entities_via_title_match.py (usa align_titles.py) --------
log "STEP 2/4: assign_entities_via_title_match.py"
python3 "${PROJECT_ROOT}/assign_entities_via_title_match.py"

# ---- 3. enrich_artist_school.py (nessun argomento CLI) --------------------
log "STEP 3/4: enrich_artist_school.py"
python3 "${PROJECT_ROOT}/enrich_artist_school_type.py"

# ---- 4. app/generate_rdf.py ------------------------------------------------
log "STEP 4/4: app/generate_rdf.py"
if [[ "$RUN_ALL" == true ]]; then
  python3 "${PROJECT_ROOT}/app/generate_rdf.py" --all
else
  python3 "${PROJECT_ROOT}/app/generate_rdf.py"
fi

log "Pipeline completata. Output: ${PROJECT_ROOT}/lot_descriptions/zac_lot_descriptions_part*.nt"
