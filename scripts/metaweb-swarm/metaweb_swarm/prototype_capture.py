"""Exact planned output capture; neither a semantic verdict nor external execution."""
from .research_recovery import defer, clear


def file_state(api, path):
    try:
        info = api.workspace.file_info(path)
        return dict(info, mtime_ns=(api.workspace.root/path).stat().st_mtime_ns)
    except FileNotFoundError:
        return None


def before(api, plan):
    return {path:file_state(api,path) for path in plan['output_paths']} if plan else {}


def capture(api, plan, experiment, previous):
    """Observe generated files in the private workspace after the executor returned."""
    paths = [plan['script']['path'], *plan['output_paths']]
    inventory, missing, unchanged, generated = [], [], [], []
    for path in paths:
        current = file_state(api, path)
        if current is None:
            missing.append(path)
            continue
        inventory.append({'path':path, **{k:v for k,v in current.items() if k!='mtime_ns'}})
        if path in previous:
            if previous[path] is not None and current==previous[path]: unchanged.append(path)
            else: generated.append(path)
    experiment.update(artifact_inventory=inventory, prototype_capture_version=1,
                      generated_outputs=generated)
    if experiment.get('status')!='COMPLETED' or experiment.get('returncode',experiment.get('exit_code'))!=0:
        return {'status':'BLOCKED','reason':'EXPERIMENT_NOT_SUCCESSFUL','next_action':'Inspect the actual Docker error; correct the script/dependency before rerunning.'}
    if missing or unchanged:
        return defer(api, plan['idea_id'], 'LOCAL', 'PROTOTYPE_OUTPUTS_REQUIRED',
                     {'missing_paths':missing,'unchanged_outputs':unchanged,
                      'script':plan['script'],'output_paths':plan['output_paths'],
                      'experiment_id':experiment['experiment_id']},
                     'Correct the actual script to WRITE every planned output during execution (e.g. Path(output).write_bytes(encoded)). Printing or a prewritten placeholder is not a generated specimen. Update record_prototype_plan for changed script bytes, then run once again. Do not label this host bookkeeping or register nonexistent files.')
    script = next(a for a in inventory if a['path']==plan['script']['path'])
    if script['sha256']!=plan['script']['sha256']:
        return {'status':'DEFERRED','reason':'PROTOTYPE_SCRIPT_CHANGED','next_action':'Script changed during execution; update the plan and rerun.'}
    clear(api.agent, 'LOCAL')
    from .prototype_workflow import enabled as workflow_enabled
    if workflow_enabled(api):
        return {'status':'READY_FOR_TEST_RECEIPT','planned_paths':paths,
                'next_action':'execute_prototype captures the receipt automatically for this exact execution. No model registration call or rerun; independent review still assesses assertions and mechanism coverage.'}
    return {'status':'READY_FOR_TEST_RECEIPT','planned_paths':paths,
            'next_action':'Call record_test with THIS experiment_id. Planned files are captured and host registration is automatic; no bookkeeping rerun. Receipt records execution only; independent review assesses assertions/scope.'}


def receipt_inventory(api, idea_id, experiment):
    from .research_tasks import gate
    issue = gate(api, idea_id)
    if issue: return None, issue
    from .prototype_review import active
    plan = active(api, idea_id)
    if not plan or experiment.get('prototype_plan_id')!=plan['id']:
        return None, {'status':'DEFERRED','reason':'PLANNED_EXECUTION_REQUIRED'}
    readiness = experiment.get('prototype_readiness', {})
    if readiness.get('status')!='READY_FOR_TEST_RECEIPT':
        return None, readiness or {'status':'DEFERRED','reason':'NEW_PLANNED_CAPTURE_REQUIRED',
                                  'next_action':'Run the current planned script once to capture exact outputs with the new contract.'}
    expected = [plan['script']['path'], *plan['output_paths']]
    inventory = []
    for path in expected:
        saved = next((a for a in experiment['artifact_inventory'] if a['path']==path), None)
        info = api.workspace.file_info(path)
        if not saved or any(saved[k]!=info[k] for k in ('sha256','bytes')):
            return None, {'status':'DEFERRED','reason':'EXECUTED_ARTIFACT_CHANGED','path':path,
                          'next_action':'Do not certify changed artifact bytes; update the plan and run the changed script again.'}
        inventory.append(saved)
    api.register_idea_artifacts(idea_id, expected)
    return inventory, None
