#!/usr/bin/env python3
"""Offline candidate inventory. Never writes reviewer fields or model outputs."""
import argparse,csv,hashlib,json,re,unicodedata,collections,sys,gzip
from pathlib import Path
import pypdfium2

def norm(t):
 return ''.join(c for c in unicodedata.normalize('NFKD',t.lower()) if not unicodedata.combining(c))
HEADER=re.compile(r'\bnr\.?\s*(03\s*d\s*-\s*\d+\s*-\s*\d{2})\s*(?:data\s*:?\s*|din\s*)?(\d{2}\.\d{2}\.\d{4})',re.I)
OPERATIVE=re.compile(r'\bd\s*e\s*c\s*i\s*d\s*e\s*:')
FORM=re.compile(r'\bse\s+(admite\s+par\s*tial|admite|resping\s*e(?:\s+ca\s+neintemeiata)?)\s+contestati\w*')
CID=re.compile(r'\b02\s*/\s*\d+\s*/\s*\d{2}\b')
def parse(pages):
 # Header must be on a page carrying issuer, not a decision quoted in body.
 heads=[]
 for p,t in enumerate(pages[:3],1):
  n=norm(t);compact=re.sub(r'\s+',' ',n)
  if 'agentia nationala' not in compact or 'solutionarea contestati' not in compact:continue
  m=HEADER.search(compact[:1800])
  if m and re.search(r'\bd\s*e\s*c\s*i\s*z\s*i\s*e\b',compact[:m.start()]):heads.append((re.sub(r'\s+','',m[1]).upper(),m[2],p))
 if not heads:return {'reason':'no_own_dated_ANSC_merits_header'}
 did,date,hpage=heads[0];tail='\n'.join(pages[max(0,len(pages)-5):]);n=norm(tail);anchors=list(OPERATIVE.finditer(n))
 if not anchors:return {'reason':'no_resolutory_anchor','decision_id':did,'decision_date':date}
 start=anchors[-1].end();resolution=n[start:];original=tail[start:];found=[];forms=list(FORM.finditer(resolution))
 for i,m in enumerate(forms):
  end=forms[i+1].start() if i+1<len(forms) else len(resolution)
  # Stop at next numbered operative item; unrelated references later are not complaints.
  block=resolution[m.end():end];cut=re.search(r'\n\s*\d+\.\s*(?:se|in)',block)
  if cut:block=block[:cut.start()]
  if re.search(r'inadmisibil|tardiv|retrag|renunt|inceteaz',block):
   return {'reason':'non_merits_or_ambiguous_operative_item','decision_id':did,'decision_date':date}
  ids=sorted(set(re.sub(r'\s+','',x) for x in CID.findall(block)))
  outcome='partially_admitted' if m[1].startswith('admite par') else ('admitted' if m[1]=='admite' else 'rejected')
  for cid in ids:found.append((cid,outcome))
 if not found:return {'reason':'no_unambiguous_merits_complaint','decision_id':did,'decision_date':date}
 outcomes=sorted({x[1] for x in found});return {'reason':'candidate','decision_id':did,'decision_date':date,'header_page':hpage,'complaints':sorted(set(found)),'proposed_outcome':outcomes[0] if len(outcomes)==1 else 'mixed','quote':original[:800].strip()}
def read(p):
 with p.open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))
