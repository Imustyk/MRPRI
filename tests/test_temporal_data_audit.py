"""Historical certification needs original evidence, not algebraic stage safety."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('temporal_audit', ROOT / 'scripts/53_temporal_data_audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def verified_evidence():
    # Synthetic provenance assertion, never an assertion about the real corpus.
    return dict(source_kind='initial_notice_release', initial_notice_identity_confirmed=True,
                timestamp_immutability_verified=True, complete_initial_payload=True,
                t0='2022-01-01T12:00:00Z', published_at='2022-01-01T12:00:00Z',
                fields=dict(startDate='2022-01-02T00:00:00Z', endDate='2022-01-12T00:00:00Z',
                            procurementMethod='open', procurementMethodDetails='openTender'))


def test_verified_original_is_eligible_for_certification():
    assert audit.publication_gate(verified_evidence()) == ('HISTORICALLY_CERTIFIED', [])


@pytest.mark.parametrize('change', [
    {'source_kind': 'compiled_snapshot'},
    {'initial_notice_identity_confirmed': False},
    {'timestamp_immutability_verified': False},
    {'complete_initial_payload': False},
    {'published_at': '2022-01-02T00:00:00Z'},
    {'published_at': '2022-01-01'},
    {'t0': None},
    {'fields': {}},
])
def test_backdated_or_incomplete_sources_do_not_certify(change):
    evidence = verified_evidence()
    evidence.update(change)
    assert audit.publication_gate(evidence)[0] == 'NOT CERTIFIED'


def test_record_pointers_and_compiled_releases_are_not_original_payloads():
    q = {'actualReleases': [{'ocid': 'x', 'uri': 'https://invalid/record'}],
         'records': [{'compiledRelease': {'tender': {}, 'date': '2022-01-01', 'tag': ['compiled']},
                      'releases': [{'uri': 'https://invalid/release'},
                                   {'tender': {}, 'date': '2022-01-01', 'tag': ['compiled']}]}]}
    assert audit.embedded_payloads(q) == []
    q['records'][0]['releases'].append({'tender': {'tenderPeriod': {}}, 'date': '2022-01-01', 'tag': ['tender']})
    assert len(audit.embedded_payloads(q)) == 1
    assert audit.publication_gate({'source_kind': 'initial_notice_release'})[0] == 'NOT CERTIFIED'


def test_mixed_planning_and_submission_window_is_detected_without_mutation():
    q = {'records': [
        {'compiledRelease': {'ocid': 'x-PN-1', 'tender': {'tenderPeriod': {'startDate': '2022-01-01T00:00:00Z'}}}},
        {'compiledRelease': {'ocid': 'x-EV-1', 'tender': {'tenderPeriod': {'startDate': '2022-01-10T00:00:00Z', 'endDate': '2022-01-20T00:00:00Z'}}}},
    ]}
    original = copy.deepcopy(q)
    merged = {'tender': {'tenderPeriod': {'startDate': '2022-01-01T00:00:00Z', 'endDate': '2022-01-20T00:00:00Z'}}}
    _, _, hybrid, ev_days = audit.modern_period_trace(q, merged)
    assert hybrid and ev_days == 10
    assert q == original
    assert audit.modern_period_trace(q, q['records'][1]['compiledRelease'])[2] is False


def test_streaming_large_archived_array_preserves_payloads(tmp_path):
    rows = [{'ocid': 'x', 'payload': 'z' * 100000}, {'ocid': 'y', 'values': [None, 1]}]
    path = tmp_path / 'archive.json'
    path.write_text(json.dumps(rows))
    assert list(audit.iter_json_array(path)) == rows


def test_truncated_archive_fails_instead_of_certifying(tmp_path):
    path = tmp_path / 'archive.json'
    path.write_text('[{"ocid": "x"},')
    with pytest.raises(ValueError):
        list(audit.iter_json_array(path))
