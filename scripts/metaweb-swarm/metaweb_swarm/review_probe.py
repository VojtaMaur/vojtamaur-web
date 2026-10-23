"""Independent review code runs only against a new copy of captured test files."""
import ast,asyncio,hashlib,json,uuid
from pathlib import PurePosixPath
from .workspace import DockerExecutor,Workspace,_relative,_read_bytes,_atomic_write


def assertion_syntax(code):
    try:tree=ast.parse(code)
    except (SyntaxError,ValueError):return False
    # Necessary evidence structure, not a semantic oracle. Ignore constant
    # assert True / print('PASS'); a reviewer still judges the actual challenge.
    tainted=set()
    def source_read(node):
        return any(isinstance(n,ast.Call) and
            (isinstance(n.func,ast.Attribute) and n.func.attr=='getsource' or
             (isinstance(n.func,ast.Name) and n.func.id=='open' or
              isinstance(n.func,ast.Attribute) and n.func.attr in {'read','read_text','read_bytes','exists'}) and
             any(isinstance(v,ast.Constant) and isinstance(v.value,str) and v.value.endswith(('.py','.js','.sh'))
                 for v in ast.walk(n))) for n in ast.walk(node))
    # Exclude assertions about implementation text (including aliases/hashes of
    # that text). Running the author script before such an assertion adds no
    # independent behavioral evidence. This remains a conservative syntax guard.
    for _ in range(len(list(ast.walk(tree)))):
        before=set(tainted)
        for n in ast.walk(tree):
            if isinstance(n,(ast.Assign,ast.AnnAssign)) and n.value is not None:
                if source_read(n.value) or any(isinstance(v,ast.Name) and v.id in tainted for v in ast.walk(n.value)):
                    targets=n.targets if isinstance(n,ast.Assign) else [n.target]
                    tainted.update(v.id for target in targets for v in ast.walk(target) if isinstance(v,ast.Name))
        if before==tainted:break
    def source_only(node):
        return source_read(node) or any(isinstance(v,ast.Name) and v.id in tainted for v in ast.walk(node))
    assertions=any(isinstance(n,ast.Assert) and not source_only(n.test) and any(isinstance(v,(ast.Name,ast.Call)) for v in ast.walk(n.test))
                   or isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr.startswith('assert')
                   and not source_only(n)
                   for n in ast.walk(tree))
    conditional_failure=any(isinstance(n,(ast.If,ast.Try)) and not source_only(n) and any(isinstance(v,ast.Raise) for v in ast.walk(n))
                            for n in ast.walk(tree))
    return bool(assertions or conditional_failure)


def latest(state,test_id,agent_id):
    return next((p for p in reversed(state.get('prototype_review_probes',[]))
                 if p['test_id']==test_id and p['agent_id']==agent_id),None)


