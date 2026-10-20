"""Bounded reporter views; original evidence stays in the checkpoint and audit."""
import json
from collections import Counter


SECTIONS = {'ideas': 'id', 'critiques': 'id', 'tests': 'id', 'prototype_reviews': 'id',
            'experiments': 'experiment_id', 'http_requests': 'id', 'external_actions': 'id',
            'approvals': 'id', 'agents': 'id', 'package_installations': 'id', 'prototype_plan_submissions': 'id'}


def short(value, limit=240):
    text = str(value or '')
    return text if len(text) <= limit else text[:limit] + ' [detail available]'


def build(state):
    config = state['config']
    budget = min(14000, config.get('history_chars', 120000) // 4,
                 max(2000, config.get('prompt_chars', 20000) // 2))
    ids = [i['id'] for i in state['ideas']]
    result = {'kind': 'CURRENT_RUN_REPORT', 'run_id': state['run_id'], 'idea_ids': ids,
              'counts': {'candidates': len(ids), 'statuses': dict(Counter(i['status'] for i in state['ideas'])),
                         'experiments': len(state.get('experiments', [])),
                         'plan_relevance_reviews': dict(Counter(p.get('preflight_review', {}).get('verdict', 'PENDING')
                             for p in state.get('prototype_plan_submissions', []))),
                         'recorded_tests': len(state.get('tests', [])),
                         'pending_test_reviews': sum(bool(t.get('prototype_review_required')) and not t.get('prototype_review')
                                                     for t in state.get('tests', [])),
                         'prototype_reviews': dict(Counter(r['verdict'] for r in state.get('prototype_reviews', []))),
                         'http_requests': len(state.get('http_requests', [])),
                         'http_statuses': dict(Counter(r.get('status', 'UNKNOWN') for r in state.get('http_requests', []))),
                         'external_actions': len(state.get('external_actions', [])),
                         'external_action_statuses': dict(Counter(r.get('status', 'UNKNOWN') for r in state.get('external_actions', []))),
                         'package_installations': len(state.get('package_installations', [])),
                         'verified_deposits': sum(len(i.get('completion_receipts', [])) for i in state['ideas']),
                         'pending_approvals': sum(a.get('status') == 'PENDING' for a in state.get('approvals', []))},
              'ideas': [], 'tests': [],
              'detail': {'tool': 'read_report_detail', 'sections': list(SECTIONS),
                         'usage': 'Pass section and record_id for one original record, or empty record_id for a paged ID index. '
                             'Read pages only as needed. Raw histories, old submissions and HTTP headers are not part of this overview.'},
              'next_action': 'Call record_research_report with ALL idea_ids, a grounded conclusion and limitations, then finish. '
                  'Unresolved/rejected ideas and zero deposits are valid findings. Exit zero is execution only; '
                  'only independent FULL_MECHANISM review certifies a local prototype. SUBCOMPONENT and REVISE stay distinct. '
                  'Use read_report_detail for original evidence; do not fetch the whole checkpoint or every old revision.'}
    for idea in state['ideas']:
        from .research_recovery import matches
        blocks=[{'agent_id': a['id'], 'reason': b.get('reason')} for a in state['agents']
                for b in a.get('research_task_blocks', []) if matches(b, a, idea, 'LOCAL')]
        tests = [t for t in state.get('tests', []) if t.get('idea_id') == idea['id']]
        test = tests[-1] if tests else {}
        observations=test.get('prototype_review', {}).get('host_facts')
        result['ideas'].append({'id': idea['id'], 'title': short(idea.get('title'), 160),
            'status': idea['status'], 'provider': short(idea.get('provider'), 100),
            'payment': short(idea.get('payment'), 20), 'local_task_deferrals': blocks[-3:],
            'summary': short(idea.get('summary')), 'blocker': short(idea.get('blocker') or idea.get('rejection_reason')),
            'critique': {k: short(idea.get('critique', {}).get(k)) for k in ('verdict', 'reason')},
            'focus': {k: short(idea.get('prototype_focus', {}).get(k)) for k in ('scope', 'goal')},
            'latest_plan_review': next(({k: short(p['preflight_review'].get(k)) for k in ('verdict', 'reason')}
                for p in reversed(state.get('prototype_plan_submissions', []))
                if p['idea_id'] == idea['id'] and p.get('preflight_review')), None),
            'latest_test': {'id': test.get('id'), 'experiment_id': test.get('experiment_id'),
                            'verdict': test.get('prototype_review', {}).get('verdict'),
                            'matching_input_outputs': len(observations['matching_recovered_outputs']) if observations else None,
                            'input_kind': observations['retained_input']['input_kind'] if observations else None,
                            'review_unresolved': test.get('prototype_review', {}).get('review_unresolved',False),
                            'reason': short(test.get('prototype_review', {}).get('reason'))}})
    result['tests'] = [{k: t.get(k) for k in ('id', 'idea_id', 'experiment_id', 'host_execution_verified')}
                       for t in state.get('tests', [])[:8]]
    result['omitted_test_summaries'] = max(0, len(state.get('tests', [])) - len(result['tests']))
    result['omitted_idea_summaries'] = 0
    while len(json.dumps(result, ensure_ascii=False)) > budget and result['ideas']:
        result['ideas'].pop()
        result['omitted_idea_summaries'] += 1
    while len(json.dumps(result, ensure_ascii=False)) > budget and result['tests']:
        result['tests'].pop()
        result['omitted_test_summaries'] += 1
    if len(json.dumps(result, ensure_ascii=False)) > budget:
        # Very large inventories use the bounded index tool rather than truncating IDs silently.
        result['idea_ids'] = []
        result['idea_ids_index_required'] = True
        result['next_action'] = 'Read the paged ideas ID index with read_report_detail(section="ideas", record_id=""); '
        result['next_action'] += 'include every current ID when recording the report. Empty overview IDs do not mean zero candidates.'
    return result


def read(api, section, record_id='', offset=0, limit=4000):
    if api.agent.get('work_kind') != 'SYNTHESIS':
        raise ValueError('Report details belong to the SYNTHESIS role')
    if section not in SECTIONS or type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 8000:
        raise ValueError('Choose a report section and a bounded detail page')
    records = api.engine.state.get(section, [])
    key = SECTIONS[section]
    if record_id:
        record = next((r for r in records if r.get(key) == record_id), None)
        if record is None:
            raise ValueError('Unknown report record ID')
        # Model conversations are audited separately, never replayed by this accessor.
        if section == 'agents':
            record = {k: v for k, v in record.items() if k != 'history'}
    else:
        record = [r.get(key) for r in records]
    body = json.dumps(record, ensure_ascii=False, indent=2)
    end = min(len(body), offset + limit)
    api.event('report_detail_read', {'section': section, 'record_id': record_id, 'offset': offset, 'end': end})
    return {'section': section, 'record_id': record_id, 'text': body[offset:end],
            'offset': offset, 'end': end, 'total_chars': len(body), 'next_offset': end if end < len(body) else None}
