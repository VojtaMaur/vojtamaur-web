"""Early, conservative corpus screening and durable discovery steering."""
import hashlib
import re
from urllib.parse import urlsplit
from .storage import canonical, now
from .baseline import owner_rejection
from .http_transport import _url, _origin, _protected, HttpPolicyError

SECTIONS = {'ALTERNATIVE DEPLOYMENTS', 'SOURCE REPOSITORY', 'COPIES OF GITHUB REPOSITORY',
            'PYTHON CLI PACKAGE', 'ARCHIVAL COPIES AND DISTRIBUTIONS', 'VIDEO SNAPSHOTS'}

def _normal(value):
    return ' '.join(value.casefold().split())

def registry_matches(baseline, provider, host):
    """Require a named entry plus URL in an existing-layer section, not any mention."""
    found = []
    for doc in baseline.documents:
        if not doc['path'].lower().endswith('archive.txt') and doc['path'] != 'context/live-3.txt':
            continue
        section, label, label_line = '', '', 0
        for number, raw in enumerate(doc['lines'], 1):
            line = raw.strip()
            if not line:
                continue
            if not raw[:1].isspace():
                section = re.sub(r'\s*\([^)]*\)', '', line.split(':', 1)[0]).strip()
                label = ''; continue
            if not line.startswith(('http://', 'https://')):
                label, label_line = line, number; continue
            if section not in SECTIONS or not label:
                continue
            if re.search(r'\b(proposed|planned|candidate|not implemented|hypothesis|example)\b', label, re.I):
                continue
            try:
                parsed = urlsplit(line)
                actual_host = (parsed.hostname or '').casefold()
            except ValueError:
                continue
            aliases = [_normal(re.sub(r'\([^)]*\)', '', x)) for x in label.split('/')]
            exact_label = _normal(provider) in aliases
            # Detect an unambiguous brand DNS label even if the model renames
            # "Figshare" to "Figshare v2 API". Do not infer a shared company
            # from multi-word products such as Cloudflare Pages versus R2.
            brand_labels = {re.sub(r'[^a-z0-9]', '', a) for a in aliases if a}
            brand_host = any(label in brand_labels for label in host.split('.')[:-1])
            alias_domain = any(re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)+',a)
                               and (host==a or host.endswith('.'+a)) for a in aliases)
            # Do not collapse related products (e.g. Cloudflare Pages vs R2).
            if not exact_label and actual_host != host and not brand_host and not alias_domain:
                continue
            found.append({'path':doc['path'], 'document_sha256':doc['sha256'], 'label':label,
                          'label_line':label_line, 'url_line':number, 'url':line, 'section':section})
            if len(found) == 8:
                return found
    return found

def enabled(api):
    return (api.engine.state['config'].get('carrier_screening', False)
            and api.agent.get('work_kind') == 'DISCOVERY')

def improvements_allowed(config):
    # Old focused deposit runs did not have the field: keep their "new carrier"
    # objective strict without rewriting a historical checkpoint.
    return config.get('allow_known_carrier_improvements', not (config.get('require_deposit_qualification') and config.get('task_style')=='focused'))

def screen_allows(api, screen):
    if not screen.get('research_allowed'): return False
    if screen.get('status')=='IMPROVEMENT_REVIEW' and not improvements_allowed(api.engine.state['config']): return False
    return True

def screened_origin(api, provider, url):
    target, _, _, _ = _url(url,api.engine.state['config'])
    origin=_origin(urlsplit(target))
    return any(s.get('agent_id')==api.agent['id'] and _normal(s['provider'])==_normal(provider)
               and _origin(urlsplit(s['service_url']))==origin and screen_allows(api,s)
               for s in api.engine.state.get('carrier_screens',[]))