async def run(api,test_id,code,specimen_paths=None):
    from .review_tasks import current
    from .prototype_review import artifact_bytes
    task=current(api.engine.state,api.agent)
    if (api.agent.get('work_kind')!='REVIEW' or not task or task.get('kind')!='PROTOTYPE_TEST'
            or task.get('target_id')!=test_id or task.get('stage')!='REVIEW_TEST'):
        return {'status':'DEFERRED','reason':'ASSIGNED_PROTOTYPE_REVIEW_REQUIRED'}
    if not isinstance(code,str) or not 20<=len(code)<=16000:raise ValueError('Probe needs 20..16000 characters of actual Python assertions')
    state=api.engine.state;config=state['config'];test=task['test_receipt']
    selected=specimen_paths or []
    if not isinstance(selected,list) or len(selected)>8 or any(not isinstance(p,str) for p in selected):
        raise ValueError('Select at most eight captured output paths')
    selected=list(dict.fromkeys(selected))
    if selected:
        execution=next((e for e in state.get('experiments',[]) if e.get('experiment_id')==test['experiment_id']),{})
        forbidden={test['prototype_plan']['script']['path'],test['prototype_plan']['input']['path'],
                   *[a['path'] for a in execution.get('coding_sources',[])]}
        outputs=set(test['prototype_plan']['output_paths'])-forbidden
        if any(p not in outputs or not any(a['path']==p for a in test['artifacts']) for p in selected):
            return {'status':'DEFERRED','reason':'CAPTURED_SPECIMEN_PATH_REQUIRED',
                    'next_action':'Select exact declared output specimens; source/input/helper files are excluded.'}
    if config['experiments']!='docker':return {'status':'BLOCKED','reason':'EXPERIMENTS_DISABLED'}
    from .probe_runtime import source_paths,forbidden_imports,defer_setup,launcher
    paths=source_paths(state,test)
    try:
        compile(code,'<review-probe>','exec')
        forbidden=forbidden_imports(code,paths) if selected else []
    except SyntaxError as error:
        return defer_setup(api,test_id,'PROBE_SYNTAX_ERROR',{'detail':str(error)[:1000]})
    if forbidden:
        return defer_setup(api,test_id,'AUTHOR_IMPORT_IN_SPECIMEN_READER',{'unavailable_author_modules':forbidden})
    if len([p for p in state.get('prototype_review_probes',[]) if p['test_id']==test_id])>=3:
        return {'status':'LIMIT_REACHED','reason':'MAX_REVIEW_PROBES_PER_TEST'}
    remaining=config['max_active_seconds']-api.engine.current_active_seconds()
    if remaining<1:return {'status':'LIMIT_REACHED','reason':'MAX_ACTIVE_SECONDS'}
    from .coding_session import unresolved_cleanup
    if unresolved_cleanup(state,api.agent['id']):return {'status':'BLOCKED','reason':'CONTAINER_CLEANUP_UNRESOLVED'}
    ident='REVIEW-PROBE-'+uuid.uuid4().hex[:16]
    driver='__review_probe_'+uuid.uuid4().hex+'.py'
    runner='__review_runner_'+uuid.uuid4().hex+'.py'
    diagnostic='__review_outcome_'+uuid.uuid4().hex+'.json'
    imports=['.review-packages']
    if not selected:imports+=sorted({str(PurePosixPath(p).parent) for p in paths})+['.packages']
    runner_body=launcher(driver,diagnostic,imports).encode()
    relative=_relative('agents/'+api.agent['id']+'/review-probes/'+ident)
    root=api.engine.store.run_dir/relative
    previous=sum(p.get('staged_bytes',0) for p in state.get('prototype_review_probes',[]))
    previous+=sum(a['bytes'] for a in state.get('prototype_artifact_blobs',{}).values())
    available=config['max_snapshot_bytes']-previous-len(code.encode())-len(runner_body)-8192
    copied=0
    bodies={}
    for artifact in test['artifacts']:
        if selected and artifact['path'] not in selected:continue
        if copied+artifact['bytes']>available:return {'status':'LIMIT_REACHED','reason':'MAX_REVIEW_PROBE_BYTES'}
        body=artifact_bytes(api,test,artifact)
        if len(body)!=artifact['bytes'] or hashlib.sha256(body).hexdigest()!=artifact['sha256']:
            return {'status':'BLOCKED','reason':'CAPTURED_PROBE_ARTIFACT_CHANGED'}
        bodies[artifact['path']]=body;copied+=len(body)

    source=test['prototype_plan']['input']
    input_path=_relative('agents/'+test['agent_id']+'/workspace/'+source['path'])
    if not selected:
        if copied+source['bytes']>available:return {'status':'LIMIT_REACHED','reason':'MAX_REVIEW_PROBE_BYTES'}
        body=_read_bytes(api.engine.store.run_dir,input_path,config['max_file_bytes'])
        if len(body)!=source['bytes'] or hashlib.sha256(body).hexdigest()!=source['sha256']:
            return {'status':'BLOCKED','reason':'RETAINED_PROBE_INPUT_CHANGED'}
        bodies[source['path']]=body;copied+=len(body)
    # Author mode mirrors worker dependencies. Both modes get the reviewer's
    # separate libraries; output-only mode never imports author packages.
    dependencies=[]
    owners=([(test['agent_id'],'.packages','AUTHOR')] if not selected else [])+[(api.agent['id'],'.review-packages','REVIEWER')]
    for owner,destination,origin in owners:
        packages=_relative('agents/'+owner+'/workspace/.packages')
        package_root=api.engine.store.run_dir/packages
        if not package_root.exists():continue
        if package_root.is_symlink():raise ValueError('Symlinked package directory is not a probe dependency')
        dependencies.append({'agent_id':owner,'origin':origin,'destination':destination})
        for path in package_root.rglob('*'):
            if path.is_symlink():raise ValueError('Symlinked probe dependency is not allowed')
            if path.is_file():
                if copied+path.stat().st_size>available:return {'status':'LIMIT_REACHED','reason':'MAX_REVIEW_PROBE_BYTES'}
                rel=(packages/path.relative_to(package_root)).as_posix()
                body=_read_bytes(api.engine.store.run_dir,_relative(rel),config['max_file_bytes'])
                bodies[destination+'/'+path.relative_to(package_root).as_posix()]=body;copied+=len(body)
    size=sum(len(b) for b in bodies.values())+len(code.encode())+len(runner_body)+8192
    if size+previous>config['max_snapshot_bytes']:return {'status':'LIMIT_REACHED','reason':'MAX_REVIEW_PROBE_BYTES'}
    record={'id':ident,'test_id':test_id,'idea_id':test['idea_id'],'agent_id':api.agent['id'],
            'code':code,'code_sha256':hashlib.sha256(code.encode()).hexdigest(),'staged_bytes':size,
            'workspace':relative.as_posix(),'status':'STAGING','assertion_syntax':assertion_syntax(code)}
    record.update(mode='SPECIMENS_ONLY' if selected else 'AUTHOR_ENVIRONMENT',specimen_paths=selected,
                  staged_paths=sorted(bodies),dependency_owners=dependencies,import_paths=imports)
    state.setdefault('prototype_review_probes',[]).append(record)
    api.event('prototype_review_probe_reserved',record)
    try:
        empty=root.parent/(ident+'-empty-source')
        empty.mkdir(parents=True,exist_ok=False)
        Workspace(empty,root,config['max_file_bytes'],config['max_snapshot_bytes'])
        for path,body in bodies.items():_atomic_write(root/_relative(path),body)
        _atomic_write(root/driver,code.encode())
        _atomic_write(root/runner,runner_body)
    except (ValueError,OSError) as error:
        record.update(status='BLOCKED',cleanup_ok=True,reason='REVIEW_PROBE_PREPARATION_FAILED',output=type(error).__name__+': '+str(error)[:2000])
        api.event('prototype_review_probe_finished',record)
        return record
    remaining=config['max_active_seconds']-api.engine.current_active_seconds()
    if remaining<1:
        record.update(status='LIMIT_REACHED',cleanup_ok=True,reason='MAX_ACTIVE_SECONDS')
        api.event('prototype_review_probe_finished',record)
        return record
    record['status']='RUNNING'
    api.event('prototype_review_probe_started',record)
    executor=DockerExecutor(config['docker_image'],max(1,min(30,int(remaining))))
    worker=asyncio.create_task(asyncio.to_thread(executor.run,root,['python','-B',runner]))
    cancelled=False
    try:result=await asyncio.shield(worker)
    except asyncio.CancelledError:
        cancelled=True
        while not worker.done():
            try:await asyncio.shield(worker)
            except asyncio.CancelledError:continue
        result=worker.result()
    except Exception as error:
        record.update(status='BLOCKED',cleanup_ok=False,reason='REVIEW_PROBE_TRANSPORT_FAILED',output=type(error).__name__+': '+str(error)[:2000])
        api.event('prototype_review_probe_finished',record)
        return record
    # A reviewer may write fixtures, never replace implementation/input evidence.
    protected=set(selected) if selected else {source['path'],test['prototype_plan']['script']['path'],*[p for p in bodies if p.startswith('.packages/')]}
    e=next((e for e in state.get('experiments',[]) if e.get('experiment_id')==test['experiment_id']),{})
    if not selected:protected.update(a['path'] for a in e.get('coding_sources',[]))
    protected.update(p for p in bodies if p.startswith('.review-packages/'))
    unchanged=True
    for path in protected:
        try:unchanged &= _read_bytes(root,_relative(path),config['max_file_bytes'])==bodies[path]
        except (OSError,ValueError,KeyError):unchanged=False
    record.update(status=result['status'],returncode=result.get('returncode',result.get('exit_code')),
                  output=str(result.get('output',''))[-16000:],implementation_unchanged=bool(unchanged),
                  cleanup_ok=result.get('cleanup_ok'),
                  meaning='Independent probe execution, not a scientific verdict. A zero exit alone does not prove relevance or a meaningful negative case.')
    try:
        observed=json.loads(_read_bytes(root,_relative(diagnostic),8192))
        if not isinstance(observed,dict) or observed.get('outcome') not in {'PASSED','SETUP_ERROR','ASSERTION_FAILED','RUNTIME_ERROR'}:raise ValueError('Invalid diagnostic')
    except (OSError,ValueError):
        observed={'outcome':'PASSED' if record['returncode']==0 else 'INDETERMINATE'}
    record.update({k:v for k,v in observed.items() if k in {'outcome','error_type','missing_module','detail'}})
    if not unchanged:record.update(status='BLOCKED',outcome='EVIDENCE_CHANGED',reason='REVIEW_PROBE_MODIFIED_IMPLEMENTATION')
    if record['outcome']=='SETUP_ERROR' and record.get('cleanup_ok') is True:
        record.update(status='DEFERRED',reason='REVIEW_PROBE_SETUP_ERROR')
    api.event('prototype_review_probe_finished',record)
    if cancelled:raise asyncio.CancelledError()
    if record['outcome']=='SETUP_ERROR' and record.get('cleanup_ok') is True:
        issue=defer_setup(api,test_id,'REVIEW_PROBE_SETUP_ERROR',
            {k:record[k] for k in ('missing_module','error_type','detail') if k in record})
        record['next_action']=issue['next_action']
    elif record['outcome']!='INDETERMINATE':
        api.agent.get('prototype_probe_setup_issues',{}).pop(test_id,None)
        api.agent.get('prototype_probe_setup_attempts',{}).pop(test_id,None)
    return record
