"""When does each production feature become observable? (scoring-time audit)

Added 2026-10-20 (branch ``feature/risk-specific-detection``). The module is
the machine-readable half of ``docs/TEMPORAL_LEAKAGE_AUDIT.md`` and answers,
per feature:

* which procurement event must happen before the feature's **inputs** exist
  (the ``stage`` in :data:`STAGES`);
* whether the value requires events **after tender publication**
  (``future_event_info``);
* whether the feature **as implemented** is point-in-time safe - i.e. its
  computation does not peek at corpus events after the evaluated row
  (``point_in_time_safe``). Corpus-reference features (CPV medians, behavioural
  shares computed over the full window) fail this axis even though their row
  inputs are local.

The distinction matters because production v0 scores the *finished* historical
corpus (as-of-now, ``post_award``), while a genuine early-warning system would
score at publication or bid close: the same 22 columns have different validity
at different moments.

Nothing here changes production v0 - no weights, bands or artefacts. The
stage-aware column sets are an API for future, explicitly approved
experiments; leakage *tests* in ``tests/test_temporal_leakage.py`` pin the
invariants.
"""

from __future__ import annotations

from .features import FEATURE_COLUMNS

#: Scoring moments, ordered from earliest to latest.
STAGES: tuple[str, ...] = (
    "publication",
    "bid_submission",
    "award_decision",
    "post_award",
)

STAGE_ORDER: dict[str, int] = {name: i for i, name in enumerate(STAGES)}

#: The procurement event each stage corresponds to.
STAGE_EVENTS: dict[str, str] = {
    "publication": (
        "tender notice is published (dates, procedure type, estimate are known)"
    ),
    "bid_submission": "bid submission closes and bids become visible",
    "award_decision": "the award decision is published (winner, values, lots)",
    "post_award": (
        "procedure reached its terminal state (cancellation, amendments, "
        "no-award outcomes); for this project: retrospective as-of-now scoring "
        "of the finished corpus - what production v0 does"
    ),
}

#: The ten features MTA-0013 classified as post-decision suspects for the ANSC
#: complaint label (``results/methodology/ansc_external_check.json`` ->
#: ``leakage.suspect_features``). Reference data, not a cycle input: the same
#: check found ``determined_by_leakage: false`` (refit without them:
#: AUC 0.4646 [0.417; 0.561]).
LEAK_SUSPECT_FEATURES: tuple[str, ...] = (
    "multi_award_tender",
    "amended",
    "n_amendments",
    "cancelled",
    "no_award_after_tender",
    "log_award_value",
    "log_award_total",
    "estimate_to_award_ratio",
    "value_vs_cpv_median",
    "value_zscore_cpv",
)

#: Fields that must never appear as model inputs. Labels (AAP sanctions, ANSC
#: complaints, planted synthetic ground truth) are evaluation-only.
LABEL_ONLY_FIELDS: tuple[str, ...] = (
    "aap_label",
    "ansc_label",
    "complaints",
    "sanction",
    "planted_pattern",
    "is_planted_anomaly",
)

#: Computation basis shared by several entries (kept next to the data it
#: describes so the matrix cannot drift from ``src/mtender/features.py``).
_CORPUS_REFERENCE_NOTE = (
    "reference statistics are computed over the whole corpus window "
    "(including events after the evaluated row) - valid for as-of-now "
    "scoring, not for point-in-time historical scoring"
)
_BEHAVIOURAL_NOTE = (
    "pair/buyer/supplier counts are taken over the full corpus window: the "
    "row's value can include relationships formed after this award - a "
    "prior-only recompute is required for point-in-time scoring"
)


def _f(
    stage: str,
    inputs: list[str],
    calculation: str,
    earliest: str,
    *,
    point_in_time_safe: bool = True,
    notes: str = "",
) -> dict:
    return {
        "stage": stage,
        "inputs": inputs,
        "calculation": calculation,
        "earliest_availability": earliest,
        "future_event_info": stage != "publication",
        "point_in_time_safe": point_in_time_safe,
        "notes": notes,
    }


