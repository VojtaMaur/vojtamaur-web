"""No-network feasibility receipts for generic HTTP deposits; no provider connectors."""
import hashlib
import os
import re
from urllib.parse import urlsplit
from .storage import canonical, now
from .http_transport import normalize_request, HttpPolicyError, _protected, _deny_git_write, _url

FIELDS = {'upload_url', 'method', 'authentication', 'credential_id', 'export_path',
          'required_external_actions', 'documentation_urls', 'provider', 'novelty_class',
          'baseline_evidence_ids', 'baseline_behavior', 'proposed_change', 'validation_plan'}


def assess_flow(plan, config):
    steps = plan.setdefault('operation_steps', [])
    if not isinstance(steps, list) or len(steps) > 20:
        raise ValueError('operation_steps must be a list of at most 20 operations')
    if not steps:
        return {'status':'UNSPECIFIED', 'effective_external_actions':plan['required_external_actions'],
                'reasons':['UPLOAD_FLOW_REQUIRED'] if config.get('require_explicit_upload_flow',False) else []}
    count=0
    for step in steps:
        if not isinstance(step,dict) or set(step)!={'method','purpose','sends_export','uses_credential'}:
            raise ValueError('Every operation needs method, purpose, sends_export, uses_credential')
        if step['method'] not in {'GET','HEAD','POST','PUT','PATCH','DELETE','OPTIONS'}:
            raise ValueError('Unsupported operation method')
        if not isinstance(step['purpose'],str) or not 5<=len(step['purpose'].strip())<=1500:
            raise ValueError('Describe each operation purpose, 5..1500 chars')
        if type(step['sends_export']) is not bool or type(step['uses_credential']) is not bool:
            raise ValueError('Operation flags must be booleans')
        if step['method'] not in {'GET','HEAD','OPTIONS'} or step['uses_credential']:
            count+=1
        if step['sends_export'] and step['method'] in {'GET','HEAD','OPTIONS'}:
            raise ValueError('Read operation cannot send the export')
    writes = [s for s in steps if s['method'] not in {'GET','HEAD','OPTIONS'}]
    if sum(s['sends_export'] for s in steps)!=1 or not writes or writes[0]['method']!=plan['method']:
        raise ValueError('Flow must send the exact export once and start with the declared method')
    declared=plan['required_external_actions']
    plan['required_external_actions']=max(declared,count)
    return {'status':'RECORDED', 'declared_external_actions':declared, 'derived_external_actions':count,
            'effective_external_actions':plan['required_external_actions'],
            'reasons':['EXECUTABLE_FLOW_REQUIRED'] if len(steps)>1 and not plan.get('execution_steps') else [],
            'meaning':'Declared protocol; multiple requests require a bounded execution plan and independent audit.'}


