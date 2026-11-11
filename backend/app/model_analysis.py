"""Read-only, same-run score comparisons. Never refits or changes verdicts."""
from __future__ import annotations

import json
from bisect import bisect_left, bisect_right
import math
import numpy as np
from .explain import DETECTOR_FIELDS


def number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def build_model_analysis(row: dict, rows: list[dict], summary: dict | None = None) -> dict:
    provenance = row.get('score_provenance') or {}
    run_id = provenance.get('run_id')
    peers = [r for r in rows if run_id and (r.get('score_provenance') or {}).get('run_id') == run_id]
    summary = summary or {}
    matched = bool(run_id and summary.get('run_id') == run_id)
    recorded = {m['model']: m for m in summary.get('models', []) if m.get('model')} if matched else {}
    detectors = []
    for key, label, field in DETECTOR_FIELDS:
        values = sorted(v for r in peers if (v := number(r.get(field))) is not None)
        score = number(row.get(field))
        verdict = (row.get('model_flags') or {}).get(key)
        params = recorded.get(key, {}).get('params') or {}
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except (ValueError, TypeError):
                params = {}
        if not isinstance(params, dict):
            params = {}
        threshold = None
        if matched and key == 'statistical_mad_zscore' and number(params.get('z_threshold')) is not None:
            threshold = {'value': float(params['z_threshold']), 'operator': '>', 'source': 'results/mongo/detection_summary.json'}
        if matched and key == 'one_class_svm' and params.get('kernel'):
            threshold = {'value': 0.0, 'operator': '>', 'source': 'scripts/06_detect_anomalies.py: score = -decision_function; matching detection_summary run'}
        bins = []
        selected_bin = None
        if values:
            counts, edges = np.histogram(values, bins=32 if values[0] != values[-1] else 1)
            if score is not None and values[0] <= score <= values[-1]:
                selected_bin = min(max(int(np.searchsorted(edges, score, side='right')) - 1, 0), len(counts) - 1)
            bins = [{'index': i, 'start': float(edges[i]), 'end': float(edges[i + 1]), 'n': int(n), 'selected': i == selected_bin} for i, n in enumerate(counts)]
        percentile = None
        if values and score is not None:
            # Midrank for ties; raw-score rank within a named run, not corruption probability.
            percentile = 100 * (bisect_left(values, score) + bisect_right(values, score)) / (2 * len(values))
        detectors.append({
            'key': key, 'label': label, 'field': field, 'score': score,
            'verdict': 'flagged' if verdict is True else 'not_flagged' if verdict is False else 'unavailable',
            'n_reference': len(values), 'n_missing_score': len(peers) - len(values),
            'score_percentile': percentile, 'bins': bins, 'threshold': threshold,
            'threshold_matches_verdict': ((score > threshold['value']) == verdict) if score is not None and threshold is not None and isinstance(verdict, bool) else None,
            'params': params, 'features': params.get('scored_features', []) if key == 'statistical_mad_zscore' else summary.get('feature_columns', []) if matched else [],
            'training_medians': None, 'training_mad': None, 'local_attribution': None,
        })
    decisions = {
        key: np.fromiter((1 if (r.get('model_flags') or {}).get(key) is True else 0 if (r.get('model_flags') or {}).get(key) is False else -1 for r in peers), dtype=np.int8)
        for key, _, _ in DETECTOR_FIELDS
    }
    agreement = []
    for left, _, _ in DETECTOR_FIELDS:
        cells = []
        for right, _, _ in DETECTOR_FIELDS:
            a, b = decisions[left], decisions[right]
            valid = (a >= 0) & (b >= 0)
            n = int(np.count_nonzero(valid))
            same = int(np.count_nonzero((a == b) & valid))
            cells.append({'left': left, 'right': right, 'n': n, 'n_agree': same, 'agreement': same / n if n else None})
        agreement.append(cells)
    return {
        'tender_id': row.get('tender_id'), 'run_id': run_id, 'source': provenance.get('source'),
        'summary_matches_run': matched, 'generated_at': summary.get('generated_at') if matched else None,
        'model_version': summary.get('model_version') if matched else None, 'n_reference': len(peers), 'n_corpus': len(rows),
        'scope': 'same_run_available_scores', 'detectors': detectors, 'agreement': agreement,
        'consensus': {'n_models_flagging': row.get('n_models_flagging'), 'flag': row.get('consensus_flag'), 'band': row.get('risk_level'), 'percentile': row.get('risk_score')},
    }