def assess(api, provider, service_url, baseline_behavior='', proposed_change='', validation_plan=''):
    if not isinstance(provider, str) or not 2 <= len(provider.strip()) <= 100:
        raise ValueError('Provider must be concrete text, 2..100 characters')
    if not isinstance(service_url, str) or not 1 <= len(service_url) <= 4000:
        raise ValueError('service_url must be a public provider/API/docs URL')
    for value in (baseline_behavior, proposed_change, validation_plan):
        if not isinstance(value, str) or len(value) > 2000:
            raise ValueError('Improvement descriptions must be text up to 2000 characters')
    config = api.engine.state['config']
    canonical_url, host, _, _ = _url(service_url, config)
    result = api.check_baseline(list(dict.fromkeys([provider.strip()] + ([host] if len(host) <= 100 else []))))
    registrations = registry_matches(api.engine.baseline, provider.strip(), host)
    rejection = owner_rejection({'provider':provider, 'title':provider}, api.engine.owner_rejections)
    improvement = all(v.strip() for v in (baseline_behavior, proposed_change, validation_plan)) and baseline_behavior.strip() != proposed_change.strip()
    status = ('POLICY_FORBIDDEN' if _protected(host) else 'OWNER_REJECTED' if rejection else
              'IMPROVEMENT_REVIEW' if registrations and improvement and improvements_allowed(config) else
              'EXISTING_LAYER' if registrations else 'BASELINE_MENTION_REVIEW' if result['matches'] else 'NO_MATCH_FOUND')
    switch = api.agent.get('carrier_switch_required')
    same_rejected = switch and _normal(switch['provider']) == _normal(provider)
    if same_rejected and status in {'NO_MATCH_FOUND', 'BASELINE_MENTION_REVIEW'}:
        status = 'IMPROVEMENT_REVIEW' if improvement and improvements_allowed(config) and switch['reason'] == 'ALREADY_KNOWN_BASELINE' else 'SWITCH_CARRIER_REQUIRED'
    allowed = status in {'IMPROVEMENT_REVIEW', 'BASELINE_MENTION_REVIEW', 'NO_MATCH_FOUND'}
    key = {'provider':provider.strip(), 'service_url':canonical_url, 'baseline_behavior':baseline_behavior,
           'proposed_change':proposed_change, 'validation_plan':validation_plan, 'status':status,
           'corpus_sha256':result['coverage']['corpus_sha256'], 'agent_id':api.agent['id']}
    key['allow_known_carrier_improvements']=improvements_allowed(config)
    receipt = dict(key, id='SCREEN-'+hashlib.sha256(canonical(key).encode()).hexdigest()[:20],
                   time=now(), research_allowed=allowed, baseline=result, registered_entries=registrations,
                   meaning='Owner register entries, not live service verification. Mentions/absence do not prove deployment/novelty. Improvement still needs independent audit.',
                   next_action=('Search a DIFFERENT carrier now; do not spend more document calls on this unchanged direction. ' +
                                ('Known-carrier improvements are outside this run: new independent carriers only.' if not improvements_allowed(config) else
                                 'A genuine improvement needs separate baseline_behavior, proposed_change and validation_plan.') if not allowed else
                                'Read actual primary API/terms; explain the exact difference and qualify as IMPROVEMENT.' if status == 'IMPROVEMENT_REVIEW' else
                                'Inspect mention evidence before claiming known/new, then read actual API/terms.' if status == 'BASELINE_MENTION_REVIEW' else
                                'Read actual API/terms; no literal matches are not proof of novelty.'))
    prior = next((r for r in api.engine.state.get('carrier_screens', []) if r['id'] == receipt['id']), None)
    receipt = prior or receipt
    if not prior:
        api.engine.state.setdefault('carrier_screens', []).append(receipt)
    api.agent['active_carrier_screen'] = {k:receipt[k] for k in ('id','provider','service_url','status','research_allowed','next_action')}
    if allowed:
        api.agent.pop('carrier_switch_required', None)
    else:
        api.agent['carrier_switch_required'] = {'provider':provider, 'source_id':receipt['id'], 'reason':status,
                                               'next_action':receipt['next_action']}
    from .discovery_leads import retain_screen
    lead = retain_screen(api, receipt)
    result = dict(receipt)
    if lead:
        result['lead_id'] = lead['id']
        result['next_action'] += ' LEAD retained: update it using record_discovery_lead; do not invent a QUAL ID.'
    api.event('carrier_screened', receipt)
    return result

def qualification_steering(api, receipt):
    if not enabled(api) or not {'ALREADY_KNOWN_BASELINE','POLICY_FORBIDDEN'}.intersection(receipt.get('reasons', [receipt['status']])):
        return
    api.agent['carrier_switch_required'] = {
        'provider':receipt['plan']['provider'], 'source_id':receipt['id'], 'reason':('POLICY_FORBIDDEN' if 'POLICY_FORBIDDEN' in receipt.get('reasons', []) else 'ALREADY_KNOWN_BASELINE'),
        'next_action':'Call screen_carrier on a DIFFERENT carrier now. No further document calls on the unchanged rejected direction. '
                      'For a real improvement, separately screen with baseline_behavior, proposed_change and validation_plan.'}
    receipt['next_action'] = api.agent['carrier_switch_required']['next_action']
    api.event('carrier_switch_required', api.agent['carrier_switch_required'])

def document_gate(api, url=None):
    if not enabled(api):
        return None
    current = api.agent.get('active_carrier_screen')
    switch = api.agent.get('carrier_switch_required')
    if switch:
        return dict(switch, status='DEFERRED', reason='SWITCH_CARRIER_REQUIRED')
    if not current:
        return {'status':'DEFERRED', 'reason':'CARRIER_SCREEN_REQUIRED',
                'next_action':'Call screen_carrier(provider, service_url) before deep document reading. It uses the captured corpus, no HTTP.'}
    if not screen_allows(api,current):
        return {'status':'DEFERRED', 'reason':'SWITCH_CARRIER_REQUIRED',
                'next_action':'This run requires NEW carriers. Screen a DIFFERENT service; a historical improvement screen grants no document scope.' if not improvements_allowed(api.engine.state['config']) else current['next_action']}
    if url is None or not screened_origin(api,current['provider'],url):
        return {'status':'DEFERRED','reason':'CARRIER_DOCUMENT_ORIGIN_NOT_SCREENED',
                'active_provider':current['provider'],
                'next_action':'Screen the ACTUAL provider on this exact document URL before reading. A different docs/API origin needs its own screen under the same provider; switching providers needs a new screen. No wildcard or inference from shared company domains.'}
    return None
