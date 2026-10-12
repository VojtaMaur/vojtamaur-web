"""Small operator-facing progress summaries; the complete audit stays on disk."""
import re


def short(value, limit=160):
    value = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str(value))
    value = " ".join(value.split())
    return value if len(value) <= limit else value[:limit - 3] + "..."


def startup(state):
    config = state["config"]
    print(f"Run: {state['run_id']} | {config.get('run_mode', 'supervised')} | {config.get('external_scope', 'sandbox-only')} | experiments={config['experiments']}", flush=True)
    for tier in ("cheap", "strong", "flag"):
        agents = [a for a in state["agents"] if a.get("model_tier") == tier]
        if agents:
            models = 'demo-fixture (no API calls)' if state.get('backend') == 'demo' else ", ".join(sorted({a.get('model') or 'UNSET' for a in agents}))
            print(f"  {tier} = {short(models)} | " + short(", ".join(a["role"] for a in agents), 260), flush=True)
    print(f"Limits: {config['max_steps']} rounds, {config['max_total_tokens']:,} tokens, {config['max_active_seconds']}s; USD ceiling={config.get('estimated_budget_usd')}", flush=True)
    print(f"Packages: {config.get('package_installation', 'disabled')} | Docker experiments: network none", flush=True)
    print(f"HTTP: {config.get('http_access', 'read-only')} | approvals={'required' if config.get('approval_required', True) else 'disabled'} | max requests={config.get('max_http_requests',100)} | external actions={config.get('max_external_actions',5)} | dedicated credentials={len(config.get('http_credentials', []))} | host accounts unavailable", flush=True)
    print(f"Prior work: {config.get('prior_work_policy', 'continue')}", flush=True)
    if config.get('semantic_dedupe'):
        model = config.get('model_tiers', {}).get('cheap') or config.get('model')
        print(f"Dedupe: current run only | ambiguous proposals: {short(model)}", flush=True)
    if config.get('carrier_screening'):
        print('Carrier routing: screen before docs | known direction -> switch', flush=True)
    if config.get('task_style') == 'focused':
        print('Task: ' + short(state['objective'], 220) + ' | role-specific tools', flush=True)
    if config.get('http_smoke_test'):
        scope = 'public HTTPS service' if config.get('http_smoke_service') else 'local service'
        print(f'Task: {scope} docs -> upload -> download -> SHA256 receipt; integration test', flush=True)
    if config.get('sandbox_smoke_test'):
        print('Task: SDK / PyPI / Docker round-trip and corruption test; no external deposit', flush=True)


def progress(kind, agent_id, data, seen):
    if kind == "idea_recorded":
        key = (data["title"], data["status"])
        if seen.get(data["id"]) == key:
            return
        seen[data["id"]] = key
        line = f"{data['id']} {data['status']}: {short(data['title'])}"
    elif kind == 'package_install_started':
        line = 'pip: ' + short(', '.join(data['requirements'])) + ' started'
    elif kind == 'prior_work_deferred':
        key = (agent_id, 'prior', data['title'])
        if seen.get(key):
            return
        seen[key] = True
        line = 'Prior work: ' + short(data['title']) + ' deferred (' + data['reason'] + ')'
    elif kind == 'package_install_finished':
        line = 'pip: ' + short(', '.join(data['requirements'])) + ' ' + data['status']
    elif kind == "experiment_started":
        line = f"Docker: {data.get('idea_id') or 'unlinked experiment'} started"
    elif kind == "experiment_finished":
        line = f"Docker: {data.get('idea_id')} {data['status']}, exit={data.get('returncode', data.get('exit_code'))}"
    elif kind == "test_recorded":
        line = f"Test: {data['idea_id']} recorded (execution receipt; assertions require review)"
    elif kind == 'http_request_finished':
        response = data.get('response', {})
        line = f"HTTP: {data['action']['payload']['method']} {data['status']}, code={response.get('status')}, bytes={response.get('response_bytes')}"
    elif kind == 'model_search_accounting_overage':
        line = f"Search accounting: {data['unfinished_attempts']} unfinished attempt(s) counted conservatively; within reserved USD"
    elif kind == 'deposit_flow_recorded':
        line = 'Flow: ' + data['status'] + (' | external actions=' + str(data['external_actions_required']) if 'external_actions_required' in data else ' | unresolved protocol')
    elif kind == 'deposit_execution_plan_recorded':
        line = f"Plan: {data['idea_id']} | {data['steps']} steps, {data['external_actions']} external actions | {data['status']}"
    elif kind == 'deposit_step_completed':
        line = f"Deposit: {data['idea_id']} | {data['step']} completed"
    elif kind == 'deposit_execution_checkpoint':
        line = f"Deposit: {data['idea_id']} {data['status']}" + (' | '+data['reason'] if data.get('reason') else '')
    elif kind == 'critique_recorded':
        line = 'Review: ' + data['idea_id'] + ' ' + data['verdict'] + (' (adjusted from REJECT)' if data.get('verdict_adjustment') else '')
    elif kind == 'deposit_candidate_retained':
        line = f"Candidate: {data['candidate_id']} {data['status']} retained from qualification (unverified draft)"
    elif kind == 'role_prerequisite_recovered':
        line = 'Resume: downstream prerequisite now available'
    elif kind == 'report_refresh_scheduled':
        line = 'Report: new evidence; refresh scheduled'
    elif kind == 'carrier_screened':
        key = (agent_id, 'screen', data['id'])
        if seen.get(key):
            return
        seen[key] = True
        line = 'Carrier: ' + short(data['provider'], 70) + ' ' + data['status'] + (' -> switch' if not data['research_allowed'] else '')
    elif kind == 'carrier_switch_required':
        key = (agent_id, 'switch', data['source_id'])
        if seen.get(key):
            return
        seen[key] = True
        line = 'Carrier: ' + short(data['provider'], 70) + ' -> switch (' + data['reason'] + ')'
    elif kind == 'carrier_document_deferred':
        key=(agent_id,'document-scope',data['url'],data['reason'])
        if seen.get(key): return
        seen[key]=True
        line='Docs: '+short(data['url'],95)+' deferred ('+data['reason']+')'
    elif kind == 'document_redirect_hint':
        line = 'Docs redirect: ' + short(data.get('redirect_url') or data['reason'], 130)
    elif kind == 'http_document_read':
        line = 'Docs: ' + short(data['url'], 130) + f" | chars {data['offset']}..{data['end']}" + (' (cached)' if data.get('cached') else '')
    elif kind == 'http_request_failed':
        line = f"HTTP: {data['action']['payload']['method']} FAILED before send; " + short(data.get('reason', ''), 200)
    elif kind == 'http_request_uncertain':
        line = f"HTTP: {data['id']} UNKNOWN; inspect remote outcome"
    elif kind == 'http_public_smoke_verified':
        line = 'HTTP public smoke: PASS, docs/terms read + upload + download + matching SHA256'
    elif kind == 'http_smoke_verified':
        line = 'HTTP smoke: PASS, docs read + upload + download + matching SHA256'
    elif kind == 'http_copy_verified':
        line = f"HTTP: {data['action_id']} exact file read-back verified"
    elif kind == 'candidate_comparison':
        line = 'Dedupe: ' + data['verdict'] + (' -> ' + data['existing_id'] if data.get('existing_id') else '')
    elif kind == "spawn_decision" and data.get("status") == "ACCEPTED":
        line = f"Specialist: {data.get('agent_id')} {short(data.get('role', ''))} [{data.get('model_tier')}={short(data.get('model'))}]"
    else:
        return
    print(f"  {agent_id} | {line}", flush=True)
