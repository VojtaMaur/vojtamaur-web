"""Review verdicts describe candidates; role completion describes assigned work."""
import hashlib

BASIS = {'UNSPECIFIED','SETUP_GAP','CAPABILITY_GAP','EVIDENCE_GAP','MECHANISM_FAILURE'}
FAILURES = {'NONE','FORMAT_PROHIBITED','AUTOMATION_PROHIBITED','RECURRING_COST','RETENTION_INCOMPATIBLE','INTEGRITY_FAILURE','BASELINE_DUPLICATE','OTHER'}

def source_quote(api, fact, urls):
    """Verify a literal quote against an unchanged own captured public document."""
    from .documents import readable
    wanted=' '.join(fact.split()).casefold()
    if len(wanted)<5:
        return None
    for request in reversed(api.engine.state.get('http_requests',[])):
        payload=request.get('action',{}).get('payload',{})
        response=request.get('response',{})
        if (request.get('agent_id')!=api.agent['id'] or request.get('status')!='COMPLETED'
                or payload.get('method')!='GET' or payload.get('url','').rstrip('/') not in {u.rstrip('/') for u in urls}
                or not 200 <= (response.get('status') or 0) < 300 or response.get('truncated')):
            continue
        try:
            body=api.workspace.read_file(response['path'])
            if hashlib.sha256(body.encode('utf-8')).hexdigest()!=response.get('stored_sha256'):
                continue
            content_type=next((v for k,v in response.get('headers',{}).items() if k.casefold()=='content-type'),'')
            text,_,_=readable(body,content_type,payload['url'])
        except (ValueError,OSError,KeyError):
            continue
        if wanted in ' '.join(text.split()).casefold():
            return {'request_id':request['id'],'url':payload['url'],'source_sha256':response['stored_sha256'],
                    'meaning':'Verbatim text present in an unchanged captured document; interpretation/failure claim not certified.'}
    return None

def decision(api, idea, verdict, basis, failure_kind, failure_fact, source_urls):
    if basis not in BASIS or failure_kind not in FAILURES:
        raise ValueError('Unknown review basis/failure kind')
    if not isinstance(failure_fact,str) or len(failure_fact)>4000:
        raise ValueError('failure_fact must be text up to 4000 characters')
    if not isinstance(source_urls,list) or len(source_urls)>8 or any(not isinstance(u,str) or len(u)>2000 for u in source_urls):
        raise ValueError('Provide up to 8 negative evidence URLs')
    result={'requested_verdict':verdict,'decision_basis':basis,'failure_kind':failure_kind,
            'failure_fact':failure_fact,'negative_evidence_urls':source_urls}
    if verdict != 'REJECT':
        return verdict,result
    reads={r['url'].rstrip('/') for r in api.agent.get('http_document_reads',{}).values()}
    independent = api.agent['role']=='Evidence Auditor' and api.agent['id']!=idea.get('agent_id')
    grounded=(basis=='MECHANISM_FAILURE' and failure_kind!='NONE' and len(failure_fact.strip())>=5
              and bool(source_urls) and all(u.rstrip('/') in reads for u in source_urls) and independent)
    quote=source_quote(api,failure_fact,source_urls) if grounded else None
    grounded=grounded and quote is not None
    if quote:
        result['negative_source_quote']=quote
    if not grounded:
        result.update(verdict_adjustment='REJECT_REQUIRES_GROUNDED_MECHANISM_FAILURE',
                      meaning='Retained as REVISE. Missing verbatim source quote, setup/capability/evidence gaps or no executed upload are not scientific rejection. Structured failure claims still require human/peer assessment.')
        return 'REVISE',result
    result['meaning']='Independent agent failure claim linked to read sources, not host certification of its truth.'
    return verdict,result

def complete_review(state, agent, raw, normalized):
    if agent['role']!='Evidence Auditor' or not state['config'].get('require_deposit_qualification'):
        return normalized,None
    if raw['status'] not in {'COMPLETED','REJECTED'}:
        return normalized,None
    candidates=[i for i in state['ideas'] if i.get('qualification_id')]
    if not candidates or not all(i.get('critique',{}).get('agent_id')==agent['id']
           and i.get('critique',{}).get('qualification_id')==i['qualification_id'] for i in candidates):
        normalized.update(status='BLOCKED',reason_for_stopping='AUDIT_RECEIPT_REQUIRED: no current critique for all assigned candidates')
        return normalized,{'reason':'AUDIT_RECEIPT_REQUIRED'}
    normalized['handoff_leads']=list(dict.fromkeys(normalized['handoff_leads']+normalized['unexplored_leads']))
    normalized['unexplored_leads']=[]
    normalized.update(status='COMPLETED',reason_for_stopping='Assigned candidate audit recorded; setup/deposit work retained for handoff')
    return normalized,{'candidate_ids':[i['id'] for i in candidates],
                       'meaning':'Review work finished; candidate verdict/status and execution gates remain independent.'}
