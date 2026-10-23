"""Focused review packets bind an auditor to evidence, never to a verdict."""
import hashlib
from .storage import canonical


def enabled(state, agent):
    from .research_tasks import enabled as research_enabled
    if research_enabled(state): return agent.get('work_kind')=='REVIEW'
    return (state['config'].get('task_style')=='focused' and state['config'].get('require_deposit_qualification')
            and agent.get('role')=='Evidence Auditor')


def pending(state, agent):
    from .research_tasks import enabled as research_enabled, reviews, evidence_revision as research_revision
    if research_enabled(state):
        from .prototype_review import pending as pending_tests
        return pending_tests(state,agent)+[{'kind':'RESEARCH_IDEA','target_id':i['id'],'revision':research_revision(i),
                 'provider':i.get('provider'),'documents':[]} for i in reviews(state,agent)]
    from .discovery_leads import awaiting_review, revision
    packets=[]
    for lead in awaiting_review(state):
        if agent['id'] in lead.get('contributors',[]): continue
        docs={}
        for doc in lead['documents']:
            url=doc['url']
            entry=docs.setdefault(url,{'url':url,'source_receipts':[],'required_ranges':[]})
            entry['source_receipts'].append({k:doc.get(k) for k in ('request_id','agent_id','sha256')})
            entry['required_ranges'].append([doc.get('offset',0),doc.get('end',0)])
        packets.append({'kind':'LEAD','target_id':lead['id'],'revision':revision(lead),
                        'provider':lead['provider'],'documents':list(docs.values())})
    for idea in state['ideas']:
        if idea.get('status') in {'REJECTED','COMPLETED'} or idea.get('agent_id')==agent['id']: continue
        q=next((q for q in state.get('deposit_qualifications',[]) if q['id']==idea.get('qualification_id') and q.get('admissible')),None)
        if not q: continue
        critique=idea.get('critique',{})
        if critique.get('agent_id')==agent['id'] and critique.get('qualification_id')==q['id']: continue
        packets.append({'kind':'IDEA','target_id':idea['id'],'revision':q['id'],
                        'provider':idea.get('provider'),'documents':[]})
    return packets


def assign(engine, agent):
    if not enabled(engine.state,agent): return
    choices=pending(engine.state,agent);old=agent.get('review_assignment',{})
    from .prototype_queue import enabled as closure_enabled
    if closure_enabled(engine.state):
        urgent=[p for p in choices if p['kind'].startswith('PROTOTYPE_')]
        if urgent:choices=urgent
    selected=next((p for p in choices if p['kind']==old.get('kind') and p['target_id']==old.get('target_id')
                  and p['revision']==old.get('revision')),choices[0] if choices else {'kind':'NONE'})
    ident=hashlib.sha256(canonical(selected).encode()).hexdigest()
    if old.get('id')==ident: return
    agent['review_assignment']=dict(selected,id=ident)
    engine.store.commit(engine.state,'review_task_assigned',
        {'agent_id':agent['id'],'kind':selected['kind'],'target_id':selected.get('target_id'),
         'provider':selected.get('provider'),'document_urls':[d['url'] for d in selected.get('documents',[])]},agent['id'])


def aliases(agent, base):
    assignment=agent.get('review_assignment',{})
    result=[base]
    from .research_recovery import source_key
    # Only redirects observed through this agent's validated document reader.
    for _ in range(8):
        before = len(result)
        for link in assignment.get('redirects',[]):
            if source_key(link['from']) in {source_key(u) for u in result} and link['to'] not in result:
                result.append(link['to'])
        if len(result) == before: break
    return result


def document_urls(agent):
    return list(dict.fromkeys(url for doc in agent.get('review_assignment',{}).get('documents',[])
                             for url in aliases(agent,doc['url'])))


def _subtract(required, intervals):
    remaining=list(required)
    for lo,hi in intervals:
        remaining=[part for a,b in remaining for part in
                   ([[a,min(b,lo)]] if a<lo else [])+([[max(a,hi),b]] if hi<b else [])
                   if part[0]<part[1]]
    return remaining


