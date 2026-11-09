"""No network: test provenance integrity and conservative certification."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('source_recovery',ROOT/'scripts/54_source_recovery_pilot.py')
pilot=importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)

@pytest.mark.parametrize('missing',['original_fields_complete','identity_verified','public_timestamp_proven'])
def test_each_missing_proof_blocks_certification(missing):
    evidence=dict(original_fields_complete=True,identity_verified=True,public_timestamp_proven=True,partial_evidence=True)
    evidence[missing]=False
    assert pilot.historical_status(**evidence)=='PARTIALLY VERIFIED'


def test_synthetic_full_evidence_passes_gate_but_does_not_certify_corpus():
    assert pilot.historical_status(original_fields_complete=True,identity_verified=True,public_timestamp_proven=True)=='CERTIFIED'
    assert pilot.historical_status()=='NOT CERTIFIED'


def test_http_200_and_old_dates_do_not_prove_publication():
    assert pilot.historical_status(partial_evidence=True)=='PARTIALLY VERIFIED'


def test_budget_exceeded_is_rejected_before_body_access(tmp_path):
    with pytest.raises(ValueError,match='limit'):
        pilot.validate_ledger([{}]*21,tmp_path)


def test_downloaded_bytes_cannot_be_substituted(tmp_path):
    body=tmp_path/'01.body';body.write_bytes(b'original')
    row=dict(request_number=1,body_file='01.body',sha256=pilot.sha(body),bytes=8)
    pilot.validate_ledger([row],tmp_path)
    body.write_bytes(b'replaced')
    with pytest.raises(ValueError,match='identity'):
        pilot.validate_ledger([row],tmp_path)


def test_truncation_and_noncontiguous_request_numbers_fail(tmp_path):
    with pytest.raises(ValueError,match='truncated'):
        pilot.validate_ledger([dict(request_number=1,body_truncated=True)],tmp_path)
    with pytest.raises(ValueError,match='numbering'):
        pilot.validate_ledger([dict(request_number=2)],tmp_path)


def test_frozen_pilot_covers_only_two_procedures_and_has_no_certified_values():
    import csv
    source=ROOT/'data/source_recovery/mta0023'
    ledger=json.loads((source/'http_provenance.json').read_text())
    pilot.validate_ledger(ledger,source)
    rows=list(csv.DictReader((ROOT/'results/tables/mta0023_publication_evidence.csv').open()))
    assert {x['ocid'] for x in rows}==set(pilot.TARGETS)
    assert len(rows)==20 and len({(x['ocid'],x['field_or_feature']) for x in rows})==20
    assert all(x['certified_value']=='' and x['original_public_timestamp_proven']=='0' for x in rows)
    assert len(ledger)==19 and all(x['http_status'] in [200,301,404] for x in ledger)
    assert all(any(target in x['url'] for target in pilot.TARGETS) or x['url'].startswith(('http://storage.mtender.gov.md/get/','https://storage.mtender.gov.md/get/')) for x in ledger)
