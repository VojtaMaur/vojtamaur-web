"""Independent relevance review of frozen code BEFORE spending a Docker execution."""
import copy
import hashlib
from .storage import now


def required(api):
    from .prototype_workflow import enabled
    return enabled(api)


def find(state, plan_id):
    return next((p for p in state.get('prototype_plan_submissions', []) if p['id'] == plan_id), None)


def queue(api, plan):
    if not required(api):
        return
    if find(api.engine.state, plan['id']):
        return
    from .prototype_review import snapshot
    record = copy.deepcopy(plan)
    record['focus'] = copy.deepcopy(api.idea(plan['idea_id']).get('prototype_focus', {}))
    record['artifacts'] = [record['script']]
    snapshot(api, record)
    api.engine.state.setdefault('prototype_plan_submissions', []).append(record)
    api.event('prototype_preflight_queued', {'plan_id': plan['id'], 'idea_id': plan['idea_id'],
        'script_sha256': plan['script']['sha256'], 'goal': record['focus'].get('goal')})


def pending(state, agent):
    from .research_tasks import revision
    tasks = []
    for owner in state['agents']:
        for p in owner.get('prototype_plans', {}).values():
            saved = find(state, p['id'])
            idea = next((i for i in state['ideas'] if i['id'] == p['idea_id']), None)
            if (not saved or saved.get('preflight_review') or not idea or idea.get('status') == 'REJECTED'
                    or p['research_revision'] != revision(idea)
                    or agent['id'] in {owner['id'], idea.get('agent_id')}):
                continue
            tasks.append({'kind': 'PROTOTYPE_PLAN', 'target_id': p['id'], 'idea_id': p['idea_id'],
                          'revision': p['id'], 'documents': []})
    return tasks


def packet(state, agent, task):
    saved = find(state, task['target_id'])
    if not saved:
        return dict(task, stage='STALE')
    idea=next(i for i in state['ideas'] if i['id'] == saved['idea_id'])
    candidate={k:idea.get(k) for k in ('id','title','mechanism','provider','summary','payment',
                                      'validation_plan','novelty_delta','proposed_change')}
    return dict(task, stage='DONE' if saved.get('preflight_review') else 'CHECK_RELEVANCE',
        candidate=candidate,
        prototype_plan=saved,
        next_action='Read the complete frozen script with read_prototype_plan. Does its actual code exercise the selected mechanism operation and a real negative case? '
            'Compare only THIS candidate and its selected scope. Never import another mechanism or require whole-system external behavior from a local component. '
            'READY permits only this exact local execution, never a prototype award. REVISE needs a concrete relevant change. '
            'A useful local subcomponent may be READY even without public deployment; require honest SUBCOMPONENT scope for external gaps.')


def selected(api, plan_id):
    task = api.agent.get('review_assignment', {})
    record = find(api.engine.state, plan_id)
    if (api.agent.get('work_kind') != 'REVIEW' or task.get('kind') != 'PROTOTYPE_PLAN'
            or task.get('target_id') != plan_id or not record
            or api.agent['id'] in {record['agent_id'], api.idea(record['idea_id']).get('agent_id')}):
        raise ValueError('Choose your independently assigned PROTOTYPE_PLAN')
    return record


def source(api, record):
    from .prototype_review import artifact_bytes
    body = artifact_bytes(api, record, record['script'])
    if hashlib.sha256(body).hexdigest() != record['script']['sha256']:
        raise ValueError('Frozen prototype plan code changed')
    return body.decode('utf-8')


def missing(api, record):
    from .review_tasks import _subtract
    return _subtract([[0, len(source(api, record))]],
                     api.agent.get('prototype_plan_reads', {}).get(record['id'], []))


def read(api, plan_id, offset=0, limit=12000):
    record = selected(api, plan_id)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 16000:
        raise ValueError('Invalid plan source paging')
    code = source(api, record)
    end = min(len(code), offset + limit)
    api.agent.setdefault('prototype_plan_reads', {}).setdefault(plan_id, []).append([offset, end])
    api.event('prototype_plan_read', {'plan_id': plan_id, 'offset': offset, 'end': end})
    return {'plan_id': plan_id, 'text': code[offset:end], 'offset': offset, 'end': end,
            'next_offset': end if end < len(code) else None, 'sha256': record['script']['sha256']}


