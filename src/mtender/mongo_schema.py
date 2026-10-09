"""Collection names and index definitions for the ``mtender`` database.

Names here are the ones actually created by the ingestion scripts; nothing is
declared that ``scripts/00_check_api.py --mongo`` cannot show as existing.

``raw_mof_procedures`` and ``raw_blacklist`` extend the specification's
ten-collection design with the two non-MTender official sources: the Ministry of
Finance monthly open-data extracts and the AAP prohibition list. They are raw
reference data, they are never joined into ``raw_tenders``, and the deviation is
recorded in ``thesis/STATUS.md``.
"""

from __future__ import annotations

RAW_RELEASES = "raw_releases"
RAW_TENDERS = "raw_tenders"
RAW_PARTIES = "raw_parties"
RAW_LOOKUPS = "raw_lookups"
RAW_MOF_PROCEDURES = "raw_mof_procedures"
RAW_BLACKLIST = "raw_blacklist"
NORM_TENDERS = "norm_tenders"
NORM_PARTIES = "norm_parties"
FEATURES_TENDERS = "features_tenders"
ANOMALY_SCORES = "anomaly_scores"
INGEST_RUNS = "ingest_runs"
VALIDATION_REPORTS = "validation_reports"

ALL_COLLECTIONS = (
    RAW_RELEASES,
    RAW_TENDERS,
    RAW_PARTIES,
    RAW_LOOKUPS,
    RAW_MOF_PROCEDURES,
    RAW_BLACKLIST,
    NORM_TENDERS,
    NORM_PARTIES,
    FEATURES_TENDERS,
    ANOMALY_SCORES,
    INGEST_RUNS,
    VALIDATION_REPORTS,
)

# Every index is justified by a query the pipeline actually runs; see
# src/mtender/aggregations.py and thesis section 2.3.2.
# Each entry is (name, [(field, direction), ...], {options}).
INDEXES: dict[str, list[tuple[str, list[tuple[str, int]], dict]]] = {
    RAW_RELEASES: [
        ("ocid_unique", [("ocid", 1)], {"unique": True}),
        # the resume check in 01b: which inventoried OCIDs still need a request
        ("settled", [("record_fetched", 1), ("ocid", 1)], {}),
    ],
    RAW_TENDERS: [
        ("ocid_unique", [("ocid", 1)], {"unique": True}),
    ],
    RAW_PARTIES: [
        ("party_key_unique", [("party_key", 1)], {"unique": True}),
        ("ocid_role", [("ocid", 1), ("role", 1)], {}),
    ],
    RAW_MOF_PROCEDURES: [
        # CPID in the open-data files is the MTender OCID, so this is the join key
        # against raw_tenders
        ("ocid_unique", [("ocid", 1)], {"unique": True}),
        # cross-source check of the procuring entity's fiscal code
        ("buyer_idno", [("buyer_idno", 1)], {}),
        ("period_type", [("period", 1), ("procurement_type", 1)], {}),
    ],
    RAW_BLACKLIST: [
        ("nr_unique", [("nr", 1)], {"unique": True}),
        ("name_key", [("name_key", 1)], {}),
    ],
    NORM_TENDERS: [
        ("ocid_unique", [("ocid", 1)], {"unique": True}),
        # used by the per-procurer and per-year aggregation pipelines
        ("buyer_published", [("buyer_id", 1), ("tender_start", 1)], {}),
    ],
    NORM_PARTIES: [
        ("identifier_lookup", [("identifier", 1)], {}),
        ("role_identifier", [("role", 1), ("identifier", 1)], {}),
    ],
    FEATURES_TENDERS: [
        ("ocid_unique", [("ocid", 1)], {"unique": True}),
    ],
    ANOMALY_SCORES: [
        # One document per (ocid, run) holding every model's score, so the
        # dashboard's "latest score for these tenders" lookup is (ocid, run_id)
        # and the model comparison is ordered by run.
        ("ocid_run", [("ocid", 1), ("run_id", 1)], {}),
        # used to pull the most anomalous procurements of one run for review
        ("run_score_desc", [("run_id", 1), ("max_score", -1)], {}),
    ],
}
