"""Deterministic draft retention and prerequisite recovery, never execution."""
import hashlib
from .storage import canonical
from .workspace import Workspace

DEPENDENCY_BLOCKS = {'LEAD_REVIEW_REQUIRED: record independent triage of documented unqualified leads', 'NO_ADMITTED_DISCOVERY_CANDIDATE', 'NO_INDEPENDENTLY_APPROVED_DEPOSIT_PLAN'}

def report_revision(state):
    body = {'discovery_leads':state.get('discovery_leads',[]), 'ideas':state.get('ideas',[]),'quals':state.get('deposit_qualifications',[]),
            'critiques':state.get('critiques',[]),'http':state.get('http_requests',[]),
            'deposit_executions':state.get('deposit_executions',[]),
            'tests':state.get('tests',[]),'experiments':state.get('experiments',[]),
            'coding_commands':state.get('coding_commands',[]),'coding_validations':state.get('coding_validations',[]),
            'shared_components':state.get('shared_components',{}),'review_probes':state.get('prototype_review_probes',[]),
            'packages':state.get('package_installations',[]),'prototype_reviews':state.get('prototype_reviews',[]),
            'external_actions':state.get('external_actions',[]),'approvals':state.get('approvals',[]),
            'research_blockers':{a['id']:a['research_blockers'] for a in state['agents'] if a.get('research_blockers')},
            'research_task_blocks':{a['id']:a['research_task_blocks'] for a in state['agents'] if a.get('research_task_blocks')},
            'prototype_queue_holds':{a['id']:a['prototype_queue_hold'] for a in state['agents'] if a.get('prototype_queue_hold')},
            'coding_local_contracts':{a['id']:a['coding_local_contracts'] for a in state['agents'] if a.get('coding_local_contracts')}}
    return hashlib.sha256(canonical(body).encode()).hexdigest()

