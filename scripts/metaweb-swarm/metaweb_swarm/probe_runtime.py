"""Host-owned review diagnostics; an import failure is not an implementation verdict."""
import ast,hashlib,json,re
from pathlib import PurePosixPath


def source_paths(state,test):
    execution=next((e for e in state.get('experiments',[]) if e.get('experiment_id')==test['experiment_id']),{})
    return {test['prototype_plan']['script']['path'],*[a['path'] for a in execution.get('coding_sources',[])]}


def forbidden_imports(code,paths):
    """Output-only readers cannot import modules deliberately absent from their copy."""
    import sys
    names={PurePosixPath(p).stem for p in paths if p.endswith('.py')}-sys.stdlib_module_names
    tree=ast.parse(code);found=set()
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):found.update(a.name.split('.')[0] for a in node.names if a.name.split('.')[0] in names)
        if isinstance(node,ast.ImportFrom) and node.module and node.module.split('.')[0] in names:found.add(node.module.split('.')[0])
    return sorted(found)


def setup_issue(agent,state,test_id):
    explicit=agent.get('prototype_probe_setup_issues',{}).get(test_id)
    if explicit:return explicit
    # Legacy import tracebacks are diagnostic only; retain their original receipts.
    previous=next((p for p in reversed(state.get('prototype_review_probes',[]))
        if p.get('test_id')==test_id and p.get('agent_id')==agent['id']),None)
    if not previous:return None
    if previous.get('outcome')=='SETUP_ERROR':return summary(previous)
    if 'outcome' not in previous and previous.get('returncode') not in (None,0):
        match=re.search(r"ModuleNotFoundError: No module named ['\"]([^'\"]+)",previous.get('output',''))
        if match:return {'reason':'REVIEW_PROBE_SETUP_ERROR','missing_module':match[1],
            'probe_id':previous['id'],'legacy_diagnostic':True,
            'next_action':'Repair the reviewer environment/import or use a separate reader. This traceback is not a prototype defect.'}
    return None


def summary(record):
    if not record:return record
    result={k:v for k,v in record.items() if k in {'id','test_id','status','reason','outcome','error_type',
        'missing_module','detail','returncode','cleanup_ok','implementation_unchanged','assertion_syntax',
        'mode','specimen_paths','dependency_owners','import_paths','staged_bytes','next_action'}}
    result['output']=str(record.get('output',''))[-5000:]
    result['staged_path_count']=len(record.get('staged_paths',[]))
    result['audit_reference']='prototype_review_probes/'+str(record.get('id','pending'))
    return result


def defer_setup(api,test_id,reason,detail):
    issue={'status':'DEFERRED','reason':reason,'test_id':test_id,**detail,
        'next_action':'Fix your probe, not the prototype. In SPECIMENS_ONLY write an independent reader; author imports are unavailable by design. Install your own third-party libraries with install_packages, then retry. No implementation verdict was recorded.'}
    fingerprint=hashlib.sha256(json.dumps({'reason':reason,**detail},sort_keys=True).encode()).hexdigest()
    prior=api.agent.setdefault('prototype_probe_setup_attempts',{}).get(test_id,{})
    attempts=prior.get('attempts',0)+1 if isinstance(prior,dict) and prior.get('fingerprint')==fingerprint else 1
    api.agent['prototype_probe_setup_attempts'][test_id]={'fingerprint':fingerprint,'attempts':attempts}
    issue['attempts']=attempts
    api.agent.setdefault('prototype_probe_setup_issues',{})[test_id]=issue
    api.event('prototype_review_probe_setup_required',issue)
    if attempts>=3:
        from .backend import BackendBlocked
        raise BackendBlocked('AUDIT_PROBE_SETUP_STALLED: '+reason+'; reviewer setup unresolved; no code repair or verdict inferred')
    return issue


def launcher(driver,result_path,imports):
    """Execute only in the bounded container. Outcome JSON is diagnostic, not proof."""
    return '''import json,pathlib,runpy,sys,traceback
sys.dont_write_bytecode=True
root=pathlib.Path.cwd()
for relative in reversed(IMPORTS):
    sys.path.insert(0,str(root/relative))
result={'outcome':'PASSED'}
exit_code=0
try:
    runpy.run_path(DRIVER,run_name='__main__')
except (ImportError,ModuleNotFoundError) as error:
    result={'outcome':'SETUP_ERROR','error_type':type(error).__name__,'missing_module':getattr(error,'name',None),'detail':str(error)[:2000]}
    traceback.print_exc();exit_code=1
except AssertionError as error:
    result={'outcome':'ASSERTION_FAILED','error_type':type(error).__name__,'detail':str(error)[:2000]}
    traceback.print_exc();exit_code=1
except SystemExit as error:
    exit_code=error.code if isinstance(error.code,int) else 1
    result={'outcome':'PASSED' if exit_code==0 else 'RUNTIME_ERROR','error_type':'SystemExit','detail':str(error)[:2000]}
except BaseException as error:
    result={'outcome':'RUNTIME_ERROR','error_type':type(error).__name__,'detail':str(error)[:2000]}
    traceback.print_exc();exit_code=1
pathlib.Path(RESULT).write_text(json.dumps(result),encoding='utf-8')
raise SystemExit(exit_code)
'''.replace('IMPORTS',repr(imports)).replace('DRIVER',repr(driver)).replace('RESULT',repr(result_path))
