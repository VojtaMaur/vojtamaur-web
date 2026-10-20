"""Repair data planning without loosening execution permissions or inventing plans."""
import hashlib
import json
from .storage import canonical


def remember(api, idea_id, steps, error):
    from .deposit_plan import PlanValidationError
    issue = error.issue if isinstance(error,PlanValidationError) else {
        'code':'PLAN_DATA_INVALID','step_id':'',
        'next_action':'Correct the data-only step schema, exact origins, first qualified endpoint, prior-step JSON pointers and raw export body. Inspect the existing source receipts; do not change permissions or invent API details.'}
    fingerprint=hashlib.sha256(canonical(steps).encode()).hexdigest()
    old=api.agent.get('planning_repair',{})
    q=api.idea(idea_id).get('qualification_id')
    scope=old.get('idea_id')==idea_id and old.get('qualification_id')==q
    # Count the unresolved validation issue, not cosmetic changes to the plan.
    position=next((n for n,s in enumerate(steps) if isinstance(s,dict) and s.get('id')==issue.get('step_id')),None) if isinstance(steps,list) else None
    signature=hashlib.sha256(canonical([idea_id,q,issue['code'],position]).encode()).hexdigest()
    counts=dict(old.get('issue_counts',{})) if scope else {}
    if not counts and scope and old.get('issue',{}).get('code')==issue['code'] and old.get('issue',{}).get('step_id')==issue['step_id']:
        counts[signature]=old.get('same_attempts',0)  # Preserve the old checkpoint's observed attempts.
    attempts=counts.get(signature,0)+1
    counts[signature]=attempts
    if len(counts)>64: counts={signature:attempts}
    api.agent['plan_attempt_serial']=api.agent.get('plan_attempt_serial',0)+1
    from .plan_drafts import retain
    draft=retain(api,idea_id,q,steps)
    problem={'status':'DEFERRED','reason':'PLAN_REVISION_REQUIRED','idea_id':idea_id,
             'qualification_id':q,'issue':issue,'fingerprint':fingerprint,'same_attempts':attempts,
             'issue_signature':signature,'issue_counts':counts,'idle_rounds':0,
             'draft_available':bool(draft),'draft_sha256':draft.get('sha256') if draft else None,
             'next_action':'Read the current draft. For response references use bind_deposit_step_response with separate actual source_step_id and documented response_pointer; do not write templates or JSON binding syntax yourself. For literal fields use edit_deposit_plan_step. Both require current draft_sha256 and validate the whole plan. No permission was created.'}
    api.agent['planning_repair']=problem
    api.event('deposit_plan_revision_required',problem)
    return problem


def legacy_problem(state, agent):
    """Recognize the recorded old forbidden-header error, never narrative blockers."""
    if agent.get('work_kind')!='LOCAL' or agent.get('planning_repair'):
        return None
    calls={}
    for item in agent.get('history',[]):
        if item.get('type')=='function_call' and item.get('name')=='record_deposit_execution_plan':
            calls[item.get('call_id')]=item
        if item.get('type')!='function_call_output' or item.get('call_id') not in calls:
            continue
        try:
            output=json.loads(item.get('output',''))
            args=json.loads(calls[item['call_id']]['arguments'])
        except (ValueError,KeyError,TypeError):
            continue
        if not isinstance(output,dict) or not isinstance(args,dict):
            continue
        message=str(output.get('reason','')).casefold()
        if (not any(s in message for s in ('authentication/routing/framing headers',
                 'authentication, routing and framing headers must not be supplied'))
                or output.get('error_type') not in {'HttpPolicyError','ValueError'}):
            continue
        idea=next((i for i in state['ideas'] if i['id']==args.get('idea_id') and i.get('status') not in {'REJECTED','COMPLETED'}),None)
        if not idea:
            continue
        current=next((q for q in state.get('deposit_qualifications',[]) if q['id']==idea.get('qualification_id')),None)
        if not current or not current.get('admissible') or current['plan'].get('execution_steps'):
            continue
        return {'status':'DEFERRED','reason':'PLAN_REVISION_REQUIRED','idea_id':idea['id'],
                'qualification_id':idea.get('qualification_id'),'same_attempts':1,
                'fingerprint':hashlib.sha256(canonical(args.get('steps',[])).encode()).hexdigest(),
                'issue':{'code':'HEADERS_INVALID','step_id':'',
                         'next_action':'Remove Authorization/framing headers; use a named credential_id requirement, valid earlier-step JSON pointers and a raw export body.'},
                'next_action':'Retry record_deposit_execution_plan for the SAME IDEA using its actual docs. Old tool validation is repairable; no grant or upload is authorized.'}
    return None


def complete(api, output):
    if api.agent.get('work_kind')!='LOCAL':
        return output
    state=api.engine.state;agent=api.agent
    repair=agent.get('planning_repair')
    if repair:
        start=agent.pop('planning_round_attempt_start',None)
        if start is not None and agent.get('plan_attempt_serial',0)==start:
            repair['idle_rounds']=repair.get('idle_rounds',0)+1
            api.event('deposit_plan_repair_no_progress',{'idea_id':repair['idea_id'],'idle_rounds':repair['idle_rounds'],'issue':repair['issue']})
        blocked=stalled(repair)
        repair['stalled']=blocked
        output.update(status='BLOCKED' if blocked else 'CONTINUE',
             reason_for_stopping='PLAN_REPAIR_STALLED: unresolved issue repeated or two rounds without a plan edit' if blocked else 'PLAN_REVISION_REQUIRED')
        output['unexplored_leads']=[repair['issue']['next_action']+' Retry existing '+repair['idea_id']+'.'] if not blocked else []
        if blocked:
            api.event('deposit_plan_repair_stalled',{'idea_id':repair['idea_id'],'issue':repair['issue'],'same_attempts':repair['same_attempts'],'idle_rounds':repair.get('idle_rounds',0)})
        return output
    agent.pop('planning_round_attempt_start',None)
    if agent.get('execution_plan_only'):
        planned=[i for i in state['ideas'] if i.get('execution_planning_agent_id')==agent['id']
                 and any(q['id']==i.get('qualification_id') and q['plan'].get('execution_steps') for q in state.get('deposit_qualifications',[]))]
        if planned:
            output['handoff_leads']=list(dict.fromkeys(output.get('handoff_leads',[])+output.get('unexplored_leads',[])+[
                'Current plan '+i['id']+' needs independent review and operator setup: '+', '.join(next(q['reasons'] for q in state['deposit_qualifications'] if q['id']==i['qualification_id'])) for i in planned]))
            output.update(status='COMPLETED',unexplored_leads=[],reason_for_stopping='Data-only plan recorded; review/setup/execution handed off')
    return output


def begin_round(agent):
    agent['planning_round_attempt_start']=agent.get('plan_attempt_serial',0)


def stalled(repair):
    return bool(repair.get('stalled') or repair.get('same_attempts',0)>=3 or repair.get('idle_rounds',0)>=2)
