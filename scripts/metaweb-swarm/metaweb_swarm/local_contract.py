"""One frozen local operation for coding and audit; no pre-execution approval."""
import hashlib
from .storage import canonical


def current(api,idea_id):
    from .research_tasks import revision
    contract=api.agent.get('coding_local_contracts',{}).get(idea_id)
    return contract if contract and contract['research_revision']==revision(api.idea(idea_id)) else None


def bind(api,task,result):
    previous=current(api,task['idea_id'])
    if previous:return previous  # Repairs cannot quietly lower the target/assertions.
    operation=(result.get('local_operation') or result['positive_assertion']).strip()
    if not 20<=len(operation)<=4000:raise ValueError('local_operation must describe a concrete format/carrier operation, 20..4000 characters')
    from .research_tasks import revision
    candidate=api.idea(task['idea_id'])
    from .format_operation import contract as format_contract
    native=format_contract(candidate,task['input']) if task.get('input') else None
    if native:operation=native['operation']
    from .operation_requirements import REQUIREMENTS
    data={'idea_id':task['idea_id'],'agent_id':api.agent['id'],'research_revision':revision(api.idea(task['idea_id'])),
          'operation':operation,'scope':task['scope_ceiling'],
          'format_contract':native,
          'evidence_requirements':REQUIREMENTS,
          'candidate_primitive':{k:candidate.get(k) for k in ('provider','mechanism','title')},
          'positive_assertion':result['positive_assertion'],'negative_assertion':result['negative_assertion'],
          'limitations':result['limitations'],
          'external_custody':'UNTESTED; public publication is outside a SUBCOMPONENT contract',
          'review_rule':'Judge whether this relevant local operation and both executable cases work. '
                        'The saved operation and assertions are the assessment target; the discovery title is background. Do not add export-byte recovery, checksum rejection, public hosting or persistence if this contract only asks for native pointer serialization and missing-field rejection. '
                        'Missing public publication alone is not a local failure. Generic metadata extraction is HELPER_ONLY and never certifies the candidate primitive. A zero checksum merely read back is not tamper rejection.'}
    contract=dict(data,id='LOCAL-'+hashlib.sha256(canonical(data).encode()).hexdigest()[:24])
    api.agent.setdefault('coding_local_contracts',{})[task['idea_id']]=contract
    api.event('coding_local_contract_selected',contract)
    return contract


def attach(api,plan,contract):
    if not contract:return
    plan['local_contract']=contract
    api.agent['prototype_plans'][contract['idea_id']]['local_contract']=contract
    for stored in api.engine.state.get('prototype_plan_submissions',[]):
        if stored.get('id')==plan['id']:stored['local_contract']=contract
    api.event('coding_local_contract_bound',{'plan_id':plan['id'],'contract':contract})


def unchanged(api,test,result,helpers):
    """New reference documents/output paths do not constitute an implementation edit."""
    old=test['prototype_plan']['script']
    if api.workspace.file_info(result['script_path'])['sha256']!=old['sha256']:return False
    experiment=next((e for e in api.engine.state.get('experiments',[]) if e.get('experiment_id')==test['experiment_id']),{})
    from pathlib import PurePosixPath
    suffixes={'.py','.js','.ts','.mjs','.cjs','.sh','.c','.h','.cpp','.rs','.go'}
    previous={a['path']:a['sha256'] for a in experiment.get('coding_sources',[]) if PurePosixPath(a['path']).suffix.lower() in suffixes}
    return not any(a['path'] in previous and a['sha256']!=previous[a['path']] for a in helpers)


def check_review(api,test,verdict,change,code,bound_evidence=None):
    contract=test['prototype_plan'].get('local_contract')
    if not contract or verdict!='REVISE':return None
    correction={'status':'DEFERRED','reason':'LOCAL_CONTRACT_ASSESSMENT_REQUIRED','local_contract':contract,
                'next_action':'Use verdict as the only coverage decision. REVISE needs a deficient captured source range in negative_refs or positive_refs '
                              'and required_local_change within the frozen local operation. '
                              'Do not turn absence of public deployment into a local code repair.'}
    if not isinstance(change,str) or not 20<=len(change.strip())<=2000 or not isinstance(code,str) or not (1 if bound_evidence else 8)<=len(code.strip())<=8000:
        return dict(correction,reason='CONCRETE_LOCAL_REPAIR_REQUIRED')
    if bound_evidence:return None  # Already hash/read/range-bound by the host.
    if source_evidence(api,test,[('defect_code',code)]):return None
    return dict(correction,reason='LOCAL_DEFECT_CODE_NOT_IN_EXECUTED_SOURCE')


def source_evidence(api,test,candidates):
    """Bind an existing model quote to captured implementation, without a new verdict."""
    from .prototype_review import artifact_bytes
    paths={test['prototype_plan']['script']['path']}
    e=next((e for e in api.engine.state.get('experiments',[]) if e.get('experiment_id')==test['experiment_id']),{})
    paths.update(a['path'] for a in e.get('coding_sources',[]))
    sources=[]
    for a in test['artifacts']:
        if a['path'] not in paths:continue
        try:text=artifact_bytes(api,test,a).decode('utf-8').replace('\r\n','\n')
        except UnicodeError:continue
        sources.append((a,text))
    for field,code in candidates:
        if not isinstance(code,str) or not 8<=len(code.strip())<=8000:continue
        quote=code.strip().replace('\r\n','\n')
        for artifact,text in sources:
            if quote in text:
                return {'field':field,'path':artifact['path'],'sha256':artifact['sha256'],'quote':quote}
    return None


def retain_after_repairs(api,test,record):
    """Three actual repair cycles, then retain the candidate instead of an endless loop."""
    if not record.get('local_contract_id') or record['verdict']!='REVISE' or record.get('review_unresolved'):return
    owner=next(a for a in api.engine.state['agents'] if a['id']==test['agent_id'])
    notes=len(owner.get('operator_notes',[]))
    attempts=[r for r in api.engine.state.get('prototype_reviews',[]) if r.get('local_contract_id')==record['local_contract_id']
              and r['verdict']=='REVISE' and not r.get('review_unresolved') and r.get('owner_notes_count',0)==notes]
    if len(attempts)<4:return  # Initial review plus three revised implementations.
    from .research_tasks import revision
    issue={'idea_id':test['idea_id'],'phase':'LOCAL','revision':revision(api.idea(test['idea_id'])),
           'operator_notes_count':notes,'status':'BLOCKED','reason':'LOCAL_CONTRACT_REPAIR_LIMIT',
           'test_id':test['id'],'local_contract_id':record['local_contract_id'],'repair_attempts':3,
           'next_action':'Three repairs did not satisfy the same local contract. Retain all evidence and this promising/blocked hypothesis; '
                         'take another candidate. Explicit operator resolution may reopen it without erasing the failed attempts.'}
    owner.setdefault('research_task_blocks',[]).append(issue)
    api.event('local_contract_repairs_retained',issue)
