"""Short explicit flow task for an already retained provider; no external action."""
import copy
from .storage import now

def pending(state, agent):
    config=state['config']
    if (agent.get('work_kind')!='DISCOVERY' or config.get('task_style')!='focused'
            or not config.get('require_explicit_upload_flow')):
        return None
    captures=agent.get('flow_task_outcomes',{})
    for q in reversed(state.get('deposit_qualifications',[])):
        if q['agent_id']==agent['id'] and q.get('admissible') and q['status']=='UPLOAD_FLOW_REQUIRED' and q['id'] not in captures:
            return q['id']
    return None

def record(api, qualification_id, steps, unknown_reason=''):
    if api.agent.get('work_kind')!='DISCOVERY':
        raise ValueError('Only discovery records a flow for its own existing qualification')
    q=next((q for q in api.engine.state.get('deposit_qualifications',[]) if q['id']==qualification_id),None)
    if not q or q['agent_id']!=api.agent['id'] or not q.get('admissible'):
        raise ValueError('Use your own existing admissible qualification')
    if not isinstance(steps,list) or not isinstance(unknown_reason,str) or len(unknown_reason)>2000:
        raise ValueError('Invalid operation_steps/unknown_reason')
    if steps and unknown_reason.strip():
        raise ValueError('Supply either documented steps or a concrete unknown_reason')
    prior=api.agent.get('flow_task_outcomes',{}).get(qualification_id)
    if prior:
        if prior['operation_steps']==steps and prior['unknown_reason']==unknown_reason:
            return prior
        raise ValueError('Flow task already recorded; revise via check_deposit_target and preserve original capture')
    if not steps:
        if len(unknown_reason.strip())<5:
            raise ValueError('Empty flow needs concrete unknown_reason; do not invent a protocol')
        result={'status':'UNKNOWN','qualification_id':qualification_id,'operation_steps':[],
                'unknown_reason':unknown_reason,'time':now(),'meaning':'Explicit unresolved protocol, no execution/verification.'}
    else:
        plan=copy.deepcopy(q['plan']);plan['operation_steps']=steps
        assessed=api.check_deposit_target(plan)
        result={'status':'RECORDED','qualification_id':qualification_id,'new_qualification_id':assessed['id'],
                'qualification_status':assessed['status'],'operation_steps':steps,'unknown_reason':'','time':now(),
                'external_actions_required':assessed['plan']['required_external_actions'],
                'meaning':'Declared protocol saved; feasibility/approval/credentials unchanged, no request executed.'}
    api.agent.setdefault('flow_task_outcomes',{})[qualification_id]=result
    api.event('deposit_flow_recorded',result)
    from .deposit_handoff import recover
    recover(api.engine)
    return result
