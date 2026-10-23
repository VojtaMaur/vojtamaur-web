"""Failed sandbox executions become independent diagnoses, never successful tests."""
import copy,hashlib,uuid
from .storage import now


def capture(api,plan,experiment):
    from .research_tasks import enabled,revision
    if api.engine.state['config'].get('coding_backend','legacy')!='legacy' or not enabled(api.engine.state) or api.agent.get('work_kind')!='LOCAL' or type(experiment.get('returncode')) is not int or experiment['returncode']==0: return
    script=next((a for a in experiment['artifact_inventory'] if a['path']==plan['script']['path']),None)
    if not script: return
    receipt={'artifacts':[script]}
    from .prototype_review import snapshot
    try: snapshot(api,receipt)
    except (OSError,ValueError) as error:
        experiment['failure_snapshot_error']=type(error).__name__+': '+str(error)[:800]
        return
    experiment['failure_evidence']={'prototype_plan':copy.deepcopy(plan),'script':script,
        'audit_artifacts':receipt['audit_artifacts'],'research_revision':revision(api.idea(plan['idea_id'])),
        'package_receipt_ids':[r['id'] for r in api.engine.state.get('package_installations',[]) if r.get('agent_id')==api.agent['id'] and r.get('status')=='COMPLETED'],
        'operator_notes_count':len(api.agent.get('operator_notes',[])),
        'meaning':'Frozen code and nonzero exit; not a test or mechanism rejection.'}


def last(state,agent,idea_id):
    from .research_tasks import revision
    idea=next((i for i in state['ideas'] if i['id']==idea_id),None)
    if not idea:return None
    for e in reversed(state.get('experiments',[])):
        if e.get('agent_id')!=agent['id'] or e.get('idea_id')!=idea_id:continue
        if e.get('status')=='COMPLETED' and e.get('returncode')==0 and e.get('prototype_plan',{}).get('research_revision')==revision(idea):return None
        if e.get('failure_evidence',{}).get('research_revision')==revision(idea):return e
    return None


def local_issue(state,agent,idea_id):
    e=last(state,agent,idea_id)
    if not e:return None
    review=e.get('failure_review')
    if not review:return {'status':'DEFERRED','reason':'FAILED_CODE_REVIEW_PENDING','experiment_id':e['experiment_id'],
        'next_action':'This nonzero Docker execution needs independent diagnosis of the frozen code and traceback. It is not a host contract failure. Do not blindly rerun.'}
    if review['disposition']=='DEFER':return {'status':'DEFERRED','reason':'FAILED_CODE_REPAIR_DEFERRED','experiment_id':e['experiment_id'],'diagnosis':review}
    return None


def pending(state,agent):
    result=[]
    for owner in state['agents']:
        if owner.get('work_kind')!='LOCAL':continue
        for idea in state['ideas']:
            e=last(state,owner,idea['id'])
            if not e or e.get('failure_review') or idea.get('status')=='REJECTED' or agent['id'] in {owner['id'],idea.get('agent_id')}:continue
            result.append({'kind':'PROTOTYPE_FAILURE','target_id':e['experiment_id'],'idea_id':idea['id'],
                'revision':e['failure_evidence']['prototype_plan']['id'],'documents':[]})
    return result


def packet(state,agent,task):
    e=next((e for e in state.get('experiments',[]) if e['experiment_id']==task.get('target_id')),None)
    if not e or not e.get('failure_evidence'):return dict(task,stage='STALE')
    return dict(task,stage='DONE' if e.get('failure_review') else 'DIAGNOSE_CODE',
        failed_execution={k:e.get(k) for k in ('experiment_id','idea_id','agent_id','returncode','output','argv','failure_evidence','failure_review')},
        candidate=next(i for i in state['ideas'] if i['id']==e['idea_id']),
        next_action='Read the exact failed script and actual traceback with read_failed_experiment, then record_failure_diagnosis. '
        'Compare implementation to the intended algorithm, not just the last parser exception. Identify missing correction/decoder logic and concrete library/API usage where useful. '
        'Give implementable repair steps and a small decisive success/failure test. Never weaken assertions to make exit zero. No prototype award or candidate rejection.')


def selected(api,experiment_id):
    e=next((e for e in api.engine.state.get('experiments',[]) if e['experiment_id']==experiment_id and e.get('failure_evidence')),None)
    if not e:raise ValueError('Choose a frozen failed experiment ID')
    task=api.agent.get('review_assignment',{})
    allowed=(api.agent.get('work_kind')=='REVIEW' and task.get('kind')=='PROTOTYPE_FAILURE' and task.get('target_id')==experiment_id
        or api.agent.get('work_kind')=='LOCAL' and e['agent_id']==api.agent['id'] and api.agent.get('research_assignment',{}).get('target_id')==e['idea_id'])
    if not allowed:raise ValueError('Read only your assigned failed experiment')
    return e


def source(api,e):
    from .prototype_review import artifact_bytes
    f=e['failure_evidence']
    data=artifact_bytes(api,{'agent_id':e['agent_id'],'audit_artifacts':f['audit_artifacts']},f['script'])
    if hashlib.sha256(data).hexdigest()!=f['script']['sha256']:raise ValueError('Failed code snapshot changed')
    return data.decode('utf-8')


def missing(api,e):
    from .review_tasks import _subtract
    return _subtract([[0,len(source(api,e))]],api.agent.get('failure_script_reads',{}).get(e['experiment_id'],[]))


