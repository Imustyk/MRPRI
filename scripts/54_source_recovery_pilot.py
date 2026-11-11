#!/usr/bin/env python3
"""Offline analysis of the frozen, <=20-request MTA-0023 pilot. No network I/O."""
from pathlib import Path
from collections import Counter
import argparse,csv,gzip,hashlib,json
from pypdf import PdfReader

TARGETS=('ocds-b3wdp1-MD-1659961877383','ocds-b3wdp1-MD-1665058207960')
LIMIT=20

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def validate_ledger(ledger,folder):
    if len(ledger)>LIMIT:
        raise ValueError('pilot resource limit exceeded')
    if [x['request_number'] for x in ledger]!=list(range(1,len(ledger)+1)):
        raise ValueError('request numbering is not contiguous')
    for x in ledger:
        if x.get('body_file'):
            p=folder/x['body_file']
            if p.name!=x['body_file'] or sha(p)!=x['sha256'] or p.stat().st_size!=x['bytes']:
                raise ValueError('source body identity mismatch')
        if x.get('body_truncated'):
            raise ValueError('truncated source cannot be analyzed')


def historical_status(*,original_fields_complete=False,identity_verified=False,public_timestamp_proven=False,partial_evidence=False):
    if original_fields_complete and identity_verified and public_timestamp_proven:
        return 'CERTIFIED'
    return 'PARTIALLY VERIFIED' if partial_evidence else 'NOT CERTIFIED'


def writecsv(path,rows):
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)


