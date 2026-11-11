"""MTA-0016/MTA-0017 tests: the case registry — schema, ingest, matching,
temporal protection.

Covers the pieces the third external label trusts: the registry schema
(required columns, no-source rejection, enum validation, evidence D never in
the label), the MTA-0017 ingest (source/episode validation, quote <=25 words,
``link_basis`` derivation, upserts), the matching ladder (identifier links
``procedure_id_in_source``/``contract_number`` first, then IDNO -> exact name
-> fuzzy candidate that stays ``low`` and is never auto-promoted), the LABEL
RULE (``link_basis`` must be an identifier link - ``buyer_period_only`` and
empty ``link_basis`` NEVER enter the label), the TEMPORAL GUARD of
``scripts/39`` (only procedures published strictly before the case's
``first_publication_date`` are positive; post-date rows leave the population),
the two label versions (all A-C vs ``verified_by_human=true``), the power gate
and the pre-registered verdict rule.

Security regression: ``scripts/38/39/40/41`` must perform no network requests -
no network imports, standalone under ``python -I``.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REGISTRY_TEMPLATE = ROOT / "data" / "external" / "case_registry.csv"
SOURCES_TEMPLATE = ROOT / "data" / "external" / "case_sources.csv"
EPISODES_TEMPLATE = ROOT / "data" / "external" / "case_episodes_raw.csv"
UNMATCHED_TEMPLATE = ROOT / "data" / "external" / "case_unmatched.csv"
SCHEMA_DOC = ROOT / "docs" / "case_registry_schema.md"


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


S38 = _load_script("38_case_registry_match.py")
S39 = _load_script("39_case_registry_check.py")
S41 = _load_script("41_case_registry_ingest.py")


# ---------------------------------------------------------------------------
# synthetic fixtures
# ---------------------------------------------------------------------------

FEATURES = pd.DataFrame({
    "ocid": ["ocd-P1", "ocd-P2", "ocd-P3", "ocd-P4", "ocd-B1"],
    "buyer_identifier": ["2000000000001", "2000000000001", "2000000000002",
                         "2000000000003", "2000000000004"],
    "buyer_name": ["PRIMARIA X", "PRIMARIA X", "MINISTERUL Y", "CONSILIUL Z",
                   "AGENTIA W"],
    "winner_identifier": ["1000000000001", "1000000000001", "1000000000002",
                          "1000000000003", "1000000000004"],
    "winner_name": ["ALPHA SRL", "ALPHA SRL", "BETA INDUSTRIES S.R.L.",
                    "GAMMA", "DELTA SRL"],
    "published_date": ["2020-01-01T00:00:00Z", "2021-06-01T00:00:00Z",
                       "2019-03-01T00:00:00Z", "2022-05-01T00:00:00Z",
                       "2021-01-01T00:00:00Z"],
    # columns scripts/39 merges for the baselines and the group control
    "log_award_total": [15.0, 16.0, 14.0, 17.0, 15.5],
    "n_bidders_log": [1.0, 0.0, 2.0, 0.0, 1.0],
    "log_award_value": [15.0, 16.0, 14.0, 17.0, 15.5],
    "procurement_method_details": ["open", "open", "open", "direct",
                                   "open"],
})


def _registry_csv(tmp_path: Path, rows: list[dict]) -> Path:
    """Write a registry CSV; missing fields default to a valid baseline."""
    base = {c: "" for c in S38.REQUIRED_COLUMNS}
    base.update({
        "case_id": "C-1", "title_short": "Эпизод",
        "entity_type": "supplier", "entity_id_mtender": "1000000000001",
        "entity_name_as_in_source": "ALPHA SRL",
        "source_url_1": "https://example.org/act", "source_type_1": "court",
        "source_date_1": "2023-01-10", "evidence_level": "A",
        "risk_type": "collusion", "first_publication_date": "2023-01-15",
        "verified_by_human": "true",
    })
    frame = pd.DataFrame([{**base, **row} for row in rows])
    path = tmp_path / "registry.csv"
    frame.to_csv(path, index=False)
    return path


def _load(tmp_path: Path, rows: list[dict],
          corpus: pd.DataFrame | None = None):
    raw = pd.read_csv(_registry_csv(tmp_path, rows), dtype="string",
                      keep_default_na=False)
    registry, validation = S38.validate_registry(raw)
    if corpus is None:
        corpus = S38.load_corpus(_features_csv(tmp_path))
    else:
        path = tmp_path / "features_custom.csv"
        corpus.to_csv(path, index=False)
        corpus = S38.load_corpus(path)
    per_case, proc, summary = S38.match_cases(registry, corpus)
    return registry, validation, corpus, per_case, summary


def _features_csv(tmp_path: Path) -> Path:
    path = tmp_path / "features.csv"
    FEATURES.to_csv(path, index=False)
    return path


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------

def test_template_header_matches_schema_exactly():
    header = pd.read_csv(REGISTRY_TEMPLATE, nrows=0).columns.tolist()
    assert header == S38.REQUIRED_COLUMNS
    assert len(pd.read_csv(REGISTRY_TEMPLATE)) == 0  # template carries no cases


def test_schema_doc_lists_every_column():
    text = SCHEMA_DOC.read_text(encoding="utf-8")
    for col in S38.REQUIRED_COLUMNS:
        assert f"`{col}`" in text, f"docs/case_registry_schema.md omits {col}"
    for token in ("evidence_level", "first_publication_date", "name_fuzzy",
                  "не принимаются", "компетентным органом",
                  "case_sources.csv", "case_episodes_raw.csv",
                  "case_unmatched.csv", "buyer_period_only",
                  "procedure_id_in_source", "25 слов",
                  "verified_by_human = true"):
        assert token in text, f"docs/case_registry_schema.md omits {token!r}"


def test_normalize_idno_variants_and_garbage():
    assert S38.normalize_idno("MD-IDNO-1006601001182") == "1006601001182"
    assert S38.normalize_idno(" 1006601001182 ") == "1006601001182"
    assert S38.normalize_idno(1006601001182.0) == "1006601001182"
    assert S38.normalize_idno("не-идно") is None
    assert S38.normalize_idno("") is None
    assert S38.normalize_idno(None) is None


def test_row_without_source_is_rejected(tmp_path):
    _, validation, *_ = _load(tmp_path, [
        {"case_id": "C-ok"},
        {"case_id": "C-bad", "source_url_1": "", "source_date_1": ""},
    ])
    assert validation["n_rows"] == 2
    assert validation["n_valid"] == 1
    assert validation["n_rejected"] == 1
    assert validation["rejected"][0]["case_id"] == "C-bad"
    assert any("источника" in r for r in validation["rejected"][0]["reasons"])


def test_row_without_first_publication_is_rejected(tmp_path):
    _, validation, *_ = _load(tmp_path, [
        {"case_id": "C-nodate", "first_publication_date": ""}])
    assert validation["n_rejected"] == 1
    assert any("first_publication_date" in r
               for r in validation["rejected"][0]["reasons"])


def test_enum_violations_rejected(tmp_path):
    _, validation, *_ = _load(tmp_path, [
        {"case_id": "C-ev", "evidence_level": "Z"},
        {"case_id": "C-risk", "risk_type": "bribery"},
        {"case_id": "C-type", "entity_type": " intermediary "},
        {"case_id": "C-range", "period_from": "2022-01-01",
         "period_to": "2021-01-01"},
    ])
    assert validation["n_rejected"] == 4


def test_duplicate_case_id_rejected(tmp_path):
    _, validation, *_ = _load(tmp_path, [{"case_id": "C-1"},
                                         {"case_id": "C-1"}])
    assert validation["n_rejected"] == 1


# ---------------------------------------------------------------------------
# matching ladder
# ---------------------------------------------------------------------------

def test_idno_match_priority_but_no_label_without_link_basis(tmp_path):
    """MTA-0017: the entity ladder alone is NEVER label-grade."""
    _, _, corpus, per_case, summary = _load(tmp_path, [
        {"entity_id_mtender": "1000000000001", "entity_name_as_in_source": "ALPHA SRL"}])
    rec = per_case[0]
    assert rec["match_method"] == "idno_exact"
    assert rec["match_confidence"] == "high"
    assert sorted(rec["procedure_ids"]) == ["ocd-P1", "ocd-P2"]
    assert rec["label_grade"] is False        # empty link_basis -> no label
    assert summary["n_matched"] == 1
    assert summary["n_matched_label_grade"] == 0
    # and it builds NO label positives
    frame, info = S39.build_label_population(per_case, corpus)
    assert frame is None or info.get("n_positives", 0) == 0


def test_procedure_ref_link_is_label_grade(tmp_path):
    """link_basis=procedure_id_in_source + resolved ocid -> label-grade."""
    _, _, _, per_case, summary = _load(tmp_path, [
        {"link_basis": "procedure_id_in_source",
         "procedure_ref_in_source": "ocd-P2",
         "entity_id_mtender": "1000000000001"}])
    rec = per_case[0]
    assert rec["match_method"] == "ocid_exact"
    assert rec["match_confidence"] == "high"
    assert rec["procedure_ids"] == ["ocd-P2"]
    assert rec["link_basis"] == "procedure_id_in_source"
    assert rec["label_grade"] is True
    assert summary["n_matched_label_grade"] == 1


def test_idno_falls_back_to_exact_name(tmp_path):
    _, _, _, per_case, _ = _load(tmp_path, [
        {"entity_id_mtender": "9999999999999", "entity_name_as_in_source": "Beta Industries S.R.L."}])
    rec = per_case[0]
    assert rec["match_method"] == "name_exact"
    assert rec["match_confidence"] == "high"
    assert rec["procedure_ids"] == ["ocd-P3"]


def test_fuzzy_is_candidate_only_never_high(tmp_path):
    _, _, corpus, per_case, summary = _load(tmp_path, [
        {"entity_id_mtender": "", "entity_name_as_in_source": "BETA"}])
    rec = per_case[0]
    assert rec["match_method"] == "name_fuzzy"
    assert rec["match_confidence"] == "low"          # never auto-promoted
    assert rec["label_grade"] is False
    assert rec["procedure_ids"] == ["ocd-P3"]        # carried as candidate
    assert summary["n_fuzzy_candidates"] == 1
    assert summary["n_matched_label_grade"] == 0
    # and the fuzzy candidate builds NO label positives
    frame, info = S39.build_label_population(per_case, corpus)
    assert frame is None or info.get("n_positives", 0) == 0


def test_buyer_match_by_buyer_columns(tmp_path):
    _, _, _, per_case, _ = _load(tmp_path, [
        {"entity_type": "buyer", "entity_id_mtender": "2000000000002",
         "entity_name_as_in_source": ""}])
    rec = per_case[0]
    assert rec["match_method"] == "idno_exact"
    assert rec["procedure_ids"] == ["ocd-P3"]


def test_manual_requires_verified_human(tmp_path):
    _, _, _, per_case, _ = _load(tmp_path, [
        {"match_method": "manual", "procedure_ids": "ocd-P4",
         "verified_by_human": "true", "match_confidence": "high"},
        {"case_id": "C-2", "match_method": "manual",
         "procedure_ids": "ocd-P4", "verified_by_human": "false",
         "entity_id_mtender": "1000000000001"},
    ])
    assert per_case[0]["match_method"] == "manual"
    assert per_case[0]["procedure_ids"] == ["ocd-P4"]
    # unverified manual falls back to the automatic ladder (IDNO 1000000000001 here)
    assert per_case[1]["match_method"] == "idno_exact"
    assert "manual без verified_by_human" in per_case[1]["note"]


def test_evidence_d_never_in_label(tmp_path):
    _, _, _, per_case, _ = _load(tmp_path, [
        {"evidence_level": "D", "link_basis": "procedure_id_in_source",
         "procedure_ref_in_source": "ocd-P1"}])
    rec = per_case[0]
    assert rec["match_method"] == "ocid_exact"     # still matched & reported
    assert rec["match_confidence"] in ("high", "medium")
    assert rec["label_grade"] is False             # but D is never label-grade


def test_declared_columns_are_crosschecked(tmp_path):
    _, _, _, per_case, _ = _load(tmp_path, [
        {"n_procedures_matched": "7", "match_confidence": "medium"}])
    diffs = S38.crosscheck_declared(per_case)
    fields = {d["field"] for d in diffs}
    assert "n_procedures_matched" in fields
    assert "match_confidence" in fields


# ---------------------------------------------------------------------------
# MTA-0017: link_basis, identifier links, period window, unmatched reasons
# ---------------------------------------------------------------------------

#: a second corpus with two MD-numbered ocids (ambiguity tests)
EXTRA_CORPUS = pd.concat([FEATURES, pd.DataFrame({
    "ocid": ["ocds-b3wdp1-MD-1111111111111", "ocds-b3wdp1-MD-2222222222222"],
    "buyer_identifier": ["2000000000005", "2000000000006"],
    "buyer_name": ["PRIMARIA Q", "PRIMARIA R"],
    "winner_identifier": ["1000000000005", "1000000000006"],
    "winner_name": ["OMEGA SRL", "SIGMA SRL"],
    "published_date": ["2020-04-01T00:00:00Z", "2020-05-01T00:00:00Z"],
    "log_award_total": [15.0, 15.0],
    "n_bidders_log": [1.0, 1.0],
    "log_award_value": [15.0, 15.0],
    "procurement_method_details": ["open", "open"],
})], ignore_index=True)


def _load_indexed(tmp_path: Path, rows: list[dict], index):
    raw = pd.read_csv(_registry_csv(tmp_path, rows), dtype="string",
                      keep_default_na=False)
    registry, validation = S38.validate_registry(raw)
    corpus = S38.load_corpus(_features_csv(tmp_path))
    per_case, proc, summary = S38.match_cases(registry, corpus,
                                              contract_index=index)
    return validation, corpus, per_case, summary


def test_link_basis_unknown_value_is_rejected(tmp_path):
    _, validation, *_ = _load(tmp_path, [
        {"case_id": "C-lb", "link_basis": "doc_page"}])
    assert validation["n_rejected"] == 1
    assert any("link_basis" in r for r in validation["rejected"][0]["reasons"])


def test_link_basis_breakdown_reported(tmp_path):
    _, _, _, _, summary = _load(tmp_path, [
        {"case_id": "C-1", "link_basis": "procedure_id_in_source",
         "procedure_ref_in_source": "ocd-P1"},
        {"case_id": "C-2", "link_basis": "buyer_period_only",
         "entity_id_mtender": "1000000000001", "period_from": "2020-01-15",
         "period_to": "2020-01-15"},
    ])
    by = summary["by_link_basis"]
    assert by["procedure_id_in_source"]["records"] == 1
    assert by["procedure_id_in_source"]["label_grade"] == 1
    assert by["buyer_period_only"]["records"] == 1
    assert by["buyer_period_only"]["label_grade"] == 0   # never label-grade
    assert summary["by_link_basis"]["(не указан)"]["records"] == 0


def test_procedure_ref_not_found_is_unmatched(tmp_path):
    _, _, _, per_case, _ = _load(tmp_path, [
        {"link_basis": "procedure_id_in_source",
         "procedure_ref_in_source": "ocds-b3wdp1-MD-999999999999"}])
    rec = per_case[0]
    assert rec["match_method"] == "none"
    assert rec["unmatched_reason"] == "вне корпуса"
    assert rec["label_grade"] is False
    assert rec["match_confidence"] == ""       # unmatched carries no confidence


def test_procedure_ref_empty_without_declared_ids_is_unmatched(tmp_path):
    _, _, _, per_case, _ = _load(tmp_path, [
        {"link_basis": "procedure_id_in_source", "procedure_ref_in_source": ""}])
    assert per_case[0]["unmatched_reason"] == "нет идентификатора"


def test_procedure_ref_ambiguous_is_unmatched(tmp_path):
    _, _, _, per_case, _ = _load(tmp_path, [
        {"link_basis": "procedure_id_in_source",
         "procedure_ref_in_source": "1111111111111 и 2222222222222"}],
        corpus=EXTRA_CORPUS)
    rec = per_case[0]
    assert rec["match_method"] == "none"
    assert rec["unmatched_reason"] == "неоднозначно"
    assert "2" in rec["unmatched_detail"]


def test_unmatched_reasons_exactly_the_three_enum_values(tmp_path):
    _, _, _, per_case, _ = _load(tmp_path, [
        {"case_id": "C-oob", "link_basis": "procedure_id_in_source",
         "procedure_ref_in_source": "ocds-b3wdp1-MD-999999999999"},
        {"case_id": "C-noid", "link_basis": "procedure_id_in_source",
         "procedure_ref_in_source": ""},
        {"case_id": "C-amb", "link_basis": "procedure_id_in_source",
         "procedure_ref_in_source": "1111111111111 и 2222222222222"}],
        corpus=EXTRA_CORPUS)
    reasons = {r["unmatched_reason"] for r in per_case}
    assert reasons == set(S38.UNMATCHED_REASONS)
    assert all(r in S38.UNMATCHED_REASONS for r in reasons)


def test_buyer_period_only_window_restricts_matches(tmp_path):
    # IDNO 1000000000001 wins ocd-P1 (2020-01-01) and ocd-P2 (2021-06-01);
    # a single-day period expands by +/-30 days -> only P1 survives
    _, _, _, per_case, _ = _load(tmp_path, [
        {"link_basis": "buyer_period_only",
         "period_from": "2020-01-15", "period_to": "2020-01-15",
         "entity_id_mtender": "1000000000001"}])
    rec = per_case[0]
    assert rec["match_method"] == "idno_exact"
    assert rec["procedure_ids"] == ["ocd-P1"]
    assert rec["unmatched_reason"] is None
    assert rec["label_grade"] is False        # buyer_period_only: no label


def test_buyer_period_only_uses_procedure_date_as_anchor(tmp_path):
    _, _, _, per_case, _ = _load(tmp_path, [
        {"link_basis": "buyer_period_only",
         "procedure_date": "2021-06-01",
         "entity_id_mtender": "1000000000001"}])
    assert per_case[0]["procedure_ids"] == ["ocd-P2"]


def test_buyer_period_only_without_any_period_is_unmatched(tmp_path):
    _, _, _, per_case, _ = _load(tmp_path, [
        {"link_basis": "buyer_period_only",
         "entity_id_mtender": "1000000000001"}])
    rec = per_case[0]
    assert rec["match_method"] == "none"
    assert rec["unmatched_reason"] == "нет идентификатора"


def test_buyer_period_only_empty_window_is_unmatched(tmp_path):
    _, _, _, per_case, _ = _load(tmp_path, [
        {"link_basis": "buyer_period_only",
         "period_from": "2030-01-01", "period_to": "2030-01-01",
         "entity_id_mtender": "1000000000001"}])
    rec = per_case[0]
    assert rec["match_method"] == "none"
    assert rec["unmatched_reason"] == "вне корпуса"
    assert "2030" in rec["unmatched_detail"]


def test_buyer_period_only_never_in_label(tmp_path):
    """MTA-0017 п. 3: buyer_period_only попадает в реестр, в метку — НИКОГДА.

    Even with evidence A, high confidence and a human verification mark the
    record stays out of the label population (only ``procedure_id_in_source``
    and ``contract_number`` may form positives).
    """
    _, _, corpus, per_case, summary = _load(tmp_path, [
        {"case_id": "C-bpo", "link_basis": "buyer_period_only",
         "entity_id_mtender": "1000000000001",
         "period_from": "2020-01-15", "period_to": "2020-01-15",
         "evidence_level": "A", "match_confidence": "high",
         "verified_by_human": "true"}])
    rec = per_case[0]
    assert rec["n_procedures_matched"] > 0         # Included in the registry.
    assert rec["label_grade"] is False             # Excluded from the label set.
    assert summary["n_matched"] == 1
    assert summary["n_matched_label_grade"] == 0
    assert summary["by_link_basis"]["buyer_period_only"]["label_grade"] == 0
    frame, info = S39.build_label_population(per_case, corpus)
    assert frame is None or info.get("n_positives", 0) == 0


def test_contract_number_resolves_via_declared_ids(tmp_path):
    _, _, _, per_case, summary = _load(tmp_path, [
        {"link_basis": "contract_number", "procedure_ref_in_source": "CN-42",
         "procedure_ids": "ocd-P3", "entity_id_mtender": "",
         "entity_name_as_in_source": "BETA"}])
    rec = per_case[0]
    assert rec["match_method"] == "contract_number"
    assert rec["match_confidence"] == "high"
    assert rec["procedure_ids"] == ["ocd-P3"]
    assert rec["label_grade"] is True
    assert summary["n_matched_label_grade"] == 1


def test_contract_number_without_index_or_ids_is_unmatched(tmp_path):
    _, _, _, per_case, _ = _load(tmp_path, [
        {"link_basis": "contract_number", "procedure_ref_in_source": "CN-999",
         "entity_id_mtender": "", "entity_name_as_in_source": "BETA"}])
    rec = per_case[0]
    assert rec["match_method"] == "none"
    assert rec["unmatched_reason"] == "нет идентификатора"


def test_contract_number_ambiguous_index_uses_declared_ids(tmp_path):
    index = {"cn-7": {"ocd-P1", "ocd-P3"}}
    # no declared ids -> ambiguous, not a silent pick
    _, _, per_case, _ = _load_indexed(tmp_path, [
        {"case_id": "C-amb", "link_basis": "contract_number",
         "procedure_ref_in_source": "CN-7", "entity_id_mtender": "",
         "entity_name_as_in_source": "BETA"}], index)
    assert per_case[0]["unmatched_reason"] == "неоднозначно"
    # declared ids disambiguate
    _, _, per_case2, _ = _load_indexed(tmp_path, [
        {"case_id": "C-ok", "link_basis": "contract_number",
         "procedure_ref_in_source": "CN-7", "procedure_ids": "ocd-P3",
         "entity_id_mtender": "", "entity_name_as_in_source": "BETA"}], index)
    assert per_case2[0]["procedure_ids"] == ["ocd-P3"]
    assert per_case2[0]["match_method"] == "contract_number"


def test_contract_number_resolves_via_contract_index(tmp_path):
    index = {"cn-7": {"ocd-P3"}}
    _, _, per_case, _ = _load_indexed(tmp_path, [
        {"link_basis": "contract_number", "procedure_ref_in_source": "CN-7",
         "entity_id_mtender": "", "entity_name_as_in_source": "BETA"}], index)
    rec = per_case[0]
    assert rec["procedure_ids"] == ["ocd-P3"]
    assert rec["match_confidence"] == "high"
    assert rec["label_grade"] is True


def test_contract_index_build_and_cache(tmp_path):
    import gzip
    raw_dir = tmp_path / "pkgs"
    raw_dir.mkdir()
    pkg = {"records": [{"compiledRelease": {"contracts": [
        {"contractNumber": "CN-777",
         "id": "ocds-b3wdp1-MD-1234567890123-AC-1"},
        {"contractNumber": "Договор 1234567890999", "id": None}]}}]}
    with gzip.open(raw_dir / "ocds-b3wdp1-MD-1234567890123.json.gz",
                   "wt", encoding="utf-8") as fh:
        json.dump(pkg, fh)
    index = S38.build_contract_index(raw_dir)
    ocid = "ocds-b3wdp1-MD-1234567890123"
    assert index["cn-777"] == {ocid}
    assert index["ocds-b3wdp1-md-1234567890123-ac-1"] == {ocid}
    # the bare numeric tail of a compound contract number resolves too
    assert index["1234567890999"] == {ocid}
    assert index["договор 1234567890999"] == {ocid}
    cache = tmp_path / "contract_index.json"
    idx1, origin1 = S38.load_contract_index(rebuild=True, raw_dir=raw_dir,
                                            cache=cache)
    assert cache.exists() and "скан" in origin1
    idx2, origin2 = S38.load_contract_index(rebuild=False, raw_dir=raw_dir,
                                            cache=cache)
    assert origin2.startswith("кэш") and idx2 == idx1


def test_entity_contradiction_downgrades_high_to_medium(tmp_path):
    _, _, _, per_case, _ = _load(tmp_path, [
        {"link_basis": "procedure_id_in_source",
         "procedure_ref_in_source": "ocd-P3",      # winner IDNO 1000000000002
         "entity_id_mtender": "1000000000001"}])   # declared IDNO differs
    rec = per_case[0]
    assert rec["match_method"] == "ocid_exact"
    assert rec["match_confidence"] == "medium"     # downgraded, not silent
    assert "не входит" in rec["note"]
    assert rec["label_grade"] is True              # medium still label-grade


def test_verified_only_population_excludes_unverified(tmp_path):
    _, _, corpus, per_case, _ = _load(tmp_path, [
        {"case_id": "C-yes", "link_basis": "procedure_id_in_source",
         "procedure_ref_in_source": "ocd-P1", "entity_id_mtender": "",
         "entity_name_as_in_source": "ALPHA SRL",
         "first_publication_date": "2021-06-01",
         "verified_by_human": "true"},
        {"case_id": "C-no", "link_basis": "procedure_id_in_source",
         "procedure_ref_in_source": "ocd-P3", "entity_id_mtender": "",
         "entity_name_as_in_source": "BETA",
         "first_publication_date": "2020-01-01",
         "verified_by_human": "false"}])
    _frame_all, info_all = S39.build_label_population(per_case, corpus)
    frame_v, info_v = S39.build_label_population(per_case, corpus,
                                                 verified_only=True)
    assert info_all["n_positives"] == 2
    assert info_v["verified_only"] is True
    assert info_v["n_label_cases_used"] == 1
    assert info_v["n_positives"] == 1              # only C-yes (P1 < 2021-06)
    assert set(frame_v.loc[frame_v["y"] == 1, "ocid"]) == {"ocd-P1"}


# ---------------------------------------------------------------------------
# MTA-0017: ingest (scripts/41)
# ---------------------------------------------------------------------------

def test_ingest_table_headers_match_templates():
    assert (pd.read_csv(SOURCES_TEMPLATE, nrows=0).columns.tolist()
            == S41.SOURCE_COLUMNS)
    assert (pd.read_csv(EPISODES_TEMPLATE, nrows=0).columns.tolist()
            == S41.EPISODE_COLUMNS)
    assert (pd.read_csv(UNMATCHED_TEMPLATE, nrows=0).columns.tolist()
            == S41.UNMATCHED_COLUMNS)
    for path in (SOURCES_TEMPLATE, EPISODES_TEMPLATE, UNMATCHED_TEMPLATE):
        assert len(pd.read_csv(path)) == 0, f"{path.name} must stay a template"


def _write_csv(path: Path, header: list[str], rows: list[dict]) -> Path:
    pd.DataFrame(rows, columns=header).to_csv(path, index=False)
    return path


def _episode(**over) -> dict:
    base = {c: "" for c in S41.EPISODE_COLUMNS}
    base.update({
        "episode_id": "ep-1", "source_id": "src-1", "location": "с. 3",
        "entity_type": "supplier", "supplier": "ALPHA SRL",
        "risk_type": "splitting", "essence": "Дробление закупки",
        "quote": "цена выросла после победы",
    })
    base.update(over)
    return base


def test_ingest_derives_link_basis():
    assert S41.derive_link_basis({"procedure_ref": "ocd-P1",
                                  "contract_number": ""}) \
        == "procedure_id_in_source"
    assert S41.derive_link_basis({"procedure_ref": "",
                                  "contract_number": "CN-1"}) \
        == "contract_number"
    assert S41.derive_link_basis({"procedure_ref": "",
                                  "contract_number": ""}) \
        == "buyer_period_only"


def _sources_dict() -> dict:
    return {"src-1": {"source_id": "src-1", "url": "https://example.org/a",
                      "source_type": "court", "publication_date": "2024-03-01",
                      "evidence_level": "A", "title": "Решение суда",
                      "notes": ""}}


def test_ingest_rejects_quote_over_25_words(tmp_path):
    episodes = _write_csv(tmp_path / "ep.csv", S41.EPISODE_COLUMNS, [
        _episode(episode_id="ep-long", quote=" ".join(["слово"] * 26)),
        _episode(episode_id="ep-ok", quote="короткая цитата")])
    out, validation = S41.load_episodes(episodes, _sources_dict())
    assert validation["n_rows"] == 2
    assert validation["n_valid"] == 1
    assert validation["n_rejected"] == 1
    assert validation["n_quotes_over_limit"] == 1
    assert any("цитата" in r for r in validation["rejected"][0]["reasons"])
    assert out[0]["episode_id"] == "ep-ok"


def test_ingest_rejects_both_identifiers(tmp_path):
    episodes = _write_csv(tmp_path / "ep.csv", S41.EPISODE_COLUMNS, [
        _episode(procedure_ref="ocd-P1", contract_number="CN-1")])
    _out, validation = S41.load_episodes(episodes, _sources_dict())
    assert validation["n_rejected"] == 1
    assert validation["n_valid"] == 0
    assert any("одновременно" in r
               for r in validation["rejected"][0]["reasons"])


def test_ingest_rejects_unknown_source_and_bad_enum(tmp_path):
    sources = _write_csv(tmp_path / "src.csv", S41.SOURCE_COLUMNS, [])
    _out, validation = S41.load_episodes(sources.parent / "nope.csv", {})
    assert validation.get("error")  # missing file is reported, not crashed
    episodes = _write_csv(tmp_path / "ep2.csv", S41.EPISODE_COLUMNS, [
        _episode(episode_id="ep-bad", source_id="ghost",
                 risk_type="bribery", entity_type=" intermediary ")])
    out, validation = S41.load_episodes(episodes, _sources_dict())
    assert out == [] and validation["n_rejected"] == 1
    reasons = validation["rejected"][0]["reasons"]
    assert any("ghost" in r for r in reasons)
    assert any("risk_type" in r for r in reasons)
    assert any("entity_type" in r for r in reasons)


def test_ingest_end_to_end_idempotent(tmp_path):
    """41 -> registry/unmatched written once, second run updates only."""
    feats = _features_csv(tmp_path)
    sources = _write_csv(tmp_path / "src.csv", S41.SOURCE_COLUMNS, [
        {"source_id": "src-1", "url": "https://example.org/a",
         "source_type": "court", "publication_date": "2024-03-01",
         "evidence_level": "A", "title": "Решение суда"}])
    episodes = _write_csv(tmp_path / "ep.csv", S41.EPISODE_COLUMNS, [
        _episode(procedure_ref="ocd-P1"),
        _episode(episode_id="ep-2", procedure_ref="", contract_number="",
                 procedure_date="2030-01-01", supplier="GHOST SRL",
                 essence="Вне периода")])
    registry = tmp_path / "registry.csv"
    unmatched = tmp_path / "unmatched.csv"
    registry.write_text(REGISTRY_TEMPLATE.read_text(encoding="utf-8"),
                        encoding="utf-8")
    unmatched.write_text(UNMATCHED_TEMPLATE.read_text(encoding="utf-8"),
                         encoding="utf-8")
    argv = ["--sources", str(sources), "--episodes", str(episodes),
            "--registry", str(registry), "--unmatched", str(unmatched),
            "--features", str(feats),
            "--out-json", str(tmp_path / "ing.json"),
            "--out-md", str(tmp_path / "ing.md")]
    proc1 = _run("41_case_registry_ingest.py", *argv)
    assert proc1.returncode == 0, proc1.stderr
    reg1 = pd.read_csv(registry, dtype="string", keep_default_na=False)
    assert list(reg1.columns) == S38.REQUIRED_COLUMNS
    assert len(reg1) == 1                       # only the matched episode
    assert reg1.iloc[0]["case_id"] == "ep-1"
    assert reg1.iloc[0]["link_basis"] == "procedure_id_in_source"
    assert reg1.iloc[0]["verified_by_human"] == "false"
    assert "episode_id=ep-1" in reg1.iloc[0]["notes"]
    assert reg1.iloc[0]["first_publication_date"] == "2024-03-01"
    un1 = pd.read_csv(unmatched, dtype="string", keep_default_na=False)
    assert list(un1.columns) == S41.UNMATCHED_COLUMNS
    assert len(un1) == 1 and un1.iloc[0]["episode_id"] == "ep-2"
    assert un1.iloc[0]["reason"] in S38.UNMATCHED_REASONS
    payload = json.loads((tmp_path / "ing.json").read_text(encoding="utf-8"))
    assert payload["task"] == "MTA-0017"
    assert payload["validation"]["episodes"]["n_rejected"] == 0
    assert payload["derived_by_link_basis"] == {"procedure_id_in_source": 1,
                                                "buyer_period_only": 1}
    assert payload["verified_by_human_default"] is False
    text = (tmp_path / "ing.md").read_text(encoding="utf-8")
    assert "Извлечено" in text and "Индикатор потенциального риска" in text

    # second run: no duplicates, updates instead of adds
    proc2 = _run("41_case_registry_ingest.py", *argv)
    assert proc2.returncode == 0, proc2.stderr
    reg2 = pd.read_csv(registry, dtype="string", keep_default_na=False)
    un2 = pd.read_csv(unmatched, dtype="string", keep_default_na=False)
    assert len(reg2) == 1 and len(un2) == 1
    assert "обновлено 1" in proc2.stdout
    # a human verification mark survives the re-ingest
    reg2.loc[reg2["case_id"] == "ep-1", "verified_by_human"] = "true"
    reg2.to_csv(registry, index=False)
    proc3 = _run("41_case_registry_ingest.py", *argv)
    assert proc3.returncode == 0, proc3.stderr
    reg3 = pd.read_csv(registry, dtype="string", keep_default_na=False)
    assert reg3.iloc[0]["verified_by_human"] == "true"


def test_ingest_never_overwrites_hand_written_row(tmp_path):
    rows = [{c: "" for c in S38.REQUIRED_COLUMNS}]
    rows[0].update({"case_id": "ep-1", "title_short": "Ручная запись",
                    "entity_type": "supplier",
                    "entity_name_as_in_source": "ALPHA SRL",
                    "source_url_1": "https://example.org/hand",
                    "source_type_1": "court", "source_date_1": "2023-01-01",
                    "evidence_level": "A", "risk_type": "other",
                    "first_publication_date": "2023-01-02",
                    "verified_by_human": "true",
                    "notes": "важная ручная пометка"})
    registry = tmp_path / "registry.csv"
    pd.DataFrame(rows, columns=S38.REQUIRED_COLUMNS).to_csv(registry,
                                                            index=False)
    sources = _write_csv(tmp_path / "src.csv", S41.SOURCE_COLUMNS, [
        {"source_id": "src-1", "url": "https://example.org/a",
         "source_type": "court", "publication_date": "2024-03-01",
         "evidence_level": "A", "title": "Решение суда"}])
    episodes = _write_csv(tmp_path / "ep.csv", S41.EPISODE_COLUMNS,
                          [_episode(procedure_ref="ocd-P1")])
    proc = _run("41_case_registry_ingest.py",
                "--sources", str(sources), "--episodes", str(episodes),
                "--registry", str(registry),
                "--unmatched", str(tmp_path / "unmatched.csv"),
                "--features", str(_features_csv(tmp_path)),
                "--out-json", str(tmp_path / "ing.json"),
                "--out-md", str(tmp_path / "ing.md"))
    assert proc.returncode == 0, proc.stderr
    after = pd.read_csv(registry, dtype="string", keep_default_na=False)
    assert len(after) == 1                        # collision -> not added
    assert after.iloc[0]["title_short"] == "Ручная запись"
    payload = json.loads((tmp_path / "ing.json").read_text(encoding="utf-8"))
    assert payload["upsert"]["collisions"] and \
        payload["upsert"]["collisions"][0]["case_id"] == "ep-1"


# ---------------------------------------------------------------------------
# temporal protection (scripts/39)
# ---------------------------------------------------------------------------

def test_temporal_guard_labels_only_pre_publication_procedures(tmp_path):
    # identifier links (MTA-0017): C-P1 -> ocd-P1, C-P2 -> ocd-P2, both
    # public from 2021-01-01; the entity ladder is not used here
    _, _, corpus, per_case, _ = _load(tmp_path, [
        {"case_id": "C-P1", "link_basis": "procedure_id_in_source",
         "procedure_ref_in_source": "ocd-P1",
         "entity_id_mtender": "", "entity_name_as_in_source": "ALPHA SRL",
         "first_publication_date": "2021-01-01"},
        {"case_id": "C-P2", "link_basis": "procedure_id_in_source",
         "procedure_ref_in_source": "ocd-P2",
         "entity_id_mtender": "", "entity_name_as_in_source": "ALPHA SRL",
         "first_publication_date": "2021-01-01"}])
    assert all(r["label_grade"] for r in per_case)
    frame, info = S39.build_label_population(per_case, corpus)
    # window: published < 2021-01-01 -> P1 (2020) and P3 (2019); P2 (2021-06)
    # postdates the case and is excluded from the population entirely
    assert set(frame["ocid"]) == {"ocd-P1", "ocd-P3"}
    assert info["n_positives"] == 1
    assert frame.loc[frame["ocid"] == "ocd-P1", "y"].iloc[0] == 1
    assert "ocd-P2" not in set(frame["ocid"])
    assert info["n_dropped_post_publication"] == 1
    assert info["max_cutoff"] == "2021-01-01"


def test_temporal_guard_same_day_excluded(tmp_path):
    # published ON the first_publication_date is NOT strictly before it
    _, _, corpus, per_case, _ = _load(tmp_path, [
        {"link_basis": "procedure_id_in_source",
         "procedure_ref_in_source": "ocd-B1",
         "entity_id_mtender": "", "entity_name_as_in_source": "DELTA SRL",
         "first_publication_date": "2021-01-01"}])
    assert per_case[0]["label_grade"] is True
    frame, info = S39.build_label_population(per_case, corpus)
    assert info["n_positives"] == 0


def test_temporal_guard_excludes_d_and_low_confidence(tmp_path):
    _, _, corpus, per_case, _ = _load(tmp_path, [
        {"case_id": "C-D", "link_basis": "procedure_id_in_source",
         "procedure_ref_in_source": "ocd-P3",
         "entity_id_mtender": "", "entity_name_as_in_source": "BETA",
         "evidence_level": "D", "first_publication_date": "2023-01-01"},
        {"case_id": "C-low", "link_basis": "procedure_id_in_source",
         "procedure_ref_in_source": "ocd-B1",
         "entity_id_mtender": "", "entity_name_as_in_source": "DELTA SRL",
         "evidence_level": "A", "match_method": "manual",
         "match_confidence": "low", "verified_by_human": "true",
         "procedure_ids": "ocd-B1", "first_publication_date": "2023-01-01"}])
    assert all(not r["label_grade"] for r in per_case)
    frame, info = S39.build_label_population(per_case, corpus)
    assert frame is None or info.get("n_positives", 0) == 0


# ---------------------------------------------------------------------------
# power gate + verdict rule
# ---------------------------------------------------------------------------

def test_small_sample_gate_blocks_verdict():
    y = np.array([1] * 12 + [0] * 100)
    sup = np.array([f"s{i % 6}" for i in range(112)])
    buy = np.array([f"b{i % 20}" for i in range(112)])
    gate = S39.small_sample_gate(y, sup, buy)
    assert gate["enough_power"] is False
    assert "выборка мала" in gate["warning"]
    y2 = np.array([1] * 40 + [0] * 200)
    sup2 = np.array([f"s{i}" for i in range(240)])
    buy2 = np.array([f"b{i % 30}" for i in range(240)])
    assert S39.small_sample_gate(y2, sup2, buy2)["enough_power"] is True


def _cluster(point, lo, hi):
    return {"point": point, "ci": [lo, hi]}


_FLAG = {"auc": {"p97_5": 0.55}}


def test_verdict_rule_a():
    v = S39.decide_verdict(_cluster(0.62, 0.55, 0.69), 0.55, 0.52, 0.53, _FLAG)
    assert v["code"] == "а" and not v["determined_by_baseline"]


def test_verdict_rule_b_ci_includes_half():
    v = S39.decide_verdict(_cluster(0.52, 0.45, 0.60), 0.50, 0.50, 0.53, _FLAG)
    assert v["code"] == "б"


def test_verdict_rule_v_determined_by_size():
    v = S39.decide_verdict(_cluster(0.58, 0.54, 0.62), 0.62, 0.50, 0.53, _FLAG)
    assert v["code"] == "в" and v["determined_by_baseline"]


def test_verdict_rule_v_below_half():
    v = S39.decide_verdict(_cluster(0.42, 0.35, 0.48), 0.50, 0.50, 0.53, _FLAG)
    assert v["code"] == "в"


def test_random_flag_control_deterministic_and_uses_no_scores():
    y = np.array([1] * 20 + [0] * 180)
    groups = np.array(["g1"] * 100 + ["g2"] * 100)
    a = S39.random_flag_control(y, groups, repeats=10, seed=7700)
    b = S39.random_flag_control(y, groups, repeats=10, seed=7700)
    assert a == b
    assert a["repeats"] == 10 and a["rate"] == 0.05
    assert 0.0 < a["auc"]["median"] < 1.0


# ---------------------------------------------------------------------------
# end-to-end on the EMPTY template (no fabrication, graceful zeros)
# ---------------------------------------------------------------------------

def _run(script: str, *argv: str, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", str(ROOT / "scripts" / script), *argv],
        capture_output=True, text=True, cwd=str(ROOT), timeout=timeout)


def test_empty_template_end_to_end(tmp_path):
    feats = _features_csv(tmp_path)
    out_json = tmp_path / "match.json"
    out_md = tmp_path / "match.md"
    proc = _run("38_case_registry_match.py", "--registry",
                str(REGISTRY_TEMPLATE), "--features", str(feats),
                "--out-json", str(out_json), "--out-md", str(out_md))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["matching"]["n_matched"] == 0
    assert payload["validation"]["n_rows"] == 0
    assert "сопоставление" in out_md.read_text(encoding="utf-8")


def test_empty_registry_check_issues_no_verdict(tmp_path):
    feats = _features_csv(tmp_path)
    out_json = tmp_path / "check.json"
    out_md = tmp_path / "check.md"
    proc = _run("39_case_registry_check.py", "--registry",
                str(REGISTRY_TEMPLATE), "--features", str(feats),
                "--out-json", str(out_json), "--out-md", str(out_md))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["status"] == "no_label"
    assert payload["verdict"]["code"] is None
    assert "МЕТКА ПУСТА" in proc.stdout


def test_populated_registry_runs_metric_path_descriptively(tmp_path):
    """End-to-end on synthetic data: the full metric path executes, the
    power gate withholds the verdict and the report says «выборка мала»."""
    feats = _features_csv(tmp_path)
    scores = tmp_path / "scores.csv"
    pd.DataFrame({"ocid": FEATURES["ocid"],
                  "max_score": [0.95, 0.4, 0.6, 0.1, 0.8]}).to_csv(
        scores, index=False)
    registry = _registry_csv(tmp_path, [
        {"case_id": "C-P1", "link_basis": "procedure_id_in_source",
         "procedure_ref_in_source": "ocd-P1", "entity_id_mtender": "",
         "entity_name_as_in_source": "ALPHA SRL",
         "first_publication_date": "2021-06-01"},
        {"case_id": "C-P3", "link_basis": "procedure_id_in_source",
         "procedure_ref_in_source": "ocd-P3", "entity_id_mtender": "",
         "entity_name_as_in_source": "BETA", "evidence_level": "B",
         "first_publication_date": "2020-01-01"},
        {"case_id": "C-P2", "link_basis": "procedure_id_in_source",
         "procedure_ref_in_source": "ocd-P2", "entity_id_mtender": "",
         "entity_name_as_in_source": "ALPHA SRL",
         "first_publication_date": "2021-06-01"},
    ])
    out_json = tmp_path / "check.json"
    out_md = tmp_path / "check.md"
    proc = _run("39_case_registry_check.py", "--registry", str(registry),
                "--features", str(feats), "--scores", str(scores),
                "--out-json", str(out_json), "--out-md", str(out_md),
                "--n-boot", "20", "--random-repeats", "20",
                "--flag-repeats", "5")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    # window < max cutoff (2021-06-01): P1, P3, B1 stay; P2 (=C-1 cutoff)
    # postdates its case and leaves the population; P4 (2022) is outside
    assert payload["label"]["n_population"] == 3
    assert payload["label"]["n_positives"] == 2       # P1 (<2021-06), P3 (<2020-01)
    assert payload["label"]["n_dropped_post_publication"] == 1
    assert payload["label"]["base_rate"] == pytest.approx(2 / 3)
    # metrics exist for the main ranking and every required comparison
    assert payload["v0_external"]["roc_auc"] is not None
    for key in ("log_award_total", "n_bidders_log", "random_ranking",
                "random_flags_5pct_within_group"):
        assert key in payload["baselines"]
    assert payload["pre_registered"]["temporal_guard"]
    # MTA-0017: the second version (verified_by_human=true) is computed too
    # (all fixture rows default to verified_by_human=true)
    assert payload["verified_only"]["status"] == "ok"
    assert payload["verified_only"]["label"]["n_positives"] == 2
    assert payload["verified_only"]["label"]["verified_only"] is True
    assert payload["pre_registered"]["versions"]
    # 2 positives < 30 -> power gate withholds the verdict
    assert payload["verdict"]["code"] is None
    assert "выборка мала" in payload["power_gate"]["warning"]
    assert "выборка мала" in out_md.read_text(encoding="utf-8")
    assert "verified_by_human" in out_md.read_text(encoding="utf-8")


def test_empty_registry_case_studies_graceful(tmp_path):
    feats = _features_csv(tmp_path)
    scores = tmp_path / "scores.csv"
    pd.DataFrame({
        "ocid": FEATURES["ocid"],
        "max_score": [0.9, 0.5, 0.3, 0.1, 0.7],
        "n_models_flagging": [3, 1, 0, 0, 2],
        "score_statistical_mad_zscore": [0.9] * 5,
        "score_isolation_forest": [0.8] * 5,
        "score_local_outlier_factor": [0.7] * 5,
        "score_one_class_svm": [0.6] * 5,
    }).to_csv(scores, index=False)
    out_md = tmp_path / "studies.md"
    proc = _run("40_case_registry_studies.py", "--registry",
                str(REGISTRY_TEMPLATE), "--features", str(feats),
                "--scores", str(scores),
                "--models", str(tmp_path / "no-such-model.joblib"),
                "--out-md", str(out_md))
    assert proc.returncode == 0, proc.stderr
    text = out_md.read_text(encoding="utf-8")
    assert "уровня A/B" in text
    assert "шаблон без записей" in text


# ---------------------------------------------------------------------------
# security regressions
# ---------------------------------------------------------------------------

def test_new_scripts_have_no_network_imports():
    for name in ("38_case_registry_match.py", "39_case_registry_check.py",
                 "40_case_registry_studies.py", "41_case_registry_ingest.py"):
        source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        for banned in ("import requests", "urllib.request", "http.client",
                       "httpx", "socket"):
            assert banned not in source, f"{name} contains {banned}"


def test_new_scripts_run_standalone_help():
    for name in ("38_case_registry_match.py", "39_case_registry_check.py",
                 "40_case_registry_studies.py", "41_case_registry_ingest.py"):
        proc = _run(name, "--help")
        assert proc.returncode == 0, proc.stderr
