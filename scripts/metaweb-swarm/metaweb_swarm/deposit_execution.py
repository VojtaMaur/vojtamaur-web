"""Resumable, provider-independent qualified deposit sequences."""
import copy
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit
from .storage import canonical, now
from .policy import action_hash
from . import deposit_plan, flow_vault
from .http_transport import normalize_request, _origin, READ_METHODS

ACTIVE={'READY','RUNNING','PAUSED','AWAITING_APPROVAL'}

def needs_planning(state):
    return any(i.get('status')!='REJECTED' and any(q['id']==i.get('qualification_id') and q.get('admissible')
               and bool({'EXECUTABLE_FLOW_REQUIRED','MULTI_STEP_EXECUTION_UNAVAILABLE'} & set(q.get('reasons',[]))) for q in state.get('deposit_qualifications',[])) for i in state['ideas'])

def lease_totals(state, excluding=''):
    """Future calls are reserved once, attempts already in the HTTP ledger are charged there."""
    totals={'requests':0,'actions':0,'body':0,'total':0}
    ledger=state.get('http_requests',[])
    for flow in state.get('deposit_executions',[]):
        if flow['id']==excluding or not flow.get('lease_active'): continue
        attempted={r.get('flow_step') for r in ledger if r.get('flow_id')==flow['id']}
        for s in flow['steps']:
            if s['id'] in attempted: continue
            totals['requests']+=1
            totals['actions']+=int(s['method'] not in READ_METHODS or bool(s['credential_id']))
            totals['body']+=s['max_body_bytes']
            totals['total']+=s['max_body_bytes']+flow['response_ceiling']+1
    return totals

def record_plan(api, idea_id, steps):
    state=api.engine.state; idea=api.idea(idea_id)
    if api.agent.get('work_kind') not in {'DISCOVERY','REVIEW','LOCAL'} or idea['status']=='REJECTED':
        raise ValueError('Execution planning requires an active candidate and a planning/review/implementation role')
    if any(f['idea_id']==idea_id for f in state.get('deposit_executions',[])):
        raise ValueError('An execution already binds this candidate; do not rewrite a partially executed plan')
    old=next((q for q in state.get('deposit_qualifications',[]) if q['id']==idea.get('qualification_id')),None)
    if not old or not old['admissible']: raise ValueError('Use an existing admitted qualification')
    export={'filename':old['plan']['export_path'],'bytes':old['export_bytes'],'sha256':old['export_sha256']}
    compiled=deposit_plan.validate(steps,state['config'],export)
    if compiled['steps'][0]['url']!=old['plan']['upload_url'] or compiled['steps'][0]['method']!=old['plan']['method'] or compiled['steps'][0]['credential_id']!=old['plan']['credential_id']:
        raise ValueError('First request must match the qualified endpoint/method/credential')
    plan=copy.deepcopy(old['plan']);plan['execution_steps']=compiled['steps']
    plan['operation_steps']=[{'method':s['method'],'purpose':s['purpose'],'sends_export':s['sends_export'],'uses_credential':bool(s['credential_id'])} for s in steps]
    # Assess with the discovery owner's source receipts, retaining ownership.
    from .engine import ToolAPI
    from .workspace import Workspace
    owner=next(a for a in state['agents'] if a['id']==old['agent_id'])
    owner_api=ToolAPI(api.engine,owner,Workspace(api.engine.store.run_dir/'snapshot',api.engine.store.run_dir/'agents'/owner['id']/'workspace'))
    q=owner_api.check_deposit_target(plan)
    previous=idea['qualification_id']
    idea.update(qualification_id=q['id'],deposit_plan=q['plan'],deposit_feasibility=q['status'],
                status='BLOCKED' if q['reasons'] else 'INVESTIGATING',blocker=q['status'] if q['reasons'] else '')
    if api.agent.get('work_kind')=='LOCAL': idea['execution_planning_agent_id']=api.agent['id']
    old['retention']={'status':'RETAINED','candidate_id':idea_id}
    q['retention']={'status':'RETAINED','candidate_id':idea_id}
    api.event('deposit_execution_plan_recorded',{'idea_id':idea_id,'previous_qualification':previous,
              'qualification_id':q['id'],'plan_sha256':compiled['sha256'],'steps':len(steps),
              'external_actions':compiled['actions'],'status':q['status'],'author_agent_id':api.agent['id'],
              'meaning':'Data-only protocol recorded; prior audit/approval does not authorize changed sequence.'})
    return {'status':q['status'],'qualification_id':q['id'],'plan_sha256':compiled['sha256'],'external_actions':compiled['actions']}

