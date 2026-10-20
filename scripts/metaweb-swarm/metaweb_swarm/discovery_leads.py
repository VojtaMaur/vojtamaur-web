"""Durable pre-qualification observations. Leads never authorize execution."""
import hashlib
from .storage import canonical, now


def revision(lead):
    return hashlib.sha256(canonical({k: lead.get(k) for k in
        ('screen_ids', 'documents', 'summary', 'open_questions', 'next_action', 'target_assessments')}).encode()).hexdigest()


def refresh_status(lead):
    if lead.get('review') and lead['review']['revision'] != revision(lead) and not lead.get('idea_id'):
        lead['status'] = 'NEEDS_EVIDENCE'


def retain_screen(api, screen):
    from .carrier_screening import enabled, screen_allows, _normal
    if not enabled(api) or not screen_allows(api, screen):
        return None
    leads = api.engine.state.setdefault('discovery_leads', [])
    lead = next((r for r in leads if _normal(r['provider']) == _normal(screen['provider'])), None)
    if lead is None:
        lead = {'id': 'LEAD-' + hashlib.sha256(_normal(screen['provider']).encode()).hexdigest()[:16],
                'provider': screen['provider'], 'agent_id': api.agent['id'], 'contributors': [],
                'screen_ids': [], 'documents': [], 'status': 'SCREENED',
                'summary': 'Screened direction only; service capabilities, price and novelty unverified.',
                'open_questions': ['Upload protocol, file acceptance, payment and retention are unverified.'],
                'next_action': 'Read primary API and terms, then record_discovery_lead with concrete findings.',
                'created_at': now()}
        leads.append(lead)
    if screen['id'] not in lead['screen_ids']:
        lead['screen_ids'].append(screen['id'])
    if api.agent['id'] not in lead['contributors']:
        lead['contributors'].append(api.agent['id'])
    refresh_status(lead)
    api.event('discovery_lead_retained', {'lead_id': lead['id'], 'screen_id': screen['id'],
              'meaning': 'Unqualified observation, not an IDEA, novelty certification or execution permission.'})
    return lead


def retain_document(api, result):
    from .carrier_screening import enabled
    if not enabled(api) or not result['text'].strip():
        return None
    current = api.agent.get('active_carrier_screen', {})
    screen = next((r for r in api.engine.state.get('carrier_screens', []) if r['id'] == current.get('id')), None)
    if not screen:
        return None
    lead = retain_screen(api, screen)
    if not lead:
        return None
    doc = {k: result[k] for k in ('request_id', 'url', 'sha256', 'offset', 'end')}
    doc['agent_id'] = api.agent['id']
    if result.get('pdf'):
        doc.update(pdf=result['pdf'],pages=result['pages'])
    if doc not in lead['documents']:
        lead['documents'].append(doc)
        if lead['status'] == 'SCREENED':
            lead['status'] = 'NEEDS_EVIDENCE'
        refresh_status(lead)
        api.event('discovery_lead_document', {'lead_id': lead['id'], 'document': doc})
    return lead


def get(api, lead_id):
    lead = next((r for r in api.engine.state.get('discovery_leads', []) if r['id'] == lead_id), None)
    if lead is None:
        return None, {'status': 'DEFERRED', 'reason': 'UNKNOWN_LEAD_ID',
                      'next_action': 'Call list_discovery_state and use an existing LEAD ID.'}
    return lead, None


def retain_qualification(api, receipt):
    lead = next((r for r in api.engine.state.get('discovery_leads', [])
                 if r['provider'].strip().casefold() == receipt['plan']['provider'].strip().casefold()
                 and api.agent['id'] in r['contributors']), None)
    if lead is None:
        return
    assessment = {k: receipt.get(k) for k in ('id', 'status', 'reasons', 'admissible', 'next_action')}
    if assessment not in lead.setdefault('target_assessments', []):
        lead['target_assessments'].append(assessment)
        refresh_status(lead)
        api.event('discovery_lead_assessed', {'lead_id': lead['id'], 'assessment': assessment})


def record(api, lead_id, summary, open_questions, next_action):
    lead, refusal = get(api, lead_id)
    if refusal:
        return refusal
    if api.agent.get('work_kind') != 'DISCOVERY' or api.agent['id'] not in lead['contributors']:
        raise ValueError('Only a screened discovery contributor can update this lead')
    if not isinstance(summary, str) or not 5 <= len(summary) <= 2000:
        raise ValueError('Lead summary must be text, 5..2000 characters')
    if (not isinstance(open_questions, list) or len(open_questions) > 8
            or any(not isinstance(q, str) or not 5 <= len(q) <= 500 for q in open_questions)):
        raise ValueError('Provide up to eight concrete questions, 5..500 characters each')
    if not isinstance(next_action, str) or not 5 <= len(next_action) <= 1000:
        raise ValueError('Lead needs a concrete next_action, 5..1000 characters')
    lead.update(summary=summary, open_questions=open_questions, next_action=next_action, updated_at=now())
    refresh_status(lead)
    lead.setdefault('contributions', []).append({'agent_id': api.agent['id'], 'summary': summary,
                       'open_questions': open_questions, 'next_action': next_action, 'time': now()})
    api.event('discovery_lead_updated', {'lead_id': lead_id, 'revision': revision(lead)})
    return lead


