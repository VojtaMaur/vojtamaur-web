"""Require a review action, never a scientific verdict, within normal request budgets."""
from dataclasses import replace
from .storage import canonical


def action(api):
    from .research_tasks import enabled
    state=getattr(getattr(api,'engine',None),'state',{})
    agent=getattr(api,'agent',{})
    if not enabled(state) or agent.get('work_kind') not in {'REVIEW','LOCAL'}: return None
    from .prototype_debug import last,missing
    if agent.get('work_kind')=='LOCAL':
        from .prototype_inputs import action as input_action
        preparation=input_action(api)
        if preparation:return preparation
        from .prototype_preflight import action as plan_action
        preflight=plan_action(api)
        if preflight:return preflight
        e=last(state,agent,agent.get('research_assignment',{}).get('target_id'))
        if not e or e.get('failure_review',{}).get('disposition')!='REPAIR':
            from .prototype_revision import action as revision_action
            revision=revision_action(api)
            if revision:return revision
            from .prototype_workflow import action as workflow_action
            return workflow_action(api)
        gaps=missing(api,e)
        if gaps:return {'tool':'read_failed_experiment','arguments':{'experiment_id':e['experiment_id'],'offset':gaps[0][0],'limit':min(16000,gaps[0][1]-gaps[0][0])},'next_action':'Read failed code and independent diagnosis before editing.'}
        plan=agent.get('prototype_plans',{}).get(e['idea_id'],{})
        if plan.get('repair',{}).get('experiment_id')==e['experiment_id']:
            from .prototype_workflow import enabled as workflow_enabled
            return {'tool':'execute_prototype' if workflow_enabled(api) else 'run_experiment','next_action':'Execute the repaired planned script once; the host binds this IDEA and captures the receipt. Retain the original assertions.'}
        try: changed=api.workspace.file_info(plan['script']['path'])['sha256']!=plan['script']['sha256']
        except (OSError,ValueError,KeyError): changed=False
        return {'tool':'record_prototype_plan' if changed else 'required','diagnosis':e['failure_review'],
            'exclude_tools':['note','get_research_task','run_experiment','record_test','execute_prototype'],
            'next_action':'Implement the diagnosed root cause with write_file, then record_prototype_plan with concrete repair_notes and repair_check. Host supplies repair links automatically; never invent a TEST-ID. Do not weaken assertions. Or record a concrete missing capability.'}
    from .review_tasks import current
    task=current(state,agent)
    if task and task.get('kind')=='PROTOTYPE_PLAN' and task.get('stage')=='CHECK_RELEVANCE':
        from .prototype_preflight import find,missing as missing_plan
        record=find(state,task['target_id']);gaps=missing_plan(api,record)
        if gaps:return {'tool':'read_prototype_plan','arguments':{'plan_id':record['id'],'offset':gaps[0][0],'limit':min(16000,gaps[0][1]-gaps[0][0])},'next_action':'Read actual code before relevance judgment.'}
        return {'tool':'review_prototype_plan','plan_id':record['id'],'next_action':task['next_action']}
    if task and task.get('kind')=='PROTOTYPE_FAILURE' and task.get('stage')=='DIAGNOSE_CODE':
        e=task['failed_execution'];gaps=missing(api,e)
        if gaps:return {'tool':'read_failed_experiment','arguments':{'experiment_id':e['experiment_id'],'offset':gaps[0][0],'limit':min(16000,gaps[0][1]-gaps[0][0])},'next_action':'Read frozen source and traceback; compare actual algorithm to the claim.'}
        return {'tool':'record_failure_diagnosis','experiment_id':e['experiment_id'],'next_action':task['next_action']}
    if not task or task.get('kind')!='PROTOTYPE_TEST' or task.get('stage')!='REVIEW_TEST': return None
    from .prototype_evidence import reading_requirements
    _,missing=reading_requirements(api,task['test_receipt'])
    if missing:
        return {'tool':'read_test_artifact','arguments':dict(test_id=task['target_id'],**missing[0]),
            'next_action':'Read this exact missing range now. Whole output reads are required; a prose endorsement cannot close the review.'}
    from .review_facts import seen
    if not seen(api,task['test_receipt']):
        return {'tool':'get_prototype_review_facts','arguments':{'test_id':task['target_id']},
            'next_action':'Read the host identity/input/hash facts before the scope judgment. Local functional coverage and external custody are separate axes.'}
    return {'tool':'review_prototype_test','test_id':task['target_id'],'host_facts':task['host_facts'],
        'next_action':'Store the verdict now. Choose REVISE for an unrelated/insufficient test, even when it exits zero. '
        'A metadata copy is not a repository operation; a local disk path is not a public recovery pointer. '
        'FULL/SUBCOMPONENT require actual relevant executable positive and negative cases; FULL also requires recovered original bytes. '
        'Data copied directly from the input does not prove decoding of the produced specimen. Relevant local code may be SUBCOMPONENT even without external publication. '
        'Use observed_recovery to acknowledge host byte facts and review_basis for the actual scope/local defect. External absence alone is not a local failure. Verdict is your judgment; the host does not select it.'}