def gate(api, flow):
    state=api.engine.state;config=state['config'];idea=api.idea(flow['idea_id'])
    q=next((q for q in state.get('deposit_qualifications',[]) if q['id']==idea.get('qualification_id')),None)
    if not q or q['id']!=flow['qualification_id'] or q['status']!='READY_FOR_AUDIT': return 'QUALIFICATION_CHANGED_OR_NOT_READY'
    from .carrier_screening import registry_matches, improvements_allowed
    if not improvements_allowed(config) and registry_matches(api.engine.baseline,q['plan']['provider'],(urlsplit(q['plan']['upload_url']).hostname or '').casefold()):
        return 'ALREADY_KNOWN_BASELINE'
    try:
        compiled=deposit_plan.validate(q['plan'].get('execution_steps',[]),config,
                                      {'bytes':q['export_bytes'],'sha256':q['export_sha256'],'filename':q['plan']['export_path']})
    except ValueError:
        return 'PLAN_NO_LONGER_WITHIN_POLICY_OR_RESOURCES'
    if config['max_http_response_bytes']>flow['response_ceiling']: return 'RESPONSE_CEILING_CHANGED'
    for s in compiled['steps']:
        if s['credential_id']:
            grant=next((c for c in config.get('http_credentials',[]) if c['id']==s['credential_id']),None)
            if not grant or not os.getenv(grant['env']): return 'ACCOUNT_SETUP_REQUIRED'
    if compiled['sha256']!=flow['plan_sha256'] or flow['steps']!=compiled['steps']: return 'EXECUTION_PLAN_CHANGED'
    if idea['status']=='REJECTED' or idea.get('payment') not in {'FREE','ONE_TIME'} or idea.get('requires_ongoing_payments'): return 'PAYMENT_OR_CANDIDATE_NOT_ELIGIBLE'
    review=idea.get('critique',{})
    reviewer=next((a for a in state['agents'] if a['id']==review.get('agent_id')),None)
    if not (review.get('verdict')=='PASS' and review.get('qualification_id')==q['id'] and reviewer
            and reviewer['role']=='Evidence Auditor' and reviewer['id']!=idea['agent_id']): return 'QUALIFIED_PLAN_NEEDS_INDEPENDENT_AUDIT'
    if config.get('http_access')!='enabled' or config.get('external_scope')!='external': return 'EXTERNAL_SCOPE_DISABLED'
    return api.implementation_allowed(idea['id'])

def request_permit(api, descriptor):
    ctx=getattr(api,'_deposit_context',None)
    if not ctx or descriptor['wire_sha256']!=ctx['wire_sha256']: return None
    flow=next((f for f in api.engine.state.get('deposit_executions',[]) if f['id']==ctx['flow_id']),None)
    if not flow or flow['agent_id']!=api.agent['id'] or gate(api,flow): return None
    if api.engine.state['config'].get('approval_required',True):
        a=next((a for a in api.engine.state['approvals'] if a['id']==flow.get('approval_id')),None)
        if not a or a['status']!='APPROVED' or a['hash']!=flow['approval_hash'] or action_hash(a['action'])!=a['hash']: return None
    return ctx

