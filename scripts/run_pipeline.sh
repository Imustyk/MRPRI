#!/usr/bin/env bash
# Full pipeline, in order. Every stage is idempotent: re-running does not
# duplicate documents and never mutates already stored raw data.
#
#   ./scripts/run_pipeline.sh                             # full history
#   ./scripts/run_pipeline.sh --since 2024-01-01T00:00:00Z  # recent only
#   ./scripts/run_pipeline.sh --inventory data/raw/other.jsonl --limit 200
#   SMOKE=1 ./scripts/run_pipeline.sh                     # tiny end-to-end check
#
# Arguments are passed through to scripts/01b_fetch_records.py verbatim, so both
# `--since 2024-01-01T00:00:00Z` and a single quoted "--since 2024-01-01" work.
set -euo pipefail

cd "$(dirname "$0")/.."
PY=.venv/bin/python

# --since 2018-10-18T00:00:00Z is the first release the platform serves.
if [ $# -eq 0 ]; then
  FETCH_ARGS=(--since 2018-10-18T00:00:00Z)
else
  FETCH_ARGS=("$@")
fi

# SMOKE=1 keeps every stage but bounds the network work, so the whole chain can
# be proved end to end in a couple of minutes instead of a full-history crawl.
if [ "${SMOKE:-0}" = "1" ]; then
  SMOKE_DB="mtender_smoke"
  FETCH_ARGS+=(--limit 120)
  echo "SMOKE=1: using database '$SMOKE_DB', at most 120 OCIDs, 20 scan pages"
else
  SMOKE_DB="${MONGO_DB_NAME:-mtender}"
fi
export MONGO_DB_NAME="$SMOKE_DB"

echo "== 0. regression tests for the verified API behaviours =="
$PY -m pytest tests -q

echo "== 0b. verify the live API and MongoDB =="
$PY scripts/00_check_api.py --mongo

# The scanner appends to the inventory and is resumable, but two concurrent
# scans would interleave writes into the same file, so skip it if one is live.
if pgrep -f "01a_scan_ocids.py" >/dev/null 2>&1; then
  echo "== 1a. scan already running elsewhere, skipping =="
else
  echo "== 1a. walk the OCID history =="
  if [ "${SMOKE:-0}" = "1" ]; then
    $PY scripts/01a_scan_ocids.py --max-pages 20
  else
    $PY scripts/01a_scan_ocids.py
  fi
fi

# --archive stores the untouched response bodies under data/raw/ocds_packages/
# so scripts/seed_mongo.py can rebuild the database without the API.
echo "== 1b. fetch OCDS packages ${FETCH_ARGS[*]} =="
$PY scripts/01b_fetch_records.py "${FETCH_ARGS[@]}" --archive

# Second and third official sources. Both are loaded after 01b because the MoF
# extract is cross-checked against the fetched records, which is the point of
# storing it separately instead of merging it into raw_tenders.
echo "== 1c. load the Ministry of Finance open-data extracts (second source) =="
$PY scripts/10_load_mof_opendata.py

echo "== 1d. load the AAP prohibition list =="
$PY scripts/11_load_blacklist.py

echo "== 2. normalise + validation report =="
$PY scripts/02_normalize_mongo.py

echo "== 3. engineer features =="
$PY scripts/03_features_mongo.py

echo "== 4. export modelling snapshot =="
$PY scripts/04_export_snapshot.py

echo "== 5. descriptive aggregations =="
$PY scripts/05_aggregations.py

echo "== 6. anomaly detection =="
$PY scripts/06_detect_anomalies.py

echo "== 7. explainability =="
$PY scripts/07_explainability.py

echo "== 8. regenerate the data dictionary from live responses =="
$PY scripts/08_data_dictionary.py --sample 60

echo "== 9. compare flagged suppliers against the official AAP blacklist =="
$PY scripts/09_external_validation.py

echo
echo "done. tables -> results/tables, figures -> results/figures, logs -> results/logs"
echo "database used: $SMOKE_DB"
echo "to rebuild that database from the archived bodies:"
echo "  MONGO_DB_NAME=$SMOKE_DB $PY scripts/seed_mongo.py --target $SMOKE_DB --drop"