def analyze(root,source,out):
    ledger=json.loads((source/'http_provenance.json').read_text());validate_ledger(ledger,source)
    old=json.loads((root/'results/tables/mta0022_source_evidence.json').read_text())
    by_number={x['request_number']:x for x in ledger};versions=[];evidence=[];pdf_details={}
    for ocid,ev_number,base_number,pdf_numbers in [(TARGETS[0],2,13,[9,10]),(TARGETS[1],8,14,[11,12])]:
        base=json.loads((source/by_number[base_number]['body_file']).read_text())
        local=json.load(gzip.open(root/'data/raw/ocds_packages'/(ocid+'.json.gz'),'rt'))
        if base!=local: # Formatting differences are allowed; changes must be reviewed.
            raise ValueError('current record content differs from frozen MTA-0022: '+ocid)
        def row(resource,kind,version_id='',parent='',date='',fields=None,status='NOT CERTIFIED',note='',page=''):
            fields=fields or {};period=fields.get('tenderPeriod',{})
            return dict(ocid=ocid,source_kind=kind,version_id=version_id,amends_release_id=parent,
                        source_claimed_event_date=date,public_available_at_verified='',
                        tenderPeriod_startDate_observed_snapshot=period.get('startDate',''),
                        tenderPeriod_endDate_observed_snapshot=period.get('endDate',''),
                        procurementMethod_observed_snapshot=fields.get('procurementMethod',''),
                        procurementMethodDetails_observed_snapshot=fields.get('procurementMethodDetails',''),
                        original_fields_at_t0_verified=0,status=status,source_url=resource['url'],
                        http_status=resource['http_status'],source_file=str((source/resource['body_file']).relative_to(root)),
                        document_sha256=resource['sha256'],source_page_or_pointer=page,notes=note)
        for number,kind in [(ev_number,'actualReleases_latest_EV_payload'),(base_number,'current_record_compiled_snapshot')]:
            resource=by_number[number];body=json.loads((source/resource['body_file']).read_text())
            releases=body['releases'] if 'releases' in body else [x['compiledRelease'] for x in body['records']]
            for i,release in enumerate(releases):
                if ocid not in release['ocid']:raise ValueError('wrong procedure payload')
                versions.append(row(resource,kind,release['id'],date=release['date'],fields=release.get('tender'),
                                    note='current representation; old date does not certify original values',
                                    page=f'/releases/{i}' if 'releases' in body else f'/records/{i}/compiledRelease'))
        refs=old[ocid]['amendment_refs'];nodes={}
        for a in refs:
            nodes[a['releaseID']]={'parent':a['amendsReleaseID'],'date':a['date']}
            nodes.setdefault(a['amendsReleaseID'],{'parent':'','date':''})
        for version_id,node in sorted(nodes.items()):
            resource=next(x for x in ledger if x['url'].endswith('/'+version_id))
            if resource['http_status']!=404:raise ValueError('version response needs new human source audit')
            versions.append(row(resource,'exact_known_releaseID_route_probe_NOT_documented_URI',version_id,node['parent'],node['date'],
                                note='identifier from amendment, not a supplied historical URL; tested route 404, other routes not disproven'))
        for number in pdf_numbers:
            resource=by_number[number];reader=PdfReader(source/resource['body_file'])
            pages=[p.extract_text() or '' for p in reader.pages]
            text='\n'.join(pages)
            if ('Conform SIA RSAP' not in text and 'informatia o gasiti pe SIA RSAP' not in text):
                raise ValueError('PDF deadline evidence requires review')
            meta=next(x for x in old[ocid]['notice_refs'] if x['url'].replace('http:','https:')==resource['url'])
            signatures=[]
            for key,field in (reader.get_fields() or {}).items():
                if field.get('/FT')=='/Sig':
                    v=field.get('/V').get_object();signatures.append({'field':key,'claimed_signing_time':str(v.get('/M')),'subfilter':str(v.get('/SubFilter')),'cryptographically_validated':False,'public_availability_proven':False})
            pdf_details[str(number)]={'ocid':ocid,'pages':len(pages),'metadata':dict(reader.metadata),'signature_metadata':signatures,'source_sha256':resource['sha256']}
            versions.append(row(resource,'notice_PDF_version_candidate',version_id=resource['url'].rsplit('/',1)[-1],date=meta['datePublished'],
                                status='PARTIALLY VERIFIED',page='1;7;8' if len(pages)==8 else '1;3;4',
                                note='publisher-linked PDF body recovered; initial public availability unproven; exact deadline delegated to SIA RSAP; date is current document metadata claim'))
        first=by_number[pdf_numbers[0]];pdf_path=str((source/first['body_file']).relative_to(root))
        candidate='2022-08-08T12:39:50Z' if ocid==TARGETS[0] else '2022-10-06T12:20:01Z'
        method='Licitație Publică' if ocid==TARGETS[0] else 'COP'
        for field in ['initial_notice_identity','t0','tenderPeriod.startDate','tenderPeriod.endDate','procurementMethod','procurementMethodDetails','bid_window_days','short_deadline','long_deadline','accelerated_like']:
            partial=field in ['initial_notice_identity','t0','procurementMethod','procurementMethodDetails']
            note={
                'initial_notice_identity':'body recovered via publisher record; buyer and title match; PDF does not itself establish immutable OCID/version-to-publication link',
                't0':'candidate from latest API package/document datePublished; PDF states dispatch date only; HTTP Date is retrieval time; signature /M not a verified publication timestamp',
                'tenderPeriod.startDate':'no exact submission start in recovered PDF; modern EV value is not original proof',
                'tenderPeriod.endDate':'PDF deadline refers to SIA RSAP; original platform deadline unavailable',
                'procurementMethod':'PDF textual procedure='+method+'; no authenticated initial OCDS enum',
                'procurementMethodDetails':'PDF textual procedure='+method+'; no validated mapping to original OCDS details; do not substitute latest compiled enum',
                'bid_window_days':'original start/end unavailable; no default 30 substituted',
                'short_deadline':'depends on uncertified original window; no default 0 substituted',
                'long_deadline':'depends on uncertified original window; no default 0 substituted',
                'accelerated_like':'PDF acceleration says not applicable, but regex input is original procurementMethodDetails, not this narrative; no derived zero certified',
            }[field]
            evidence.append(dict(ocid=ocid,field_or_feature=field,status=historical_status(partial_evidence=partial),
                                 certified_value='',candidate_t0_not_verified=candidate if field=='t0' else '',
                                 observed_document_procedure_text=method if field in ['procurementMethod','procurementMethodDetails'] else '',
                                 original_public_timestamp_proven=0,source_file=pdf_path,document_sha256=first['sha256'],
                                 source_url=first['url'],source_page_or_pointer=('1' if field in ['initial_notice_identity','procurementMethod','procurementMethodDetails'] else ('8' if ocid==TARGETS[0] else '4')) if partial else ('7' if ocid==TARGETS[0] else '3'),blocking_reason=note))
    out.mkdir(parents=True,exist_ok=True)
    writecsv(out/'mta0023_release_versions.csv',versions);writecsv(out/'mta0023_publication_evidence.csv',evidence)
    (out/'mta0023_pdf_inspection.json').write_text(json.dumps(pdf_details,ensure_ascii=False,indent=2)+'\n')
    summary=dict(requests_total=len(ledger),budget=LIMIT,http_status_counts=dict(Counter(str(x['http_status']) for x in ledger)),
                 successful_pdf_responses=4,unique_pdf_bodies=len({by_number[n]['sha256'] for n in [9,10,11,12]}),
                 version_rows=len(versions),field_feature_rows=len(evidence),status_counts=dict(Counter(x['status'] for x in evidence)),
                 certified_t0_procedures=0,certified_publication_features=0,publication_feature_count=8,decision='NO-GO')
    (out/'mta0023_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument('--source',type=Path);parser.add_argument('--out',type=Path)
    a=parser.parse_args();analyze(a.root,a.source or a.root/'data/source_recovery/mta0023',a.out or a.root/'results/tables')
