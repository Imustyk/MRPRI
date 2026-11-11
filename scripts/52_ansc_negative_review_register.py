#!/usr/bin/env python3
"""Register explicitly confirmed MTA-0021 complaints and audit procedure labels.
Offline only. Existing MTA-0019 inputs and the blank evidence template are read-only.
No machine-predicted outcome is a source of human confirmation.
"""
from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime
import argparse,csv,gzip,hashlib,importlib.util,json,re
from pypdf import PdfReader
ROOT=Path(__file__).resolve().parents[1]
def read(path):
 with path.open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def file_identity(path,expected):
 if not path.is_file():return False,'original_missing'
 if not re.fullmatch('[0-9a-f]{64}',expected or ''):return False,'missing_or_invalid_sha256'
 return (True,'') if sha(path)==expected else (False,'sha256_mismatch')
def stable_csv(path,rows,fields=None):
 fields=fields or list(rows[0]);import io
 b=io.StringIO(newline='');w=csv.DictWriter(b,fieldnames=fields);w.writeheader();w.writerows(rows);data=b.getvalue().encode('utf-8')
 if path.exists():
  if path.read_bytes()!=data:raise ValueError('refuse to change existing registration: '+str(path))
 else:path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
def stable_json(path,value):
 data=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
 if path.exists():
  if path.read_bytes()!=data:raise ValueError('refuse to change existing audit: '+str(path))
 else:path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
def walk_urls(value):
 if isinstance(value,dict):
  if value.get('url'):yield value['url']
  for v in value.values():yield from walk_urls(v)
 elif isinstance(value,list):
  for v in value:yield from walk_urls(v)
def fold_procedures(rows,old_identifiers=None):
 """Pure fail-closed gate. Duplicate identical complaints count once.
 Conflicting, unknown, unlinked, unverified, overlapping and incomplete cases
 never receive a scalar endpoint. No class is inferred from absence of evidence.
 """
 old_identifiers=old_identifiers or {};unique={};conflicted=set()
 for row in rows:
  key=(row['decision_id'],row['complaint_id'])
  if key in unique and unique[key]!=row:
   conflicted.update([row['ocid'],unique[key]['ocid']])
  else:unique[key]=row
 complaint_owners=defaultdict(set)
 for row in unique.values():complaint_owners[row['complaint_id']].add((row['decision_id'],row['ocid']))
 shared_cids={cid for cid,owners in complaint_owners.items() if len(owners)>1}
 groups=defaultdict(list)
 for row in unique.values():groups[row['ocid']].append(row)
 accepted=[];audit=[]
 for ocid,rs in sorted(groups.items()):
  reasons=[]
  if any(x['complaint_id'] in shared_cids for x in rs):reasons.append('complaint_identity_shared_across_decisions_or_procedures')
  if ocid in conflicted:reasons.append('conflicting_duplicate_complaint')
  if len({x['decision_id'] for x in rs})!=1:reasons.append('additional_decisions_require_adjudication')
  if len({x['document_sha256'] for x in rs})!=1:reasons.append('multiple_pdf_identity_requires_adjudication')
  if {x['reviewer_outcome'] for x in rs}!={'rejected'}:reasons.append('unknown_or_conflicting_outcomes_require_adjudication')
  for x in rs:
   if x.get('verified_ocid')!=ocid:reasons.append('OCID_conflicts_with_primary_verification')
   try:datetime.strptime(x.get('reviewer_decision_date',''),'%Y-%m-%d')
   except ValueError:reasons.append('verified_decision_date_missing')
   if x.get('reviewer_document_type')!='ansc_decision':reasons.append('not_verified_ANSC_decision')
   if x.get('reviewer_link_verified')!='confirmed':reasons.append('OCID_not_confirmed')
   if not re.fullmatch('[0-9a-f]{64}',x.get('document_sha256','')) or x.get('technical_verified')!='1':reasons.append('identity_or_technical_verification_failed')
   if x.get('all_complaints_accounted')!='1':reasons.append('additional_or_unverified_complaints')
   if x.get('review_status')!='confirmed':reasons.append('complaint_not_human_confirmed')
   for key,field in [('hashes','document_sha256'),('decisions','decision_id'),('complaints','complaint_id'),('ocids','ocid')]:
    if x[field] in old_identifiers.get(key,set()):reasons.append('overlap_with_MTA0019_'+key)
   md=re.search(r'MD-(\d+)',ocid)
   if not md:reasons.append('invalid_canonical_OCID')
   elif md.group(1) in old_identifiers.get('procedure_digits',set()):reasons.append('possible_canonical_overlap_with_MTA0019')
  reasons=sorted(set(reasons));base={'ocid':ocid,'reviewed_complaint':1,'n_complaints':len(rs),'confirmed_procedure_label':int(not reasons),'block_reasons':';'.join(reasons)};audit.append(base)
  if not reasons:
   x=rs[0];accepted.append({'ocid':ocid,'canonical_ocid':ocid,'decision_id':x['decision_id'],'complaint_ids':';'.join(sorted(y['complaint_id'] for y in rs)),'n_complaints':len(rs),'document_sha256':x['document_sha256'],'document_url':x['document_url'],'ansc_upheld':0,'decision_date':x['reviewer_decision_date'],'review_type':x['review_type'],'confirmation_source':x['confirmation_source'],'source_dataset':'MTA-0021_negative_review'})
 return accepted,audit

