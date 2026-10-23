"""Repair a successful execution whose independent coverage review was REVISE."""
import hashlib


def reference_issue(api, idea_id, test_id='', experiment_id='', active=True):
    """Reject phantom/cross-owner/stale links before storing a new plan."""
    from .research_tasks import revision
    from .prototype_debug import last
    state = api.engine.state
    rev = revision(api.idea(idea_id))
    for value, kind in ((test_id, 'TEST'), (experiment_id, 'EXPERIMENT')):
        if not isinstance(value, str):
            raise ValueError('Repair IDs must be strings; new plans use empty strings')
        if not value:
            continue
        if kind == 'TEST':
            record = next((t for t in state.get('tests', []) if t['id'] == value), None)
            current = latest(state, api.agent, idea_id)
            valid = (record and record.get('agent_id') == api.agent['id'] and record.get('idea_id') == idea_id
                     and record.get('host_execution_verified') and record.get('prototype_review', {}).get('verdict') == 'REVISE'
                     and record.get('prototype_plan', {}).get('research_revision') == rev)
        else:
            record = next((e for e in state.get('experiments', []) if e['experiment_id'] == value), None)
            current = last(state, api.agent, idea_id)
            valid = (record and record.get('agent_id') == api.agent['id'] and record.get('idea_id') == idea_id
                     and record.get('failure_evidence', {}).get('research_revision') == rev)
        if not valid or active and current is not record:
            return {'status': 'DEFERRED', 'reason': 'INVALID_REPAIR_REFERENCE', 'reference_kind': kind,
                    'provided_id': value, 'expected_id': (current or {}).get('id' if kind == 'TEST' else 'experiment_id', ''),
                    'next_action': 'Use the exact current own REVISE TEST-ID or diagnosed failed EXPERIMENT-ID. '
                        'For a new plan leave repair IDs empty. A research revision hash is not a test ID.'}
    return None


def latest(state, agent, idea_id):
    from .research_tasks import revision
    idea = next((i for i in state['ideas'] if i['id'] == idea_id), None)
    if not idea:
        return None
    for test in reversed(state.get('tests', [])):
        if (test.get('agent_id') == agent['id'] and test.get('idea_id') == idea_id
                and test.get('host_execution_verified')
                and test.get('prototype_plan', {}).get('research_revision') == revision(idea)):
            review=test.get('prototype_review', {})
            return test if review.get('verdict') == 'REVISE' and not review.get('review_unresolved') else None
    return None


def packet(test):
    review = test['prototype_review']
    return {'test_id': test['id'], 'review_id': review['id'], 'verdict': 'REVISE',
            'reason': review['reason'], 'script': test['prototype_plan']['script'],
            'local_contract':test['prototype_plan'].get('local_contract'),
            'required_local_change':review.get('required_local_change'),'defect_code':review.get('defect_code'),
            'prototype_plan': test['prototype_plan'],
            'next_action': 'The exit-zero receipt is NOT completion of this task. Read read_revised_test, '
                'implement the missing operation/assertions identified by the independent reviewer, then '
                'record_prototype_plan with repair_notes and repair_check; the host binds repair IDs. '
                'If the requested property cannot be tested locally, record_research_blocker with the '
                'specific missing capability/evidence; retain this idea and take the next one.'}


def selected(api, test_id):
    task = api.agent.get('research_assignment', {})
    test = latest(api.engine.state, api.agent, task.get('target_id'))
    if api.agent.get('work_kind') != 'LOCAL' or not test or test['id'] != test_id:
        raise ValueError('Choose the REVISE test ID for your current LOCAL assignment, not a failed experiment ID')
    return test


def source(api, test):
    from .prototype_review import artifact_bytes
    script = test['prototype_plan']['script']
    data = artifact_bytes(api, test, script)
    if hashlib.sha256(data).hexdigest() != script['sha256']:
        raise ValueError('Executed source no longer matches its audit snapshot')
    return data.decode('utf-8')


def missing(api, test):
    from .review_tasks import _subtract
    return _subtract([[0, len(source(api, test))]],
                     api.agent.get('revision_script_reads', {}).get(test['id'], []))


def read(api, test_id, offset=0, limit=12000):
    test = selected(api, test_id)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 16000:
        raise ValueError('Invalid revision source paging')
    code = source(api, test)
    end = min(len(code), offset + limit)
    api.agent.setdefault('revision_script_reads', {}).setdefault(test_id, []).append([offset, end])
    api.event('revised_test_read', {'test_id': test_id, 'offset': offset, 'end': end,
                                  'sha256': test['prototype_plan']['script']['sha256']})
    return dict(packet(test), text=code[offset:end], offset=offset, end=end,
                total_chars=len(code), next_offset=end if end < len(code) else None)


def repair_issue(api, idea_id, script, revision_test_id, notes, check):
    test = latest(api.engine.state, api.agent, idea_id)
    if not test:
        return None
    if missing(api, test):
        return {'status': 'DEFERRED', 'reason': 'OWN_REVISED_SCRIPT_READ_REQUIRED', 'revision': packet(test)}
    if script['sha256'] == test['prototype_plan']['script']['sha256']:
        return {'status': 'DEFERRED', 'reason': 'REVISED_TEST_NEEDS_CODE_CHANGE', 'revision': packet(test)}
    if (revision_test_id != test['id'] or not isinstance(notes, str) or not 20 <= len(notes) <= 4000
            or not isinstance(check, str) or not 20 <= len(check) <= 2000):
        return {'status': 'DEFERRED', 'reason': 'REVIEW_REPAIR_PLAN_REQUIRED', 'revision': packet(test)}
    return None


