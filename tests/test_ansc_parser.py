"""MTA-0012 tests: ANSC document parsing (scripts 29-30).

All parser tests run on SYNTHETIC strings only - nothing downloaded, no
network. The author's known pair (letter 01-02-01/05/933/26 of 07.04.2026,
decision 03D-159-26, procurements MD-1771250199749 / MD-1772439133346) is
used as a synthetic fixture to pin the regexes.

Security regression: ``scripts/30`` must refuse to run without the explicit
``--allow-network`` flag - even under ``python -I``.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


S30 = _load_script("30_ansc_sample_parse.py")

SYNTHETIC_DOC = """
HOTĂRÂREA NR. 03D-159-26 din 07.04.2026
Nr. registru 01-02-01/05/933/26
Contestaţia nr. 1234b/05.04.2026 a contestatorului
Cu privire la procedura de achiziţie MD-1771250199749
şi MD-1772439133346. ADMITE contestaţia parţial.
"""


def test_decision_number():
    text = "Hotărârea nr. 03D-159-26 din 07.04.2026, 03d-159-26 repetat."
    assert S30.parse_decision_number(text) == ["03D-159-26"]


def test_decision_number_requires_full_shape():
    # bare "159-26" or "03D-159" must NOT be recognised
    assert S30.parse_decision_number("nr. 159-26 şi 03D-159") == []


def test_register_number():
    assert S30.parse_register_numbers("Nr. registru 01-02-01/05/933/26") == \
        ["01-02-01/05/933/26"]


def test_complaint_number():
    got = S30.parse_complaint_numbers("Contestaţia nr. 1234b/05.04.2026")
    assert "1234b/05.04.2026" in got


def test_dates():
    assert S30.parse_dates("din 07.04.2026, între 15.12.2023 şi 01.01.2024") == \
        ["01.01.2024", "07.04.2026", "15.12.2023"]


def test_procurement_ids():
    got = S30.parse_procurement_ids(
        "MD-1771250199749 и MD-1772439133346, md-1539840280133")
    assert got == ["MD-1539840280133", "MD-1771250199749",
                   "MD-1772439133346"]


def test_outcome_admis():
    assert S30.parse_outcome("ADMITE contestaţia ca întemeiată. Admis.") == \
        "admis"


def test_outcome_respins():
    assert S30.parse_outcome("RESPINGE contestaţia ca neîntemeiată.") == \
        "respins"


def test_outcome_partial_beats_plain():
    assert S30.parse_outcome("admite parţial contestaţia") == "admis_partial"
    assert S30.parse_outcome("Admis parțial. Respinge restul.") == \
        "admis_partial"


def test_outcome_none_when_absent():
    assert S30.parse_outcome("Procedura de achiziţie publică.") is None


def test_synthetic_author_example_all_fields():
    text = SYNTHETIC_DOC
    assert S30.parse_decision_number(text) == ["03D-159-26"]
    assert S30.parse_register_numbers(text) == ["01-02-01/05/933/26"]
    assert "1234b/05.04.2026" in S30.parse_complaint_numbers(text)
    assert "07.04.2026" in S30.parse_dates(text)
    assert S30.parse_procurement_ids(text) == ["MD-1771250199749",
                                               "MD-1772439133346"]
    assert S30.parse_outcome(text) == "admis_partial"


def test_url_host_gate():
    assert S30.url_host(
        "http://storage.mtender.gov.md/get/abc-123") == "storage.mtender.gov.md"
    assert S30.url_host("https://evil.example.com/x") == "evil.example.com"


def test_allocate_stratified_prefers_strong_and_is_deterministic():
    rows = []
    for year, n, strong in (("2018", 60, "0"), ("2019", 30, "0"),
                            ("2020", 10, "1")):
        for i in range(n):
            rows.append({"year": year, "ocid": f"ocd-{year}-{i:03d}",
                         "url": f"http://storage.mtender.gov.md/get/{i}",
                         "strong": strong})
    sample = S30.allocate_stratified(rows, 10)
    assert len(sample) == 10
    assert sum(1 for r in sample if r["year"] == "2018") == 6
    assert sum(1 for r in sample if r["year"] == "2019") == 3
    assert sum(1 for r in sample if r["year"] == "2020") == 1
    # strong rows come first inside their year group
    assert sample[0]["year"] == "2018" or sample[0]["strong"] == "1"
    assert sample == S30.allocate_stratified(rows, 10)


def test_script30_refuses_without_allow_network():
    proc = subprocess.run(
        [sys.executable, "-I", str(ROOT / "scripts" /
                                   "30_ansc_sample_parse.py")],
        capture_output=True, text=True, cwd=str(ROOT), timeout=120)
    assert proc.returncode == 2, proc.stderr
    assert "--allow-network" in proc.stderr


def test_inventory_keywords_cover_author_list():
    s29 = _load_script("29_ansc_docs_inventory.py")
    assert s29.KEYWORDS == [
        "ansc",
        "autoritatea nationala pentru solutionarea contestatiilor",
        "agentia nationala pentru solutionarea contestatiilor",
        "contestati",
        "decizi",
        "03d-",
        "hotarare ansc",
        "жалоб",
        "решение анск",
    ]
    # diacritic-insensitive match: "contestaţi" ~ "contestație"
    assert s29.matched_keywords("Lista contestaţilor") == ["contestati"]
    assert s29.matched_keywords("decizie de atribuire") == ["decizi"]
