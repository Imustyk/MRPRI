"""Step 09 - compare the detected anomalies against the official AAP blacklist.

The AAP "Lista de interdicție" is the only official integrity list for Moldovan
procurement. This stage matches the suppliers in the scored snapshot against it
and reports, for every match, what the detectors said about that supplier.

**Matching method and its limits, stated up front (spec §13).**

The blacklist is published as an HTML table of *names*. It carries no IDNO, no
fiscal code and no tender identifier, so a join on a real identifier is
impossible. MTender, by contrast, *does* publish the supplier fiscal code
(``MD-IDNO-<code>``), which is why ``winner_identifier`` is now populated. The
consequence is stated in the output: a name-based join can produce both false
positives (two distinct companies sharing a name, or a renamed company) and
false negatives (abbreviations, diacritics, "SRL" vs "S.A."). Nothing here is
treated as proof of anything; the blacklist entry is a signal to check the
award by hand, and an absence of a match is not a clean bill of health.

Two match strengths are reported separately and never mixed:

``exact_normalised``
    the blacklisted name and the supplier name are identical after removing
    case, diacritics, punctuation and legal-form tokens (SRL, SA, ...).
``ambiguous``
    one normalised name contains the other. These are candidates for manual
    review only and are not counted as matches.

Output: results/tables/blacklist_matches.csv, results/mongo/external_validation.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.config import DATA_PROCESSED, DATA_RAW, MONGO_META, TABLES  # noqa: E402
from src.mtender.names import match_level, normalise_name  # noqa: E402,F401

BLACKLIST_JSON = DATA_RAW / "blacklist" / "aap_lista_interdictie_2026-09-25.json"
SNAPSHOT = DATA_PROCESSED / "tenders.json"

def _band(n_models: int) -> str:
    """Same agreement rule as the dashboard: 0 low, 1 medium, 2 high, 3+ critical."""
    if n_models >= 3:
        return "critical"
    if n_models == 2:
        return "high"
    if n_models == 1:
        return "medium"
    return "low"


def _latest_scores() -> dict[str, dict[str, Any]]:
    """ocid -> consensus percentile and band, from the newest scoring run.

    Mirrors the dashboard's rule: the maximum per-detector percentile rank,
    with the band taken from how many detectors agreed. Run ids sort
    chronologically because they are UTC timestamps.
    """
    try:
        from src.mtender.mongo_client import connect
        from src.mtender.mongo_schema import ANOMALY_SCORES
    except Exception:  # pragma: no cover - import guard only
        return {}
    try:
        _client, db = connect()
    except Exception:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for doc in db[ANOMALY_SCORES].find(
        {},
        {"ocid": 1, "run_id": 1, "n_models_flagging": 1, "max_score": 1},
    ):
        ocid = doc.get("ocid")
        run = str(doc.get("run_id") or "")
        prev = out.get(ocid)
        if prev is None or run > str(prev.get("run_id") or ""):
            # Same rule as the dashboard: the consensus percentile is the
            # highest per-detector percentile rank, expressed 0-100.
            doc["risk_score"] = (
                round(doc["max_score"] * 100, 2) if doc.get("max_score") is not None else None
            )
            out[ocid] = doc
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--blacklist", type=Path, default=BLACKLIST_JSON)
    ap.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    args = ap.parse_args()

    if not args.blacklist.exists():
        print(
            f"blacklist not found: {args.blacklist}\n"
            "Section 13 of the specification requires this comparison. Fetch the "
            "AAP Lista de interdicție before reporting Chapter 3.4.",
            file=sys.stderr,
        )
        return 1
    if not args.snapshot.exists():
        print(f"snapshot not found: {args.snapshot}", file=sys.stderr)
        return 1

    bl = json.loads(args.blacklist.read_text(encoding="utf-8"))
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    entries = bl.get("entries") or []

    # The modelling snapshot holds features only; the detector output lives in
    # the anomaly_scores collection, keyed by ocid and run. Joining here keeps
    # the reported percentile identical to the one the dashboard shows.
    scores = _latest_scores()
    if not scores:
        print(
            "warning: anomaly_scores is empty, so the reported percentiles will be null. "
            "Run scripts/06_detect_anomalies.py first.",
            file=sys.stderr,
        )

    # Index the scored suppliers. One supplier can win several procedures, so
    # every award is kept and later aggregated.
    observed: dict[str, list[dict]] = {}
    for row in snapshot:
        key = normalise_name(row.get("winner_name"))
        if key:
            observed.setdefault(key, []).append(row)

    rows: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    for entry in entries:
        bl_key = normalise_name(entry.get("name"))
        best = "none"
        matched: list[dict] = []
        if bl_key:
            for key, awards in observed.items():
                level = match_level(bl_key, key)
                if level == "exact_normalised" and best != "exact_normalised":
                    best, matched = level, awards
                elif level == "ambiguous" and best == "none":
                    best, matched = level, awards

        record = {
            "blacklist_nr": entry.get("nr"),
            "blacklist_name": entry.get("name"),
            "decision": entry.get("decision"),
            "ground": entry.get("ground"),
            "until": entry.get("until"),
            "match_level": best,
            "observed_name": None,
            "observed_idno": None,
            "n_awards": 0,
            "award_total_mdl": 0.0,
            "max_percentile": None,
            "risk_bands": "",
        }
        if matched:
            names = {a.get("winner_name") for a in matched if a.get("winner_name")}
            idnos = {a.get("winner_identifier") for a in matched if a.get("winner_identifier")}
            pct = [
                s.get("risk_score")
                for s in (scores.get(a.get("ocid")) for a in matched)
                if s and s.get("risk_score") is not None
            ]
            bands = {
                _band(int(s["n_models_flagging"]))
                for s in (scores.get(a.get("ocid")) for a in matched)
                if s and s.get("n_models_flagging") is not None
            }
            record.update(
                observed_name="; ".join(sorted(names)) or None,
                observed_idno="; ".join(sorted(idnos)) or None,
                n_awards=len(matched),
                award_total_mdl=round(sum(a.get("award_total_mdl") or 0.0 for a in matched), 2),
                max_percentile=round(max(pct), 1) if pct else None,
                risk_bands="; ".join(sorted(bands)),
            )
        rows.append(record)
        if best == "ambiguous":
            ambiguous.append(record)

    exact = [r for r in rows if r["match_level"] == "exact_normalised"]
    TABLES.mkdir(parents=True, exist_ok=True)
    out_csv = TABLES / "blacklist_matches.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    with_idno = sum(1 for r in rows if r["observed_idno"])
    summary = {
        "blacklist_source": bl.get("source"),
        "blacklist_publisher": bl.get("publisher"),
        "blacklist_collected_at": bl.get("collected_at"),
        "n_blacklist_entries": len(entries),
        "n_distinct_suppliers_in_snapshot": len(observed),
        "n_exact_normalised_matches": len(exact),
        "n_ambiguous_candidates": len(ambiguous),
        "n_entries_with_no_name_evidence": sum(1 for r in rows if r["match_level"] == "none"),
        "n_matches_with_supplier_idno": with_idno,
        "total_awards_to_matched_suppliers": sum(r["n_awards"] for r in exact),
        "matching_method": "normalised legal name (case, diacritics, punctuation, legal-form tokens removed)",
        "identifier_matching_possible": False,
        "limitation": (
            "The AAP blacklist publishes company names only: no IDNO, fiscal code or "
            "tender identifier. A join on a real identifier is therefore impossible, so "
            "this comparison is name-based and approximate. It can miss a supplier that "
            "is listed under a different abbreviation or a former name, and it can in "
            "principle match an unrelated company of the same name. A match is a prompt "
            "to inspect that award manually, not evidence of wrongdoing by the supplier, "
            "and a missing match does not clear a supplier."
        ),
        "matches": exact,
        "ambiguous_candidates": ambiguous,
        "note": (
            "Two blacklist entries refer to the same operator (SRL Vulturii Protectori, "
            "decisions 6/25 and 10/25) and some decisions were suspended by court, per the "
            "publisher's own note in the collected snapshot."
        ),
    }
    MONGO_META.mkdir(parents=True, exist_ok=True)
    (MONGO_META / "external_validation.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"blacklist entries          : {len(entries)}")
    print(f"distinct suppliers scored  : {len(observed)}")
    print(f"exact normalised matches   : {len(exact)}")
    for r in exact:
        print(
            f"   {r['blacklist_name']} -> {r['observed_name']} "
            f"({r['n_awards']} award(s), max percentile {r['max_percentile']})"
        )
    print(f"ambiguous candidates       : {len(ambiguous)}")
    print(f"matches carrying an IDNO   : {with_idno}")
    print(f"table  -> {out_csv}")
    print(f"report -> {MONGO_META / 'external_validation.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