def _capacity(api,flow):
    state=api.engine.state;cfg=state['config']
    flow['lease_active']=True
    held=lease_totals(state)
    ledger=state.get('http_requests',[]);external=state.get('external_actions',[])
    if len(ledger)+held['requests']>cfg['max_http_requests']: return 'MAX_HTTP_REQUESTS'
    if len(external)+held['actions']>cfg['max_external_actions']: return 'MAX_EXTERNAL_ACTIONS'
    if sum(r['action']['payload'].get('bytes',0) for r in external)+held['body']>cfg['max_external_bytes']: return 'MAX_EXTERNAL_BYTES'
    if sum(r['budget_bytes'] for r in ledger)+held['total']>cfg['max_http_total_bytes']: return 'MAX_HTTP_TOTAL_BYTES'
    return api.check_model_budget()

def _finish(api,flow,status,reason='',release=True):
    flow.update(status=status,reason=reason,updated_at=now())
    if release: flow['lease_active']=False
    idea=api.idea(flow['idea_id'])
    if status not in {'COMPLETED','READY','RUNNING'} and idea['status']!='REJECTED':
        idea.update(status='LIMIT_REACHED' if status=='LIMIT_REACHED' else 'BLOCKED',
                    blocker=reason or status,next_action='Inspect '+flow['id']+' and its per-step HTTP receipts before continuing; never blindly repeat an unknown remote write.')
    api.event('deposit_execution_checkpoint',{'id':flow['id'],'idea_id':flow['idea_id'],'status':status,
              'reason':reason,'completed_steps':len(flow['completed_steps'])})
    return public(flow)

def public(flow):
    return {k:flow.get(k) for k in ('id','idea_id','qualification_id','plan_sha256','status','reason',
                                   'approval_id','completed_steps','receipt')}

async def execute(api,idea_id):
    if api.agent.get('work_kind')!='LOCAL': return {'status':'BLOCKED','reason':'IMPLEMENTATION_ROLE_REQUIRED'}
    state=api.engine.state;cfg=state['config'];idea=api.idea(idea_id)
    with api.engine.mutex:
        flows=state.setdefault('deposit_executions',[])
        flow=next((f for f in flows if f['idea_id']==idea_id),None)
        if not flow and api.agent.get('execution_plan_only'): return {'status':'BLOCKED','reason':'PLANNING_ONLY_WAIT_FOR_CURRENT_AUDIT'}
        if flow and flow['agent_id']!=api.agent['id']: return {'status':'BLOCKED','reason':'EXECUTION_OWNER_MISMATCH'}
        if flow and flow['status'] in {'COMPLETED','FAILED','UNKNOWN','REJECTED'}: return public(flow)
        if flow and flow['status']=='RUNNING' and flow['id'] in getattr(api.engine,'_running_deposits',set()):
            return {'status':'BLOCKED','reason':'EXECUTION_ALREADY_RUNNING'}
        if not flow:
            q=next((q for q in state.get('deposit_qualifications',[]) if q['id']==idea.get('qualification_id')),None)
            if not q or not q['plan'].get('execution_steps'): return {'status':'BLOCKED','reason':'EXECUTABLE_FLOW_REQUIRED'}
            compiled=deposit_plan.validate(q['plan']['execution_steps'],cfg,{'bytes':q['export_bytes'],'sha256':q['export_sha256'],'filename':q['plan']['export_path']})
            flow={'id':'FLOW-'+uuid.uuid4().hex[:16],'idea_id':idea_id,'agent_id':api.agent['id'],
                  'qualification_id':q['id'],'plan_sha256':compiled['sha256'],'steps':compiled['steps'],
                  'export':{'filename':q['plan']['export_path'],'bytes':q['export_bytes'],'sha256':q['export_sha256']},
                  'status':'READY','completed_steps':[],'lease_active':False,'created_at':now(),
                  'response_ceiling':cfg['max_http_response_bytes']}
            # No record/approval if prerequisites are not satisfied.
            reason=gate(api,flow)
            if reason: return {'status':'BLOCKED','reason':reason}
            flows.append(flow);api.event('deposit_execution_created',public(flow))
        reason=gate(api,flow)
        if reason: return _finish(api,flow,'BLOCKED',reason)
        reason=_capacity(api,flow)
        if reason: return _finish(api,flow,'LIMIT_REACHED',reason)
        action={'idea_id':idea_id,'kind':'PUBLISH','description':'Execute reviewed exact-export HTTP sequence and verify public bytes',
                'target':flow['steps'][0]['url'],'payload':{'plan_sha256':flow['plan_sha256'],'qualification_id':flow['qualification_id'],
                'export':flow['export'],'steps':flow['steps'],'bytes':sum(s['max_body_bytes'] for s in flow['steps'])}}
        digest=action_hash(action)
        if cfg.get('approval_required',True):
            a=next((a for a in state['approvals'] if a['hash']==digest),None)
            if not a:
                a={'id':f"APPROVAL-{len(state['approvals'])+1:04d}",'agent_id':api.agent['id'],'status':'PENDING',
                   'action':action,'hash':digest,'created_at':now(),'decision':None,'note':'','executed':False,'executor':'deposit_sequence'}
                state['approvals'].append(a);api.event('approval_requested',a)
            flow.update(approval_id=a['id'],approval_hash=digest)
            if a['status']!='APPROVED':
                return _finish(api,flow,'AWAITING_APPROVAL' if a['status']=='PENDING' else 'REJECTED',
                               'HUMAN_APPROVAL_REQUIRED' if a['status']=='PENDING' else 'ACTION_DECLINED')
        # Reacquire a durable lease only AFTER approval, rechecking all budgets.
        flow['lease_active']=True
        api.engine._running_deposits=getattr(api.engine,'_running_deposits',set())
        api.engine._running_deposits.add(flow['id'])
        flow['status']='RUNNING';api.event('deposit_execution_started',public(flow))
    try:
        return await _drive(api,flow)
    finally:
        api.engine._running_deposits.discard(flow['id'])
        api.__dict__.pop('_deposit_context',None)