def instruction_suffix(api):
    required=action(api)
    return '\nHOST REVIEW ACTION (task data, not permission to bypass any limit): '+canonical(required) if required else ''


def wrap_provider(sdk,provider,api):
    from .research_tasks import enabled
    if not enabled(getattr(getattr(api,'engine',None),'state',{})) or getattr(api,'agent',{}).get('work_kind') not in {'REVIEW','LOCAL'}:
        return provider
    from agents.models.interface import Model,ModelProvider
    class ReviewModel(Model):
        def __init__(self,inner): self.inner=inner
        def settings(self,args,kwargs):
            required=action(api)
            if not required: return args,kwargs
            tools=kwargs.get('tools',args[3] if len(args)>3 else [])
            if required['tool']!='required' and required['tool'] not in {getattr(t,'name',None) for t in tools}:
                raise RuntimeError('Required assigned review tool is unavailable')
            args=list(args);kwargs=dict(kwargs)
            if required.get('exclude_tools'):
                tools=[t for t in tools if getattr(t,'name',None) not in required['exclude_tools']]
                if 'tools' in kwargs: kwargs['tools']=tools
                else: args[3]=tools
            if 'model_settings' in kwargs:
                kwargs['model_settings']=replace(kwargs['model_settings'],tool_choice=required['tool'])
            else: args[2]=replace(args[2],tool_choice=required['tool'])
            return tuple(args),kwargs
        async def get_response(self,*args,**kwargs):
            args,kwargs=self.settings(args,kwargs)
            return await self.inner.get_response(*args,**kwargs)
        async def stream_response(self,*args,**kwargs):
            args,kwargs=self.settings(args,kwargs)
            async for event in self.inner.stream_response(*args,**kwargs): yield event
    class ReviewProvider(ModelProvider):
        def get_model(self,name): return ReviewModel(provider.get_model(name))
    return ReviewProvider()


def schedule(state,pending,steps_left,concurrency):
    """Protect the known review queue and final report; never extend hard budgets."""
    from .research_tasks import enabled
    from .config import schedule_batch,round_allowance
    if not enabled(state): return schedule_batch(pending,steps_left,concurrency)
    from .review_tasks import pending as review_pending
    auditors=[a for a in pending if a.get('work_kind')=='REVIEW' and review_pending(state,a)]
    reporters=[a for a in pending if a.get('work_kind')=='SYNTHESIS']
    reserve=len(reporters)
    for agent in auditors:
        reserve+=min(round_allowance(state['config'],agent)-agent['rounds'],
                     sum(2 if p['kind'] in {'PROTOTYPE_TEST','PROTOTYPE_FAILURE','PROTOTYPE_PLAN'} else 1 for p in review_pending(state,agent)))
    # Close already-recorded tests before spending another local/discovery quantum.
    if reporters and steps_left<=len(reporters):
        return sorted(reporters,key=lambda a:(a['rounds'],a['id']))[:1]
    test_reviews=[a for a in auditors if any(p['kind'] in {'PROTOTYPE_TEST','PROTOTYPE_FAILURE','PROTOTYPE_PLAN'} for p in review_pending(state,a))]
    if test_reviews: return sorted(test_reviews,key=lambda a:(a['rounds'],a['id']))[:min(concurrency,max(1,steps_left-len(reporters)))]
    if auditors and steps_left<=reserve: return sorted(auditors,key=lambda a:(a['rounds'],a['id']))[:1]
    return schedule_batch(pending,steps_left,concurrency)
