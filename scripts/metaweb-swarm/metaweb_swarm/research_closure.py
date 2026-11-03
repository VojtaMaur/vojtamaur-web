"""Operator-only capture of existing sketches and a bounded review/report phase."""
import hashlib
import json
from .storage import atomic_write,canonical


def prepare(engine,note,extend_tokens=0,extend_seconds=0,extend_steps=0,report_only=False):
    state=engine.state
    if state['config'].get('task_style')!='brainstorming':raise ValueError('Closure requires a brainstorming run')
    if not note.strip():raise ValueError('Operator note required')
    if any(type(v) is not int or v<0 for v in (extend_tokens,extend_seconds,extend_steps)):
        raise ValueError('Extensions must be nonnegative integers')
    if state.get('budget_reservations') or state['usage'].get('unknown_steps'):
        raise ValueError('Resolve outstanding provider reservations before closing research')
    if report_only:
        if not state['ideas']:prepare(engine,note,report_only=False)
        return prepare_report_only(engine,note,extend_tokens,extend_seconds,extend_steps)
    if state.get('research_closure',{}).get('prepared'):return state['research_closure']
    from .engine import ToolAPI,refresh_reports
    root=engine.store.run_dir
    closure=state.setdefault('research_closure',{'captured':{},'sketches':{},'note':note,
        'previous_agents':[{k:a.get(k) for k in ('id','status','reason_for_stopping','rounds')} for a in state['agents']]})
    # Snapshot the existing audit before capture adds any events; never execute
    # a recorded tool call. Arguments are untrusted proposal data only.
    for line in (root/'raw/events.jsonl').read_text(encoding='utf-8').splitlines():
        event=json.loads(line);data=event.get('data',{})
        if event.get('kind')!='sdk_tool_started' or data.get('name')!='screen_carrier':continue
        args=data.get('arguments',{})
        try:args=json.loads(args) if isinstance(args,str) else args
        except ValueError:continue
        if not isinstance(args,dict) or not isinstance(args.get('proposed_change'),str) or not args['proposed_change'].strip():continue
        ident=hashlib.sha256(canonical({'agent':event['agent_id'],'args':args}).encode()).hexdigest()[:20]
        closure['sketches'][ident]={'agent_id':event['agent_id'],'arguments':args,'event_seq':event['seq']}
    atomic_write(root/'context/CLOSURE_SKETCHES.json',canonical(closure['sketches']))
    engine.store.commit(state,'research_closure_capture_started',{'sketch_count':len(closure['sketches']),'note':note})
    for ident,sketch in closure['sketches'].items():
        if ident in closure['captured']:continue
        agent=next(a for a in state['agents'] if a['id']==sketch['agent_id']);args=sketch['arguments']
        same=next((key for key in closure['captured'] if closure['sketches'][key]['agent_id']==sketch['agent_id']
                   and closure['sketches'][key]['arguments'].get('provider','').casefold()==args.get('provider','').casefold()),None)
        if same:
            closure['captured'][ident]=closure['captured'][same]
            continue
        # Capture has no files/artifacts to touch; do not copy or rescan a full
        # agent workspace merely to retain an existing text proposal.
        api=ToolAPI(engine,agent,None)
        result=api.submit_idea({'title':args.get('provider','Unknown provider')+' — retained research sketch',
            'provider':args.get('provider',''),'mechanism':'Unverified proposal retained from prior research; inspect closure sketch '+ident,
            'summary':args['proposed_change'],'proposed_change':args['proposed_change'],
            'baseline_behavior':args.get('baseline_behavior',''),'validation_plan':args.get('validation_plan',''),
            'status':'INVESTIGATING','payment':'UNKNOWN','novelty':'Unassessed; retained for independent critique, not a new verified discovery.',
            'next_action':'Review recorded proposal and original sources; sketch '+ident+' in context/CLOSURE_SKETCHES.json.',
            'evidence':[],'artifacts':[],'scores':{},'failure_domains':[]},host_closure_capture=True)
        if result.get('id'):
            api.idea(result['id'])['closure_provisional']=True
        closure['captured'][ident]=result
        engine.store.commit(state,'research_closure_sketch_captured',{'sketch_id':ident,'result':result})
    for name,value in [('max_total_tokens',extend_tokens),('max_active_seconds',extend_seconds),('max_steps',extend_steps)]:
        state['config'][name]+=value
    for agent in state['agents']:
        if agent.get('history'):
            atomic_write(root/'raw'/f"{agent['id']}-before-closure.json",canonical(agent['history']))
            agent['history']=[]
        agent['research_closure']=True
        if agent.get('work_kind') in {'REVIEW','SYNTHESIS'}:
            extra=len(state['ideas'])+1 if agent['work_kind']=='REVIEW' else 2
            agent.update(status='PENDING',round_limit=agent['rounds']+extra,reason_for_stopping='Operator requested bounded research closure')
        else:agent.update(status='COMPLETED',reason_for_stopping='Discovery stopped for closure; prior outcome retained in closure audit')
    closure.update(prepared=True,extensions={'tokens':extend_tokens,'seconds':extend_seconds,'steps':extend_steps})
    state.update(status='PAUSED',stop_reason='Research closure prepared; resume explicitly')
    engine.store.commit(state,'research_closure_prepared',closure)
    refresh_reports(engine.store,state)
    return closure