def write(p,rows):
 if not rows:return
 with p.open('w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def build_evidence(r,o):
 xs=read(o/'ansc_mta0021_candidates.csv');rs=read(r/'data/external/ansc_manual_review_50.csv')
 # A separate blind identity manifest for a future review, no labels or scores.
 write(o/'ansc_mta0021_blind_identity.csv',[{k:x[k] for k in ['ocid','document_url','decision_id','local_pdf','sha256','header_page']} for x in xs])
 p=r/'data/raw/ocds_packages/ocds-b3wdp1-MD-1586171621901.json.gz';d=json.load(gzip.open(p,'rt'));rec=[x['compiledRelease'] for x in d['records']];pn,base,ev=rec;assert pn['ocid']==rs[7]['ocid'];assert base['ocid']=='ocds-b3wdp1-MD-1586171621901'
 assert any(x.get('identifier')==base['ocid'] and 'parent' in x.get('relationship',[]) for x in pn['relatedProcesses']);assert any(x.get('identifier')==pn['ocid'] and 'planning' in x.get('relationship',[]) for x in base['relatedProcesses'])
 urls={x['url'] for a in ev['awards'] for x in a.get('documents',[])};assert all(rs[i-1]['document_url'] in urls for i in [8,9,10])
 write(o/'ansc_mta0021_alias_proposal.csv',[{'review_row':8,'source_ocid':pn['ocid'],'proposed_feature_ocid':base['ocid'],'evidence_file':str(p),'evidence_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'evidence':'mutual parent/planning relatedProcesses; evaluation record shares tender.id and all three decision URLs','status':'PRIMARY_LOCAL_LINK_EVIDENCE_FOUND_NOT_APPLIED'}])
 sys.path.insert(0,str(r/'src'));from mtender.stage_features import FEATURE_AVAILABILITY,strict_stage_columns
 allowed=strict_stage_columns('publication');availability=[]
 for name,m in FEATURE_AVAILABILITY.items():
  availability.append({'feature':name,'prediction_stage':'publication','earliest_stage':m['stage'],'stage_eligible':int(name in allowed),'corpus_point_in_time_safe':int(m['point_in_time_safe']),'inputs':'|'.join(m['inputs']),'required_evidence':'timestamped original notice at t0, no later amendments; pre-registered missing policy' if name in allowed else 'excluded at publication; '+m['earliest_availability'],'current_historical_certification':'NOT_CERTIFIED'})
 write(o/'ansc_mta0021_feature_availability.csv',availability)
 history=[]
 for x in xs:
  path=r/'data/raw/ocds_packages'/(x['ocid'].split('-PN-')[0]+'.json.gz');count=0;exists=path.exists()
  if exists:
   q=json.load(gzip.open(path,'rt'))
   # Embedded release payload with notice values; URI-only pointers do not qualify.
   for release in q.get('releases',[]):
    if isinstance(release,dict) and release.get('date') and release.get('tender'):count+=1
   for record in q.get('records',[]):
    for release in record.get('releases',[]) or []:
     if isinstance(release,dict) and release.get('date') and release.get('tender'):count+=1
  history.append({'ocid':x['ocid'],'raw_package_exists':int(exists),'embedded_timestamped_release_payloads':count,'publication_snapshot_certified':0})
 write(o/'ansc_mta0021_history_coverage.csv',history)
 summary={'publication_safe_features':allowed,'candidate_buyers':len({x['buyer_id_features'] for x in xs}),'negative_candidate_buyers':len({x['buyer_id_features'] for x in xs if x['proposed_outcome']=='rejected'}),'strata':dict(collections.Counter(x['publication_year']+'|'+x['proposed_outcome'] for x in xs)),'raw_packages':sum(x['raw_package_exists'] for x in history),'embedded_notice_histories':sum(x['embedded_timestamped_release_payloads']>0 for x in history),'certified_publication_snapshots':0}
 (o/'ansc_mta0021_evidence_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);ap.add_argument('--out',type=Path);ap.add_argument('--protocol',type=Path);args=ap.parse_args();r=args.root;o=args.out or r/'results/tables';o.mkdir(parents=True,exist_ok=True)
 inv=read(r/'results/tables/ansc_decision_inventory.csv');meta=json.loads((r/'results/methodology/ansc_decision_inventory.json').read_text());sandbox=Path(meta['sandbox_dir']);review=read(r/'data/external/ansc_manual_review_50.csv');priorhash={hashlib.sha256(Path(x['local_pdf_path']).read_bytes()).hexdigest() for x in review};priorocid={x['ocid'] for x in review};priordid=set()
 for x in review:
  priordid.update(re.findall(r'03D-\d+-\d{2}',x['decision_id'],re.I))
 features={x['ocid']:x for x in read(r/'data/features/features.csv')};stats=collections.Counter();byhash={};pdfpaths=set()
 for x in inv:
  p=sandbox/(hashlib.sha1(x['url'].encode()).hexdigest()[:16]+'.pdf')
  if not p.is_file():stats['mapped_missing_local_file']+=1;continue
  if p.read_bytes()[:5]!=b'%PDF-':stats['mapped_non_pdf']+=1;continue
  h=hashlib.sha256(p.read_bytes()).hexdigest();pdfpaths.add(p);entry=byhash.setdefault(h,{'path':p,'rows':[]});entry['rows'].append(x)
 stats['inventory_rows']=len(inv);stats['mapped_pdf_urls']=sum(len(x['rows']) for x in byhash.values());stats['unique_local_pdf_hashes']=len(byhash);stats['orphan_pdf_files']=len(set(sandbox.glob('*.pdf'))-pdfpaths)
 candidates=[];backlog=[]
 for j,(h,e) in enumerate(sorted(byhash.items()),1):
  p=e['path'];refs=e['rows'];stats['pdfs_scanned']+=1
  try:
   d=pypdfium2.PdfDocument(p);N=len(d)
   # Only first three pages for screening; all pages only after own header detected.
   head=[]
   for k in range(min(N,3)):
    page=d[k];tp=page.get_textpage();head.append(tp.get_text_range());tp.close();page.close()
   header_possible=any(HEADER.search(re.sub(r'\s+',' ',norm(t))[:1800]) and 'agentia nationala' in re.sub(r'\s+',' ',norm(t)) for t in head)
   if not header_possible:
    stats['no_readable_own_dated_header']+=1
    if sum(len(re.sub(r'\W','',t)) for t in head)<50:
     stats['scan_or_unreadable_header']+=1;backlog.append({'sha256':h,'local_pdf':str(p),'reason':'scan_or_unreadable_header'})
    elif any(x['decision_numbers'] for x in refs):
     backlog.append({'sha256':h,'local_pdf':str(p),'reason':'metadata_decision_number_but_own_header_unresolved'})
    d.close();continue
   pages=list(head)
   for k in range(len(head),N):
    page=d[k];tp=page.get_textpage();pages.append(tp.get_text_range());tp.close();page.close()
   d.close();parsed=parse(pages);stats[parsed['reason']]+=1
  except Exception as exc:
   stats['pdf_parse_error']+=1;backlog.append({'sha256':h,'local_pdf':str(p),'reason':'parse_error:'+type(exc).__name__});continue
  if parsed['reason']!='candidate':backlog.append({'sha256':h,'local_pdf':str(p),'reason':parsed['reason']});continue
  year=parsed['decision_date'][-4:]
  if year not in ['2022','2023','2024']:stats['merits_other_decision_year']+=1;continue
  if h in priorhash:stats['target_year_previously_reviewed_hash']+=1;continue
  did=parsed['decision_id'];newcase=did.upper() not in {a.upper() for a in priordid}
  alltext='\n'.join(pages);ownids=set(re.findall(r'MD\s*-\s*(\d{9,16})',alltext,re.I));links={x['ocid'] for x in refs}
  for ocid in sorted(links):
   row=next(x for x in refs if x['ocid']==ocid);digits=re.search(r'MD-(\d+)',ocid);f=features.get(ocid,{});pub=f.get('published_date','');rowid=digits[1] if digits else ''
   candidates.append({'ocid':ocid,'document_url':row['url'],'decision_id':did,'decision_date_proposed':parsed['decision_date'],'decision_year':year,'complaint_ids_proposed':';'.join(x[0] for x in parsed['complaints']),'complaint_outcomes_proposed':';'.join(a+'='+b for a,b in parsed['complaints']),'proposed_outcome':parsed['proposed_outcome'],'local_pdf':str(p),'sha256':h,'duplicate_url_count':len(refs),'ocids_for_same_hash':';'.join(sorted(links)),'own_procedure_digits_in_pdf':int(rowid in ownids),'publication_date_features':pub,'publication_year':pub[:4],'feature_exact_join':int(bool(f)),'buyer_id_features':f.get('buyer_id',''),'new_decision_vs_review50':int(newcase),'new_ocid_vs_review50':int(ocid not in priorocid),'test_year_screen':int(pub[:4] in ['2022','2023','2024']),'header_page':parsed['header_page'],'resolution_quote_proposed':parsed['quote'],'review_status':'CANDIDATE_NOT_HUMAN_VERIFIED'})
  if j%500==0:print('scanned',j,flush=True)
 candidates.sort(key=lambda x:(x['publication_year'],x['proposed_outcome'],x['sha256'],x['ocid']));write(o/'ansc_mta0021_candidates.csv',candidates);write(o/'ansc_mta0021_unresolved.csv',backlog)
 classes=['admitted','partially_admitted','rejected','mixed'];counts={}
 for label in classes:
  xs=[x for x in candidates if x['proposed_outcome']==label];new=[x for x in xs if x['new_decision_vs_review50'] and x['new_ocid_vs_review50']];test=[x for x in new if x['test_year_screen'] and x['own_procedure_digits_in_pdf']]
  counts[label]={'pdfs':len({x['sha256'] for x in xs}),'decisions':len({x['decision_id'] for x in xs}),'new_decisions':len({x['decision_id'] for x in new}),'new_ocids':len({x['ocid'] for x in new}),'test_screen_decisions':len({x['decision_id'] for x in test}),'test_screen_ocids':len({x['ocid'] for x in test})}
 summary={'baseline':'c9c9a08','protocol_sha256':hashlib.sha256((args.protocol or r/'docs/MTA-0021_INCLUSION_PROTOCOL.md').read_bytes()).hexdigest(), 'stats':dict(stats),'inventory_formats':dict(collections.Counter(x['format'] for x in inv)),'unresolved_records':len(backlog),'candidate_rows':len(candidates),'class_counts':counts,'years':dict(collections.Counter((x['decision_year']+'|'+x['proposed_outcome']) for x in {x['sha256']:x for x in candidates}.values())),'new_reviewed_labels':0,'note':'All counts are unverified machine-screen candidates; scans without a readable header remain unresolved; no population-complete assertion.'}
 (o/'ansc_mta0021_inventory.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');build_evidence(r,o);print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
