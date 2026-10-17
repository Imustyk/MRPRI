"""Procedure-level external labels derived from the AAP interdiction list.

The AAP "Lista de interdicție" is the only official integrity list published
for Moldovan public procurement. It is a table of **company names** - no IDNO,
no tender id - so the join to MTender can only be made on a normalised name
(``src/mtender/names.py``), and only full equality after folding is ever called
a match. Ambiguous (substring) candidates are carried through the table but are
never counted as positives.

The label produced here means exactly one thing:

    the winning supplier of this procedure appears on the official AAP
    interdiction list as of the collected snapshot date.

It is **not** a label of "this procedure is corrupt": the AAP ground can be
non-execution of contract clauses rather than bid manipulation, the decision
usually postdates the procedure, and a supplier not on the list is not thereby
cleared. Every consumer of these labels must state that limitation next to the
number it prints.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from .config import DATA_FEATURES, DATA_RAW, TABLES
from .names import match_level, normalise_name

BLACKLIST_JSON = DATA_RAW / "blacklist" / "aap_lista_interdictie_2026-09-25.json"
FEATURES_CSV = DATA_FEATURES / "features.csv"

#: Columns the label table needs from the feature snapshot.
LABEL_COLUMNS = [
    "ocid",
    "winner_name",
    "winner_identifier",
    "buyer_name",
    "published_date",
    "tender_start",
    "award_date",
    "award_value",
    "award_total",
    "cpv_primary",
]


def load_blacklist(path: Path | str = BLACKLIST_JSON) -> list[dict[str, Any]]:
    """Entries of the AAP snapshot, with the decision date parsed when present."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = list(payload.get("entries") or [])
    for entry in entries:
        entry["decision_date"] = parse_decision_date(entry.get("decision"))
    return entries


def parse_decision_date(value: Any) -> str | None:
    """``"13/23 din 07.12.2023"`` -> ``"2023-12-07"``; None when unparsable."""
    if not isinstance(value, str):
        return None
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", value)
    if not m:
        return None
    day, month, year = m.groups()
    return f"{year}-{month}-{day}"


def load_scored_corpus(
    features_csv: Path | str = FEATURES_CSV,
    scores_csv: Path | str | None = None,
) -> pd.DataFrame:
    """Features + production detector scores + AAP labels, aligned **by ocid**.

    Every analysis in the methodology cycle compares a ranking or a flag vector
    against the AAP label, and ``results/tables/tender_anomaly_scores.csv`` is
    sorted by ``n_models_flagging`` while ``features.csv`` is sorted by ``ocid``.
    Joining them positionally (two arrays, same length, different order) silently
    produces plausible-looking but meaningless metrics - the bug this function
    exists to prevent. The merge here is the only sanctioned way to get a
    aligned corpus, and tests/test_external_labels.py checks the alignment.
    """
    labels, _ = build_label_table(features_csv)
    if scores_csv is None:
        scores_csv = TABLES / "tender_anomaly_scores.csv"
    scores = pd.read_csv(scores_csv, low_memory=False)
    keep = [c for c in (
        "ocid", "n_models_flagging", "consensus", "max_score",
        "score_statistical_mad_zscore", "score_isolation_forest",
        "score_local_outlier_factor", "score_one_class_svm",
        "flag_statistical_mad_zscore", "flag_isolation_forest",
        "flag_local_outlier_factor", "flag_one_class_svm",
    ) if c in scores.columns]
    df = scores[keep].merge(
        labels[[c for c in labels.columns if c != "winner_key"]],
        on="ocid", how="left", validate="one_to_one",
    )
    df["is_aap_positive"] = df["is_aap_positive"].fillna(0).astype(int)
    if df["n_models_flagging"].isna().any():
        raise ValueError("scored rows lost during the ocid join - check the score export")
    return df


def _nrs_for(key: Any, key_to_nrs: dict[str, list[int]]) -> str | None:
    """``"3;7"`` for a matched supplier, None otherwise.

    The empty-list case must return None and never ``""``: an empty string is
    not missing, so ``.notna()`` would label every named winner positive - a bug
    this function exists to prevent (caught by tests/test_external_labels.py).
    """
    if not key:
        return None
    nrs = key_to_nrs.get(key)
    if not nrs:
        return None
    return ";".join(str(n) for n in sorted(set(nrs)))


