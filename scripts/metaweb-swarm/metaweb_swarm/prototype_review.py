"""Freeze a local test contract; execution and mechanism coverage are separate receipts."""
import hashlib
import json
import uuid
import re
from .storage import canonical, now
from .workspace import _relative, _read_bytes


def enabled(api):
    from .research_tasks import enabled as research_enabled
    return research_enabled(api.engine.state)


def snapshot(api, receipt):
    """Keep executed evidence outside mutable agent workspaces, with a byte quota."""
    from .workspace import _atomic_write
    state=api.engine.state
    blobs=state.setdefault('prototype_artifact_blobs',{})
    bodies={}
    for a in receipt['artifacts']:
        body=_read_bytes(api.workspace.root,_relative(a['path']),state['config']['max_file_bytes'])
        if hashlib.sha256(body).hexdigest()!=a['sha256']: raise ValueError('Executed artifact changed before snapshot')
        if a['sha256'] not in blobs: bodies[a['sha256']]=body
    if sum(b['bytes'] for b in blobs.values())+sum(len(b) for b in bodies.values())>state['config']['max_snapshot_bytes']:
        raise ValueError('MAX_PROTOTYPE_ARTIFACT_BYTES: audit snapshot quota exhausted')
    for sha,body in bodies.items():
        path=f'audit/prototype-artifacts/{sha}.bin'
        _atomic_write(api.engine.store.run_dir/path,body)
        blobs[sha]={'path':path,'sha256':sha,'bytes':len(body)}
    receipt['audit_artifacts']=[dict(blobs[a['sha256']],source_path=a['path']) for a in receipt['artifacts']]


def artifact_bytes(api, receipt, artifact):
    saved=next((a for a in receipt.get('audit_artifacts',[]) if a['source_path']==artifact['path']
                and a['sha256']==artifact['sha256']),None)
    relative=_relative(saved['path'] if saved else f"agents/{receipt['agent_id']}/workspace/{artifact['path']}")
    return _read_bytes(api.engine.store.run_dir,relative,api.engine.state['config']['max_file_bytes'])


def enforce_scope(state):
    """On explicit resume, legacy exit-zero claims keep receipts but lose certification."""
    from .research_tasks import enabled as research_enabled, revision
    if not research_enabled(state): return []
    changed=[]
    for idea in state['ideas']:
        valid=any(t.get('host_execution_verified') and t.get('prototype_review',{}).get('verdict')=='FULL_MECHANISM'
                  and t.get('prototype_plan',{}).get('research_revision')==revision(idea)
                  for t in state.get('tests',[]) if t.get('idea_id')==idea['id'])
        if not valid and (idea.get('prototype_tested') or idea.get('status')=='PROTOTYPED'):
            changed.append({'idea_id':idea['id'],'previous_status':idea['status']})
            idea['prototype_tested']=False
            if idea['status']=='PROTOTYPED': idea.update(status='INVESTIGATING',best_evidenced_status='INVESTIGATING')
            idea['prototype_validation']='Execution receipt retained; independent mechanism coverage is absent/stale.'
    return changed