def current(state, agent):
    assignment=agent.get('review_assignment')
    if not assignment: return None
    packet={k:v for k,v in assignment.items() if k not in {'redirects'}}
    if packet['kind']=='NONE': return dict(packet,stage='DONE',next_action='No pending assigned review; finish this role.')
    if packet['kind']=='PROTOTYPE_PLAN':
        from .prototype_preflight import packet as plan_packet
        return plan_packet(state,agent,packet)
    if packet['kind']=='PROTOTYPE_FAILURE':
        from .prototype_debug import packet as failure_packet
        return failure_packet(state,agent,packet)
    if packet['kind']=='PROTOTYPE_TEST':
        from .prototype_review import packet as test_packet
        return test_packet(state,agent,packet)
    if packet['kind']=='RESEARCH_IDEA':
        from .research_tasks import evidence_revision as research_revision
        idea=next((i for i in state['ideas'] if i['id']==packet['target_id']),None)
        if not idea or research_revision(idea)!=packet['revision']: return dict(packet,stage='STALE')
        done=any(c.get('agent_id')==agent['id'] and c.get('idea_id')==idea['id']
                 and c.get('research_revision')==packet['revision'] for c in state.get('critiques',[]))
        from .research_recovery import evidence_gap, current as repair_current, blocked
        gap = evidence_gap(agent, idea)
        stop = blocked(agent, idea, 'REVIEW')
        return dict(packet,stage='DONE' if done else 'TASK_DEFERRED' if stop else 'CRITIQUE',candidate=idea,
                    local_test_focus_required=state['config'].get('require_prototype_focus',False),
                    **gap, repair=stop or repair_current(agent, idea, 'REVIEW'),
                    next_action='Audit THIS existing current-run IDEA. Read its evidence and record_critique for this ID. '
                        'For PASS read each missing_documents URL yourself, following only observed redirect hints. Missing evidence cannot be PASS: record REVISE with EVIDENCE_GAP if it cannot be resolved. '
                        'Missing evidence/test is REVISE, not REJECT. No deposit qualification is required for local research. '
                        'When local_test_focus_required, include local_test_scope FULL_MECHANISM/SUBCOMPONENT/DEFER and local_test_goal in record_critique. Select a useful mechanism-specific inverse of the produced format or documented carrier operation; not generic JSON parsing/copying. '
                        'A missing prototype is the implementation task, never a prerequisite for starting local work. Novelty uncertainty is separate from local testability. A local disk path is not a public retrieval URL. '
                        'After recording it, continue with the next host packet in the next bounded round.')
    from .discovery_leads import revision
    if packet['kind']=='IDEA':
        idea=next((i for i in state['ideas'] if i['id']==packet['target_id']),None)
        if not idea or idea.get('qualification_id')!=packet['revision']: return dict(packet,stage='STALE')
        critique=idea.get('critique',{})
        done=critique.get('agent_id')==agent['id'] and critique.get('qualification_id')==packet['revision']
        return dict(packet,stage='DONE' if done else 'CRITIQUE',next_action='Review only this existing IDEA and exact qualification; no new discovery.')
    lead=next((l for l in state.get('discovery_leads',[]) if l['id']==packet['target_id']),None)
    if not lead or revision(lead)!=packet['revision'] or lead.get('idea_id'):
        return dict(packet,stage='STALE',next_action='Assignment changed; continue in the next bounded round with a fresh packet.')
    if lead.get('review',{}).get('agent_id')==agent['id'] and lead['review'].get('revision')==packet['revision']:
        return dict(packet,stage='DONE',next_action='Preliminary review recorded. Qualification/discovery belongs to the discovery role; this LEAD grants no execution.')
    missing=[];failures=[]
    for doc in packet['documents']:
        urls=aliases(agent,doc['url']);reads=[r for r in agent.get('http_document_reads',{}).values() if r.get('url') in urls]
        intervals=[[r.get('offset',0),r.get('end',0)] for r in reads]
        intervals += [span for url in urls for span in agent.get('review_document_ranges',{}).get(url,{}).get('ranges',[])
                      if reads and agent['review_document_ranges'][url]['sha256']==reads[-1].get('sha256')]
        needed=doc['required_ranges']
        if reads:
            total=reads[-1].get('total_chars')
            if isinstance(total,int): needed=[[a,min(b,total)] for a,b in needed if a<total]
        remaining=_subtract(needed,intervals)
        if not reads or remaining:
            missing.append({'url':urls[-1],'original_url':doc['url'],
                'offset':remaining[0][0] if remaining else 0,
                'limit':min(16000,max(1,remaining[0][1]-remaining[0][0])) if remaining else 12000})
            for url in urls:
                failure=assignment.get('document_failures',{}).get(url)
                if failure and len(agent.get('operator_notes',[]))<=failure.get('operator_notes_count',0): failures.append(failure)
    stage='DOCUMENT_BLOCKED' if failures else 'READ_DOCUMENTS' if missing else 'TRIAGE'
    return dict(packet,stage=stage,missing_documents=missing,document_failures=failures,
        allowed_document_urls=document_urls(agent),
        next_action='Read these exact primary document ranges yourself with read_document, then record_lead_review for this LEAD. Do not search another service or use record_critique. Missing deposit evidence is an evidence gap, not an automatic rejection.')


def read_gate(api,url):
    task=current(api.engine.state,api.agent)
    if not task or task['kind']!='LEAD': return None
    if task['stage']=='STALE' or url not in document_urls(api.agent):
        return {'status':'DEFERRED','reason':'ASSIGNED_REVIEW_DOCUMENT_REQUIRED','review_task':task,
                'next_action':'Use the exact missing_documents URL and range in this packet; no new carrier discovery in this assignment.'}
    return None