def build_label_table(
    features_csv: Path | str = FEATURES_CSV,
    blacklist_json: Path | str = BLACKLIST_JSON,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """One row per procedure with its AAP label and matching provenance.

    Returns ``(table, summary)`` where ``table`` has columns
    ``ocid, winner_name, winner_key, match_level, blacklist_nrs, is_aap_positive``
    plus the identity columns needed to report per-entry rankings, and
    ``summary`` counts matches / ambiguous candidates the same way
    ``scripts/09_external_validation.py`` does.
    """
    entries = load_blacklist(blacklist_json)
    usecols = [c for c in LABEL_COLUMNS if c in pd.read_csv(features_csv, nrows=0).columns]
    df = pd.read_csv(features_csv, usecols=usecols, low_memory=False)

    # index observed suppliers by folded name, exactly as script 09 does
    df["winner_key"] = df["winner_name"].map(normalise_name)
    observed_keys = set(k for k in df["winner_key"].dropna().unique())

    exact_keys: dict[str, list[int]] = {}
    ambiguous_keys: dict[str, list[int]] = {}
    per_entry: list[dict[str, Any]] = []

    for entry in entries:
        bl_key = normalise_name(entry.get("name"))
        level, hit_key = "none", None
        if bl_key:
            if bl_key in observed_keys:
                level, hit_key = "exact_normalised", bl_key
            else:
                for key in observed_keys:
                    if match_level(bl_key, key) == "ambiguous":
                        level, hit_key = "ambiguous", key
                        break
        record = {
            "blacklist_nr": entry.get("nr"),
            "blacklist_name": entry.get("name"),
            "decision": entry.get("decision"),
            "decision_date": entry.get("decision_date"),
            "ground": entry.get("ground"),
            "until": entry.get("until"),
            "suspended": bool(entry.get("suspended")),
            "match_level": level,
            "matched_key": hit_key,
            "n_procedures": 0,
        }
        if level == "exact_normalised" and hit_key:
            rows = df.index[df["winner_key"] == hit_key].tolist()
            exact_keys.setdefault(hit_key, []).extend(rows)
            record["n_procedures"] = len(rows)
        elif level == "ambiguous" and hit_key:
            record["n_procedures"] = int((df["winner_key"] == hit_key).sum())
        per_entry.append(record)

    # one procedure may match two entries (same operator listed twice)
    key_to_nrs: dict[str, list[int]] = {}
    for rec in per_entry:
        if rec["match_level"] == "exact_normalised" and rec["matched_key"]:
            key_to_nrs.setdefault(rec["matched_key"], []).append(int(rec["blacklist_nr"]))

    df["blacklist_nrs"] = df["winner_key"].map(lambda k: _nrs_for(k, key_to_nrs))
    df["match_level"] = df["winner_key"].map(
        lambda k: "exact_normalised" if k in key_to_nrs else None
    )
    df["is_aap_positive"] = df["blacklist_nrs"].notna().astype(int)

    exact = [r for r in per_entry if r["match_level"] == "exact_normalised"]
    summary = {
        "blacklist_source": json.loads(Path(blacklist_json).read_text(encoding="utf-8")).get("source"),
        "blacklist_collected_at": json.loads(
            Path(blacklist_json).read_text(encoding="utf-8")
        ).get("collected_at"),
        "n_blacklist_entries": len(entries),
        "n_entries_with_no_name_evidence": sum(1 for r in per_entry if r["match_level"] == "none"),
        "n_exact_normalised_matches": len(exact),
        "n_ambiguous_candidates": sum(1 for r in per_entry if r["match_level"] == "ambiguous"),
        "n_distinct_matched_suppliers": len(key_to_nrs),
        "n_positive_procedures": int(df["is_aap_positive"].sum()),
        "n_procedures_total": int(len(df)),
        "label_unit": "procedure (ocid), inherited from the winning supplier's name match",
        "matching_method": (
            "normalised legal name (case, diacritics, punctuation, legal-form tokens removed); "
            "full equality only, substring hits stay 'ambiguous' and are never labelled positive"
        ),
        "limitation": (
            "Weak external label: supplier-level attribution (every procedure of a matched "
            "supplier is positive), name-based (no IDNO join is possible), and the AAP decision "
            "usually postdates the procedure it labels. Not a ground truth for 'this procedure "
            "is corrupt'."
        ),
        "per_entry": per_entry,
    }
    return df, summary
