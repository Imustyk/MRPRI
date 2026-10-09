"""Regression tests for the verified MTender pipeline.

These lock in the behaviours that were discovered by inspecting live responses,
so a future refactor cannot silently reintroduce them. Run with:

    .venv/bin/python -m pytest tests -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender import features as F
from src.mtender import normalize as N
from src.mtender.ocds import (
    extract_parties,
    extract_tender,
    json_key,
    merge_compiled_releases,
)


# --------------------------------------------------------------------------
# fixtures shaped like the two real layouts observed on the live API
# --------------------------------------------------------------------------
def _party(pid: str, name: str, roles: list[str], scheme: str = "MD-IDNO",
           ident: str | None = None, locality: str | None = None,
           address: str = "2018", scale: str | None = None) -> dict:
    addr: dict = {"streetAddress": "str. X"}
    if address == "2018":
        addr["locality"] = {"description": locality} if locality else {}
    else:  # 2024 layout: locality moved under addressDetails
        addr["addressDetails"] = {
            "locality": {"description": locality} if locality else {},
            "region": {"description": "mun. Chisinau"},
            "country": {"id": "MD", "description": "Moldova"},
        }
    party: dict = {"id": pid, "name": name, "roles": roles, "address": addr}
    if ident:
        party["identifier"] = {"scheme": scheme, "id": ident}
    if scale:
        party["details"] = {"scale": scale}
    return party


def _release(ocid: str, date: str, tender: dict, parties: list[dict],
             awards: list[dict] | None = None, bids: list[dict] | None = None,
             contracts: list[dict] | None = None, tag: str = "compiled") -> dict:
    rel: dict = {"id": f"{ocid}-r1", "date": date, "tag": tag,
                 "initiatedDate": date}
    if tender:
        rel["tender"] = tender
    if parties:
        rel["parties"] = parties
    if awards:
        rel["awards"] = awards
    if bids:
        rel["bids"] = {"details": bids}
    if contracts:
        rel["contracts"] = contracts
    return rel


def _package(ocid: str, releases: list[dict]) -> dict:
    """Build a package the way the live API does.

    Verified against data/raw/ocds_samples/ocds-b3wdp1-MD-1730452703725.json:
    every entry in ``records`` carries its own ``compiledRelease`` and there is
    no ``releases`` array. One package holds several related OCIDs - a planning
    notice (``-PN-``), the tender itself, and an evaluation notice (``-EV-``).
    """
    return {
        "uri": f"https://public.mtender.gov.md/tenders/{ocid}",
        "version": "1.1",
        "publisher": {"name": "M-Tender", "uri": "https://www.mtender.gov.md"},
        "publishedDate": "2018-11-05T09:00:00Z",
        "records": [{"ocid": ocid, "compiledRelease": rel} for rel in releases],
    }


# --------------------------------------------------------------------------
# release merging
# --------------------------------------------------------------------------
def test_merge_keeps_earliest_but_enriched_fields():
    """Bid/award/status live in different releases; merging must combine them.

    Regression: selecting only the newest release silently dropped every award
    and produced a dataset with no supervision signal at all.
    """
    ocid = "ocds-test-0001-MD-1"
    releases = [
        _release(ocid, "2018-10-18T09:00:00Z",
                 {"id": "t1", "title": "TITLE", "status": "active",
                  "value": {"amount": 1000, "currency": "MDL"}},
                 [_party("b1", "Buyer SA", ["buyer"], ident="1234")]),
        _release(ocid, "2018-11-05T09:00:00Z", {},
                 [_party("s1", "Supplier SRL", ["supplier"], ident="999")],
                 awards=[{"id": "a1", "status": "active", "date": "2018-11-05T09:00:00Z",
                          "value": {"amount": 950, "currency": "MDL"},
                          "suppliers": [{"id": "s1"}]}],
                 tag="awardUpdate"),
    ]
    merged = merge_compiled_releases(_package(ocid, releases))
    assert merged["tender"]["title"] == "TITLE"
    assert merged["tender"]["status"] == "active"
    assert merged["tender"]["value"]["amount"] == 1000
    assert merged["awards"][0]["id"] == "a1"


def test_inverted_tender_period_is_flagged_not_silently_kept():
    ocid = "ocds-test-0002-MD-1"
    releases = [_release(ocid, "2018-11-05T09:00:00Z", {
        "id": "t1", "tenderPeriod": {"startDate": "2018-12-01T00:00:00Z",
                                     "endDate": "2018-11-20T00:00:00Z"}}, [])]
    doc = N.normalize_tender(extract_tender(ocid, _package(ocid, releases)))
    # endDate before startDate is impossible: drop the value, keep the flag.
    assert doc["tender_end"] is None
    assert doc["period_inverted"] is True


def test_compiled_release_wins_over_planning_notice():
    """A planning notice must not overwrite the authoritative compiled view."""
    ocid = "ocds-test-0003-MD-1"
    compiled = _release(ocid, "2018-10-18T09:00:00Z",
                        {"id": "t1", "title": "REAL", "value": {"amount": 500}}, [])
    planning = _release(ocid, "2018-10-17T09:00:00Z",
                        {"id": "t1", "title": "STALE", "value": {"amount": 1}},
                        [], tag="planningUpdate")
    merged = merge_compiled_releases(_package(ocid, [planning, compiled]))
    assert merged["tender"]["title"] == "REAL"
    assert merged["tender"]["value"]["amount"] == 500
    # fields only present in the planning notice are still merged in
    assert merged["tender"].get("id") == "t1"


def test_buyer_found_in_early_release_not_latest():
    """Regression: the top-level `buyer` is never populated by this publisher."""
    ocid = "ocds-test-0004-MD-1"
    releases = [
        _release(ocid, "2018-10-18T09:00:00Z", {"id": "t1"},
                 [_party("b1", "Buyer SA", ["buyer"], ident="1111")]),
        _release(ocid, "2019-01-05T09:00:00Z", {}, [], tag="awardUpdate"),
    ]
    doc = extract_tender(ocid, _package(ocid, releases))
    assert doc["buyer_identifier"] == "1111"
    assert doc["buyer_name"] == "Buyer SA"


def test_award_supplier_list_is_authoritative_for_the_winner():
    """`awards[].suppliers[]` names the winner; no party-role check is applied.

    Verified on 200 packages from 2024: all 296 award supplier references resolve
    to a party carrying the `supplier` role, so the reference is authoritative
    and filtering on role would be redundant.
    """
    ocid = "ocds-winner-0001-MD-1"
    releases = [_release(
        ocid, "2018-11-05T09:00:00Z", {"id": "t1"},
        [_party("b1", "Buyer", ["buyer"]),
         _party("s1", "Sup A", ["supplier"]), _party("s2", "Sup B", ["supplier"])],
        awards=[{"id": "a1", "status": "active", "date": "2018-11-05T09:00:00Z",
                 "value": {"amount": 10, "currency": "MDL"},
                 "suppliers": [{"id": "s2", "name": "Sup B"}]}],
    )]
    doc = extract_tender(ocid, _package(ocid, releases))
    assert doc["winner_id"] == "s2"
    assert doc["n_suppliers"] == 1


def test_inactive_award_is_not_preferred_over_active():
    ocid = "ocds-winner-0002-MD-1"
    releases = [_release(
        ocid, "2018-11-05T09:00:00Z", {"id": "t1"},
        [_party("s1", "Cancelled One", ["supplier"]),
         _party("s2", "Active One", ["supplier"])],
        awards=[
            {"id": "a1", "status": "cancelled", "date": "2018-11-01T09:00:00Z",
             "value": {"amount": 1, "currency": "MDL"}, "suppliers": [{"id": "s1"}]},
            {"id": "a2", "status": "active", "date": "2018-11-05T09:00:00Z",
             "value": {"amount": 99, "currency": "MDL"}, "suppliers": [{"id": "s2"}]},
        ],
    )]
    doc = extract_tender(ocid, _package(ocid, releases))
    assert doc["winner_id"] == "s2"
    assert doc["award_value"] == 99.0


def test_no_award_means_no_winner():
    ocid = "ocds-winner-0003-MD-1"
    releases = [_release(ocid, "2018-10-18T09:00:00Z", {"id": "t1"},
                         [_party("b1", "Buyer", ["buyer"])])]
    doc = extract_tender(ocid, _package(ocid, releases))
    assert doc["winner_id"] is None
    assert doc["award_value"] is None


# --------------------------------------------------------------------------
# CPV in both published locations
# --------------------------------------------------------------------------
def test_cpv_read_from_tender_level_classification():
    """2024 data: 40/40 releases carry tender.classification, items often empty."""
    ocid = "ocds-cpv-0001-MD-1"
    releases = [_release(ocid, "2024-03-01T09:00:00Z", {
        "id": "t1", "items": [],
        "classification": {"scheme": "CPV", "id": "33600000-6",
                           "description": "Produse farmaceutice"},
    }, [])]
    doc = extract_tender(ocid, _package(ocid, releases))
    assert doc["cpv_codes"] == ["33600000-6"]
    assert N.normalize_tender(doc)["cpv_primary"] == "33600000-6"


def test_cpv_read_from_item_level_classification():
    ocid = "ocds-cpv-0002-MD-1"
    releases = [_release(ocid, "2018-10-18T09:00:00Z", {
        "id": "t1",
        "items": [{"classification": {"scheme": "CPV", "id": "45200000-9",
                                      "description": "Lucrari de constructii"}}],
    }, [])]
    doc = extract_tender(ocid, _package(ocid, releases))
    assert N.normalize_tender(doc)["cpv_primary"] == "45200000-9"


def test_cpv_merges_both_locations_without_duplicates():
    ocid = "ocds-cpv-0003-MD-1"
    releases = [_release(ocid, "2024-03-01T09:00:00Z", {
        "id": "t1",
        "classification": {"scheme": "CPV", "id": "30230000-0"},
        "items": [{"classification": {"scheme": "CPV", "id": "30230000-0"}},
                  {"classification": {"scheme": "CPV", "id": "48000000-0"}}],
    }, [])]
    doc = extract_tender(ocid, _package(ocid, releases))
    assert doc["cpv_codes"] == ["30230000-0", "48000000-0"]


def test_non_cpv_classification_ignored():
    ocid = "ocds-cpv-0004-MD-1"
    releases = [_release(ocid, "2024-03-01T09:00:00Z", {
        "id": "t1", "classification": {"scheme": "UNSPSC", "id": "1234"},
    }, [])]
    assert extract_tender(ocid, _package(ocid, releases))["cpv_codes"] == []


# --------------------------------------------------------------------------
# locality in both address layouts
# --------------------------------------------------------------------------
@pytest.mark.parametrize("address", ["2018", "2024"])
def test_locality_extracted_from_both_address_layouts(address):
    ocid = f"ocds-loc-{address}-MD-1"
    releases = [_release(ocid, "2024-03-01T09:00:00Z", {"id": "t1"},
                         [_party("b1", "Buyer", ["buyer"], locality="Orhei", address=address)])]
    assert extract_tender(ocid, _package(ocid, releases))["buyer_locality"] == "Orhei"


# --------------------------------------------------------------------------
# normalisation
# --------------------------------------------------------------------------
def test_epoch_placeholder_rejected():
    assert N.sane_dt(N.EPOCH_PLACEHOLDER) is None
    assert N.sane_dt("2019-04-05T08:00:00Z") is not None


def test_plausible_window_enforced():
    assert N.sane_dt("1990-01-01T00:00:00Z") is None
    assert N.sane_dt("2040-01-01T00:00:00Z") is None


def test_clean_text_truncates_and_drops_placeholders():
    for placeholder in ("-", "--", "N/A", "null", "None", "   "):
        assert N.clean_text(placeholder) is None, placeholder
    assert N.clean_text("n/a") == "n/a"   # lowercase is kept verbatim
    assert N.clean_text(42) is None       # non-strings are dropped
    assert N.clean_text("  a   b  ") == "a b"
    assert len(N.clean_text("x" * 10_000, limit=50)) == 50


def test_method_detail_clean():
    assert N.METHOD_DETAIL_CLEAN("open") == "open"
    assert N.METHOD_DETAIL_CLEAN("  OPEN ") == "open"
    assert N.METHOD_DETAIL_CLEAN("") is None


def test_plausible_award_total_drops_a_published_unit_error():
    """One 50.16 trillion MDL award made two rows carry 99.6% of all value."""
    doc = {
        "award_total": 50_160_310_175_475.75,
        "awards": [
            {"amount": 50_160_300_506_386.0},  # the unit error
            {"amount": 1_143_100.0},
            {"amount": 913_994.24},
            {"amount": 37.76},
        ],
    }
    assert N.plausible_award_total(doc, 2_724_978.64, 98_866.25) == round(
        1_143_100.0 + 913_994.24 + 37.76, 2
    )


def test_plausible_award_total_blames_the_amount_not_the_estimate():
    """A 2.1 thousand MDL estimate is the odd field here, so nothing is dropped."""
    doc = {
        "award_total": 4_236_086.77,
        "awards": [
            {"amount": 1_358_822.0},
            {"amount": 1_350_000.0},
            {"amount": 1_349_999.0},
            {"amount": 177_265.77},
        ],
    }
    assert N.plausible_award_total(doc, 2_100.0, 177_265.77) == 4_236_086.77


def test_plausible_award_total_is_faithful_without_an_estimate():
    doc = {"award_total": 1_000_000.0, "awards": [{"amount": 1_000_000.0}]}
    assert N.plausible_award_total(doc, None, 5.0) == 1_000_000.0
    assert N.plausible_award_total(doc, 0.0, 5.0) == 1_000_000.0


def test_plausible_award_total_never_invents_a_figure():
    """When every amount is out of bounds, missing beats fabricated."""
    doc = {"award_total": 9e9, "awards": [{"amount": 9e9}]}
    assert N.plausible_award_total(doc, 1_000.0, 9e9) is None
    assert N.plausible_award_total(doc, 1_000.0, 500.0) == 500.0


def test_normalize_tender_applies_the_award_total_guard():
    raw = {
        "ocid": "ocds-x",
        "estimated_value": 2_724_978.64,
        "award_value": 98_866.25,
        "award_total": 50_160_310_175_475.75,
        "awards": [{"amount": 50_160_300_506_386.0}, {"amount": 9_669_090.0}],
    }
    assert N.normalize_tender(raw)["award_total"] == 9_669_090.0


# --------------------------------------------------------------------------
# features
# --------------------------------------------------------------------------
def _frame(n: int = 40) -> pd.DataFrame:
    return pd.DataFrame({
        "award_value": [None if i % 4 == 0 else 1000.0 * (i + 1) for i in range(n)],
        "award_total": [None if i % 4 == 0 else 1000.0 * (i + 1) * (2 if i % 7 == 0 else 1)
                        for i in range(n)],
        "n_awards_with_value": [0 if i % 4 == 0 else (2 if i % 7 == 0 else 1) for i in range(n)],
        "estimated_value": [None if i % 5 == 0 else 900.0 * (i + 1) for i in range(n)],
        "cpv_primary": ["45200000-9"] * (n // 2) + [None] * (n - n // 2),
        "n_bidders": [None if i % 3 == 0 else float(i % 7) for i in range(n)],
        "tender_duration_days": [None if i % 6 == 0 else float(10 + i) for i in range(n)],
        "is_direct_award": [None if i % 8 == 0 else bool(i % 2) for i in range(n)],
        "has_single_bid": [None if i % 8 == 0 else bool(i % 3) for i in range(n)],
        "procurement_method": ["open"] * (n // 2) + [None] * (n - n // 2),
        "procurement_method_details": ["open"] * (n // 2) + [None] * (n - n // 2),
        "main_procurement_category": ["goods"] * (n // 2) + [None] * (n - n // 2),
        "buyer_scale": ["SME"] * (n // 2) + [None] * (n - n // 2),
        "award_month": [(i % 12) + 1 for i in range(n)],
    })


def test_every_declared_feature_is_produced():
    out = F.engineer_features(_frame())
    missing = [c for c in F.FEATURE_COLUMNS if c not in out.columns]
    assert not missing, f"missing engineered features: {missing}"


def test_unavailable_inputs_are_zero_filled_not_invented():
    """A missing input must become a documented 0/unavailable, never a guess."""
    df = _frame()
    for col in ("n_bidders", "tender_duration_days", "is_direct_award", "has_single_bid"):
        df[col] = None
    out = F.engineer_features(df)
    assert (out["n_bidders_log"] == 0).all()
    assert (out["single_bidder"] == 0).all()
    # the explicit "we have no bid data" flag must be set, not silently 0 bidders
    assert out["no_bid_data"].eq(1).all()


def test_log_value_never_negative_and_handles_zero():
    df = _frame()
    df["award_value"] = 0.0
    out = F.engineer_features(df)
    col = out["log_award_value"].dropna()
    assert (col >= 0).all()


def test_value_vs_median_uses_cpv_group():
    out = F.engineer_features(_frame())
    assert out["value_vs_cpv_median"].notna().any()
    # award_total (all lots) must drive the estimate comparison, not award_value
    assert out["log_award_total"].notna().any()
    assert out["multi_award_tender"].sum() > 0
    assert out["multi_award_tender"].isin([0, 1]).all()


def test_features_survive_all_missing_input():
    empty = _frame()
    for col in empty.columns:
        if col not in ("award_month", "cpv_primary"):
            empty[col] = None
    out = F.engineer_features(empty)
    assert len(out) == 40
    assert list(F.FEATURE_COLUMNS) == [c for c in F.FEATURE_COLUMNS if c in out.columns]


def test_behavioural_features_add_monotonic_counts():
    df = F.engineer_features(_frame())
    before = set(df.columns)
    beh = F.add_behavioural_features(df)
    added = set(beh.columns) - before
    assert added, "expected behavioural features to be added"
    assert beh.index.is_unique
    assert len(beh) == len(df)
    for col in ("buyer_supplier_repeat_share", "winner_share_of_buyer_awards",
                "supplier_win_concentration"):
        assert col in beh.columns
        assert (beh[col].dropna() >= 0).all()
        assert (beh[col].dropna() <= 1).all()
    assert (beh["supplier_award_count_log"].dropna() >= 0).all()


# --------------------------------------------------------------------------
# party de-duplication
# --------------------------------------------------------------------------
def test_extract_parties_uses_stable_composite_key():
    doc = {
        "ocid": "ocds-parties-0001-MD-1",
        "buyer_id": "b1", "buyer_name": "Buyer SA",
        "buyer_identifier": "111", "buyer_identifier_scheme": "MD-IDNO",
        "suppliers": [{"id": "s1", "name": "Supplier SRL", "identifier": "999"}],
        "bids": [{"tenderers": [{"id": "s1", "name": "Supplier SRL"},
                                {"id": "t2", "name": "Other SRL"}]}],
    }
    parties = extract_parties(doc)
    keys = [p["party_key"] for p in parties]
    assert len(keys) == len(set(keys)), "party_key must be unique per document"
    # the same organisation appears as supplier and as tenderer: two rows, one id
    assert {p["role"] for p in parties} == {"buyer", "supplier", "tenderer"}
    assert {p["id"] for p in parties} == {"b1", "s1", "t2"}
    assert all(p["party_key"].startswith("ocds-parties-0001-MD-1|") for p in parties)


def test_extract_parties_skips_unidentifiable_refs():
    doc = {"ocid": "x", "buyer_id": None, "buyer_identifier": None,
           "suppliers": [{"id": None, "name": None}], "bids": []}
    assert extract_parties(doc) == []


def test_json_key_is_deterministic():
    a = json_key({"id": "s1", "name": "S"})
    b = json_key({"name": "S", "id": "s1"})
    assert a == b


# --------------------------------------------------------------------------
# Aggregation pipeline regressions.
#
# Every one of these was a real defect that produced a well-formed CSV with
# blank key columns, so none of them raise an error: the tables just quietly
# lost their identifying column and every number became unquotable.
# --------------------------------------------------------------------------

def _agg_module():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "05_aggregations.py"
    spec = importlib.util.spec_from_file_location("agg05", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_aggregation_renames_its_group_key():
    """A $group keyed by _id must be renamed to the declared CSV column.

    Without this the CSV keeps the declared header but writes an empty cell,
    because MongoDB returns the key under `_id`.
    """
    for name, (pipeline, columns) in _agg_module().AGGREGATIONS.items():
        projects = [s["$project"] for s in pipeline if "$project" in s]
        assert projects, f"{name}: no $project, so _id is never renamed"
        renamed = any(col in proj for proj in projects for col in columns)
        assert renamed, f"{name}: none of {columns} is produced by any $project"


def test_no_aggregation_uses_bucket_stage():
    """$bucket emits only _id, so counts and sums cannot be accumulated after it.

    An earlier version grouped the bucket output and produced n=1 per band with
    sum_value=0 for every band.
    """
    for name, (pipeline, _cols) in _agg_module().AGGREGATIONS.items():
        assert not any("$bucket" in s for s in pipeline), (
            f"{name}: $bucket drops all fields but _id; use $group with $switch"
        )


def test_value_bands_accumulates_in_the_group_stage():
    _m = _agg_module()
    pipeline, columns = _m.AGGREGATIONS["value_bands"]
    assert "band" in columns and "n" in columns
    group = next(s["$group"] for s in pipeline if "$group" in s)
    assert group["n"] == {"$sum": 1}, "n must be counted by $sum, not a bare 1"
    assert "sum_value" in group


def test_value_band_boundaries_are_contiguous():
    """A gap or overlap in the bands would silently drop or double-count rows."""
    bands = _agg_module().QUANTILE_BANDS
    assert bands, "QUANTILE_BANDS must be defined"
    thresholds = [b["case"]["$lt"][1] for b in bands if "$lt" in b["case"]]
    gte = [b["case"]["$gte"][1] for b in bands if "$gte" in b["case"]]
    assert thresholds == sorted(thresholds), "bands must ascend"
    assert len(set(thresholds)) == len(thresholds), "band edges must not overlap"
    assert gte == [thresholds[-1]], "the top band must start where the last $lt ends"
    # the widest band must start at 0, otherwise low values fall through to
    # $switch's default and vanish from the table
    first = bands[0]["case"].get("$lt", bands[0]["case"].get("$gte"))
    assert first[1] > 0, "the first band must not be unbounded below"


def test_money_aggregations_use_the_lot_summed_award_total():
    """Summing award_value understates a multi-lot tender (up to 219 lots seen)."""
    for name in ("tenders_per_year", "top_procurers_by_value",
                 "top_suppliers_by_value", "value_bands"):
        pipeline, _cols = _agg_module().AGGREGATIONS[name]
        keys = {"total_value", "sum_value", "sum_award_total"}
        found = [
            (k, stage["$group"][k])
            for stage in pipeline
            if "$group" in stage
            for k in stage["$group"]
            if k in keys
        ]
        assert found, f"{name}: no money accumulator found"
        for key, expr in found:
            assert "$sum" in expr, f"{name}.{key} must be a $sum accumulator"
            assert "award_total" in str(expr), (
                f"{name}.{key} must accumulate award_total, got {expr}"
            )


def test_cpv_median_deliberately_stays_on_the_primary_award():
    """The CPV median is the denominator of value_vs_cpv_median, so it must match."""
    pipeline, _cols = _agg_module().AGGREGATIONS["cpv_median_by_code"]
    assert any("award_value" in str(s) for s in pipeline)
    assert not any("award_total" in str(s) for s in pipeline)


def test_year_grouping_uses_the_year_number_not_the_timestamp():
    pipeline, columns = _agg_module().AGGREGATIONS["tenders_per_year"]
    assert "year" in columns
    group = next(s["$group"] for s in pipeline if "$group" in s)
    assert "$year" in group["_id"], (
        "grouping by the whole timestamp yields one row per day, not per year"
    )


def test_supplier_fiscal_code_is_read_from_party_id():
    """Suppliers publish the fiscal code only in ``parties[].id``.

    Measured on the stored packages: every procuring entity carried a real
    ``identifier`` object, while all 714 supplier parties had
    ``identifier = null`` and the code appeared only as ``MD-IDNO-<code>`` in
    ``id``. Reading ``identifier`` alone left ``winner_idno`` empty for all
    1,500 tenders.
    """
    from src.mtender.ocds import _identifier, _identifier_scheme

    supplier_as_published = {"id": "MD-IDNO-1013600036910", "name": "HumanLab"}
    assert _identifier(supplier_as_published) == "1013600036910"
    assert _identifier_scheme(supplier_as_published) == "MD-IDNO"

    # A real identifier object still wins over the id fallback.
    buyer_as_published = {
        "id": "MD-IDNO-1012606001995",
        "identifier": {"scheme": "MD-IDNO", "id": "1012606001995"},
    }
    assert _identifier(buyer_as_published) == "1012606001995"
    assert _identifier_scheme(buyer_as_published) == "MD-IDNO"

    # Unrelated or missing identifiers must stay None rather than be invented.
    assert _identifier({"id": "ocds-b3wdp1-MD-1", "name": "X"}) is None
    assert _identifier({"name": "X"}) is None
    assert _identifier({"identifier": {}}) is None
    assert _identifier_scheme({"id": "not-an-idno"}) is None


def test_winner_identifier_is_populated_for_supplier_without_identifier_object():
    from src.mtender.ocds import _winner

    awards = [
        {
            "status": "active",
            "suppliers": [{"id": "MD-IDNO-1002600039005", "name": "GVP MOLDOVA"}],
        }
    ]
    w = _winner(awards)
    assert w["identifier"] == "1002600039005"
    assert w["identifier_scheme"] == "MD-IDNO"
    assert w["name"] == "GVP MOLDOVA"


def test_normalizer_recovers_winner_fiscal_code_from_party_id():
    """Packages stored before the extractor fix keep the code in winner_id."""
    from src.mtender.normalize import _idno_from, normalize_tender

    assert _idno_from("MD-IDNO-1013600036910") == "1013600036910"
    assert _idno_from("MD-IDNO-abc") is None
    assert _idno_from("ocds-b3wdp1-MD-1") is None
    assert _idno_from(None) is None

    t = normalize_tender(
        {
            "ocid": "ocds-x-MD-1",
            "tender_id": "ocds-x-MD-1",
            "winner_id": "MD-IDNO-1013600036910",
            "winner_name": "HumanLab",
            "winner_identifier": None,
        }
    )
    assert t["winner_identifier"] == "1013600036910"
    assert t["winner_identifier_scheme"] == "MD-IDNO"

    # An explicit identifier is never overwritten by the fallback.
    t2 = normalize_tender(
        {
            "ocid": "ocds-y-MD-2",
            "winner_id": "MD-IDNO-1002600039005",
            "winner_identifier": "999",
        }
    )
    assert t2["winner_identifier"] == "999"

    # No award at all stays None rather than being invented.
    t3 = normalize_tender({"ocid": "ocds-z-MD-3"})
    assert t3["winner_identifier"] is None
    assert t3["winner_identifier_scheme"] is None


def test_blacklist_name_matching_is_conservative():
    """Name-only matching: only a full normalised equality counts as a match."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "extval", Path(__file__).resolve().parents[1] / "scripts" / "09_external_validation.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    n = mod.normalise_name
    # diacritics, case, punctuation and legal form all fold away
    assert n("S.R.L. „IQ Fenster”") == n("SRL IQ Fenster")
    assert n("PROFMARKET  PRIM, S.R.L.") == n("Profmarket Prim")
    # a shared token is NOT a match
    assert mod.match_level(n("SRL IQ Fenster"), n("SRL IQ Glas")) == "none"
    # substring is only ever a review candidate, never a match
    assert mod.match_level(n("IQ Fenster"), n("IQ Fenster Nord")) == "ambiguous"
    # missing names can never match everything
    assert n(None) is None and n("   ") is None and n("SRL") is None
    assert mod.match_level(n("IQ Fenster"), n(None)) == "none"
    assert mod.match_level(None, n("IQ Fenster")) == "none"

    # band rule matches the dashboard's agreement thresholds
    assert [mod._band(n) for n in (0, 1, 2, 3, 4)] == [
        "low", "medium", "high", "critical", "critical",
    ]