def read_result(api,url,result):
    task=current(api.engine.state,api.agent)
    if task and task['kind']=='RESEARCH_IDEA':
        assignment = api.agent['review_assignment']
        if result.get('redirect_url') and len(assignment.setdefault('redirects',[])) < 8:
            link = {'from':url,'to':result['redirect_url'],'request_id':result['request_id']}
            if link not in assignment['redirects']: assignment['redirects'].append(link)
            api.event('review_document_redirect', link)
        return dict(result, review_task=current(api.engine.state,api.agent))
    if not task or task['kind']!='LEAD' or url not in document_urls(api.agent): return result
    assignment=api.agent['review_assignment']
    if result.get('status')=='COMPLETED' and result.get('request_id') in api.agent.get('http_document_reads',{}):
        own=api.agent['http_document_reads'][result['request_id']]
        ranges=api.agent.setdefault('review_document_ranges',{})
        entry=ranges.setdefault(url,{'sha256':own['sha256'],'ranges':[]})
        if entry['sha256']!=own['sha256']: entry.update(sha256=own['sha256'],ranges=[])
        span=[own['offset'],own['end']]
        if span not in entry['ranges']: entry['ranges'].append(span)
        assignment.get('document_failures',{}).pop(url,None)
    elif result.get('redirect_url') and len(assignment.setdefault('redirects',[]))<8:
        assignment['redirects'].append({'from':url,'to':result['redirect_url'],'request_id':result['request_id']})
    elif result.get('status') not in {'DEFERRED','LIMIT_REACHED'}:
        assignment.setdefault('document_failures',{})[url]={'url':url,'reason':result.get('reason','DOCUMENT_READ_UNAVAILABLE'),
            'request_id':result.get('request_id'),'operator_notes_count':len(api.agent.get('operator_notes',[]))}
    api.event('review_document_checkpoint',{'target_id':task['target_id'],'url':url,'status':result.get('status'),
              'stage':current(api.engine.state,api.agent)['stage'],'request_id':result.get('request_id')})
    return dict(result,review_task=current(api.engine.state,api.agent))


def triage_gate(api,lead_id,urls):
    task=current(api.engine.state,api.agent)
    if not task or task['kind']!='LEAD': return None
    if task['target_id']!=lead_id or task['stage']!='TRIAGE' or any(u not in document_urls(api.agent) for u in urls):
        return {'status':'DEFERRED','reason':'ASSIGNED_LEAD_REVIEW_REQUIRED','review_task':task,
                'next_action':'Complete this packet\'s own document reads, then triage its exact LEAD with those source URLs.'}
    return None


def tool_names(state,agent,names):
    if not enabled(state,agent): return names
    task=current(state,agent)
    if task and task['kind']=='LEAD': return {'get_review_task','read_document','record_lead_review','note'}
    names=set(names)|{'get_review_task'}
    if not any(i.get('qualification_id') and i.get('status') not in {'REJECTED','COMPLETED'} for i in state['ideas']):
        names.discard('record_critique');names.discard('submit_idea')
    return names


def complete(state,agent,normalized):
    task=current(state,agent)
    if not task or task['kind']=='NONE': return None
    from .research_recovery import active_blocks
    stalled = bool(active_blocks(state, agent, 'REVIEW'))
    if task['stage']=='TASK_DEFERRED' and not pending(state,agent):
        normalized.update(status='BLOCKED',reason_for_stopping='REVIEW_REPAIR_STALLED: unresolved review retained without a verdict',unexplored_leads=[])
    elif task['stage']=='DOCUMENT_BLOCKED':
        normalized.update(status='BLOCKED',reason_for_stopping='REVIEW_DOCUMENT_BLOCKED: assigned primary source could not be read',unexplored_leads=[])
    elif task['stage']=='DONE' and not pending(state,agent):
        normalized['handoff_leads']=list(dict.fromkeys(normalized['handoff_leads']+normalized['unexplored_leads']))
        normalized.update(status='BLOCKED' if stalled else 'COMPLETED',
            reason_for_stopping='REVIEW_REPAIR_STALLED: other reviews finished; unresolved review retained' if stalled else 'Assigned independent review receipts recorded; discovery/setup handed off',unexplored_leads=[])
    else:
        normalized.update(status='CONTINUE',reason_for_stopping='ASSIGNED_REVIEW_PENDING',
            unexplored_leads=['Continue only the current review packet: '+canonical(task.get('missing_documents',[])) if task['stage']=='READ_DOCUMENTS' or task.get('missing_documents')
                              else 'Record the assigned review or continue with the next host packet; no new carrier discovery.'])
    return normalized,{'reason':normalized['reason_for_stopping'],'target_id':task.get('target_id'),'stage':task['stage']}
