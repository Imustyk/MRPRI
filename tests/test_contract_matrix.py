"""Contract-matrix tests (docs/contract_matrix.yaml + scripts/23).

The matrix is the acceptance contract between the business and the model:
the model is accepted only when every row is "met" or a documented
"not_verifiable". These tests cover the structure rules that must hold
regardless of the artefacts on disk:

1. every model KPI references at least one existing business KPI;
2. statuses come from the allowed enum and not_verifiable rows carry a
   documented reason + doc reference;
3. every referenced check id exists in the checker's registry and every
   comparator is known;
4. comparators apply as the thresholds in the matrix claim.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _rows() -> list[dict]:
    payload = yaml.safe_load((ROOT / "docs" / "contract_matrix.yaml").read_text("utf-8"))
    return payload["rows"]


def test_matrix_structure_is_valid():
    s23 = _load_script("23_check_contract.py")
    assert s23.validate_structure(_rows()) == []


def test_every_model_kpi_links_business_kpi():
    rows = _rows()
    biz = {r["id"] for r in rows if r["type"] == "business"}
    model = [r for r in rows if r["type"] == "model"]
    assert biz and model
    for row in model:
        assert row.get("linked_to"), f"{row['id']} has no business KPI"
        assert set(row["linked_to"]) <= biz, f"{row['id']} references unknown KPI"


def test_check_ids_exist_in_registry():
    s23 = _load_script("23_check_contract.py")
    for row in _rows():
        if row.get("verifiable", True) is not False:
            assert row["check"] in s23.REGISTRY, f"{row['id']}: unknown check"


def test_not_verifiable_rows_are_documented():
    rows = [r for r in _rows() if r.get("status") == "not_verifiable"]
    # the structural limits of the method that stay not-verifiable (B8, B9);
    # M10 moved out of this set once LIME was implemented - it is now
    # verifiable and unmet, which is a stronger statement than "unverifiable"
    assert len(rows) >= 2
    ids = {r["id"] for r in rows}
    assert ids == {"B8", "B9"}, ids
    for row in rows:
        assert row.get("verifiable") is False, row["id"]
        assert row.get("reason"), f"{row['id']}: not_verifiable without reason"
        assert row.get("doc_ref"), f"{row['id']}: not_verifiable without doc_ref"


def test_comparators_apply_as_documented():
    s23 = _load_script("23_check_contract.py")
    cmp = s23.COMPARATORS
    assert cmp[">="](1.0, 1.0) and not cmp[">="](0.0, 0.0124)   # precision@200
    assert not cmp["<"](1.00536, 1.0)                            # cost ratio B2/M8
    assert not cmp["<="](32.0, 0.0)                              # bias verdicts B4/M9
    assert cmp["<"](0.0, 0.0124) and cmp["<="](4.758, 10.0)