def plan(api, idea_id, property_tested, input_path, script_path, output_paths,
         positive_assertion, negative_assertion, scope, limitations,
         repair_experiment_id='',repair_notes='',repair_check='',revision_test_id=''):
    from .research_tasks import gate, revision
    issue = gate(api, idea_id)
    if issue: return issue
    from .prototype_revision import reference_issue
    issue=reference_issue(api,idea_id,revision_test_id,repair_experiment_id)
    if issue:return issue
    issue = payment_issue(api.idea(idea_id)) if enabled(api) else None
    if issue: return issue
    if scope not in {'FULL_MECHANISM', 'SUBCOMPONENT'}:
        raise ValueError('scope must be FULL_MECHANISM or SUBCOMPONENT')
    from .prototype_focus import plan_issue
    issue=plan_issue(api,api.idea(idea_id),scope)
    if issue: return issue
    for name, value in [('property_tested',property_tested),('positive_assertion',positive_assertion),
                        ('negative_assertion',negative_assertion),('limitations',limitations)]:
        if not isinstance(value,str) or len(value)>4000 or (name!='limitations' and len(value.strip())<10):
            raise ValueError(name+' needs a concrete bounded description')
    if scope == 'SUBCOMPONENT' and len(limitations.strip())<10:
        raise ValueError('Describe which parts of the mechanism remain untested')
    if re.search(r'\b(?:does not|do not|cannot|will not)\s+(?:test|prove|verify|validate|exercise)\b', negative_assertion, re.I):
        from .research_recovery import defer
        return defer(api, idea_id, 'LOCAL', 'NEGATIVE_TEST_REQUIRED',
                     {'negative_assertion':negative_assertion},
                     'Describe an actual modified/corrupt/truncated/invalid input and the assertion that rejects it. Untested carrier behavior belongs in limitations, not negative_assertion. Implement that negative test in the script.')
    if not isinstance(output_paths,list) or not 1 <= len(output_paths) <= 16:
        raise ValueError('Declare 1..16 generated specimen paths')
    paths=[str(_relative(p)).replace('\\','/') for p in [input_path,script_path,*output_paths]]
    if len(set(paths))!=len(paths): raise ValueError('Input, script and generated outputs must have distinct paths')
    input_path,script_path=paths[:2];output_paths=paths[2:]
    from .research_recovery import defer, clear, materialized_inputs
    inputs = materialized_inputs(api.agent)
    try:
        info=api.workspace.file_info(input_path)
    except FileNotFoundError:
        return defer(api, idea_id, 'LOCAL', 'PROTOTYPE_INPUT_PATH_MISSING',
                     {'field':'input_path', 'requested_path':input_path, 'materialized_inputs':inputs},
                     'materialize_export FIRST; use its returned workspace path in BOTH input_path and the script. Correct the script with write_file, then call record_prototype_plan again. No deposit draft is involved.')
    try:
        script=api.workspace.file_info(script_path)
    except FileNotFoundError:
        return defer(api, idea_id, 'LOCAL', 'PROTOTYPE_SCRIPT_PATH_MISSING',
                     {'field':'script_path', 'requested_path':script_path, 'materialized_inputs':inputs},
                     'Write the actual test script at script_path with write_file FIRST; then call record_prototype_plan again. No experiment has run and no deposit draft is involved.')
    if script['binary']: raise ValueError('Test script must be readable text')
    from .prototype_preflight import submission_issue
    issue=submission_issue(api,idea_id,script)
    if issue:return issue
    export=next((e for e in api.agent.get('materialized_exports',[]) if e['path']==input_path
                 and all(e[k]==info[k] for k in ('bytes','sha256'))),None)
    if not export:
        return defer(api, idea_id, 'LOCAL', 'RETAINED_EXPORT_INPUT_REQUIRED',
                     {'field':'input_path', 'requested_path':input_path, 'materialized_inputs':inputs,
                      'actual_input':info},
                     'Use an unchanged materialize_export input at its exact returned workspace path, not an invented fixture or another IDEA output. Correct input/script and resubmit record_prototype_plan.')
    from .prototype_inputs import plan_issue as input_issue
    issue=input_issue(api,export,scope)
    if issue:return issue
    from .prototype_debug import repair_issue
    issue=repair_issue(api,idea_id,script,repair_experiment_id,repair_notes,repair_check)
    if issue:return issue
    from .prototype_revision import repair_issue as revision_issue
    issue=revision_issue(api,idea_id,script,revision_test_id,repair_notes,repair_check)
    if issue:return issue
    data={'idea_id':idea_id,'research_revision':revision(api.idea(idea_id)), 'agent_id':api.agent['id'],
          'property_tested':property_tested,'input':dict(export),'script':dict(path=script_path,**script),
          'output_paths':output_paths,'positive_assertion':positive_assertion,
          'negative_assertion':negative_assertion,'scope':scope,'limitations':limitations}
    if revision_test_id:data['revision_repair']={'test_id':revision_test_id,'notes':repair_notes,'success_check':repair_check}
    if repair_experiment_id:data['repair']={'experiment_id':repair_experiment_id,'notes':repair_notes,'success_check':repair_check}
    ident='PROTO-PLAN-'+hashlib.sha256(canonical(data).encode()).hexdigest()[:24]
    record=dict(data,id=ident)
    from .prototype_preflight import queue
    queue(api,record)
    api.agent.setdefault('prototype_plans',{})[idea_id]=record
    clear(api.agent, 'LOCAL')
    api.event('prototype_plan_recorded',record)
    from .prototype_workflow import enabled as workflow_enabled
    if workflow_enabled(api):
        return dict(record,next_action='Frozen code queued for independent relevance review; the host checkpoints this turn without polling. After READY use execute_prototype(argv), which captures execution and the test receipt together. Host supplies all repair IDs; no manual record_test or bookkeeping rerun.')
    return dict(record,next_action='Execute this exact script linked to the IDEA. It must WRITE the declared outputs during execution and test altered/invalid input. Inspect prototype_readiness; when ready, record_test with that same experiment ID. No bookkeeping registration/rerun. Scope still awaits independent review.')