async def _drive(api,flow):
    cfg=api.engine.state['config'];state=api.engine.state
    source='deposit-input/'+flow['id']+'/'+flow['export']['filename'].split('/')[-1]
    try:
        api.materialize_export(flow['export']['filename'],source)
    except (ValueError,OSError):
        return _finish(api,flow,'BLOCKED','EXPORT_UNAVAILABLE_OR_CHANGED')
    if any(api.workspace.file_info(source)[k]!=flow['export'][k] for k in ('bytes','sha256')):
        return _finish(api,flow,'BLOCKED','EXPORT_BYTES_CHANGED')
    responses={}; records={}
    for s in flow['steps']:
        with api.engine.mutex:
            prior=next((r for r in state.get('http_requests',[]) if r.get('flow_id')==flow['id'] and r.get('flow_step')==s['id']),None)
            if prior:
                if not _success(prior,s):
                    status='UNKNOWN' if prior['status'] in {'RESERVED','UNKNOWN'} else 'FAILED'
                    return _finish(api,flow,status,'PREVIOUS_STEP_REQUIRES_RECONCILIATION',release=status!='UNKNOWN')
                records[s['id']]=prior
                if prior.get('private_response'):
                    try: responses[s['id']]=flow_vault.load(api.engine.store.run_dir,prior['private_response'])
                    except (ValueError,OSError): return _finish(api,flow,'BLOCKED','PRIVATE_RESPONSE_UNAVAILABLE_OR_CHANGED')
                if s['id'] not in flow['completed_steps']:
                    flow['completed_steps'].append(s['id']);api.event('deposit_step_recovered',{'flow_id':flow['id'],'step':s['id'],'request_id':prior['id']})
                continue
            if (api.engine.store.run_dir/'PAUSE.flag').exists(): return _finish(api,flow,'PAUSED','PAUSE_REQUESTED',release=False)
            reason=gate(api,flow)
            if reason: return _finish(api,flow,'BLOCKED',reason)
            try:
                refs=set(deposit_plan.references(s['url'])+deposit_plan.references(json.loads(s['headers_json'] or '{}'))+deposit_plan.references(json.loads(s['body_json']) if s['body_json'] else None))
                for ref in refs:
                    if ref not in responses: raise ValueError('Response binding unavailable')
                    if s['max_age_seconds'] and (datetime.now(timezone.utc)-datetime.fromisoformat(records[ref]['finished_at'])).total_seconds()>s['max_age_seconds']:
                        return _finish(api,flow,'BLOCKED','RESPONSE_CAPABILITY_EXPIRED')
                url=deposit_plan.resolve_url(s['url'],responses)
                if _origin(urlsplit(url)) not in s['allowed_origins']: raise ValueError('Returned endpoint outside reviewed origins')
                request={'url':url,'method':s['method'],'headers':deposit_plan.resolve(json.loads(s['headers_json'] or '{}'),responses,flow['export']),
                         'credential_id':s['credential_id']}
                if s['body_json']: request['body_json']=deposit_plan.resolve(json.loads(s['body_json']),responses,flow['export'])
                if s['sends_export']: request['upload_path']=source
                descriptor,prepared=normalize_request(request,cfg,api.workspace)
                if len(prepared.body)>s['max_body_bytes']: raise ValueError('Resolved step body exceeds its reviewed ceiling')
                needed=any(s['id'] in set(deposit_plan.references(later['url'])+deposit_plan.references(json.loads(later['headers_json'] or '{}'))+deposit_plan.references(json.loads(later['body_json']) if later['body_json'] else None)) for later in flow['steps'])
                api._deposit_context={'flow_id':flow['id'],'flow_step':s['id'],'wire_sha256':descriptor['wire_sha256'],'approval_id':flow.get('approval_id'),'private_bindings':needed,
                                      'private_target':bool(deposit_plan.REF.search(s['url'])) and s['id']!=flow['steps'][-1]['id']}
            except (ValueError,KeyError,IndexError,TypeError):
                return _finish(api,flow,'BLOCKED','RESPONSE_BINDING_OR_POLICY_FAILED')
        try:
            record=await api.http_request(request,flow['idea_id'],s['purpose'])
        finally: api.__dict__.pop('_deposit_context',None)
        with api.engine.mutex:
            if not record.get('id'):
                return _finish(api,flow,record.get('status','BLOCKED'),record.get('reason','STEP_NOT_SENT'))
            if not _success(record,s):
                uncertain=record['status'] in {'RESERVED','UNKNOWN'}
                return _finish(api,flow,'UNKNOWN' if uncertain else 'FAILED','HTTP_STEP_NOT_SUCCESSFUL',release=not uncertain)
            records[s['id']]=record
            if record.get('private_response'):
                try: responses[s['id']]=flow_vault.load(api.engine.store.run_dir,record['private_response'])
                except (ValueError,OSError): return _finish(api,flow,'BLOCKED','PRIVATE_RESPONSE_UNAVAILABLE_OR_CHANGED')
            flow['completed_steps'].append(s['id'])
            api.event('deposit_step_completed',{'flow_id':flow['id'],'idea_id':flow['idea_id'],'step':s['id'],'request_id':record['id']})
    payload=next(s for s in flow['steps'] if s['sends_export'])
    try:
        with api.engine.mutex:
            existing=records[payload['id']].get('receipt')
            flow['receipt']=existing if existing and existing.get('download_request_id')==records[flow['steps'][-1]['id']]['id'] else api.verify_http_copy(records[payload['id']]['id'],records[flow['steps'][-1]['id']]['id'],source)
            flow['receipt']['flow_id']=flow['id']
            flow['receipt']['meaning']='Anonymous final GET matched exact retained export after all planned successful operations; no guarantee of permanence.'
            if flow.get('approval_id'):
                next(a for a in state['approvals'] if a['id']==flow['approval_id'])['executed']=True
            return _finish(api,flow,'COMPLETED')
    except ValueError:
        return _finish(api,flow,'FAILED','PUBLIC_READBACK_HASH_MISMATCH_OR_INVALID_RECEIPT')