#: Availability matrix for the 22 production features. Inputs and formulas
#: mirror ``src/mtender/features.py::engineer_features`` /
#: ``add_behavioural_features`` (see tests/test_temporal_leakage.py for the
#: consistency check against FEATURE_COLUMNS).
FEATURE_AVAILABILITY: dict[str, dict] = {
    # -- financial ----------------------------------------------------------
    "log_award_value": _f(
        "award_decision",
        ["award_value"],
        "log1p(award_value), clipped at 0",
        "award decision published",
        notes="row-local; feature is undefined (NaN->0 fill) before an award exists",
    ),
    "value_vs_cpv_median": _f(
        "award_decision",
        ["award_value", "cpv_primary", "all award values in corpus"],
        "award / median(award | CPV), clip [0, 20], missing -> 1.0",
        "award decision published",
        point_in_time_safe=False,
        notes=_CORPUS_REFERENCE_NOTE,
    ),
    "value_zscore_cpv": _f(
        "award_decision",
        ["award_value", "cpv_primary", "award value distribution per CPV"],
        "(award - median) / std per CPV, clip [-10, 10], missing -> 0.0",
        "award decision published",
        point_in_time_safe=False,
        notes=_CORPUS_REFERENCE_NOTE,
    ),
    "estimate_to_award_ratio": _f(
        "award_decision",
        ["estimated_value", "award_total"],
        "estimated_value / award_total, clip [0, 20], missing -> 1.0",
        "award decision published (estimate itself is known at publication)",
        notes="numerator is available at publication; the ratio needs the award",
    ),
    "log_award_total": _f(
        "award_decision",
        ["award_total", "award_value"],
        "log1p(sum over all lots; award_value as fallback)",
        "award decision published",
        notes="the only figure comparable with estimated_value",
    ),
    "multi_award_tender": _f(
        "award_decision",
        ["n_awards_with_value"],
        "int(n_awards_with_value > 1)",
        "award decision published",
        notes="lot structure is visible only once awards exist",
    ),
    # -- competition --------------------------------------------------------
    "n_bidders_log": _f(
        "bid_submission",
        ["n_bidders (from tender.bids.details)"],
        "log1p(n_bidders)",
        "bid submission closes (bids published)",
        notes="bids are per-lot entries; n_bidders counts distinct tenderers",
    ),
    "single_bidder": _f(
        "bid_submission",
        ["n_bidders"],
        "int(n_bidders == 1)",
        "bid submission closes",
        notes="a single bidder is a review indicator, not wrongdoing",
    ),
    "no_bid_data": _f(
        "bid_submission",
        ["n_bidders"],
        "int(n_bidders == 0)",
        "bid submission closes",
        notes="0 marks unpublished bid data, not proven absence of bids",
    ),
    "multi_supplier_award": _f(
        "award_decision",
        ["n_suppliers (award parties)"],
        "int(n_suppliers > 1)",
        "award decision published",
        notes="supplier identity comes with the award",
    ),
    # -- procedural ---------------------------------------------------------
    "bid_window_days": _f(
        "publication",
        ["tender_start", "tender_end"],
        "days between start and end, clip [0, 3650], missing -> 30",
        "tender notice published",
        notes="missing -> default 30 days is a documented fill, not a measurement",
    ),
    "short_deadline": _f(
        "publication",
        ["tender_start", "tender_end"],
        "int(0 <= bid_window_days < 7)",
        "tender notice published",
    ),
    "long_deadline": _f(
        "publication",
        ["tender_start", "tender_end"],
        "int(bid_window_days > 90)",
        "tender notice published",
    ),
    "n_amendments": _f(
        "post_award",
        ["n_amendments"],
        "count of published amendments",
        "grows from the first amendment until the procedure ends",
        notes=(
            "amendments occur any time after publication and can continue past "
            "the award; OCDS amendment lists may also touch award/contract "
            "entries, so the final count exists only at terminal state"
        ),
    ),
    "amended": _f(
        "post_award",
        ["n_amendments"],
        "int(n_amendments > 0)",
        "same as n_amendments (value can flip after publication)",
        notes="flips from 0 to 1 on the first amendment - not stable at publication",
    ),
    "accelerated_like": _f(
        "publication",
        ["procurement_method_details"],
        "regex: accelerated|urgent|exception in the procedure type",
        "tender notice published",
        notes="a name-based proxy for procedure urgency, not a legal classification",
    ),
    "cancelled": _f(
        "post_award",
        ["status"],
        "int(status in {cancelled, unsuccessful})",
        "terminal status only",
        notes="mid-flight status is not the final outcome",
    ),
    "no_award_after_tender": _f(
        "post_award",
        ["status", "award_value"],
        "int(status == 'complete' and award_value missing)",
        "terminal status only",
        notes="requires the final status; meaningless while the tender runs",
    ),
    # -- behavioural --------------------------------------------------------
    "buyer_supplier_repeat_share": _f(
        "award_decision",
        ["buyer_id", "winner_id", "all awards in corpus"],
        "awards of this (buyer, winner) pair / awards of this buyer",
        "award decision published (pair and buyer counts)",
        point_in_time_safe=False,
        notes=_BEHAVIOURAL_NOTE,
    ),
    "winner_share_of_buyer_awards": _f(
        "award_decision",
        ["buyer_id", "winner_id", "all awards in corpus"],
        "same pair/buyer share (mirrors buyer_supplier_repeat_share)",
        "award decision published",
        point_in_time_safe=False,
        notes=_BEHAVIOURAL_NOTE,
    ),
    "supplier_win_concentration": _f(
        "award_decision",
        ["winner_id", "all awards in corpus"],
        "supplier's award count / all awards in corpus, clip [0, 1]",
        "award decision published",
        point_in_time_safe=False,
        notes=_BEHAVIOURAL_NOTE + "; denominator is corpus-wide",
    ),
    "supplier_award_count_log": _f(
        "award_decision",
        ["winner_id", "all awards in corpus"],
        "log1p(supplier award count over corpus window)",
        "award decision published",
        point_in_time_safe=False,
        notes=_BEHAVIOURAL_NOTE,
    ),
}


