"""Review verdicts describe candidates; role completion describes assigned work."""
import hashlib
import re
from .storage import canonical

BASIS = {'UNSPECIFIED','SETUP_GAP','CAPABILITY_GAP','EVIDENCE_GAP','MECHANISM_FAILURE'}
FAILURES = {'NONE','FORMAT_PROHIBITED','AUTOMATION_PROHIBITED','RECURRING_COST','RETENTION_INCOMPATIBLE','INTEGRITY_FAILURE','BASELINE_DUPLICATE','OTHER'}

# Reject an inappropriate criterion, never infer a scientific verdict from prose.
ABSENT_EXECUTION = re.compile(
    r'\b(?:no|without|missing|lacks?|absence of|lack of)\s+'
    r'(?:(?:a|an|any|independent|actual|successful|completed|executed|final|real|public|verified|byte-exact|exact-byte)\s+)*'
    r'(?:deposit|upload|read[- ]?back)(?:\s+(?:test|evidence|receipt|verification))?\b'
    r'|\b(?:upload|deposit|(?:public )?read[- ]?back)\s+(?:(?:test|evidence|receipt)\s+)?'
    r'(?:has not|is not|was not|not yet|not)\s+(?:been\s+)?(?:completed|executed|performed|verified)\b'
    r'|\bnot (?:yet )?(?:uploaded|deposited)\b', re.I)


def predeployment_issue(api, idea, verdict, reason, basis, failure_kind):
    if (verdict=='PASS' or basis=='MECHANISM_FAILURE' or failure_kind!='NONE'
            or not ABSENT_EXECUTION.search(reason)):
        return None
    q=next((q for q in api.engine.state.get('deposit_qualifications',[]) if q['id']==idea.get('qualification_id')),None)
    if not q:
        return None
    fingerprint=hashlib.sha256(canonical({'idea':idea['id'],'qualification':q['id'],'reason':reason}).encode()).hexdigest()
    old=api.agent.get('predeployment_review_repair',{})
    attempts=old.get('same_attempts',0)+1 if old.get('fingerprint')==fingerprint else 1
    result={'status':'DEFERRED' if attempts<3 else 'BLOCKED',
            'reason':'PRE_DEPLOYMENT_REVIEW_NO_EXECUTION_REQUIRED','idea_id':idea['id'],
            'qualification_id':q['id'],'review_stage':'PRE_DEPLOYMENT','execution_receipt_required':False,
            'setup_blockers':q.get('reasons',[]),'same_attempts':attempts,'fingerprint':fingerprint,
            'next_action':'Revise the SAME candidate review from primary evidence and current setup/capability/resource gaps. '
                'Do not require a completed upload or public read-back receipt BEFORE execution. '
                'A real observed mechanism/integrity failure belongs to MECHANISM_FAILURE with concrete source evidence; no automatic PASS is issued.'}
    api.agent['predeployment_review_repair']=result
    api.event('predeployment_review_deferred',result)
    return result

def source_quote(api, fact, urls):
    """Verify a literal quote against an unchanged own captured public document."""
    from .pdf_documents import source_document
    from .workspace import _read_bytes, _relative
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
            body=_read_bytes(api.workspace.root, _relative(response['path']), 8_000_000)
            text,_,_,metadata=source_document(api,request,body)
        except (ValueError,OSError,KeyError):
            continue
        if wanted in ' '.join(text.split()).casefold():
            pages=[p['page'] for p in metadata.get('page_spans',[]) if wanted in ' '.join(text[p['start']:p['end']].split()).casefold()]
            return {'request_id':request['id'],'url':payload['url'],'source_sha256':response['stored_sha256'], 'pages':pages,
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
    from .research_tasks import enabled as research_enabled
    if research_enabled(state) and agent.get('work_kind')=='REVIEW':
        from .review_tasks import complete
        return complete(state,agent,normalized) or (normalized,None)
    if agent['role']!='Evidence Auditor' or not state['config'].get('require_deposit_qualification'):
        return normalized,None
    repair=agent.get('predeployment_review_repair')
    if repair and any(i['id']==repair['idea_id'] and i.get('qualification_id')==repair['qualification_id'] for i in state['ideas']):
        normalized.update(status='CONTINUE' if repair['same_attempts']<3 else 'BLOCKED',
                          reason_for_stopping='PRE_DEPLOYMENT_REVIEW_NO_EXECUTION_REQUIRED')
        normalized['unexplored_leads']=[repair['next_action']] if repair['same_attempts']<3 else []
        return normalized,{'reason':'PRE_DEPLOYMENT_REVIEW_NO_EXECUTION_REQUIRED'}
    from .review_tasks import complete
    assigned=complete(state,agent,normalized)
    if assigned: return assigned
    if raw['status'] not in {'COMPLETED','REJECTED'}:
        return normalized,None
    candidates=[i for i in state['ideas'] if i.get('qualification_id')]
    from .discovery_leads import awaiting_review
    documented_leads = [r for r in state.get('discovery_leads', []) if r.get('documents') and not r.get('idea_id')]
    if awaiting_review(state):
        normalized.update(status='BLOCKED', reason_for_stopping='LEAD_REVIEW_REQUIRED: record independent triage of documented unqualified leads')
        return normalized, {'reason':'LEAD_REVIEW_REQUIRED'}
    if (not candidates and not documented_leads) or not all(i.get('critique',{}).get('agent_id')==agent['id']
           and i.get('critique',{}).get('qualification_id')==i['qualification_id'] for i in candidates):
        normalized.update(status='BLOCKED',reason_for_stopping='AUDIT_RECEIPT_REQUIRED: no current critique for all assigned candidates')
        return normalized,{'reason':'AUDIT_RECEIPT_REQUIRED'}
    normalized['handoff_leads']=list(dict.fromkeys(normalized['handoff_leads']+normalized['unexplored_leads']))
    normalized['unexplored_leads']=[]
    normalized.update(status='COMPLETED',reason_for_stopping='Assigned candidate audit recorded; setup/deposit work retained for handoff')
    return normalized,{'candidate_ids':[i['id'] for i in candidates],
                       'meaning':'Review work finished; candidate verdict/status and execution gates remain independent.'}
