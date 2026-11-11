#!/usr/bin/env python3
"""Offline MTA-0022 source audit; never modifies features, labels or ETL.
Reads archived BSON directly, without a MongoDB connection or model imports.
"""
from pathlib import Path
from datetime import datetime
from collections import Counter,defaultdict
import argparse,csv,gzip,hashlib,json,re,sqlite3,sys,zipfile
from bson import decode_file_iter
ROOT=Path(__file__).resolve().parents[1]
PUB=['bid_window_days','short_deadline','long_deadline','accelerated_like']
SOURCE_FIELDS=['ocid','fetched_at','list_date','record_fetched','n_records','published_date','tender_start','tender_end','procurement_method','procurement_method_details','release_dates','release_tags','run_id']
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def readcsv(p):
 with p.open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))
def writecsv(p,rows):
 with p.open('w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)
def dt(x):
 try:
  value=datetime.fromisoformat(x.replace('Z','+00:00'))
  return value if value.tzinfo is not None else None
 except (TypeError,ValueError,AttributeError):return None
def publication_gate(e):
 """Evidence flags require verified publisher/version provenance, not date alone."""
 reasons=[]
 if e.get('source_kind')!='initial_notice_release':reasons.append('not_original_notice_payload')
 for key in ['initial_notice_identity_confirmed','timestamp_immutability_verified','complete_initial_payload']:
  if e.get(key) is not True:reasons.append(key+'_not_proven')
 if not dt(e.get('t0')) or not dt(e.get('published_at')):reasons.append('publication_timestamp_not_verified')
 elif dt(e['published_at'])>dt(e['t0']):reasons.append('source_after_t0')
 fields=e.get('fields',{})
 for name in ['startDate','endDate','procurementMethod','procurementMethodDetails']:
  if not fields.get(name):reasons.append('missing_initial_'+name)
 return ('NOT CERTIFIED',reasons) if reasons else ('HISTORICALLY_CERTIFIED',[])
def iter_json_array(p):
 decoder=json.JSONDecoder();buffer='';started=False;eof=False
 with p.open(encoding='utf-8') as f:
  while True:
   if not eof and len(buffer)<65536:
    chunk=f.read(65536);eof=not chunk;buffer+=chunk
   buffer=buffer.lstrip()
   if not started:
    if not buffer.startswith('['):raise ValueError('expected JSON array')
    buffer=buffer[1:];started=True;continue
   buffer=buffer.lstrip(' ,\r\n\t')
   if buffer.startswith(']'):return
   if not buffer and eof:raise ValueError('truncated JSON array')
   try:value,end=decoder.raw_decode(buffer)
   except json.JSONDecodeError:
    if eof:raise
    chunk=f.read(65536);eof=not chunk;buffer+=chunk;continue
   yield value;buffer=buffer[end:]
def walk(value,path=''):
 if isinstance(value,dict):
  yield path,value
  for k,v in value.items():yield from walk(v,path+'/'+str(k))
 elif isinstance(value,list):
  for i,v in enumerate(value):yield from walk(v,path+'/'+str(i))
def embedded_payloads(q):
 return [(p,x) for p,x in walk(q) if re.search(r'/releases/\d+$',p) and isinstance(x.get('tender'),dict) and x.get('date') and x.get('tag') and 'compiled' not in x['tag']]
def modern_period_trace(q,merged):
 pn=next((x['compiledRelease'] for x in q.get('records',[]) if '-PN-' in x.get('compiledRelease',{}).get('ocid','')),{});ev=next((x['compiledRelease'] for x in q.get('records',[]) if '-EV-' in x.get('compiledRelease',{}).get('ocid','')),{});pp=pn.get('tender',{}).get('tenderPeriod',{});ep=ev.get('tender',{}).get('tenderPeriod',{});mp=merged.get('tender',{}).get('tenderPeriod',{})
 hybrid=bool(pp.get('startDate') and ep.get('startDate') and pp['startDate']!=ep['startDate'] and mp.get('startDate')==pp['startDate'] and mp.get('endDate')==ep.get('endDate'))
 end,start=dt(ep.get('endDate')),dt(ep.get('startDate'));window=(end-start).days if end and start else ''
 return pn,ev,hybrid,window

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=ROOT);ap.add_argument('--out',type=Path);args=ap.parse_args();r=args.root;o=args.out or r/'results/tables';o.mkdir(parents=True,exist_ok=True)
 sys.path.insert(0,str(r));from src.mtender.ocds import merge_compiled_releases
 from src.mtender.stage_features import FEATURE_AVAILABILITY,strict_stage_columns
 targets={x['ocid']:x for x in readcsv(r/'results/tables/ansc_mta0021_combined_procedure_labels.csv') if x['publication_date'][:4] in ['2022','2023','2024']};assert len(targets)==8 and Counter(x['ansc_upheld'] for x in targets.values())=={'1':2,'0':6}
 features={x['ocid']:x for x in readcsv(r/'data/features/features.csv') if x['ocid'] in targets};sources=[];dump_selected={};fingerprints={};evidence={}
 for folder in ['pre_rebuild','pre_audit']:
  d=r/'results/backup'/folder/'mtender'
  for coll in ['raw_releases','raw_tenders','norm_tenders','features_tenders','raw_lookups','ingest_runs','raw_mof_procedures']:
   p=d/(coll+'.bson')
   if not p.exists():continue
   n=0;selected=[];keys=set()
   with p.open('rb') as f:
    for row in decode_file_iter(f):
     n+=1;keys.update(row)
     if row.get('ocid') in targets:selected.append({k:row.get(k) for k in SOURCE_FIELDS if k in row})
   digest=sha(p);fingerprints[str(p.relative_to(r))]=digest;key=folder+'/'+coll;dump_selected[key]=selected
   sources.append({'source':str(p.relative_to(r)),'kind':'archived_BSON_projection_or_inventory','records':n,'TEST_matches':len(selected),'bytes':p.stat().st_size,'sha256':digest,'schema_keys':'|'.join(sorted(keys)),'initial_notice_certification':'NOT CERTIFIED'})
   print('read',key,'records',n,'TEST',len(selected),flush=True)
 archives=list((r/'data/raw/ocds_packages').glob('*.json.gz'))
 sources.append({'source':'data/raw/ocds_packages/*.json.gz','kind':'single_fetch_record_packages_compiled_not_version_history','records':len(archives),'TEST_matches':len(targets),'bytes':sum(p.stat().st_size for p in archives),'sha256':'target SHA-256 in history coverage and input fingerprints','schema_keys':'publishedDate|records.compiledRelease|actualReleases URI pointers','initial_notice_certification':'NOT CERTIFIED'})
 inventory=[]
 with (r/'data/raw/ocid_inventory.jsonl').open() as f:
  for line in f:
   x=json.loads(line)
   if x.get('ocid') in targets:inventory.append(x)
 sources.append({'source':'data/raw/ocid_inventory.jsonl','kind':'OCID_list_metadata','records':'','TEST_matches':len(inventory),'bytes':(r/'data/raw/ocid_inventory.jsonl').stat().st_size,'sha256':sha(r/'data/raw/ocid_inventory.jsonl'),'schema_keys':'ocid|list_date|fetched_at|source|run_id','initial_notice_certification':'NOT CERTIFIED'})
 processed={};count=0
 for x in iter_json_array(r/'data/processed/tenders.json'):
  count+=1
  if x.get('ocid') in targets:processed[x['ocid']]={k:x.get(k) for k in SOURCE_FIELDS if k in x}
 sources.append({'source':'data/processed/tenders.json','kind':'derived_export','records':count,'TEST_matches':len(processed),'bytes':(r/'data/processed/tenders.json').stat().st_size,'sha256':sha(r/'data/processed/tenders.json'),'schema_keys':'derived feature/source projection','initial_notice_certification':'NOT CERTIFIED'})
 sample_matches=0;sample_payloads=0;samplefiles=list((r/'data/raw/ocds_samples').glob('*.json'))+[r/'data/raw/sample_ocds.json',r/'data/raw/sample_ocds_live.json']
 for p in samplefiles:
  q=json.loads(p.read_text());sample_payloads+=len(embedded_payloads(q));sample_matches+=sum(x.get('ocid') in targets for path,x in walk(q))
 sources.append({'source':'data/raw/ocds_samples/*.json + sample_ocds*.json','kind':'API_sample_archives','records':len(samplefiles),'TEST_matches':sample_matches,'bytes':sum(p.stat().st_size for p in samplefiles),'sha256':'see per-file input fingerprints','schema_keys':'sample packages; no target matches','initial_notice_certification':'NOT CERTIFIED'})
 for p in samplefiles:fingerprints[str(p.relative_to(r))]=sha(p)
 con=sqlite3.connect('file:'+str(r/'data/workspace/workspace.db')+'?mode=ro',uri=True);schema=con.execute("SELECT name,sql FROM sqlite_master WHERE type='table'").fetchall();con.close()
 sources.append({'source':'data/workspace/workspace.db','kind':'read_only_SQLite_schema','records':len(schema),'TEST_matches':'not_history_store','bytes':(r/'data/workspace/workspace.db').stat().st_size,'sha256':sha(r/'data/workspace/workspace.db'),'schema_keys':'|'.join(x[0] for x in schema),'initial_notice_certification':'NOT CERTIFIED'})
 for p in sorted((r/'data/raw/opendata').glob('*.xlsx')):
  hits=set()
  with zipfile.ZipFile(p) as z:
   for name in z.namelist():
    if name.startswith('xl/') and name.endswith('.xml'):
     b=z.read(name)
     hits.update(ocid for ocid in targets if ocid.encode() in b)
  sources.append({'source':str(p.relative_to(r)),'kind':'MoF_monthly_reference_not_notice_history','records':'','TEST_matches':len(hits),'bytes':p.stat().st_size,'sha256':sha(p),'schema_keys':'XLSX XML exact OCID search','initial_notice_certification':'NOT CERTIFIED'})
 # Protected inputs: metadata outputs from earlier tasks are not rewritten.
 protected=[p for p in (r/'data/external').glob('ansc*.csv')]+[r/'data/features/features.csv',r/'results/tables/ansc_mta0021_combined_procedure_labels.csv']
 protected += [r/p for p in ['scripts/01a_scan_ocids.py','scripts/01b_fetch_records.py','scripts/02_normalize_mongo.py','scripts/03_features_mongo.py','scripts/04_export_snapshot.py','src/mtender/ocds.py','src/mtender/features.py','src/mtender/stage_features.py','tests/test_temporal_leakage.py']]
 for p in protected:fingerprints[str(p.relative_to(r))]=sha(p)
 old_dates={x['ocid']:x.get('decision_date','') for x in readcsv(r/'data/external/ansc_upheld_labels.csv') if x.get('ansc_upheld') in ['0','1']};new_dates={x['ocid']:x['decision_date'] for x in readcsv(r/'results/tables/ansc_mta0021_verified_procedures.csv')};sb=Path(json.loads((r/'results/methodology/ansc_decision_inventory.json').read_text())['sandbox_dir'])
 history=[];cert=[];notice_refs=[]
 for ocid,label in sorted(targets.items()):
  p=r/'data/raw/ocds_packages'/(ocid+'.json.gz');q=json.load(gzip.open(p,'rt'));digest=sha(p);fingerprints[str(p.relative_to(r))]=digest;merged=merge_compiled_releases(q);pn,ev,hybrid,ev_window=modern_period_trace(q,merged);t=merged.get('tender',{});f=features[ocid];payloads=embedded_payloads(q)
  initial=[x for path,x in payloads if any(tag in ['tender','tenderNotice'] for tag in x.get('tag',[]))];pub=q.get('publishedDate','');docs={};amendments=[];record_proofs=[]
  for index,record in enumerate(q.get('records',[])):
   cr=record.get('compiledRelease',{});record_proofs.append({'pointer':f'/records/{index}/compiledRelease','ocid':cr.get('ocid'),'id':cr.get('id'),'tag':cr.get('tag'),'date':cr.get('date'),'tenderPeriod':cr.get('tender',{}).get('tenderPeriod'),'procurementMethod':cr.get('tender',{}).get('procurementMethod'),'procurementMethodDetails':cr.get('tender',{}).get('procurementMethodDetails')})
   amendments += cr.get('tender',{}).get('amendments',[]) or []
  for path,x in walk(q):
   if x.get('url') and x.get('documentType'):docs[x['url']]=(path,x)
  notices=[]
  amendments=list({(a.get('id'),a.get('releaseID'),a.get('amendsReleaseID')):a for a in amendments}.values())
  for url,(path,x) in docs.items():
   if x.get('documentType') in ['tenderNotice','notice','contractNotice'] or any(word in (x.get('title') or '').lower() for word in ['anunt','anunț','anunţ']):
    cached=(sb/(hashlib.sha1(url.encode()).hexdigest()[:16]+'.pdf')).exists();z={'ocid':ocid,'pointer':path,'url':url,'title':x.get('title'),'datePublished':x.get('datePublished'),'dateModified':x.get('dateModified'),'local_cached_body':int(cached)};notices.append(z);notice_refs.append(z)
  raws=[x for x in dump_selected.get('pre_audit/raw_tenders',[]) if x['ocid']==ocid];raws_meta=[x for x in dump_selected.get('pre_audit/raw_releases',[]) if x['ocid']==ocid];fetched=raws[0].get('fetched_at','') if raws else '';listdate=raws_meta[0].get('list_date','') if raws_meta else ''
  date=new_dates.get(ocid) or old_dates.get(ocid,'')
  if date and not re.match(r'\d{4}-',date):date=datetime.strptime(date,'%d.%m.%Y').date().isoformat()
  event_dates=[a.get('date','') for rec in q.get('records',[]) for a in rec.get('compiledRelease',{}).get('awards',[]) if a.get('date')];evdate=ev.get('date','');later=bool(dt(evdate) and dt(date+'T00:00:00+00:00') and dt(evdate)>dt(date+'T00:00:00+00:00'))
  e={'source_kind':'compiled_snapshot','initial_notice_identity_confirmed':False,'timestamp_immutability_verified':False,'complete_initial_payload':False,'t0':None,'published_at':None,'fields':{}};status,reasons=publication_gate(e)
  h={'canonical_ocid':ocid,'label':label['ansc_upheld'],'source_dataset':label['source_dataset'],'initial_publication_date_verified':'','publication_date_candidate_package':pub,'notice_publication_candidate_metadata':min((x['datePublished'] for x in notices if x.get('datePublished')),default=''),'publication_timestamp_status':'NOT CERTIFIED','primary_initial_notice_payloads':len(initial),'embedded_versioned_release_payloads':len(payloads),'immutable_publication_timestamp_proven':0,'notice_document_references':len(notices),'notice_bodies_locally_cached':sum(x['local_cached_body'] for x in notices),'original_tender_start_verified':'','original_tender_end_verified':'','original_procurement_method_verified':'','original_procurement_method_details_verified':'','compiled_PN_start_snapshot':pn.get('tender',{}).get('tenderPeriod',{}).get('startDate',''),'compiled_EV_start_snapshot':ev.get('tender',{}).get('tenderPeriod',{}).get('startDate',''),'compiled_EV_end_snapshot':ev.get('tender',{}).get('tenderPeriod',{}).get('endDate',''),'compiled_method_snapshot':t.get('procurementMethod',''),'compiled_details_snapshot':t.get('procurementMethodDetails',''),'modern_export_window_diagnostic':f.get('bid_window_days',''),'modern_EV_window_diagnostic':ev_window,'ETL_mixed_PN_EV_period_detected':int(hybrid),'recorded_notice_amendments':len(amendments),'field_specific_change_history':'UNKNOWN','first_local_fetch_timestamp':fetched,'API_list_date_candidate_not_t0':listdate,'latest_EV_timestamp':evdate,'list_date_equals_EV_timestamp':int(listdate==evdate),'latest_EV_after_ANSC_decision':int(later),'ANSC_decision_date_existing_endpoint':date,'current_award_entry_dates':';'.join(sorted(set(event_dates))),'all_four_publication_features_status':status,'award_decision_snapshot_status':'NOT CERTIFIED','source_file':str(p),'source_sha256':digest,'source_pointers':'/publishedDate;/records/*/compiledRelease;/actualReleases','blocking_reasons':';'.join(reasons)};history.append(h)
  evidence[ocid]={'package_sha256':digest,'compiled_records':record_proofs,'notice_refs':notices,'amendment_refs':amendments,'dump_projections':{k:[v for v in ds if v.get('ocid')==ocid] for k,ds in dump_selected.items()},'derived_JSON_projection':processed.get(ocid),'record_package_is_not_release_history':True}
  for feature in PUB:
   meta=FEATURE_AVAILABILITY[feature];policy={'bid_window_days':'floor((end-start)/1 day), fill 30, clip [0,3650]','short_deadline':'int(0 <= window < 7), inherits filled window','long_deadline':'int(window > 90), inherits filled window','accelerated_like':'regex accelerated|urgent|exception (case-insensitive); missing/nonmatching -> 0'}[feature]
   cert.append({'canonical_ocid':ocid,'feature':feature,'prediction_stage':'publication','stage_eligible':int(feature in strict_stage_columns('publication')),'stage_status':'STAGE_ELIGIBLE','historical_status':status,'certified_value':'','primary_inputs':'|'.join(meta['inputs']),'required_availability':'first public contract notice t0, verified original version','calculation_and_missing_policy':policy,'observed_snapshot_value_do_not_use_at_t0':f.get(feature,''),'history_limitation':'unknown original period/method; no immutable original notice body','modern_period_merge_issue':int(hybrid) if feature!='accelerated_like' else 0,'source_file':str(p),'source_sha256':digest,'field_pointer':'/records/*/compiledRelease/tender/'+('procurementMethodDetails' if feature=='accelerated_like' else 'tenderPeriod'),'original_timestamp_proven':0})
 writecsv(o/'mta0022_test_history_coverage.csv',history);writecsv(o/'mta0022_feature_certification.csv',cert);writecsv(o/'mta0022_source_inventory.csv',sources)
 (o/'mta0022_source_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,default=str,indent=2)+'\n');(o/'mta0022_input_fingerprints.json').write_text(json.dumps(fingerprints,indent=2)+'\n')
 summary={'target_procedures':8,'classes':dict(Counter(x['ansc_upheld'] for x in targets.values())),'history_t0_certified':sum(x['all_four_publication_features_status']=='HISTORICALLY_CERTIFIED' for x in history),'certified_publication_feature_cells':sum(x['historical_status']=='HISTORICALLY_CERTIFIED' for x in cert),'publication_feature_cells':len(cert),'modern_PN_EV_hybrid_periods':sum(x['ETL_mixed_PN_EV_period_detected'] for x in history),'notice_amendment_procedures':sum(x['recorded_notice_amendments']>0 for x in history),'notice_references':len(notice_refs),'notice_bodies_locally_cached':sum(x['local_cached_body'] for x in notice_refs),'latest_EV_after_endpoint':sum(x['latest_EV_after_ANSC_decision'] for x in history),'award_decision_certified':0,'decision':'NO-GO; no automatic stage switch','bson_sources_read':len(dump_selected),'source_rows':len(sources),'sample_target_matches':sample_matches}
 (o/'mta0022_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
