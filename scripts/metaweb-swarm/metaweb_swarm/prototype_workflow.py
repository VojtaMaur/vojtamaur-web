"""Host-owned repair links and one execution/receipt operation for LOCAL work."""


def enabled(api):
    from .research_tasks import enabled as research_enabled
    state = getattr(getattr(api, 'engine', None), 'state', {})
    return (state.get('config',{}).get('coding_backend','legacy')=='legacy'
            and research_enabled(state) and getattr(api, 'agent', {}).get('work_kind') == 'LOCAL'
            and state['config'].get('require_prototype_focus', False))


def plan(api, idea_id, property_tested, input_path, script_path, output_paths,
         positive_assertion, negative_assertion, scope, limitations,
         repair_notes='', repair_check=''):
    """Resolve links from the current owned assignment, never from model-supplied IDs."""
    from .research_tasks import gate
    issue = gate(api, idea_id)
    if issue:
        return issue
    from .prototype_debug import last
    from .prototype_revision import latest
    failed = last(api.engine.state, api.agent, idea_id)
    revised = latest(api.engine.state, api.agent, idea_id)
    return api.record_prototype_plan(idea_id, property_tested, input_path, script_path, output_paths,
        positive_assertion, negative_assertion, scope, limitations,
        repair_experiment_id=failed['experiment_id'] if failed else '',
        revision_test_id=revised['id'] if revised else '',
        repair_notes=repair_notes, repair_check=repair_check)


async def execute(api, argv):
    """Run the current frozen plan and record its captured outputs without another LLM turn."""
    if not enabled(api):
        return {'status': 'DEFERRED', 'reason': 'RESEARCH_LOCAL_WORKFLOW_REQUIRED'}
    idea_id = api.agent.get('research_assignment', {}).get('target_id', '')
    from .research_tasks import gate
    issue = gate(api, idea_id)
    if issue:
        return issue
    from .prototype_review import active, experiment_gate
    issue = experiment_gate(api, argv, idea_id)
    if issue:
        return issue
    plan = active(api, idea_id)
    if not plan:
        return {'status': 'DEFERRED', 'reason': 'PROTOTYPE_PLAN_REQUIRED'}
    # A receipt interrupted between execution and registration is finished below,
    # using the same captured bytes. Never rerun just to register an experiment.
    previous = next((e for e in reversed(api.engine.state.get('experiments', []))
                     if e.get('agent_id') == api.agent['id'] and e.get('prototype_plan_id') == plan['id']
                     and e.get('argv') == argv), None)
    if previous and previous.get('prototype_readiness', {}).get('status') == 'READY_FOR_TEST_RECEIPT':
        result = previous
    else:
        attempt = api.agent.get('prototype_execution', {})
        if attempt.get('status') == 'RUNNING':
            return {'status': 'BLOCKED', 'reason': 'LOCAL_EXECUTION_OUTCOME_UNRESOLVED',
                    'attempt': attempt, 'next_action': 'Inspect the tool audit and container before resolving the interrupted execution.'}
        api.agent['prototype_execution'] = {'status': 'RUNNING', 'plan_id': plan['id'], 'argv': argv}
        api.event('prototype_execution_started', api.agent['prototype_execution'])
        result = await api.run_experiment(argv, idea_id)
        api.agent['prototype_execution'] = {'status': 'FINISHED', 'plan_id': plan['id'],
            'experiment_id': result.get('experiment_id'), 'outcome': result.get('status')}
        api.event('prototype_execution_finished', api.agent['prototype_execution'])
    if result.get('prototype_readiness', {}).get('status') != 'READY_FOR_TEST_RECEIPT':
        return result
    receipt = api.record_test(idea_id, result['experiment_id'],
        'Host-captured execution of ' + plan['id'] + ': ' + plan['property_tested'] +
        '\nPositive/negative assertions are in the frozen plan and await independent review.')
    if not receipt.get('id'):
        return dict(result,status=receipt.get('status','DEFERRED'),reason='TEST_RECEIPT_INCOMPLETE',
                    test_receipt=receipt,next_action='Execution finished but its receipt is incomplete. Resolve the exact capture diagnostic; do not claim a tested prototype.')
    return dict(result, test_receipt=receipt,
        next_action='Execution and receipt captured together. Do not rerun for bookkeeping. Independent review determines actual coverage; no external deposit is implied.')


def action(api):
    if not enabled(api):
        return None
    from .prototype_review import active
    from .prototype_preflight import find
    from .prototype_debug import last
    idea_id = api.agent.get('research_assignment', {}).get('target_id')
    plan = active(api, idea_id) if idea_id else None
    if not plan or last(api.engine.state, api.agent, idea_id):
        return None
    saved = find(api.engine.state, plan['id'])
    if (saved or {}).get('preflight_review', {}).get('verdict') != 'READY':
        return None
    try:
        changed = api.workspace.file_info(plan['script']['path'])['sha256'] != plan['script']['sha256']
    except (OSError, ValueError):
        changed = True
    if changed:
        return {'tool': 'record_prototype_plan', 'next_action': 'Code changed since review. Freeze the actual script again; the old relevance check cannot authorize changed bytes.'}
    if any(t.get('agent_id') == api.agent['id'] and t.get('prototype_plan', {}).get('id') == plan['id']
           for t in api.engine.state.get('tests', [])):
        return None
    return {'tool': 'execute_prototype', 'next_action': 'Run the independently checked script now. The host captures execution and its receipt together; no IDs or manual registration.'}


def progress(api):
    idea_id = api.agent.get('research_assignment', {}).get('target_id')
    plan = api.agent.get('prototype_plans', {}).get(idea_id, {})
    try:
        code = api.workspace.file_info(plan['script']['path'])['sha256']
    except (KeyError, OSError, ValueError):
        code = None
    return (idea_id, code,
            len([e for e in api.engine.state.get('experiments', []) if e.get('agent_id') == api.agent['id']]),
            len([t for t in api.engine.state.get('tests', []) if t.get('agent_id') == api.agent['id']]))


def begin(api):
    if not enabled(api):
        return
    current = progress(api)
    if not current[0] or current[0] not in api.agent.get('prototype_plans', {}):
        return
    old = api.agent.setdefault('prototype_workflow_progress', {})
    notes = len(api.agent.get('operator_notes', []))
    if old.get('idea_id') != current[0] or old.get('operator_notes_count') != notes:
        old.clear()
        old.update(idea_id=current[0], operator_notes_count=notes, stalled_rounds=0)
    old['before'] = current


def finish(api):
    if not enabled(api):
        return
    tracking = api.agent.get('prototype_workflow_progress', {})
    if not tracking.get('before') or tracking.get('checked_round') == api.agent['rounds']:
        return
    current = progress(api)
    tracking['checked_round'] = api.agent['rounds']
    tracking['stalled_rounds'] = tracking['stalled_rounds'] + 1 if tuple(tracking['before']) == current else 0
    if tracking['stalled_rounds'] < 2 or not current[0]:
        return
    from .research_tasks import revision
    record = {'idea_id': current[0], 'phase': 'LOCAL', 'revision': revision(api.idea(current[0])),
              'operator_notes_count': len(api.agent.get('operator_notes', [])), 'status': 'BLOCKED',
              'reason': 'PROTOTYPE_WORKFLOW_STALLED',
              'next_action': 'Two LOCAL rounds produced no changed script, execution or test. Retain the hypothesis and take another candidate; inspect the model/tool audit before reopening.'}
    api.agent.setdefault('research_task_blocks', []).append(record)
    api.event('prototype_workflow_stalled', record)