def recover(engine):
    if not engine.state['config'].get('require_deposit_qualification'):
        return
    from .engine import ToolAPI
    from .config import round_allowance
    state=engine.state
    changed=False
    from .planning_recovery import legacy_problem, stalled
    for agent in state['agents']:
        problem=legacy_problem(state,agent)
        if problem:
            agent['planning_repair']=problem
            engine.store.commit(state,'legacy_plan_revision_recognized',problem,agent['id'])
        repair=agent.get('planning_repair')
        if repair and agent.get('work_kind')=='LOCAL':
            from .plan_drafts import hydrate_legacy
            hydrate_legacy(ToolAPI(engine,agent,Workspace(engine.store.run_dir/'snapshot',engine.store.run_dir/'agents'/agent['id']/'workspace')))
        if (agent.get('work_kind')=='LOCAL' and agent['status']=='BLOCKED' and repair
                and not stalled(repair) and agent['rounds']<round_allowance(state['config'],agent)
                and any(i['id']==repair['idea_id'] and i.get('qualification_id')==repair.get('qualification_id')
                        and i.get('status') not in {'REJECTED','COMPLETED'} for i in state['ideas'])
                and not any(f['idea_id']==repair['idea_id'] for f in state.get('deposit_executions',[]))):
            try:
                engine.prompt(agent)
            except ValueError as error:
                if str(error).startswith('Focused task/state exceeds prompt_chars'):
                    continue  # Unchanged host preflight failure must never consume another round.
                raise
            agent.update(status='PENDING',execution_plan_only=True,reason_for_stopping='PLAN_REVISION_REQUIRED: repair recorded tool arguments')
            engine.store.commit(state,'role_prerequisite_recovered',{'agent_id':agent['id'],'reason':'PLAN_REVISION_REQUIRED'})
            changed=True
    for receipt in state.get('deposit_qualifications',[]):
        if not receipt.get('admissible'):
            continue
        retained_id = receipt.get('retention',{}).get('candidate_id')
        if retained_id and any(i['id']==retained_id for i in state['ideas']):
            continue  # Superseded qualifications must never roll a revised IDEA back.
        if any(i.get('qualification_id')==receipt['id'] for i in state['ideas']):
            continue
        owner=next((a for a in state['agents'] if a['id']==receipt['agent_id'] and a.get('work_kind')=='DISCOVERY'),None)
        if not owner:
            continue
        # A deferred semantic comparison stays durable; do not repeat it unchanged.
        registry=hashlib.sha256(canonical(state['ideas']).encode()).hexdigest()
        if receipt.get('retention',{}).get('deferred_registry')==registry:
            continue
        plan=receipt['plan']
        matching=next((i for i in state['ideas'] if i.get('host_retained_deposit_draft')
                       and i.get('provider')==plan['provider']
                       and i.get('deposit_plan',{}).get('upload_url')==plan['upload_url']
                       and i.get('host_retained_export_sha256')==receipt.get('export_sha256')
                       and i.get('novelty_class')==plan['novelty_class']),None)
        api=ToolAPI(engine,owner,Workspace(engine.store.run_dir/'snapshot',engine.store.run_dir/'agents'/owner['id']/'workspace'))
        payload={'id':matching['id'] if matching else '', 'qualification_id':receipt['id'],
                 'provider':plan['provider'],'title':plan['provider']+' - exact retained export deposit',
                 'mechanism':'Exact-byte retained export deposit through '+plan['upload_url'],
                 'summary':'Host-retained qualification draft from '+receipt['id']+'. Service claims, cost, novelty, file acceptance and custody need independent review.',
                 'status':'DISCOVERED','payment':'UNKNOWN','novelty':'Not independently assessed.',
                 'novelty_class':plan['novelty_class'],'baseline_evidence_ids':plan['baseline_evidence_ids'],
                 'novelty_delta':plan.get('proposed_change','') if plan['novelty_class']=='IMPROVEMENT' else '',
                 'baseline_behavior':plan.get('baseline_behavior',''),'proposed_change':plan.get('proposed_change',''),
                 'validation_plan':plan.get('validation_plan',''),
                 'evidence':[{'url':url,'claim':'Documentation URL recorded by qualification; semantic claims not verified.','verified':False} for url in plan['documentation_urls']]}
        result=api.submit_idea(payload)
        if 'id' in result:
            result['host_retained_deposit_draft']=True
            result['host_retained_export_sha256']=receipt.get('export_sha256')
            receipt['retention']={'status':'RETAINED','candidate_id':result['id']}
            api.event('deposit_candidate_retained',{'qualification_id':receipt['id'],'candidate_id':result['id'],'status':result['status'],
                       'meaning':'Unverified host draft, no upload, approval, pricing claim or new discovery certification.'})
            changed=True
        else:
            receipt['retention']={'status':'DEFERRED','reason':result.get('reason'),'deferred_registry':registry}
            api.event('deposit_candidate_retention_deferred',{'qualification_id':receipt['id'],**receipt['retention']})
    from .discovery_leads import awaiting_review
    # Link only already-admitted IDEAs; a LEAD cannot relax admission or execution.
    for lead in state.get('discovery_leads', []):
        matching = next((i for i in state['ideas'] if i.get('provider','').strip().casefold()==lead['provider'].strip().casefold()), None)
        if matching and lead.get('idea_id') != matching['id']:
            lead['idea_id'] = matching['id']
            lead['status'] = 'ADMITTED'
            engine.store.commit(state, 'discovery_lead_promoted', {'lead_id':lead['id'],'idea_id':matching['id']})
            changed = True
    for agent in state['agents']:
        if agent['status']!='BLOCKED' or agent.get('reason_for_stopping') not in DEPENDENCY_BLOCKS:
            continue
        ready = (any(i.get('status')!='REJECTED' for i in state['ideas']) or bool(awaiting_review(state))) if agent['role']=='Evidence Auditor' else any(
            i.get('deposit_feasibility')=='READY_FOR_AUDIT' and i.get('status')!='REJECTED'
            and i.get('critique',{}).get('verdict')=='PASS'
            and i.get('critique',{}).get('qualification_id')==i.get('qualification_id') for i in state['ideas'])
        if agent.get('work_kind')=='LOCAL' and not ready:
            from .deposit_execution import needs_planning
            ready=needs_planning(state)
            agent['execution_plan_only']=ready
        if ready and agent['rounds'] < round_allowance(state['config'],agent):
            agent.update(status='PENDING',reason_for_stopping='Dependency now available; reevaluated by host')
            engine.store.commit(state,'role_prerequisite_recovered',{'agent_id':agent['id']})
            changed=True
    for agent in state['agents']:
        if (agent.get('status')=='BLOCKED' and str(agent.get('reason_for_stopping','')).startswith('REVIEW_DOCUMENT_BLOCKED')
                and agent['rounds']<round_allowance(state['config'],agent)):
            from .review_tasks import current
            task=current(state,agent)
            if task and task['stage']=='STALE':
                agent.update(status='PENDING',reason_for_stopping='Changed review packet permits a new bounded source read')
                engine.store.commit(state,'role_prerequisite_recovered',{'agent_id':agent['id'],'reason':'REVIEW_TASK_CHANGED'})
                changed=True
    for agent in state['agents']:
        if (agent['role']=='Evidence Auditor' and agent['status']=='COMPLETED'
                and agent['rounds'] < round_allowance(state['config'],agent)
                and (bool(awaiting_review(state)) or any(i.get('qualification_id') and i.get('status')!='REJECTED'
                        and i.get('critique',{}).get('qualification_id')!=i['qualification_id'] for i in state['ideas']))):
            agent.update(status='PENDING',reason_for_stopping='New qualification needs independent review')
            engine.store.commit(state,'role_prerequisite_recovered',{'agent_id':agent['id'],'reason':'QUALIFICATION_CHANGED'})
            changed=True
    for agent in state['agents']:
        if (agent.get('work_kind')=='LOCAL' and agent['status']=='COMPLETED'
                and agent['rounds']<round_allowance(state['config'],agent)
                and state['config'].get('run_mode')=='autonomous'
                and any(i.get('execution_planning_agent_id')==agent['id'] and i.get('status') not in {'REJECTED','COMPLETED'}
                        and i.get('deposit_feasibility')=='READY_FOR_AUDIT'
                        and i.get('critique',{}).get('verdict')=='PASS'
                        and i.get('critique',{}).get('qualification_id')==i.get('qualification_id')
                        and not any(f['idea_id']==i['id'] for f in state.get('deposit_executions',[])) for i in state['ideas'])):
            agent.update(status='PENDING',execution_plan_only=False,reason_for_stopping='Prepared sequence now independently reviewed; execute within grants')
            engine.store.commit(state,'role_prerequisite_recovered',{'agent_id':agent['id'],'reason':'EXECUTABLE_PLAN_REVIEWED'})
            changed=True
    # Return an independently specified evidence/qualification task once, within
    # the existing discovery round allowance. Never reopen setup/human blockers.
    from .discovery_leads import revision
    for lead in state.get('discovery_leads', []):
        review = lead.get('review', {})
        if (lead.get('idea_id') or review.get('revision') != revision(lead)
                or review.get('disposition') not in {'NEEDS_EVIDENCE','QUALIFY'}):
            continue
        for agent in state['agents']:
            if (agent['id'] not in lead['contributors'] or agent.get('work_kind') != 'DISCOVERY'
                    or agent['status'] != 'COMPLETED'
                    or agent['rounds'] >= round_allowance(state['config'],agent)):
                continue
            key = hashlib.sha256(canonical(review).encode()).hexdigest()
            seen = agent.setdefault('lead_handoffs_seen', {})
            if seen.get(lead['id']) == key:
                continue
            seen[lead['id']] = key
            agent.update(status='PENDING', reason_for_stopping='Independent lead triage specifies bounded follow-up')
            engine.store.commit(state,'lead_followup_scheduled',{'agent_id':agent['id'],'lead_id':lead['id'],'next_action':review['next_action']})
            changed=True
    current=report_revision(state)
    for agent in state['agents']:
        if (agent.get('work_kind')=='SYNTHESIS' and agent['status']=='COMPLETED'
                and agent['rounds'] < round_allowance(state['config'],agent)
                and (changed or agent.get('report_revision') not in {None,current})):
            agent.update(status='PENDING',reason_for_stopping='New retained evidence requires report update')
            engine.store.commit(state,'report_refresh_scheduled',{'agent_id':agent['id']})