def active(api, idea_id):
    from .research_tasks import revision
    p=api.agent.get('prototype_plans',{}).get(idea_id)
    return p if p and p['research_revision']==revision(api.idea(idea_id)) else None


def payment_issue(idea):
    if idea.get('payment') not in {'FREE','ONE_TIME'} or idea.get('requires_ongoing_payments') is True:
        return {'status':'DEFERRED','reason':'PAYMENT_INDEPENDENCE_REQUIRED','idea_id':idea['id'],
                'next_action':'Discovery/audit must read primary pricing and update this existing provider variant. Unknown cost is not FREE; recurring-payment variants are excluded. Retain the hypothesis without a test claim.'}
    return None


def experiment_gate(api, argv, idea_id):
    if not enabled(api) or not idea_id: return None
    issue = payment_issue(api.idea(idea_id))
    if issue: return issue
    from .prototype_debug import local_issue,last
    issue=local_issue(api.engine.state,api.agent,idea_id)
    if issue:return issue
    p=active(api,idea_id)
    if not p:
        if api.agent.get('work_kind')!='LOCAL': return None  # Unplanned exploration cannot receive a scoped test receipt.
        return {'status':'DEFERRED','reason':'PROTOTYPE_PLAN_REQUIRED',
                'next_action':'Write a real test script for the assigned property and record_prototype_plan with retained input, outputs, positive and negative assertions and honest scope.'}
    from .prototype_revision import reference_issue
    issue=reference_issue(api,idea_id,p.get('revision_repair',{}).get('test_id',''),p.get('repair',{}).get('experiment_id',''),active=False)
    if issue:return issue
    failure=last(api.engine.state,api.agent,idea_id)
    if failure and p.get('repair',{}).get('experiment_id')!=failure['experiment_id']:
        return {'status':'DEFERRED','reason':'ROOT_CAUSE_REPAIR_REQUIRED','diagnosis':failure.get('failure_review'),
                'next_action':'Read the diagnosis, repair the code and update record_prototype_plan with repair_notes and repair_check. The host binds repair IDs; do not supply any ID in the model-facing planning tool.'}
    if any(t.get('idea_id')==idea_id and t.get('prototype_review',{}).get('verdict')=='REVISE'
           and t.get('prototype_plan',{}).get('research_revision')==p['research_revision']
           and t.get('prototype_plan',{}).get('script',{}).get('sha256')==p['script']['sha256']
           for t in api.engine.state.get('tests',[])):
        return {'status':'DEFERRED','reason':'REVISED_TEST_NEEDS_CODE_CHANGE',
                'next_action':'Read the actual REVISE reason and correct the script/assertions/output bytes. Renaming or repeating the same failed implementation is not another useful test. Update the plan after the actual repair.'}
    try: info=api.workspace.file_info(p['script']['path'])
    except (ValueError,OSError): info={}
    if info.get('sha256')!=p['script']['sha256']:
        return {'status':'DEFERRED','reason':'PROTOTYPE_SCRIPT_CHANGED','next_action':'Update the test contract for the actual script before executing.'}
    from .prototype_preflight import gate as preflight_gate
    issue=preflight_gate(api,p)
    if issue:return issue
    if p['script']['path'] not in argv:
        return {'status':'DEFERRED','reason':'PLANNED_SCRIPT_REQUIRED','next_action':'Execute the exact script path returned in prototype_plan, not a print placeholder.'}
    runtimes=api.agent.get('sandbox_capabilities',{}).get('runtimes',{})
    command=argv[0] if argv else ''
    if runtimes and command in runtimes and not runtimes[command]:
        return {'status':'DEFERRED','reason':'RUNTIME_UNAVAILABLE','runtimes':runtimes,
                'next_action':'Port the test to an available runtime; the bundled sandbox provides Python. pip packages do not install Node.'}
    if command in {'python','python3'} and p['script']['path'].endswith(('.mjs','.js','.cjs')):
        return {'status':'DEFERRED','reason':'SCRIPT_RUNTIME_MISMATCH',
                'next_action':'Python cannot execute JavaScript. Write a real Python implementation or use an actually available Node runtime.'}
    # Merely listing the file as an unused argument to `python -c` does not run it.
    # Keep arbitrary implementation inside the declared script; bind the actual invocation.
    index=argv.index(p['script']['path'])
    prefix=argv[:index]
    direct=False
    if command in {'python','python3'}:
        direct=all(option in {'-B','-u','-E','-s','--'} for option in prefix[1:])
        if prefix[1:3]==['-m','pytest']:
            direct=all(option in {'-q','-v','-s','-x','--disable-warnings'} for option in prefix[3:])
    elif command=='pytest': direct=all(option in {'-q','-v','-s','-x','--disable-warnings'} for option in prefix[1:])
    elif command=='node': direct=all(option in {'--test','--no-warnings'} for option in prefix[1:])
    if not direct:
        return {'status':'DEFERRED','reason':'DIRECT_TEST_EXECUTION_REQUIRED',
                'next_action':'Run python <planned script>, python -m pytest <planned script>, or an available node <planned script>. No -c/shell substitute or assertion-disabling optimization flags.'}
    return None