def availability(feature: str) -> dict:
    """Availability record for one feature; raises KeyError with a hint."""
    try:
        return FEATURE_AVAILABILITY[feature]
    except KeyError as exc:  # pragma: no cover - defensive
        raise KeyError(
            f"{feature!r} is not in the production feature set "
            f"(see src/mtender/features.py FEATURE_COLUMNS)"
        ) from exc


def stage_columns(stage: str, *, strict: bool = False) -> list[str]:
    """Columns whose **inputs** exist by ``stage`` (ordered as FEATURE_COLUMNS).

    ``strict=True`` additionally drops every ``point_in_time_safe=False``
    feature - the set that is valid for *point-in-time* scoring at that stage.
    Exception: at ``post_award`` strict equals the plain set, because that is
    retrospective as-of-now scoring, where corpus-wide reference statistics are
    observable by definition (this is what production v0 does).

    Raises ValueError for unknown stages so typos cannot silently return [].
    """
    if stage not in STAGE_ORDER:
        raise ValueError(
            f"unknown stage {stage!r}; expected one of: {', '.join(STAGES)}"
        )
    out = []
    for feature in FEATURE_COLUMNS:
        meta = FEATURE_AVAILABILITY[feature]
        if STAGE_ORDER[meta["stage"]] > STAGE_ORDER[stage]:
            continue
        if strict and stage != "post_award" and not meta["point_in_time_safe"]:
            continue
        out.append(feature)
    return out


def strict_stage_columns(stage: str) -> list[str]:
    """``stage_columns(stage, strict=True)`` - see there."""
    return stage_columns(stage, strict=True)


def feature_matrix() -> dict:
    """JSON-serialisable matrix for scripts/33 and the audit report."""
    stages = {}
    for stage in STAGES:
        columns = stage_columns(stage)
        strict = stage_columns(stage, strict=True)
        stages[stage] = {
            "event": STAGE_EVENTS[stage],
            "n_features": len(columns),
            "features": columns,
            "n_features_point_in_time": len(strict),
            "features_point_in_time": strict,
        }
    unsafe = [
        f for f in FEATURE_COLUMNS if not FEATURE_AVAILABILITY[f]["point_in_time_safe"]
    ]
    return {
        "stages": stages,
        "availability": FEATURE_AVAILABILITY,
        "leak_suspect_features": list(LEAK_SUSPECT_FEATURES),
        "label_only_fields": list(LABEL_ONLY_FIELDS),
        "not_point_in_time_safe": unsafe,
        "production_stage": "post_award",
        "production_note": (
            "v0 scores the finished corpus retrospectively (as-of-now); stage "
            "sets are diagnostics for future, explicitly approved experiments"
        ),
        "source": "src/mtender/features.py (engineer_features / add_behavioural_features)",
        "disclaimer": (
            "Feature timing validity, not a corruption finding: an anomaly "
            "score is a potential risk indicator requiring independent review."
        ),
    }