def review(api, plan_id, verdict, reason, mechanism_operation, evidence_code=''):
    record = selected(api, plan_id)
    if record.get('preflight_review'):
        return record['preflight_review']
    gaps = missing(api, record)
    if gaps:
        return {'status': 'DEFERRED', 'reason': 'OWN_PLANNED_SCRIPT_READ_REQUIRED', 'missing_ranges': gaps}
    if verdict not in {'READY', 'REVISE'} or not isinstance(reason, str) or not 20 <= len(reason) <= 4000:
        raise ValueError('Provide READY/REVISE and a concrete bounded reason')
    if not isinstance(mechanism_operation, str) or not 20 <= len(mechanism_operation) <= 2000:
        raise ValueError('Name the actual mechanism operation, not generic file integrity')
    if verdict == 'READY' and (not isinstance(evidence_code, str) or not 10 <= len(evidence_code) <= 4000
                               or evidence_code not in source(api, record)):
        return {'status': 'DEFERRED', 'reason': 'PLANNED_OPERATION_CODE_REQUIRED',
                'next_action': 'Quote exact executable code implementing the relevant operation; otherwise REVISE with the missing operation.'}
    result = {'plan_id': plan_id, 'idea_id': record['idea_id'], 'agent_id': api.agent['id'],
              'verdict': verdict, 'reason': reason, 'mechanism_operation': mechanism_operation,
              'evidence_code': evidence_code, 'time': now(),
              'meaning': 'Pre-execution relevance judgment only, not proof of success or external approval.'}
    record['preflight_review'] = result
    api.event('prototype_preflight_reviewed', result)
    return result


def gate(api, plan):
    if not required(api):
        return None
    saved = find(api.engine.state, plan['id'])
    if not saved:
        # Legacy plans are reviewed on explicit resume; no old certificate is invented.
        queue(api, plan)
        saved = find(api.engine.state, plan['id'])
    review = (saved or {}).get('preflight_review', {})
    if review.get('verdict') == 'READY':
        return None
    return {'status': 'DEFERRED', 'reason': 'PROTOTYPE_PLAN_REVIEW_PENDING' if not review else 'PROTOTYPE_PLAN_REVISE',
            'plan_id': plan['id'], 'review': review,
            'next_action': 'Await independent code relevance review without another paid LOCAL round.' if not review else
                'Change the actual code to implement the reviewer-selected mechanism operation, then record_prototype_plan again. No test or experiment IDs are required.'}


def submission_issue(api, idea_id, script):
    if not required(api):
        return None
    from .research_tasks import revision
    rejected = [p for p in api.engine.state.get('prototype_plan_submissions', [])
                if p['agent_id'] == api.agent['id'] and p['idea_id'] == idea_id
                and p.get('preflight_review', {}).get('verdict') == 'REVISE'
                and p['research_revision'] == revision(api.idea(idea_id))]
    if rejected and script['sha256'] == rejected[-1]['script']['sha256']:
        return {'status': 'DEFERRED', 'reason': 'PLANNED_OPERATION_NEEDS_CODE_CHANGE',
                'review': rejected[-1]['preflight_review'],
                'next_action': 'Correct the actual script; changing a title, assertion description or scope alone cannot fix an unrelated implementation.'}
    return None


def local_issue(state, agent, idea_id):
    from .research_tasks import revision
    plan = agent.get('prototype_plans', {}).get(idea_id, {})
    idea = next((i for i in state['ideas'] if i['id'] == idea_id), None)
    if not idea or plan.get('research_revision') != revision(idea):
        return None
    saved = find(state, plan.get('id'))
    if saved and not saved.get('preflight_review'):
        return {'status': 'DEFERRED', 'reason': 'PROTOTYPE_PLAN_REVIEW_PENDING', 'plan_id': plan['id']}
    return None


def action(api):
    plan = api.agent.get('prototype_plans', {}).get(api.agent.get('research_assignment', {}).get('target_id'))
    if not plan or not required(api):
        return None
    from .research_tasks import revision
    if plan['research_revision'] != revision(api.idea(plan['idea_id'])):
        return None
    saved = find(api.engine.state, plan['id'])
    review = (saved or {}).get('preflight_review', {})
    if review.get('verdict') == 'REVISE':
        try:
            changed = api.workspace.file_info(plan['script']['path'])['sha256'] != plan['script']['sha256']
        except (OSError, ValueError):
            changed = False
        return {'tool': 'record_prototype_plan' if changed else 'required', 'review': review,
                'exclude_tools': ['run_experiment', 'record_test', 'execute_prototype', 'note', 'get_research_task'],
                'next_action': 'Implement the exact missing operation, then resubmit the plan. Host binds repair IDs automatically. Or record a concrete capability blocker.'}
    return None


def hold(engine):
    for agent in engine.state['agents']:
        if agent.get('work_kind') != 'LOCAL' or agent['status'] != 'PENDING':
            continue
        issue = local_issue(engine.state, agent, agent.get('research_assignment', {}).get('target_id'))
        if issue:
            agent.update(status='BLOCKED', reason_for_stopping=issue['reason'])
            engine.store.commit(engine.state, 'prototype_waiting_for_preflight', issue, agent['id'])