def technical_document(r,items,blind,inventory,features,parser):
 x=items[0];did=x['decision_id'];ocid=x['ocid_candidate'];p=Path(x['local_pdf']);reasons=[];ok,reason=file_identity(p,x['document_sha256']);proof={'decision_id':did,'ocid':ocid,'document_sha256':x['document_sha256'],'original_path':str(p),'sha256_verified':int(ok),'decision_date_verified':0,'source_header_identity_verified':0,'own_MD_header':'','own_MD_resolution':'','raw_link_verified':0,'buyer_id_verified':0,'exact_join_available':int(ocid in features),'all_complaints_accounted':0,'publication_features_certified':0,'eligible_for_temporal_test':0}
 proof.update(pdf_pages='',verified_decision_date='',raw_package='',raw_package_sha256='',raw_compiled_records='',document_container_ocid='',raw_parent_relationship=0,buyer_id='',inventory_PDF_hashes=0,own_decision_ids_in_local_procedure_docs='',embedded_timestamped_release_payloads=0,publication_date='',publication_date_source='features.csv metadata, not original notice snapshot',test_period='unknown',historical_limitations='publication_values_not_certified')
 if not ok:return proof,[reason],''
 if not all(x[k]==blind[did][b] for k,b in [('document_sha256','sha256'),('ocid_candidate','ocid'),('document_url','document_url')]):reasons.append('identity_manifest_conflict')
 pages=[z.extract_text() or '' for z in PdfReader(p).pages];N=len(pages);proof['pdf_pages']=N
 head=' '.join(pages[0].split());tail='\n'.join(pages[-3:]);n=parser.norm(tail);anchors=list(parser.OPERATIVE.finditer(n));resolution=tail[anchors[-1].end():] if anchors else '';resolution=' '.join(re.sub(r'^\s*\d+\s*$','',resolution,flags=re.M).split());quote=resolution.split('Decizia ')[0].strip()
 parsed=parser.parse(pages);date=''
 try:date=datetime.strptime(parsed.get('decision_date',''),'%d.%m.%Y').date().isoformat()
 except ValueError:pass
 proof['decision_date_verified']=int(bool(date) and all(date==z['expected_decision_date'] for z in items));proof['verified_decision_date']=date if proof['decision_date_verified'] else ''
 if not proof['decision_date_verified']:reasons.append('decision_date_conflict')
 proof['source_header_identity_verified']=int(parsed.get('decision_id')==did and 'agentia nationala' in parser.norm(head))
 if not proof['source_header_identity_verified']:reasons.append('decision_header_conflict')
 expected={z['complaint_id'] for z in items};found=set(a for a,b in parsed.get('complaints',[]));outcomes={b for a,b in parsed.get('complaints',[])}
 accounted=found==expected and outcomes=={'rejected'} and all(cid in re.sub(r'\s','',head) for cid in expected)
 if not accounted:reasons.append('operative_complaint_or_outcome_conflict')
 first=min(int(z['evidence_pages'].split('-')[0]) for z in items);last=max(int(z['evidence_pages'].split('-')[-1]) for z in items)
 # Explicit source-page assertion, independent of combined-pack numbering.
 selected='\n'.join(pages[first-1:last]);source_resolution=bool(parser.OPERATIVE.search(parser.norm(selected))) or bool(parser.FORM.search(parser.norm(selected)))
 if not source_resolution or not all(cid in re.sub(r'\s','',selected) for cid in expected):reasons.append('evidence_page_conflict')
 digits=re.search(r'MD-(\d+)',ocid).group(1)
 ownh=bool(re.search(r'MD\s*-\s*'+digits+r'\b',head));ownr=bool(re.search(r'MD\s*-\s*'+digits+r'\b',resolution));proof['own_MD_header']='MD-'+digits if ownh else '';proof['own_MD_resolution']='MD-'+digits if ownr else ''
 if not ownh or not ownr:reasons.append('OCID_document_number_conflict')
 raw=r/'data/raw/ocds_packages'/(ocid+'.json.gz');proof['raw_package']=str(raw);proof['raw_package_sha256']=sha(raw) if raw.exists() else '';rawbase=None;bid='';linked=False;histories=0
 if raw.exists():
  try:
   package=json.load(gzip.open(raw,'rt'));records=[a.get('compiledRelease',{}) for a in package.get('records',[])];base=[a for a in records if a.get('ocid')==ocid];rawbase=base[0] if len(base)==1 else None;proof['raw_compiled_records']=len(records)
   for c in records:
    direct=c.get('ocid')==ocid;parent=any(z.get('identifier')==ocid and 'parent' in z.get('relationship',[]) for z in c.get('relatedProcesses',[]))
    if x['document_url'] in set(walk_urls(c)) and (direct or parent):linked=True;proof['document_container_ocid']=c.get('ocid','');proof['raw_parent_relationship']=int(parent)
   bid=(rawbase or {}).get('tender',{}).get('procuringEntity',{}).get('id','')
   for rec in package.get('records',[]):
    histories+=sum(isinstance(a,dict) and bool(a.get('date')) and bool(a.get('tender')) for a in (rec.get('releases') or []))
   histories+=sum(isinstance(a,dict) and bool(a.get('date')) and bool(a.get('tender')) for a in (package.get('releases') or []))
  except (OSError,ValueError):reasons.append('raw_package_unreadable')
 if not rawbase or not linked:reasons.append('raw_OCID_URL_link_not_proven')
 proof['raw_link_verified']=int(bool(rawbase) and linked and ownh and ownr)
 buyer_digits=re.sub(r'\D','',bid);buyer_match=bool(buyer_digits) and buyer_digits in re.sub(r'\s','',head)
 f=features.get(ocid,{})
 if f and bid!=f.get('buyer_id'):buyer_match=False
 proof['buyer_id_verified']=int(buyer_match);proof['buyer_id']=bid
 if not buyer_match:reasons.append('buyer_identifier_conflict')
 sibling_hashes=set();sibling_own=set();sibling_complaints=set();unresolved=False
 sandbox=p.parent
 for other in inventory:
  if other['ocid']!=ocid:continue
  op=sandbox/(hashlib.sha1(other['url'].encode()).hexdigest()[:16]+'.pdf')
  if not op.exists():unresolved=True;continue
  oh=sha(op)
  if oh in sibling_hashes:continue
  sibling_hashes.add(oh);pr=parser.parse([a.extract_text() or '' for a in PdfReader(op).pages])
  if pr.get('decision_id'):sibling_own.add(pr['decision_id'])
  if pr.get('reason')=='candidate':sibling_complaints.update(a for a,b in pr['complaints'])
  elif pr.get('decision_id'):unresolved=True
 if sibling_own!={did} or sibling_complaints!=expected or unresolved:accounted=False;reasons.append('additional_or_unresolved_local_decisions')
 proof['inventory_PDF_hashes']=len(sibling_hashes);proof['own_decision_ids_in_local_procedure_docs']=';'.join(sorted(sibling_own));proof['all_complaints_accounted']=int(accounted);proof['embedded_timestamped_release_payloads']=histories;proof['publication_date']=f.get('published_date','');proof['publication_date_source']='features.csv metadata, not original notice snapshot';proof['test_period']='TEST_2022_2024' if proof['publication_date'][:4] in ['2022','2023','2024'] else 'outside_TEST_or_unknown';proof['historical_limitations']='compiled_snapshot_only;publication_values_not_certified'
 return proof,sorted(set(reasons)),quote

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=ROOT);ap.add_argument('--out-root',type=Path);ap.add_argument('--confirmation',type=Path);args=ap.parse_args();r=args.root;o=args.out_root or r
 ledger=json.loads((args.confirmation or r/'data/external/ansc_mta0021_negative_confirmation.json').read_text());assert ledger['review_type']=='targeted_assisted_review';items=ledger['records'];assert len(items)==8 and all(x['confirmed_outcome']=='rejected' for x in items)
 pack=r/'results/ansc_review_pages/MTA-0021_negative_candidates_evidence_pack.pdf';assert sha(pack)==ledger['evidence_pack_sha256'],'evidence pack changed'
 blind={x['decision_id']:x for x in read(r/'results/tables/ansc_mta0021_blind_identity.csv')};inventory=read(r/'results/tables/ansc_decision_inventory.csv');features={x['ocid']:x for x in read(r/'data/features/features.csv')}
 spec=importlib.util.spec_from_file_location('screen',r/'scripts/51_ansc_validation_recovery.py');parser=importlib.util.module_from_spec(spec);spec.loader.exec_module(parser)
 assert len({(x['decision_id'],x['complaint_id']) for x in items})==8 and len({x['complaint_id'] for x in items})==8,'duplicate confirmation records'
 bydid=defaultdict(list)
 for x in items:bydid[x['decision_id']].append(x)
 rows=[];proofs=[]
 for did,xs in bydid.items():
  proof,reasons,quote=technical_document(r,xs,blind,inventory,features,parser);proof['technical_block_reasons']=';'.join(reasons);proof['technical_verified']=int(not reasons);proofs.append(proof)
  for x in xs:
   rows.append({'decision_id':did,'ocid':x['ocid_candidate'],'document_sha256':x['document_sha256'],'complaint_id':x['complaint_id'],'reviewer_document_type':'ansc_decision' if proof['source_header_identity_verified'] else 'uncertain','reviewer_outcome':x['confirmed_outcome'],'reviewer_link_verified':'confirmed' if proof['raw_link_verified'] and proof['buyer_id_verified'] and not reasons else 'uncertain','reviewer_decision_date':proof.get('verified_decision_date',''),'reviewer_evidence_page':x['evidence_pages'].split('-')[0],'reviewer_notes':'Human-confirmed complaint outcome; original source pages '+x['evidence_pages']+'. Technical identity/date/link verified separately. Whitespace and standalone folio numbers removed for cross-page quotation. '+(';'.join(reasons) or 'No blocking discrepancy in bounded local records.'),'document_url':x['document_url'],'local_pdf_path':x['local_pdf'],'reviewer_evidence_quote':quote,'review_status':'confirmed','review_type':ledger['review_type'],'confirmation_source':ledger['confirmation_source'],'confirmation_sha256':ledger['confirmation_sha256'],'evidence_pack_sha256':ledger['evidence_pack_sha256'],'verified_ocid':proof['ocid'] if proof['raw_link_verified'] and proof['buyer_id_verified'] else '', 'technical_verified':str(int(not reasons)),'all_complaints_accounted':str(proof['all_complaints_accounted'])})
 old=read(r/'data/external/ansc_manual_review_50.csv');oldc=read(r/'data/external/ansc_complaint_level_review.csv');oldid={'hashes':{sha(Path(x['local_pdf_path'])) for x in old},'decisions':set(z.upper() for x in old for z in re.findall(r'03D-\d+-\d{2}',x['decision_id'],re.I)),'complaints':{x['complaint_id'] for x in oldc},'ocids':{x['ocid'] for x in old},'procedure_digits':{re.search(r'MD-(\d+)',x['ocid']).group(1) for x in old}}
 procedures,fold_audit=fold_procedures(rows,oldid);pb={x['ocid']:x for x in proofs};audits=[]
 for a in fold_audit:
  p=pb[a['ocid']];audits.append(dict(p,**a,review_type=ledger['review_type']))
 for x in procedures:
  p=pb[x['ocid']];x.update(publication_date=p['publication_date'],publication_date_source=p['publication_date_source'],buyer_id=p['buyer_id'],reviewed_complaint=1,confirmed_procedure_label=1,exact_join_available=p['exact_join_available'],publication_features_certified=0,eligible_for_temporal_test=0)
 complaints=[]
 for x in rows:
  complaints.append({'ocid':x['ocid'],'decision_id':x['decision_id'],'document_url':x['document_url'],'complaint_id':x['complaint_id'],'complaint_outcome':x['reviewer_outcome'],'complaint_evidence_page':x['reviewer_evidence_page'],'complaint_evidence_quote':x['reviewer_evidence_quote'],'link_status':x['reviewer_link_verified'],'review_status':x['review_status'],'reviewer_complaint_outcome':x['reviewer_outcome'],'notes':x['reviewer_notes'],'document_sha256':x['document_sha256'],'verified_decision_date':x['reviewer_decision_date'],'review_type':x['review_type'],'confirmation_source':x['confirmation_source'],'confirmation_sha256':x['confirmation_sha256'],'evidence_pack_sha256':x['evidence_pack_sha256']})
 stable_csv(o/'data/external/ansc_mta0021_negative_review.csv',rows);stable_csv(o/'data/external/ansc_mta0021_complaint_level_review.csv',complaints)
 if procedures:stable_csv(o/'results/tables/ansc_mta0021_verified_procedures.csv',procedures)
 stable_csv(o/'results/tables/ansc_mta0021_label_audit.csv',audits)
 # Preserve the old document-label endpoint and source identifiers as-is.
 combined=[];old_export=read(r/'data/external/ansc_upheld_labels.csv');oldbyocid=defaultdict(list)
 for x in old_export:
  if x['ansc_upheld'] in ['0','1']:oldbyocid[x['ocid']].append(x)
 for ocid,xs in sorted(oldbyocid.items()):
  assert len({x['ansc_upheld'] for x in xs})==1,'conflicting old label'
  x=xs[0];f=features.get(ocid,{});strict=any(c['ocid']==ocid and c['review_status']=='confirmed' and c['reviewer_complaint_outcome'] in ['admitted','partially_admitted','rejected'] for c in oldc)
  combined.append({'ocid':ocid,'ansc_upheld':x['ansc_upheld'],'source_dataset':'MTA-0019','source_decision_id':x['decision_id'],'n_source_URL_rows':len(xs),'n_complaints':sum(c['ocid']==ocid for c in oldc),'complaint_confirmed':int(strict),'review_type':'human_confirmed_assisted_review','exact_join_available':int(bool(f)),'publication_date':f.get('published_date',''),'buyer_id':f.get('buyer_id',''),'publication_features_certified':0,'eligible_for_temporal_test':0,'canonical_status':'PN_alias_unapplied' if '-PN-' in ocid else 'source_OCID_unchanged'})
 for x in procedures:combined.append({'ocid':x['ocid'],'ansc_upheld':'0','source_dataset':'MTA-0021','source_decision_id':x['decision_id'],'n_source_URL_rows':1,'n_complaints':x['n_complaints'],'complaint_confirmed':1,'review_type':x['review_type'],'exact_join_available':x['exact_join_available'],'publication_date':x['publication_date'],'buyer_id':x['buyer_id'],'publication_features_certified':0,'eligible_for_temporal_test':0,'canonical_status':'exact_raw_parent_and_feature_OCID'})
 stable_csv(o/'results/tables/ansc_mta0021_combined_procedure_labels.csv',combined)
 test=[x for x in combined if x['publication_date'][:4] in ['2022','2023','2024']];summary={'candidate_pool':26,'documents_reviewed':len(proofs),'human_complaints':len(rows),'sha256_verified':sum(x['sha256_verified'] for x in proofs),'dates_verified':sum(x['decision_date_verified'] for x in proofs),'OCID_confirmed':sum(x['reviewer_link_verified']=='confirmed' for x in rows),'confirmed_OCID_procedures':len(procedures),'new_negative_procedures':len(procedures),'new_exact_join':sum(x['exact_join_available'] for x in procedures),'publication_features_certified':0,'temporal_test_eligible':0,'combined_document_labels':dict(Counter(x['ansc_upheld'] for x in combined)),'combined_strict_labels':dict(Counter(x['ansc_upheld'] for x in combined if x['complaint_confirmed'])),'combined_exact_join_labels':dict(Counter(x['ansc_upheld'] for x in combined if x['exact_join_available'])),'TEST_metadata_classes':dict(Counter(x['ansc_upheld'] for x in test)),'TEST_buyers':len({x['buyer_id'] for x in test if x['buyer_id']}),'TEST_years':{year:dict(Counter(x['ansc_upheld'] for x in test if x['publication_date'][:4]==year)) for year in ['2022','2023','2024']},'TEST_after_publication_certification':{'positive':0,'negative':0},'decision':'NO-GO','review_type':'targeted_assisted_review','blocked_procedures':sum(not x['confirmed_procedure_label'] for x in fold_audit),'overlap_with_MTA0019':False if not any('overlap' in x['block_reasons'] for x in fold_audit) else True,'scope_limit':'Only six authorized documents and their local procedure records; no other positive candidates or 546-PDF backlog processed.'}
 stable_json(o/'results/methodology/ansc_mta0021_negative_review_audit.json',summary);print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