def read(api,experiment_id,offset=0,limit=12000):
    e=selected(api,experiment_id)
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=16000:raise ValueError('Invalid failure script paging')
    code=source(api,e);end=min(len(code),offset+limit)
    api.agent.setdefault('failure_script_reads',{}).setdefault(experiment_id,[]).append([offset,end])
    api.event('failed_code_read',{'experiment_id':experiment_id,'offset':offset,'end':end,'sha256':e['failure_evidence']['script']['sha256']})
    return {'experiment_id':experiment_id,'script_path':e['failure_evidence']['script']['path'],'script_sha256':e['failure_evidence']['script']['sha256'],
        'text':code[offset:end],'offset':offset,'end':end,'total_chars':len(code),'next_offset':end if end<len(code) else None,
        'returncode':e['returncode'],'traceback':str(e.get('output',''))[-16000:],
        'prototype_plan':e['failure_evidence']['prototype_plan'],'diagnosis':e.get('failure_review')}


def diagnose(api,experiment_id,problem_kind,diagnosis,repair_steps,success_check,disposition):
    e=selected(api,experiment_id)
    if api.agent.get('work_kind')!='REVIEW' or api.agent['id'] in {e['agent_id'],api.idea(e['idea_id']).get('agent_id')}:
        return {'status':'DEFERRED','reason':'INDEPENDENT_FAILURE_REVIEW_REQUIRED'}
    if e.get('failure_review'):return e['failure_review']
    gaps=missing(api,e)
    if gaps:return {'status':'DEFERRED','reason':'OWN_FAILED_SCRIPT_READ_REQUIRED','missing_ranges':gaps}
    if problem_kind not in {'ALGORITHM_MISSING','DEPENDENCY','CODE_BUG','CONTRACT_MISMATCH','ENVIRONMENT','UNKNOWN'} or disposition not in {'REPAIR','DEFER'}:raise ValueError('Invalid diagnostic category')
    if not isinstance(diagnosis,str) or not 20<=len(diagnosis)<=6000 or not isinstance(success_check,str) or not 20<=len(success_check)<=2000:raise ValueError('Concrete diagnosis and decisive success check required')
    if not isinstance(repair_steps,list) or not 1<=len(repair_steps)<=8 or any(not isinstance(s,str) or not 10<=len(s)<=2000 for s in repair_steps):raise ValueError('Provide 1..8 concrete repair steps')
    record={'id':'DEBUG-'+uuid.uuid4().hex[:16],'experiment_id':experiment_id,'idea_id':e['idea_id'],'agent_id':api.agent['id'],
        'problem_kind':problem_kind,'diagnosis':diagnosis,'repair_steps':repair_steps,'success_check':success_check,'disposition':disposition,'time':now(),
        'meaning':'Independent debugging guidance only; failed execution remains failed.'}
    e['failure_review']=record
    api.event('failure_diagnosis_recorded',record)
    return record


def repair_issue(api,idea_id,script,repair_experiment_id,repair_notes,repair_check):
    e=last(api.engine.state,api.agent,idea_id)
    if not e:return None
    issue=local_issue(api.engine.state,api.agent,idea_id)
    if issue:return issue
    kind=e['failure_review']['problem_kind']
    dependency_changed=kind=='DEPENDENCY' and any(r.get('agent_id')==api.agent['id'] and r.get('status')=='COMPLETED'
        and r['id'] not in e['failure_evidence'].get('package_receipt_ids',[]) for r in api.engine.state.get('package_installations',[]))
    environment_resolved=kind=='ENVIRONMENT' and len(api.agent.get('operator_notes',[]))>e['failure_evidence'].get('operator_notes_count',0)
    if script['sha256']==e['failure_evidence']['script']['sha256'] and not dependency_changed and not environment_resolved:
        return {'status':'DEFERRED','reason':'FAILED_SCRIPT_UNCHANGED','diagnosis':e['failure_review'],'next_action':'Implement the root-cause repair, then update the plan. Renaming or repeating failed code is not progress.'}
    if repair_experiment_id!=e['experiment_id'] or not isinstance(repair_notes,str) or not 20<=len(repair_notes)<=4000 or not isinstance(repair_check,str) or not 20<=len(repair_check)<=2000:
        return {'status':'DEFERRED','reason':'ROOT_CAUSE_REPAIR_REQUIRED','experiment_id':e['experiment_id'],'diagnosis':e['failure_review'],
            'next_action':'In record_prototype_plan supply concrete repair_notes linking actual code edits to the diagnosis, and repair_check naming the decisive test. The model-facing tool binds the failed experiment automatically; do not invent or supply a TEST-ID. Fix the algorithm, not merely its parser or claims.'}
    return None


def hold(engine):
    for agent in engine.state['agents']:
        if agent.get('work_kind')!='LOCAL' or agent['status']!='PENDING':continue
        idea_id=agent.get('research_assignment',{}).get('target_id')
        if not idea_id:continue
        issue=local_issue(engine.state,agent,idea_id)
        from .research_tasks import local_candidates
        if issue and not local_candidates(engine.state,agent):
            agent.update(status='BLOCKED',reason_for_stopping=issue['reason'])
            engine.store.commit(engine.state,'prototype_waiting_for_diagnosis',issue,agent['id'])