def test_gate(api, idea_id, experiment, inventory):
    if not enabled(api): return None
    p=active(api,idea_id)
    if not p or experiment.get('prototype_plan_id')!=p['id']:
        return {'status':'DEFERRED','reason':'PLANNED_EXECUTION_REQUIRED',
                'next_action':'record_prototype_plan, execute its script with that IDEA, then record_test for the new execution.'}
    artifacts={a['path']:a for a in inventory}
    if any(path not in artifacts for path in [p['script']['path'],*p['output_paths']]):
        return {'status':'DEFERRED','reason':'PLANNED_ARTIFACTS_REQUIRED',
                'next_action':'Register the actual planned script and generated specimens before rerunning the linked experiment.'}
    if artifacts[p['script']['path']]['sha256']!=p['script']['sha256']:
        return {'status':'DEFERRED','reason':'PLANNED_SCRIPT_BYTES_REQUIRED'}
    try: actual=api.workspace.file_info(p['input']['path'])
    except (ValueError,OSError): actual={}
    if any(actual.get(k)!=p['input'][k] for k in ('sha256','bytes')):
        return {'status':'DEFERRED','reason':'PROTOTYPE_INPUT_CHANGED'}
    return None


def pending(state, agent):
    from .research_tasks import revision
    result=[]
    for t in state.get('tests',[]):
        idea=next((i for i in state['ideas'] if i['id']==t['idea_id']),None)
        if (not t.get('prototype_review_required') or not idea or idea.get('status')=='REJECTED'
                or agent['id'] in {t['agent_id'],idea.get('agent_id')}
                or t.get('prototype_plan',{}).get('research_revision')!=revision(idea)):
            continue
        if any(r['test_id']==t['id'] for r in state.get('prototype_reviews',[])): continue
        result.append({'kind':'PROTOTYPE_TEST','target_id':t['id'],'idea_id':idea['id'],
                       'revision':t['prototype_plan']['id'],'provider':idea.get('provider'),'documents':[]})
    from .prototype_debug import pending as failure_pending
    from .prototype_preflight import pending as plan_pending
    return result+failure_pending(state,agent)+plan_pending(state,agent)