def awaiting_review(state):
    # Screening alone is not a reason to pay an auditor to rediscover the service.
    return [r for r in state.get('discovery_leads', []) if r.get('documents')
            and not r.get('idea_id') and r.get('review', {}).get('revision') != revision(r)]


def review(api, lead_id, disposition, reason, next_action, failure_fact='', source_urls=None):
    lead, refusal = get(api, lead_id)
    if refusal:
        return refusal
    if api.agent['role'] != 'Evidence Auditor' or api.agent['id'] in lead['contributors']:
        raise ValueError('Lead triage needs an independent Evidence Auditor')
    if disposition not in {'NEEDS_EVIDENCE', 'SETUP_REQUIRED', 'NOT_SUITABLE', 'QUALIFY'}:
        raise ValueError('Unknown lead disposition')
    for text in (reason, next_action):
        if not isinstance(text, str) or not 5 <= len(text) <= 2000:
            raise ValueError('Triage needs concrete reason and next_action, 5..2000 characters')
    urls = source_urls or []
    if (not isinstance(urls, list) or len(urls) > 8
            or any(not isinstance(u, str) or len(u) > 2000 for u in urls)
            or not isinstance(failure_fact, str) or len(failure_fact) > 4000):
        raise ValueError('Invalid triage evidence')
    from .review_tasks import triage_gate
    gate=triage_gate(api,lead_id,urls)
    if gate: return gate
    reads = {r['url'].rstrip('/') for r in api.agent.get('http_document_reads', {}).values()}
    if not urls or not all(u.rstrip('/') in reads for u in urls):
        return {'status': 'DEFERRED', 'reason': 'INDEPENDENT_LEAD_DOCUMENTS_REQUIRED',
                'missing_document_urls':[u for u in urls if u.rstrip('/') not in reads],
                'next_action': 'Read the relevant primary documents yourself with read_document, then record_lead_review.'}
    quote = None
    requested = disposition
    if disposition == 'NOT_SUITABLE':
        from .review_contract import source_quote
        quote = source_quote(api, failure_fact, urls)
        if not quote:
            disposition = 'NEEDS_EVIDENCE'
    result = {'agent_id': api.agent['id'], 'disposition': disposition, 'requested_disposition': requested,
              'reason': reason, 'next_action': next_action, 'source_urls': urls,
              'failure_fact': failure_fact, 'source_quote': quote, 'revision': revision(lead), 'time': now(),
              'meaning': 'Independent preliminary judgment; never PASS or upload authorization.'}
    lead.update(status=disposition, review=result)
    lead.setdefault('reviews', []).append(result)
    api.event('discovery_lead_reviewed', {'lead_id': lead_id, **result})
    return result


def state_view(api):
    return {'active_screen': api.agent.get('active_carrier_screen'),
            'leads': [{k: r.get(k) for k in ('id', 'provider', 'status', 'summary', 'open_questions',
                      'next_action', 'documents', 'target_assessments', 'review', 'idea_id')} for r in api.engine.state.get('discovery_leads', [])],
            'own_admissible_qualifications': [{'id': q['id'], 'provider': q['plan']['provider'], 'status': q['status']}
                for q in api.engine.state.get('deposit_qualifications', [])
                if q['agent_id'] == api.agent['id'] and q.get('admissible')],
            'next_action': 'Use existing IDs. Unqualified LEADs need evidence/triage; check_deposit_target creates QUAL IDs; only then record_deposit_flow or submit_idea.'}


def complete_discovery(state, agent, output):
    if agent.get('work_kind') != 'DISCOVERY' or output['status'] not in {'COMPLETED', 'REJECTED'}:
        return output
    missing = [r['id'] for r in state.get('discovery_leads', [])
               if r.get('documents') and agent['id'] in r['contributors'] and not r.get('idea_id')
               and not any(c['agent_id'] == agent['id'] for c in r.get('contributions', []))]
    if missing:
        output.update(status='CONTINUE', reason_for_stopping='LEAD_FINDINGS_REQUIRED: record the partial results before finishing')
        output['unexplored_leads'] = ['Use record_discovery_lead for ' + ', '.join(missing)
                    + ': concrete findings, unanswered questions and next action. Do not restart discovery or manufacture qualification IDs.']
    return output