def report_packet(state):
    from .report_packet import short
    return {'kind':'FINAL_RESEARCH_SYNTHESIS','run_id':state['run_id'],
        'counts':{'ideas':len(state['ideas']),'critiques':len(state['critiques'])},
        'ideas':[{'id':i['id'],'provider':short(i.get('provider'),120),'status':i['status'],
            'proposal':short(i.get('proposed_change') or i.get('summary'),500),
            'reviews':[{'reviewer':c.get('agent_id'),'verdict':c['verdict'],'reason':short(c.get('reason'),550)}
                       for c in state['critiques'] if c.get('idea_id')==i['id']],
            'assessment':'UNREVIEWED' if not any(c.get('idea_id')==i['id'] for c in state['critiques']) else 'SEE_RECORDED_REVIEWS'}
            for i in state['ideas']]}


def prepare_report_only(engine,note,tokens,seconds,steps):
    from .engine import refresh_reports
    state=engine.state;root=engine.store.run_dir
    if state.get('research_closure',{}).get('report_only'):return state['research_closure']
    closure=state.setdefault('research_closure',{})
    closure['before_report_only']=[{k:a.get(k) for k in ('id','status','reason_for_stopping','rounds')} for a in state['agents']]
    for field,value in [('max_total_tokens',tokens),('max_active_seconds',seconds),('max_steps',steps)]:state['config'][field]+=value
    for agent in state['agents']:
        agent['research_closure']=True
        if agent.get('work_kind')=='SYNTHESIS':
            if agent.get('history'):atomic_write(root/'raw'/f"{agent['id']}-before-final-report.json",canonical(agent['history']))
            agent.update(history=[],final_report_only=True,status='PENDING',round_limit=agent['rounds']+1,
                         reason_for_stopping='One-shot report from retained evidence; no further review')
            state['config'].setdefault('role_round_limits',{})[agent['role']]=agent['rounds']+1
        else:agent.update(status='COMPLETED',reason_for_stopping='Operator stopped further research/review; assessment gaps retained in final packet')
    closure.update(prepared=True,report_only=True,note=note,report_only_extensions={'tokens':tokens,'seconds':seconds,'steps':steps})
    atomic_write(root/'context/FINAL_RESEARCH_PACKET.json',canonical(report_packet(state)))
    state.update(status='PAUSED',stop_reason='One-shot final synthesis prepared; resume explicitly')
    engine.store.commit(state,'research_report_only_prepared',closure)
    refresh_reports(engine.store,state)
    return closure