def packet(state, agent, task):
    t=next((t for t in state.get('tests',[]) if t['id']==task.get('target_id')),None)
    if not t: return dict(task,stage='STALE')
    idea=next((i for i in state['ideas'] if i['id']==t['idea_id']),None)
    done=any(r['test_id']==t['id'] for r in state.get('prototype_reviews',[]))
    # Bytes live in immutable audit snapshots; facts do not require replaying payloads.
    from .review_facts import facts
    observations=facts(state,t)
    source=t['prototype_plan']['input']
    identities=[dict(a,matches_retained_input=(a['sha256']==source['sha256'] and a['bytes']==source['bytes'])) for a in t['artifacts']]
    return dict(task,stage='DONE' if done else 'REVIEW_TEST',candidate=idea,host_facts=observations,
        byte_identity={'retained_input':source,'outputs':identities,
                       'meaning':'Different hashes/lengths are not an exact byte copy. Text normalization can alter both; recovered bytes must be separately emitted and match the original.'},
        prototype_plan=t['prototype_plan'],test_receipt=t,
        execution=next(({k:e.get(k) for k in ('experiment_id','argv','returncode','exit_code','output','status')}
                        for e in state.get('experiments',[]) if e['experiment_id']==t['experiment_id']),None),
        next_action='Read the actual script AND generated reports/specimens via read_test_artifact. Quote executable positive_code and negative_code cases when reviewing. Compare emitted failures and raw byte hashes to the original mechanism and frozen plan. '
            'No deliberately altered/invalid input plus actual rejection/recovery assertion means REVISE, even for SUBCOMPONENT. Merely reading JSON/writing a report is not a tested recovery component. Failed probes are not success. '
            'A PNG opening is not QR decoding; a QR hash is not remote custody; JSON is not CBOR; concatenation is not erasure recovery. '
            'review_prototype_test FULL_MECHANISM only for actual complete coverage, SUBCOMPONENT for a useful limited test, REVISE for unrelated/broken assertions. Never reject the hypothesis just because its test is insufficient.')


def read_artifact(api, test_id, path, offset=0, limit=12000):
    task=api.get_review_task()
    if task.get('kind')!='PROTOTYPE_TEST' or task.get('target_id')!=test_id:
        return {'status':'DEFERRED','reason':'ASSIGNED_PROTOTYPE_REVIEW_REQUIRED','review_task':task}
    t=task['test_receipt'];a=next((a for a in t['artifacts'] if a['path']==path),None)
    if not a: raise ValueError('Use an exact artifact path from the assigned test receipt')
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=16000:
        raise ValueError('Invalid artifact paging')
    body=artifact_bytes(api,t,a)
    if hashlib.sha256(body).hexdigest()!=a['sha256']:
        return {'status':'DEFERRED','reason':'TEST_ARTIFACT_CHANGED','next_action':'Record REVISE; current file no longer matches the executed receipt.'}
    api.agent.setdefault('prototype_artifact_checks',{}).setdefault(test_id,{})[path]=a['sha256']
    try: text=body.decode('utf-8')
    except UnicodeError:
        api.event('prototype_artifact_read',{'test_id':test_id,'path':path,'sha256':a['sha256'],'binary':True})
        return {'status':'COMPLETED','path':path,'sha256':a['sha256'],'bytes':len(body),'binary':True,
                'matches_retained_input':a['sha256']==t['prototype_plan']['input']['sha256'] and a['bytes']==t['prototype_plan']['input']['bytes'],
                'meaning':'Binary hash checked; this tool does not decode the specimen.'}
    end=min(len(text),offset+limit)
    api.agent.setdefault('prototype_artifact_reads',{}).setdefault(test_id,{}).setdefault(path,[]).append([offset,end])
    api.event('prototype_artifact_read',{'test_id':test_id,'path':path,'sha256':a['sha256'],'offset':offset,'end':end})
    return {'status':'COMPLETED','path':path,'sha256':a['sha256'],'offset':offset,'end':end,
            'total_chars':len(text),'text':text[offset:end],'next_offset':end if end<len(text) else None,
            'matches_retained_input':a['sha256']==t['prototype_plan']['input']['sha256'] and a['bytes']==t['prototype_plan']['input']['bytes']}


