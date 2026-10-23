"""Immutable identity/recovery observations, separate from coverage judgments."""
import hashlib
from .storage import canonical


def facts(state, test):
    from .research_tasks import revision
    from .prototype_inputs import descriptor
    plan = test['prototype_plan']
    idea = next((i for i in state['ideas'] if i['id'] == test['idea_id']), {})
    source = plan['input']
    matches = [dict(path=a['path'], sha256=a['sha256'], bytes=a['bytes']) for a in test['artifacts']
               if a['path'] in plan['output_paths'] and a['sha256'] == source['sha256'] and a['bytes'] == source['bytes']]
    return {'test_id': test['id'], 'idea_id': test['idea_id'], 'plan_idea_id': plan['idea_id'],
            'candidate_title': idea.get('title'), 'candidate_revision_current': bool(idea and plan['research_revision'] == revision(idea)),
            'identity_bound': plan['idea_id'] == test['idea_id'] and bool(idea),
            'retained_input': dict(source, input_kind='DESCRIPTOR' if descriptor(source.get('export', '')) else 'PAYLOAD'),
            'matching_recovered_outputs': matches,
            'external_custody': 'NOT_ESTABLISHED_BY_LOCAL_EXECUTION',
            'local_contract':plan.get('local_contract'),
            'review_rule':'Generic metadata extraction is HELPER_ONLY, not Open Library/Gist/Commons primitive coverage. Reading a zero checksum back proves parsing, not tamper rejection. Inspect which operation rejects/recovers invalid input against independent expected data; if absent choose REVISE or honestly HELPER_ONLY.',
            'scope_rule': 'Judge actual local operations and negative cases separately from public hosting, '
                'discoverability and custody. Relevant working local code can be SUBCOMPONENT without upload. '
                'Matching byte facts are real, but do not prove decoding or format conformance. '
                'Identity binding does not prove semantic relevance; explain any unrelated code using its actual operations. '
                'A descriptor roundtrip preserves only the descriptor, not website content. '
                'Use REVISE for a concrete local defect, not solely because external publication is absent.'}


def read(api, test_id):
    from .review_tasks import current
    task = current(api.engine.state, api.agent)
    if api.agent.get('work_kind') != 'REVIEW' or not task or task.get('kind') != 'PROTOTYPE_TEST' or task.get('target_id') != test_id:
        raise ValueError('Read facts only for your assigned independent prototype review')
    test = task['test_receipt']
    result = facts(api.engine.state, test)
    fingerprint = hashlib.sha256(canonical(result).encode()).hexdigest()
    api.agent.setdefault('prototype_fact_reads', {})[test_id] = fingerprint
    api.event('prototype_facts_read', dict(test_id=test_id, fingerprint=fingerprint))
    return result


def seen(api, test):
    expected = hashlib.sha256(canonical(facts(api.engine.state, test)).encode()).hexdigest()
    return api.agent.get('prototype_fact_reads', {}).get(test['id']) == expected


def check(api, test, verdict, observed_recovery, review_basis, recovered_path):
    observed=seen(api,test)
    if observed_recovery == 'NOT_EVALUATED' and review_basis == 'UNSPECIFIED' and not observed:
        return None  # Compatibility for direct legacy callers; live SDK dispatch reads facts first.
    actual = facts(api.engine.state, test)
    if not observed:
        return {'status': 'DEFERRED', 'reason': 'CURRENT_REVIEW_FACTS_REQUIRED', 'facts': actual}
    matching = actual['matching_recovered_outputs']
    if matching and observed_recovery == 'NOT_EVALUATED':
        return {'status':'DEFERRED','reason':'RECOVERY_OBSERVATION_REQUIRED','facts':actual,
                'next_action':'Acknowledge the matching output bytes with MATCHES_INPUT and the exact recovered_path. '
                    'You can still reject unrelated or defective code; byte identity alone is not a functional endorsement.'}
    if verdict == 'REVISE' and review_basis == 'UNSPECIFIED':
        return {'status':'DEFERRED','reason':'LOCAL_REVIEW_BASIS_REQUIRED','facts':actual,
                'next_action':'State LOCAL_DEFECT, IRRELEVANT_TEST or EXTERNAL_GAP_ONLY. Judge the local operation separately from public custody.'}
    path_matches = any(a['path'] == recovered_path for a in matching)
    path_exists = any(a['path'] == recovered_path for a in test['artifacts']
                      if a['path'] in test['prototype_plan']['output_paths'])
    conflict = (observed_recovery == 'MATCHES_INPUT' and not path_matches
                or observed_recovery == 'DIFFERS_FROM_INPUT' and (path_matches or not path_exists)
                or observed_recovery == 'NO_RECOVERED_OUTPUT' and bool(matching))
    if conflict:
        return {'status': 'DEFERRED', 'reason': 'REVIEW_RECOVERY_FACT_CONFLICT', 'facts': actual,
                'next_action': 'Correct the factual observation using host hashes/lengths; '
                    'you may still choose REVISE for a concrete implementation/relevance defect.'}
    if verdict == 'REVISE' and review_basis == 'EXTERNAL_GAP_ONLY':
        return {'status': 'DEFERRED', 'reason': 'LOCAL_COMPONENT_ASSESSMENT_REQUIRED', 'facts': actual,
                'next_action': 'Assess the local operation. Choose SUBCOMPONENT only when meaningful positive/negative '
                    'cases pass the evidence contract; otherwise record REVISE with a specific LOCAL_DEFECT '
                    'or IRRELEVANT_TEST. Missing public deposit alone is not a local test failure.'}
    return None
