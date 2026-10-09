"""Verified MTender/OCDS access constants and filesystem layout.

Every URL in this module was discovered from an official source and tested with
a real HTTP request on the verification date recorded in
``docs/API_INVESTIGATION_REPORT.md``. Nothing here is assumed.

Verification date: 2026-09-26
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
DATA_FEATURES = ROOT / "data" / "features"
RESULTS = ROOT / "results"
TABLES = RESULTS / "tables"
FIGURES = RESULTS / "figures"
MODELS = RESULTS / "models"
MONGO_META = RESULTS / "mongo"

for _p in (DATA_RAW, DATA_PROCESSED, DATA_FEATURES, TABLES, FIGURES, MODELS, MONGO_META):
    _p.mkdir(parents=True, exist_ok=True)

# --- Verified MTender endpoints (see docs/API_INVESTIGATION_REPORT.md) --------

#: OCID list. Keyset pagination: ``limit`` (<=300) + ``offset`` = ISO-8601 date
#: cursor. Response: {"data": [{"ocid", "date"}], "offset": <next cursor>}
MTENDER_BASE = "https://public.mtender.gov.md"
LIST_PATH = "/tenders/"
RECORD_PATH = "/tenders/{ocid}"

#: Server-side hard cap on ``limit``, measured by requesting 300/1000/2000/5000.
MAX_LIMIT = 300

#: The OCID list returns HTTP 200 with an empty body intermittently and
#: HTTP 500 for a malformed cursor, so every call is retried.
LIST_MAX_RETRIES = 6
RECORD_MAX_RETRIES = 5
HTTP_TIMEOUT = 60.0

#: Politeness: measured latency is ~40 ms per record and no rate limiting was
#: observed at 15 concurrent requests, but ingestion stays conservative.
INGEST_CONCURRENCY = int(os.environ.get("MTENDER_CONCURRENCY", "6"))
REQUEST_PAUSE_SECONDS = float(os.environ.get("MTENDER_PAUSE", "0.0"))

USER_AGENT = "diplom-thesis-research/1.0 (academic public-procurement anomaly research)"

# --- MongoDB (verified running locally, see docs/API_INVESTIGATION_REPORT.md)

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017/?replicaSet=rs0")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "mtender")
