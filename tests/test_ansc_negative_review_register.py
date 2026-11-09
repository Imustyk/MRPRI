from pathlib import Path
import importlib.util,csv,hashlib
import pytest
p=Path(__file__).with_name('52_ansc_negative_review_register.py')
if not p.exists():p=Path(__file__).resolve().parents[1]/'scripts/52_ansc_negative_review_register.py'
s=importlib.util.spec_from_file_location('registration',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def row(cid='02/1/22'):
 return {'decision_id':'03D-1-22','complaint_id':cid,'ocid':'ocds-b3wdp1-MD-1640000000000','verified_ocid':'ocds-b3wdp1-MD-1640000000000','document_sha256':'a'*64,'reviewer_outcome':'rejected','reviewer_document_type':'ansc_decision','reviewer_link_verified':'confirmed','reviewer_decision_date':'2022-06-24','technical_verified':'1','all_complaints_accounted':'1','review_status':'confirmed','document_url':'local-identity','review_type':'targeted_assisted_review','confirmation_source':'explicit user'}
def test_two_complaints_one_procedure():
 out,a=m.fold_procedures([row(),row('02/2/22')]);assert len(out)==1 and out[0]['ansc_upheld']==0 and out[0]['n_complaints']==2
def test_duplicate_identical_complaint_not_counted_twice():
 out,_=m.fold_procedures([row(),row(),row('02/2/22')]);assert out[0]['n_complaints']==2
@pytest.mark.parametrize('field,value',[('reviewer_outcome','unknown'),('reviewer_link_verified','uncertain'),('document_sha256',''),('technical_verified','0'),('all_complaints_accounted','0'),('verified_ocid','ocds-b3wdp1-MD-1640000000999'),('reviewer_document_type','other_document'),('reviewer_decision_date','')])
def test_ineligible_record_never_exports_zero(field,value):
 x=row();x[field]=value;out,a=m.fold_procedures([x]);assert not out and a[0]['block_reasons']
def test_conflicting_outcomes_require_adjudication():
 x=row('02/2/22');x['reviewer_outcome']='admitted';assert not m.fold_procedures([row(),x])[0]
def test_duplicate_complaint_with_conflicting_ocid_blocks_both():
 x=row();x['ocid']=x['verified_ocid']='ocds-b3wdp1-MD-1640000000001';out,a=m.fold_procedures([row(),x]);assert not out and all('conflicting_duplicate_complaint' in x['block_reasons'] for x in a)
def test_additional_decision_requires_adjudication():
 x=row('02/2/22');x['decision_id']='03D-2-22';assert not m.fold_procedures([row(),x])[0]
@pytest.mark.parametrize('key,field',[('hashes','document_sha256'),('decisions','decision_id'),('complaints','complaint_id'),('ocids','ocid')])
def test_old_source_overlap_blocks_export(key,field):
 x=row();assert not m.fold_procedures([x],{key:{x[field]}})[0]
def test_possible_canonical_overlap_blocks_export():
 assert not m.fold_procedures([row()],{'procedure_digits':{'1640000000000'}})[0]
def test_original_file_hash_mismatch_missing_and_valid(tmp_path):
 p=tmp_path/'source.pdf';assert m.file_identity(p,'a'*64)[0] is False
 p.write_bytes(b'original bytes');assert m.file_identity(p,'a'*64)==(False,'sha256_mismatch');assert not m.file_identity(p,'')[0];assert m.file_identity(p,hashlib.sha256(p.read_bytes()).hexdigest())==(True,'')
def test_stable_registration_is_idempotent_and_refuses_silent_relabel(tmp_path):
 p=tmp_path/'human.csv';m.stable_csv(p,[row()]);before=p.read_bytes();m.stable_csv(p,[row()]);assert p.read_bytes()==before and len(list(csv.DictReader(p.open())))==1
 x=row();x['reviewer_outcome']='unknown'
 with pytest.raises(ValueError,match='refuse to change'):m.stable_csv(p,[x])
 assert p.read_bytes()==before

def test_same_complaint_under_other_decision_and_procedure_blocks_both():
 x=row();x['decision_id']='03D-2-22';x['ocid']=x['verified_ocid']='ocds-b3wdp1-MD-1640000000001'
 out,a=m.fold_procedures([row(),x]);assert not out and all('complaint_identity_shared' in z['block_reasons'] for z in a)
