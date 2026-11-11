"""Same-run explanatory comparisons must not become invented model results."""
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.model_analysis import build_model_analysis
from backend.app.adapter import project_tender

KEYS = ['statistical_mad_zscore','isolation_forest','local_outlier_factor','one_class_svm']

def row(tid='one', run='run-A', score=0.0):
    return {'tender_id':tid,'score_provenance':{'run_id':run,'source':'fixture'},'rule_score':score,'iso_score':score,'lof_score':score,'svm_score':score,'model_flags':{k:False for k in KEYS},'risk_score':0,'risk_level':'low','n_models_flagging':0,'consensus_flag':False}

def summary(run='run-A'):
    return {'run_id':run,'feature_columns':['f1'],'models':[{'model':KEYS[0],'params':'{"z_threshold":5,"scored_features":["f1"]}'},{'model':KEYS[1],'params':{'contamination':.05}},{'model':KEYS[2],'params':{'contamination':.05}},{'model':KEYS[3],'params':{'nu':.05,'kernel':'rbf'}}]}

def test_same_run_only_and_input_not_mutated():
    rows=[row(),row('two',score=10),row('other','run-B',100)]
    before=deepcopy(rows)
    out=build_model_analysis(rows[0],rows,summary())
    assert out['n_reference']==2
    assert sum(b['n'] for b in out['detectors'][0]['bins'])==2
    assert rows==before

@pytest.mark.parametrize('run',[None,''])
def test_unknown_run_has_no_forged_reference(run):
    r=row(run=run)
    out=build_model_analysis(r,[r],summary())
    assert out['n_reference']==0
    assert all(m['bins']==[] and m['score_percentile'] is None and m['threshold'] is None for m in out['detectors'])

def test_missing_scores_and_zero_stay_distinct():
    rows=[row(),row('missing',score=None),row('bad',score=float('nan'))]
    out=build_model_analysis(rows[0],rows,summary())
    m=out['detectors'][0]
    assert m['score']==0 and m['n_reference']==1 and m['n_missing_score']==2
    assert m['score_percentile']==50
    assert sum(b['selected'] for b in m['bins'])==1


def test_histogram_includes_maximum_and_reports_midrank_ties():
    rows=[row(score=0),row('tie',score=0),row('max',score=100)]
    out=build_model_analysis(rows[2],rows,summary())
    m=out['detectors'][0]
    assert sum(b['n'] for b in m['bins'])==3
    assert m['bins'][-1]['selected'] is True
    assert m['score_percentile']==pytest.approx(100*2.5/3)


def test_contamination_is_never_a_score_threshold():
    out=build_model_analysis(row(),[row()],summary())
    assert out['detectors'][1]['threshold'] is None
    assert out['detectors'][2]['threshold'] is None
    assert out['detectors'][0]['threshold']['value']==5
    assert out['detectors'][3]['threshold']['value']==0
    assert out['model_version'] is None


def test_summary_mismatch_hides_unconfirmed_parameters():
    out=build_model_analysis(row(),[row()],summary('other'))
    assert not out['summary_matches_run']
    assert all(not m['features'] and not m['params'] and m['threshold'] is None for m in out['detectors'])


def test_boundary_disagreement_does_not_rewrite_verdict():
    r=row(score=8)
    out=build_model_analysis(r,[r],summary())
    assert out['detectors'][0]['verdict']=='not_flagged'
    assert out['detectors'][0]['threshold_matches_verdict'] is False
    assert r['model_flags'][KEYS[0]] is False


def test_agreement_denominators_exclude_unknown_decisions():
    rows=[row(),row('second')]
    rows[1]['model_flags'][KEYS[1]]=None
    rows[1]['model_flags'][KEYS[0]]=True
    cell=build_model_analysis(rows[0],rows,summary())['agreement'][0][1]
    assert cell['n']==1 and cell['n_agree']==1 and cell['agreement']==1


def test_provenance_projects_real_score_document_only():
    projected=project_tender({'ocid':'test'},{'run_id':'actual','_source':'mongodb.anomaly_scores'})
    assert projected['score_provenance']=={'run_id':'actual','source':'mongodb.anomaly_scores'}
    assert project_tender({'ocid':'test'},None)['score_provenance']['run_id'] is None


def test_model_analysis_http_and_unknown_id(monkeypatch):
    from backend.app import store
    monkeypatch.setattr(store,'load_tenders',lambda:[row()])
    monkeypatch.setattr(store,'detection_run',summary)
    client=TestClient(app)
    response=client.get('/api/tenders/one/model-analysis')
    assert response.status_code==200 and len(response.json()['detectors'])==4
    assert client.get('/api/tenders/missing/model-analysis').status_code==404