def review(api, test_id, verdict, reason, positive_code='', negative_code='', recovered_path='',
           observed_recovery='NOT_EVALUATED',review_basis='UNSPECIFIED'):
    from .research_tasks import revision
    task=api.get_review_task()
    if (task.get('kind')!='PROTOTYPE_TEST' or task.get('target_id')!=test_id or task.get('stage')!='REVIEW_TEST'
            or api.agent.get('work_kind')!='REVIEW'):
        return {'status':'DEFERRED','reason':'ASSIGNED_PROTOTYPE_REVIEW_REQUIRED','review_task':task}
    if verdict not in {'FULL_MECHANISM','SUBCOMPONENT','REVISE'} or not isinstance(reason,str) or not 20<=len(reason.strip())<=8000:
        raise ValueError('Concrete coverage verdict and reason required')
    t=task['test_receipt'];p=t['prototype_plan'];idea=api.idea(t['idea_id'])
    requested_verdict=verdict
    if api.agent['id'] in {t['agent_id'],idea.get('agent_id')}:
        return {'status':'DEFERRED','reason':'INDEPENDENT_PROTOTYPE_REVIEW_REQUIRED'}
    if p['research_revision']!=revision(idea): return {'status':'DEFERRED','reason':'PROTOTYPE_CLAIM_CHANGED'}
    if observed_recovery not in {'MATCHES_INPUT','DIFFERS_FROM_INPUT','NO_RECOVERED_OUTPUT','NOT_EVALUATED'} or review_basis not in {'LOCAL_DEFECT','IRRELEVANT_TEST','EXTERNAL_GAP_ONLY','UNSPECIFIED'}:
        raise ValueError('Invalid typed review observation/basis')
    from .review_facts import check as check_facts, facts
    issue=check_facts(api,t,verdict,observed_recovery,review_basis,recovered_path)
    adjustment=None
    unresolved=False
    if issue:
        from .prototype_evidence import review_failure
        deferred,stop=review_failure(api,test_id,issue,positive_code,negative_code,recovered_path)
        if not stop:return deferred
        verdict='REVISE';adjustment='MODEL_REVIEW_UNRESOLVED';unresolved=True
        reason=('Independent scope review unresolved after three inconsistent factual assessments; '
                'this is not evidence of an implementation or mechanism failure. Last proposed judgment: '+reason)[:8000]
        owner=next(a for a in api.engine.state['agents'] if a['id']==t['agent_id'])
        owner.setdefault('research_task_blocks',[]).append({'idea_id':idea['id'],'phase':'LOCAL',
            'revision':revision(idea),'operator_notes_count':len(owner.get('operator_notes',[])),
            'status':'BLOCKED','reason':'INDEPENDENT_REVIEW_UNRESOLVED','test_id':test_id,
            'next_action':'Keep the executed evidence and hypothesis. Resolve the independent assessment; do not repair code from a contradictory factual claim.'})
    if verdict!='REVISE':
        from .prototype_inputs import descriptor
        descriptor_issue=({'status':'DEFERRED','reason':'DESCRIPTOR_SCOPE_LIMIT',
                    'next_action':'This receipt restores descriptor bytes, not the web payload. Judge a useful metadata operation as SUBCOMPONENT, or test actual export content. Legacy plans do not certify web preservation.'}
                    if verdict=='FULL_MECHANISM' and descriptor(p['input'].get('export','')) else None)
        own=api.agent.get('prototype_artifact_reads',{}).get(test_id,{}).get(p['script']['path'],[])
        script=next(a for a in t['artifacts'] if a['path']==p['script']['path'])
        body=artifact_bytes(api,t,script)
        from .review_tasks import _subtract
        if hashlib.sha256(body).hexdigest()!=p['script']['sha256'] or _subtract([[0,len(body.decode('utf-8'))]],own):
            return {'status':'DEFERRED','reason':'OWN_EXECUTED_SCRIPT_READ_REQUIRED',
                    'next_action':'Read all pages of the actual unchanged script with read_test_artifact before endorsing coverage.'}
        for a in t['artifacts']:
            artifact=artifact_bytes(api,t,a)
            if hashlib.sha256(artifact).hexdigest()!=a['sha256']:
                return {'status':'DEFERRED','reason':'TEST_ARTIFACT_CHANGED','next_action':'Record REVISE; executed artifact evidence was modified after the receipt.'}
        if verdict=='FULL_MECHANISM' and p['scope']!='FULL_MECHANISM':
            return {'status':'DEFERRED','reason':'SUBCOMPONENT_CANNOT_CERTIFY_MECHANISM'}
        from .prototype_evidence import approval_gate
        issue=descriptor_issue or approval_gate(api,t,positive_code,negative_code,recovered_path)
        if not issue and verdict=='FULL_MECHANISM' and not recovered_path:
            issue={'status':'DEFERRED','reason':'RECOVERED_BYTES_REQUIRED',
                    'next_action':'FULL mechanism approval requires a captured recovered output matching the retained original bytes, plus meaningful positive and damaged-input tests. A metadata-only helper has a narrower scope.'}
        if issue:
            from .prototype_evidence import review_failure
            deferred,stop=review_failure(api,test_id,issue,positive_code,negative_code,recovered_path)
            if not stop: return deferred
            verdict='REVISE';adjustment=issue['reason']
            reason=('Host evidence contract retained this test as REVISE after three repeated unsupported approval attempts: '+issue['reason']+'. Original reviewer reason: '+reason)[:8000]
    record={'id':'PROTO-REVIEW-'+uuid.uuid4().hex[:16],'test_id':test_id,'idea_id':idea['id'],
            'agent_id':api.agent['id'],'verdict':verdict,'reason':reason,'prototype_plan_id':p['id'],
            'time':now(),'evidence_contract':3,'host_facts':facts(api.engine.state,t),
            'observed_recovery':observed_recovery,'review_basis':review_basis,'positive_code':positive_code,'negative_code':negative_code,
            'review_unresolved':unresolved,
            'recovered_path':recovered_path,
            'requested_verdict':requested_verdict,'contract_adjustment':adjustment,
            'meaning':'Independent interpretation of executed code and output reads. Literal syntax/read/hash guards are not scientific certification of the mechanism.'}
    api.engine.state.setdefault('prototype_reviews',[]).append(record)
    t['prototype_review']=record
    for linked in idea.get('test_receipts',[]):
        if linked['id']==test_id: linked['prototype_review']=record
    if verdict=='FULL_MECHANISM':
        idea['prototype_tested']=True
        if idea.get('status') not in {'REJECTED','BLOCKED','COMPLETED'} and not idea.get('status_conflicts'):
            idea.update(status='PROTOTYPED',best_evidenced_status='PROTOTYPED')
    elif verdict=='SUBCOMPONENT': idea['prototype_component_tested']=True
    api.event('prototype_review_recorded',record)
    return record