def _success(record,step):
    return (record['status'] in {'COMPLETED','VERIFIED'} and record.get('response',{}).get('status') in step['success_codes']
            and not record.get('response',{}).get('truncated') and not record.get('response',{}).get('error'))

async def resume(engine):
    """Advance already requested flows before any further paid role dispatch."""
    from .engine import ToolAPI
    from .workspace import Workspace
    for flow in list(engine.state.get('deposit_executions',[])):
        if flow['status'] not in ACTIVE: continue
        if flow['status']=='AWAITING_APPROVAL':
            a=next((a for a in engine.state['approvals'] if a['id']==flow.get('approval_id')),None)
            if not a or a['status']=='PENDING': continue
        agent=next(a for a in engine.state['agents'] if a['id']==flow['agent_id'])
        api=ToolAPI(engine,agent,Workspace(engine.store.run_dir/'snapshot',engine.store.run_dir/'agents'/agent['id']/'workspace'))
        engine.state['active_batch_started_at']=now()
        result=await execute(api,flow['idea_id'])
        engine.state['active_batch_started_at']=None
        if result['status']=='COMPLETED':
            agent.update(status='COMPLETED',reason_for_stopping='Requested deposit sequence finished with exact public byte receipt',
                         summary='Host executor completed '+flow['id']+'; inspect per-step HTTP receipts.')
        elif result['status'] not in {'RUNNING','READY'}:
            agent.update(status='BLOCKED',reason_for_stopping=result.get('reason') or result['status'])
        api.event('deposit_execution_resume_result',public(flow))

