#!/usr/bin/env python3
"""Read-only final ANSC audit; writes derived tables only, never reviewer data.
Run after scripts 46 validate, 45 and 47. No model fitting or comparison.
"""
from pathlib import Path
import argparse,csv,hashlib,json,importlib.util,math,collections,sys
ROOT=Path(__file__).resolve().parents[1]
def read(p):
 with p.open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))
def write(p,rows):
 with p.open('w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def load(name):
 s=importlib.util.spec_from_file_location('audit_'+name[:2],ROOT/'scripts'/name);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=ROOT);ap.add_argument('--out',type=Path);args=ap.parse_args();global_root=args.root
 # Explicit root supports auditing a checkout while keeping outputs elsewhere.
 r=global_root;o=args.out or r/'results/tables';o.mkdir(parents=True,exist_ok=True)
 rows=read(r/'data/external/ansc_manual_review_50.csv');pilot=read(r/'data/external/ansc_manual_review_pilot10.csv');cs=read(r/'data/external/ansc_complaint_level_review.csv')
 assert len(rows)==50 and all(all(x[k] for k in ['reviewer_outcome','reviewer_document_type','reviewer_link_verified']) for x in rows)
 bykey={(x['ocid'],x['document_url']):x for x in rows};assert len(bykey)==50
 for p in pilot:
  x=bykey[(p['ocid'],p['document_url'])];assert all(p[k]==x[k] for k in p if k.startswith('reviewer_'))
 groups={}
 for i,x in enumerate(rows,1):groups.setdefault(hashlib.sha256(Path(x['local_pdf_path']).read_bytes()).hexdigest(),[]).append(i)
 unique=[rows[g[0]-1] for g in groups.values()];repindex={id(rows[g[0]-1]):g[0] for g in groups.values()}
 duplicate_rows=[{'sha256':h,'row_indexes':','.join(map(str,g)),'n_urls':len(g),'ocid':rows[g[0]-1]['ocid']} for h,g in groups.items() if len(g)>1];write(o/'ansc_final_duplicates.csv',duplicate_rows)
 # Load existing label rule with checkout-independent import.
 spec=importlib.util.spec_from_file_location('audit_labels',r/'scripts/47_ansc_upheld_labels.py');labels=importlib.util.module_from_spec(spec);spec.loader.exec_module(labels)
 doc=[x for x in unique if x['reviewer_document_type']=='ansc_decision'];merits=[x for x in doc if x['reviewer_outcome'] in ['admitted','partially_admitted','rejected'] or x['reviewer_notes'].startswith('multiple:')];linked=[x for x in merits if x['reviewer_link_verified']=='confirmed']
 c_by_ocid=collections.defaultdict(list)
 for c in cs:c_by_ocid[c['ocid']].append(c)
 consistent=[];pending=[]
 for x in linked:
  associated=c_by_ocid[x['ocid']]
  valid=[c for c in associated if c['review_status']=='confirmed' and c['link_status']=='confirmed' and c['reviewer_complaint_outcome'] in ['admitted','partially_admitted','rejected']]
  if valid and (x['reviewer_outcome']=='unknown' or all(c['reviewer_complaint_outcome']==x['reviewer_outcome'] for c in valid)):consistent.append(x)
  else:pending.append(repindex[id(x)])
 complaint_binary=[c for x in consistent for c in c_by_ocid[x['ocid']] if c['review_status']=='confirmed' and c['link_status']=='confirmed' and c['reviewer_complaint_outcome'] in ['admitted','partially_admitted','rejected']]
 document_binary=[x for x in unique if labels.derive_label(x)[0] is not None];strict=[x for x in consistent if labels.derive_label(x)[0] is not None]
 features={x['ocid']:x for x in read(r/'data/features/features.csv')}
 outcomes=read(r/'results/tables/ansc_outcomes.csv');dates={x['url']:x['decision_date'] for x in outcomes}
 audit=[]
 for x in document_binary:
  f=features.get(x['ocid'],{});audit.append({'row_index':repindex[id(x)],'ocid':x['ocid'],'label':labels.derive_label(x)[0],'complaint_confirmed':int(x in strict),'feature_join':int(bool(f)),'buyer_id':f.get('buyer_id',''),'published_date':f.get('published_date',''),'procurement_method':f.get('procurement_method',''),'procurement_method_details':f.get('procurement_method_details',''),'n_bidders':f.get('n_bidders',''),'decision_date_extractor_unverified':dates.get(x['document_url'],''),'temporal_certified':0})
 write(o/'ansc_final_label_audit.csv',audit)
 funnel=[(1,'Reviewed URL rows',len(rows),'unit=URL; all reviewer enum fields filled'),(2,'Unique PDFs',len(unique),'unit=SHA-256 PDF; remove six repeated URLs'),(3,'ANSC documents',len(doc),'exclude other_document'),(4,'Final merits documents including multi-complaint',len(merits),'exclude interim suspension, not an upheld outcome'),(5,'Final documents with confirmed OCID link',len(linked),'exclude uncertain row 3'),(6,'Documents with confirmed complaint outcomes',len(consistent),'pending complaint records at rows '+str(pending)),(7,'Binary complaint records',len(complaint_binary),'UNIT CHANGE: complaints; retain separate outcomes, never independent procedures'),(8,'Unique procedures with one allowed scalar label (strict)',len(strict),'exclude two multi-complaint PDFs, no forced document label'),(9,'Strict procedures with certified full point-in-time model features',0,'full historical feature snapshot not temporally certified; corpus/future-event features'),(10,'Procedures eligible for formal independent temporal model comparison',0,'no certified holdout, sparse classes, selection bias')]
 write(o/'ansc_final_funnel.csv',[{'step':a,'stage':b,'n':c,'explanation':d} for a,b,c,d in funnel])
 metrics=json.loads((r/'results/methodology/ansc_review_metrics.json').read_text())['metrics'];assert metrics['n_labeled']==len(unique)
 machine=read(r/'data/external/ansc_review_sample_50.csv');joined=[]
 for g in groups.values():
  i=g[0]-1;x=dict(machine[i]);assert x['document_url']==rows[i]['document_url'];x.update({k:v for k,v in rows[i].items() if k.startswith('reviewer_')});joined.append(x)
 merits_scalar=[x for x in joined if x['reviewer_document_type']=='ansc_decision' and x['reviewer_link_verified']=='confirmed' and x['reviewer_outcome'] in ['admitted','partially_admitted','rejected']]
 correct=sum(x['reviewer_outcome']==x['extracted_outcome'] for x in merits_scalar)
 def count(xs,key):return dict(collections.Counter(x[key] for x in xs))
 data={'reviewed_urls':50,'unique_pdfs':len(unique),'unique_ocids':len({x['ocid'] for x in rows}),'complaint_records':len(cs),'unique_complaint_ids':len({c['complaint_id'] for c in cs}),'confirmed_complaints':sum(c['review_status']=='confirmed' for c in cs),'preliminary_complaints':sum(c['review_status']!='confirmed' for c in cs),'doc_types_unique':count(unique,'reviewer_document_type'),'links_url':count(rows,'reviewer_link_verified'),'links_unique':count(unique,'reviewer_link_verified'),'uncertain_rows':[i for i,x in enumerate(rows,1) if x['reviewer_link_verified']=='uncertain'],'document_binary_n':len(document_binary),'document_binary_labels':dict(collections.Counter(labels.derive_label(x)[0] for x in document_binary)),'strict_binary_n':len(strict),'strict_binary_labels':dict(collections.Counter(labels.derive_label(x)[0] for x in strict)),'confirmed_binary_complaints':len(complaint_binary),'binary_complaint_labels':dict(collections.Counter(1 if c['reviewer_complaint_outcome']!='rejected' else 0 for c in complaint_binary)),'pending_merits_complaint_rows':pending,'unique_exclusion_reasons':dict(collections.Counter(labels.derive_label(x)[1] for x in unique if labels.derive_label(x)[0] is None)),'feature_join_n':sum(a['feature_join'] for a in audit),'methods_details_document_binary':count(audit,'procurement_method_details'),'competitive_ge2':sum(a['feature_join'] and float(a['n_bidders'] or 0)>=2 for a in audit),'single_bidder':sum(a['feature_join'] and float(a['n_bidders'] or 0)==1 for a in audit),'no_bidder_data':sum(a['feature_join'] and float(a['n_bidders'] or 0)==0 for a in audit),'test_labels_document_binary':dict(collections.Counter(a['label'] for a in audit if a['published_date'][:4] in ['2022','2023','2024'])),'buyers_document_binary':len({a['buyer_id'] for a in audit if a['buyer_id']}),'buyers_strict':len({a['buyer_id'] for a in audit if a['buyer_id'] and a['complaint_confirmed']}),'years_document_binary':dict(collections.Counter(a['published_date'][:4] or 'missing' for a in audit)),'methods_document_binary':count(audit,'procurement_method'),'strict_years':dict(collections.Counter(a['published_date'][:4] or 'missing' for a in audit if a['complaint_confirmed'])),'raw_dates_present_binary':sum(bool(a['decision_date_extractor_unverified']) for a in audit),'full_feature_temporal_certified':0,'merits_scalar_extraction_correct':correct,'merits_scalar_extraction_n':len(merits_scalar),'funnel':funnel,'decision':'NO-GO for formal MTA-0020; descriptive audit only','metric_snapshot':metrics,'source_sha256':{p:hashlib.sha256((r/p).read_bytes()).hexdigest() for p in ['data/external/ansc_manual_review_50.csv','data/external/ansc_manual_review_pilot10.csv','data/external/ansc_complaint_level_review.csv','data/external/ansc_review_sample_50.csv','data/features/features.csv']}}
 (o/'ansc_final_audit.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in data.items() if k not in ['metric_snapshot','source_sha256','funnel']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