def assess(api, plan):
    if not isinstance(plan, dict) or not FIELDS.issubset(plan) or set(plan) - (FIELDS | {'operation_steps','execution_steps'}):
        raise ValueError('Deposit plan requires exactly: ' + ', '.join(sorted(FIELDS)))
    plan = dict(plan)
    for key in FIELDS - {'documentation_urls', 'baseline_evidence_ids', 'required_external_actions'}:
        if not isinstance(plan[key], str) or len(plan[key]) > 4000:
            raise ValueError('Invalid deposit plan field: ' + key)
    for key in ('documentation_urls', 'baseline_evidence_ids'):
        if not isinstance(plan[key], list) or len(plan[key]) > 20 or any(not isinstance(s, str) or len(s) > 2000 for s in plan[key]):
            raise ValueError('Invalid deposit plan field: ' + key)
    if type(plan['required_external_actions']) is not int or plan['required_external_actions'] < 1:
        raise ValueError('required_external_actions must be a positive integer')
    if plan['authentication'] not in {'ANONYMOUS', 'DEDICATED_CREDENTIAL', 'ACCOUNT_REQUIRED', 'UNKNOWN'}:
        raise ValueError('Invalid authentication mode')
    if plan['novelty_class'] not in {'POTENTIALLY_NEW', 'IMPROVEMENT', 'KNOWN_CARRIER', 'UNASSESSED'}:
        raise ValueError('Invalid novelty_class')
    plan['method'] = plan['method'].upper()
    if plan['method'] not in {'POST', 'PUT', 'PATCH'} or not plan['provider'].strip():
        raise ValueError('An upload needs POST/PUT/PATCH and a concrete provider')
    for url in ([plan['upload_url']] if plan['upload_url'].strip() else []) + plan['documentation_urls']:
        parsed = urlsplit(url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError('Plan URLs must be HTTP(S), without credentials/fragments')
        if any(word in parsed.query.lower() for word in ('token=', 'password=', 'api_key=', 'secret=')):
            raise ValueError('Never put credentials in a deposit plan URL')
    if plan['authentication'] in {'ANONYMOUS', 'UNKNOWN'} and plan['credential_id']:
        raise ValueError('Anonymous or unknown-auth plans cannot name a credential')
    config = api.engine.state['config']
    flow = assess_flow(plan, config)
    host = (urlsplit(plan['upload_url']).hostname or '').lower()
    canonical_error = False
    try:
        canonical_url, host, _, _ = _url(plan['upload_url'], config)
        plan['upload_url'] = canonical_url
    except HttpPolicyError:
        canonical_error = True
    # Target policy takes precedence over missing accounts and budgets.
    reasons = list(flow['reasons'])
    from .carrier_screening import registry_matches, improvements_allowed, enabled, screened_origin
    registered = registry_matches(api.engine.baseline,plan['provider'],host)
    if registered and not improvements_allowed(config):
        reasons.append('ALREADY_KNOWN_BASELINE')
    if enabled(api) and plan['upload_url'].strip():
        if not all(screened_origin(api,plan['provider'],u) for u in [plan['upload_url']]+plan['documentation_urls']):
            reasons.append('CARRIER_SCOPE_REQUIRED')
    forbidden = _protected(host.rstrip("."))
    try:
        _deny_git_write(plan['upload_url'])
    except HttpPolicyError:
        forbidden = True
    if forbidden:
        reasons.append('POLICY_FORBIDDEN')
    elif not plan['upload_url'].strip():
        reasons.append('TARGET_DETAILS_REQUIRED')
    elif canonical_error:
        reasons.append('TARGET_POLICY_UNSUPPORTED')
    else:
        try:
            normalize_request({'method': plan['method'], 'url': plan['upload_url']}, config, api.workspace)
        except (ValueError, OSError):
            reasons.append('TARGET_POLICY_UNSUPPORTED')
    if config.get('http_access') != 'enabled' or config.get('external_scope') != 'external':
        reasons.append('EXTERNAL_SCOPE_DISABLED')
    export = next((f for f in api.engine.state.get('exports', {}).get('files', []) if f['path'] == plan['export_path']), None)
    if plan.get('execution_steps'):
        from .deposit_plan import validate
        if not export: raise ValueError('Executable plan needs a retained export')
        compiled=validate(plan['execution_steps'],config,export)
        first=compiled['steps'][0]
        if (first['url'],first['method'],first['credential_id'])!=(plan['upload_url'],plan['method'],plan['credential_id']):
            raise ValueError('Executable first step differs from qualified target')
        operations=[{'method':s['method'],'purpose':s['purpose'],'sends_export':s['sends_export'],'uses_credential':bool(s['credential_id'])} for s in compiled['steps']]
        if operations!=plan['operation_steps']: raise ValueError('Declared operations differ from executable steps')
        flow['execution_plan_sha256']=compiled['sha256']
        for s in compiled['steps']:
            if s['credential_id']:
                grant=next((c for c in config.get('http_credentials',[]) if c['id']==s['credential_id']),None)
                if not grant or not os.getenv(grant['env']): reasons.append('ACCOUNT_SETUP_REQUIRED')
    if not export:
        reasons.append('EXPORT_UNAVAILABLE')
    elif export['bytes'] > min(config.get('max_external_bytes', 0), config.get('max_http_request_bytes', 0)):
        reasons.append('RESOURCE_LIMIT')
    if plan['required_external_actions'] > config.get('max_external_actions', 0):
        reasons.append('RESOURCE_LIMIT')
    # Bound grants to the exact target host; never consult ambient account stores.
    grant = next((c for c in config.get('http_credentials', []) if c['id'] == plan['credential_id']), None)
    available = bool(grant and host in grant['hosts'] and os.getenv(grant['env']))
    if plan['authentication'] == 'UNKNOWN':
        reasons.append('AUTHENTICATION_UNVERIFIED')
    elif plan['authentication'] != 'ANONYMOUS' and not available:
        reasons.append('ACCOUNT_SETUP_REQUIRED')
    baseline = api.check_baseline([plan['provider']] + ([host] if host else []))
    archive_hits = []
    for hit in baseline['matches']:
        if not hit['path'].lower().endswith(('archive.txt', 'live-3.txt')):
            continue
        urls = re.findall(r'https?://[^\s<>\)\]"\x27]+', hit['excerpt'])
        exact_host = any((urlsplit(u).hostname or '').casefold() == host.casefold() for u in urls)
        exact_provider = re.search(r'(?<!\w)' + re.escape(plan['provider']) + r'(?!\w)', hit['excerpt'], re.I)
        if exact_host or exact_provider:
            archive_hits.append(hit)
    valid_ids = [i for i in plan['baseline_evidence_ids'] if i in {hit['id'] for hit in baseline['matches']}]
    if plan['novelty_class'] == 'KNOWN_CARRIER' and valid_ids:
        reasons.append('ALREADY_KNOWN_BASELINE')
    elif plan['novelty_class'] in {'UNASSESSED', 'KNOWN_CARRIER'}:
        reasons.append('BASELINE_COMPARISON_REQUIRED')
    elif archive_hits and not (plan['novelty_class'] == 'IMPROVEMENT' and valid_ids
          and all(plan[k].strip() for k in ('baseline_behavior', 'proposed_change', 'validation_plan'))
          and plan['baseline_behavior'] != plan['proposed_change']):
        # An ARCHIVE mention alone is not proof of use. Require an explicit comparison;
        # do not falsely reject a service or infer novelty from absent literal matches.
        reasons.append('BASELINE_COMPARISON_REQUIRED')
    observed = set()
    for source in api.agent.get('external_sources', []):
        url = source.get('url') if isinstance(source, dict) else source
        if isinstance(url, str): observed.add(url.rstrip('/').split('#')[0])
    if len(set(plan['documentation_urls'])) < 2 or not all(u.rstrip('/') in observed for u in plan['documentation_urls']):
        reasons.append('PRIMARY_SOURCES_REQUIRED')
    reasons = list(dict.fromkeys(reasons))
    priority = ['POLICY_FORBIDDEN', 'TARGET_DETAILS_REQUIRED', 'TARGET_POLICY_UNSUPPORTED', 'AUTHENTICATION_UNVERIFIED', 'EXTERNAL_SCOPE_DISABLED',
                'EXPORT_UNAVAILABLE', 'RESOURCE_LIMIT', 'UPLOAD_FLOW_REQUIRED', 'EXECUTABLE_FLOW_REQUIRED', 'MULTI_STEP_EXECUTION_UNAVAILABLE', 'ALREADY_KNOWN_BASELINE',
                'BASELINE_COMPARISON_REQUIRED', 'CARRIER_SCOPE_REQUIRED', 'PRIMARY_SOURCES_REQUIRED', 'ACCOUNT_SETUP_REQUIRED']
    reason = next((r for r in priority if r in reasons), 'READY_FOR_AUDIT')
    lead_reasons = {'ACCOUNT_SETUP_REQUIRED','RESOURCE_LIMIT','UPLOAD_FLOW_REQUIRED','EXECUTABLE_FLOW_REQUIRED','MULTI_STEP_EXECUTION_UNAVAILABLE'}
    admissible = not reasons or (bool(reasons) and set(reasons)<=lead_reasons)
    admission_kind = 'READY_FOR_AUDIT' if not reasons else 'BLOCKED_LEAD' if admissible else 'NOT_ADMITTED'
    result = {'id': 'QUAL-' + hashlib.sha256(canonical({'plan': plan, 'reasons': reasons, 'agent': api.agent['id']}).encode()).hexdigest()[:20],
              'agent_id': api.agent['id'], 'plan': plan, 'status': reason, 'reasons': reasons,
              'admissible': admissible, 'admission_kind':admission_kind, 'execution_ready':not reasons,
              'flow_assessment':flow, 'credential_available': available,
              'export_sha256': export['sha256'] if export else None,
              'export_bytes': export['bytes'] if export else None,
              'baseline': baseline, 'registered_entries':registered, 'time': now(),
              'meaning': 'No HTTP executed; source URLs observed, semantic terms/retention and novelty require independent audit.',
              'next_action': 'Do not request credentials or approval for forbidden targets; research another carrier.' if forbidden else
                             'Read the actual write API and record its endpoint; no guessed upload URL or public-download-as-upload assumption.' if reason == 'TARGET_DETAILS_REQUIRED' else
                             'Verify write authentication from API docs; a public download URL does not prove anonymous upload.' if reason == 'AUTHENTICATION_UNVERIFIED' else
                             'Retain this as a BLOCKED candidate now; missing credentials/resources/flow are setup leads, not rejection. Submit qualification_id or the host will retain an unverified draft at the next checkpoint. No upload is authorized.' if admission_kind == 'BLOCKED_LEAD' else
                             'Submit this qualification_id with your discovery candidate, then hand off to independent auditor.' if admissible else
                             'Resolve the recorded reasons or research another carrier; rejected plans remain in the audit.'}
    existing = next((r for r in api.engine.state.get('deposit_qualifications', []) if r['id'] == result['id']), None)
    from .carrier_screening import qualification_steering
    if existing:
        qualification_steering(api, existing)
        return existing
    api.engine.state.setdefault('deposit_qualifications', []).append(result)
    api.event('deposit_target_assessed', result)
    qualification_steering(api, result)
    from .console import short
    print(f"  {api.agent['id']} | Target: {short(host or plan['provider'], 80)} {reason}", flush=True)
    return result

def bind_submission(api, data):
    """Admission happens before semantic dedupe or assigning an IDEA ID."""
    if not api.engine.state['config'].get('require_deposit_qualification'):
        return None, None
    if not data.get('id') and api.agent.get('work_kind') != 'DISCOVERY':
        return None, {'status': 'DEFERRED', 'reason': 'DISCOVERY_OWNS_NEW_CANDIDATES', 'next_action': 'Review existing IDs or report missing discovery; do not invent a candidate.'}
    old = api.idea(data['id']) if data.get('id') else None
    identity = data.get('qualification_id') or (old or {}).get('qualification_id')
    receipt = next((r for r in api.engine.state.get('deposit_qualifications', []) if r['id'] == identity), None)
    if not receipt or not receipt['admissible']:
        return None, {'status': 'DEFERRED', 'reason': 'DEPOSIT_QUALIFICATION_REQUIRED', 'qualification_status': receipt.get('status') if receipt else None,
                      'next_action': 'Call check_deposit_target with a concrete plan BEFORE submit_idea; only admissible receipts become candidates.'}
    if not data.get('id') and receipt['agent_id'] == api.agent['id']:
        retained = next((i for i in api.engine.state['ideas'] if i.get('qualification_id') == receipt['id']), None)
        if retained:
            data['id'] = retained['id']
            old = retained
    if not old and receipt['agent_id'] != api.agent['id']:
        return None, {'status': 'DEFERRED', 'reason': 'QUALIFICATION_OWNER_MISMATCH'}
    if data.get('provider', '').strip().casefold() != receipt['plan']['provider'].strip().casefold():
        return None, {'status': 'DEFERRED', 'reason': 'QUALIFICATION_PROVIDER_MISMATCH'}
    return receipt, None

def execution_gate(api, idea, descriptor):
    receipt = next((r for r in api.engine.state.get('deposit_qualifications', []) if r['id'] == (idea or {}).get('qualification_id')), None)
    if not receipt or receipt['status'] != 'READY_FOR_AUDIT':
        return 'DEPOSIT_QUALIFICATION_NOT_READY'
    plan = receipt['plan']
    from .carrier_screening import registry_matches, improvements_allowed
    host=(urlsplit(plan['upload_url']).hostname or '').casefold()
    if not improvements_allowed(api.engine.state['config']) and registry_matches(api.engine.baseline,plan['provider'],host):
        return 'ALREADY_KNOWN_BASELINE'
    if plan.get('execution_steps'):
        return 'EXECUTION_SEQUENCE_REQUIRED'
    flow = assess_flow(dict(plan), api.engine.state['config'])
    if flow['reasons']:
        return flow['reasons'][0]
    if (descriptor['url'], descriptor['method'], descriptor['credential_id']) != (plan['upload_url'], plan['method'], plan['credential_id']):
        return 'UPLOAD_DIFFERS_FROM_QUALIFIED_PLAN'
    if len(descriptor.get('files', [])) != 1 or not any(f.get('sha256') == receipt['export_sha256'] and f.get('bytes') == receipt['export_bytes'] for f in descriptor.get('files', [])):
        return 'UPLOAD_IS_NOT_QUALIFIED_EXPORT'
    if (idea or {}).get('critique', {}).get('qualification_id') != receipt['id']:
        return 'QUALIFIED_PLAN_NEEDS_INDEPENDENT_AUDIT'
    return None
