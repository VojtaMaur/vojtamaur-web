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
    print(f"Prior work: {config.get('prior_work_policy', 'continue')}", flush=True)
    if config.get('semantic_dedupe'):
        model = config.get('model_tiers', {}).get('cheap') or config.get('model')
        print(f"Dedupe: current run only | ambiguous proposals: {short(model)}", flush=True)
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
    elif kind == 'candidate_comparison':
        line = 'Dedupe: ' + data['verdict'] + (' -> ' + data['existing_id'] if data.get('existing_id') else '')
    elif kind == "spawn_decision" and data.get("status") == "ACCEPTED":
        line = f"Specialist: {data.get('agent_id')} {short(data.get('role', ''))} [{data.get('model_tier')}={short(data.get('model'))}]"
    else:
        return
    print(f"  {agent_id} | {line}", flush=True)