def action(api):
    test = latest(api.engine.state, api.agent, api.agent.get('research_assignment', {}).get('target_id'))
    if not test:
        return None
    from .research_tasks import revision
    from .research_recovery import blocked
    idea = api.idea(test['idea_id'])
    if blocked(api.agent, idea, 'LOCAL') or any(
            b.get('idea_id') == idea['id'] and b.get('revision') == revision(idea)
            and b.get('operator_notes_count') == len(api.agent.get('operator_notes', []))
            for b in api.agent.get('research_blockers', [])):
        return None
    gaps = missing(api, test)
    if gaps:
        return {'tool': 'read_revised_test', 'arguments': {'test_id': test['id'], 'offset': gaps[0][0],
                'limit': min(16000, gaps[0][1] - gaps[0][0])},
                'next_action': 'Read the exact rejected test source and independent REVISE reason. '
                    'This is a successful execution with insufficient coverage, not a crashed experiment.'}
    plan = api.agent.get('prototype_plans', {}).get(test['idea_id'], {})
    if plan.get('revision_repair', {}).get('test_id') == test['id']:
        executed = next((e for e in reversed(api.engine.state.get('experiments', []))
                         if e.get('agent_id') == api.agent['id'] and e.get('idea_id') == test['idea_id']
                         and e.get('prototype_plan_id') == plan['id']), None)
        if executed and executed.get('status') == 'COMPLETED' and executed.get('returncode') == 0:
            from .prototype_workflow import enabled as workflow_enabled
            return {'tool': 'execute_prototype' if workflow_enabled(api) else 'record_test', 'experiment_id': executed['experiment_id'],
                    'next_action': 'Record this exact revised execution once. Do not rerun for bookkeeping; '
                        'the new receipt goes back to independent scope review.'}
        from .prototype_workflow import enabled as workflow_enabled
        return {'tool': 'execute_prototype' if workflow_enabled(api) else 'run_experiment',
                'next_action': 'Execute the changed, revision-linked script. The host-owned workflow records its receipt automatically.'}
    return {'tool': 'required', 'revision': packet(test),
            'exclude_tools': ['note', 'list_current_ideas', 'get_research_task', 'read_failed_experiment'],
            'next_action': 'Repair the actual implementation and tests with write_file, then update '
                'record_prototype_plan with repair_notes and repair_check; the host binds all repair IDs; '
                'or record_research_blocker for a concrete capability/evidence obstacle. '
                'An old receipt, a note or a declaration of completion does not close this assignment.'}


def begin(api):
    """One progress baseline per actual LOCAL round, including interrupted SDK turns."""
    if api.engine.state['config'].get('coding_backend')=='sdk_shell':return
    test = latest(api.engine.state, api.agent, api.agent.get('research_assignment', {}).get('target_id'))
    if not test:
        return
    progress = api.agent.setdefault('prototype_revision_progress', {})
    notes_count = len(api.agent.get('operator_notes', []))
    if progress.get('test_id') != test['id'] or progress.get('operator_notes_count') != notes_count:
        progress.clear()
        progress.update(test_id=test['id'], script_sha256=test['prototype_plan']['script']['sha256'],
                        stalled_rounds=0, operator_notes_count=notes_count)


def finish(api):
    """Two rounds without new script bytes/receipt defer this assignment, never reject it."""
    if api.engine.state['config'].get('coding_backend')=='sdk_shell':return
    progress = api.agent.get('prototype_revision_progress', {})
    if not progress or progress.get('checked_round') == api.agent['rounds']:
        return
    test = latest(api.engine.state, api.agent, api.agent.get('research_assignment', {}).get('target_id'))
    if not test or progress.get('test_id') != test['id']:
        return
    from .research_recovery import blocked
    idea = api.idea(test['idea_id'])
    if blocked(api.agent, idea, 'LOCAL'):
        return
    progress['checked_round'] = api.agent['rounds']
    path = test['prototype_plan']['script']['path']
    plan = api.agent.get('prototype_plans', {}).get(test['idea_id'], {})
    path = plan.get('script', {}).get('path', path)
    try:
        actual = api.workspace.file_info(path)['sha256']
    except (OSError, ValueError):
        actual = None
    changed = actual is not None and actual != progress['script_sha256']
    progress['stalled_rounds'] = 0 if changed else progress['stalled_rounds'] + 1
    if changed:
        progress['script_sha256'] = actual
    if progress['stalled_rounds'] < 2:
        return
    from .research_tasks import revision
    record = {'idea_id': idea['id'], 'phase': 'LOCAL', 'revision': revision(idea),
              'operator_notes_count': len(api.agent.get('operator_notes', [])),
              'status': 'BLOCKED', 'reason': 'PROTOTYPE_REVISION_STALLED',
              'test_id': test['id'], 'stalled_rounds': progress['stalled_rounds'],
              'next_action': 'No changed implementation or new test receipt in two revision rounds. '
                  'Retain this idea and evidence; take the next current-run candidate. '
                  'A changed claim or an operator resolution can reopen this local assignment.'}
    api.agent.setdefault('research_task_blocks', []).append(record)
    api.event('prototype_revision_stalled', record)
