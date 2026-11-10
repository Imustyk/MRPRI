"""Research-facing cohort invariants: no substituted dates or fabricated scores."""
from backend.app.adapter import build_snapshot_cohorts, build_stats, project_tender


def test_score_denominator_keeps_unknown_out_and_zero_in():
    result = build_snapshot_cohorts([
        {'published_at':'2022-01-02T00:00:00Z','risk_score':0},
        {'published_at':'2022-01-03T00:00:00Z','risk_score':100},
        {'published_at':'2022-01-04T00:00:00Z','risk_score':None},
    ])
    assert result['monthly'] == [{'month':'2022-01','n':3,'n_scored':2,'n_unscored':1,'avg_risk':50}]
    assert result['publication_time_certified'] is False


def test_calendar_gaps_and_unscored_cohorts_stay_null():
    result = build_snapshot_cohorts([
        {'published_at':'2022-01-02T00:00:00Z','risk_score':80},
        {'published_at':'2022-03-02T00:00:00Z','risk_score':None},
    ])
    assert result['monthly'][1] == {'month':'2022-02','n':0,'n_scored':0,'n_unscored':0,'avg_risk':None}
    assert result['monthly'][2]['avg_risk'] is None


def test_no_fallback_to_other_available_dates():
    result = build_snapshot_cohorts([{'list_date':'2022-01-01T00:00:00Z','tender_start':'2022-01-01T00:00:00Z','award_date':'2022-01-01T00:00:00Z','risk_score':90}])
    assert result['monthly'] == []
    assert result['n_missing_date'] == 1


def test_invalid_naive_and_placeholder_dates_are_accounted_for():
    result = build_snapshot_cohorts([{'published_at':date,'risk_score':90} for date in ['bad','2022-02-30T00:00:00Z','2022-01-01','1970-01-01T00:00:00Z',None,'']])
    assert result['n_invalid_date'] == 4
    assert result['n_missing_date'] == 2
    assert result['n_dated'] == 0


def test_grouping_uses_utc_and_handles_year_boundary():
    result = build_snapshot_cohorts([{'published_at':'2023-01-01T00:30:00+02:00','risk_score':60}, {'published_at':'2023-02-01T00:00:00Z','risk_score':70}])
    assert [row['month'] for row in result['monthly']] == ['2022-12','2023-01','2023-02']
    assert result['n_dated'] == 2


def test_nonfinite_and_out_of_range_scores_are_not_in_mean():
    result = build_snapshot_cohorts([{'published_at':'2022-01-01T00:00:00Z','risk_score':v} for v in [float('nan'),float('inf'),-1,101,None]])
    assert result['n_scored'] == 0
    assert result['monthly'][0]['n_unscored'] == 5
    assert result['monthly'][0]['avg_risk'] is None


def test_empty_input_is_finite_and_has_explicit_provenance():
    result = build_snapshot_cohorts([])
    assert result['monthly'] == []
    assert result['n_total'] == result['n_dated'] == 0
    assert result['source_field'] == 'OCDS package.publishedDate'
    assert result['interpretation'] == 'retrospective_snapshot_cohorts'


def test_stats_retains_legacy_list_date_contract_separately():
    row = project_tender({'ocid':'fixture','published_date':'2022-01-01T00:00:00Z','list_date':'2023-04-01T00:00:00Z'}, None)
    result = build_stats([row], [])
    assert result['monthly'][0]['month'] == '2023-04'
    assert result['snapshot_cohorts']['monthly'][0]['month'] == '2022-01'