def operator_command(run_dir, idea_id, steps=None):
    """Operator CLI entry, no inference backend, unchanged run permissions/budgets."""
    import time
    from .engine import Engine, ToolAPI, refresh_reports
    from .storage import Store
    from .workspace import Workspace
    store=Store(run_dir)
    try: name=store.load().get('backend') or 'demo'
    finally: store.close()
    engine=Engine(run_dir,None,name)
    engine.console_enabled=True
    try:
        idea=next((i for i in engine.state['ideas'] if i['id']==idea_id),None)
        if not idea: raise ValueError('Unknown IDEA ID')
        agent=next((a for a in engine.state['agents'] if a['id']==idea['agent_id']),None) if steps is not None else next((a for a in engine.state['agents'] if a.get('work_kind')=='LOCAL'),None)
        if not agent: raise ValueError('Run needs an assigned implementation role')
        if steps is None: agent['execution_plan_only']=False  # Explicit operator execution still goes through full gate().
        api=ToolAPI(engine,agent,Workspace(engine.store.run_dir/'snapshot',engine.store.run_dir/'agents'/agent['id']/'workspace'))
        if steps is not None: return record_plan(api,idea_id,steps)
        if (engine.store.run_dir/'PAUSE.flag').exists(): return {'status':'PAUSED','reason':'PAUSE_REQUESTED; use resume to clear the operator flag'}
        if engine.state.get('active_batch_started_at'):
            elapsed=max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(engine.state['active_batch_started_at'])).total_seconds())
            engine.state['active_seconds']+=elapsed
            api.event('crash_elapsed_time_charged',{'seconds':elapsed,'basis':'Conservative wall time since interrupted execution'})
        engine.active_base_seconds=engine.state['active_seconds'];engine.active_start_time=time.monotonic()
        engine.state['active_batch_started_at']=now();api.event('operator_deposit_execution_requested',{'idea_id':idea_id,'inference':False})
        try: return __import__('asyncio').run(execute(api,idea_id))
        finally:
            engine.state['active_seconds']=engine.current_active_seconds()
            engine.state['active_batch_started_at']=None
            api.event('operator_deposit_execution_finished',{'idea_id':idea_id,'inference':False})
    finally:
        refresh_reports(engine.store,engine.state)
        engine.close()
