"""Select captured content rather than accidentally preserving only its descriptor."""
from pathlib import PurePosixPath


def descriptor(path):
    return str(path).casefold().endswith('.manifest.json')


def choices(state, agent, idea=None):
    files = state.get('exports', {}).get('files', [])
    limit = state['config'].get('max_export_file_bytes', 134217728)
    payloads = [e for e in files if not descriptor(e['path']) and e['path'].lower().endswith(('.epub', '.zip', '.pdf', '.txt'))
                and 0 < e['bytes'] <= limit]
    materialized = {m['export'].casefold().removesuffix('.manifest.json')
                    for m in agent.get('materialized_exports', []) if descriptor(m['export'])}
    def rank(entry):
        name = entry['path'].casefold()
        associated = name in materialized or str(PurePosixPath(name).with_suffix('')) in materialized
        return ('metaweb' not in name, not associated, entry['bytes'], name)
    return sorted(payloads, key=rank)


def view(state, agent, idea=None):
    payloads = choices(state, agent, idea)
    return {'recommended_payload': payloads[0] if payloads else None,
            'available_payloads': payloads[:8], 'payload_count': len(payloads),
            'descriptor_count': sum(descriptor(e['path']) for e in state.get('exports', {}).get('files', [])),
            'next_action': 'Use prepare_prototype_input for a verified captured content copy in this workspace. '
                'A .manifest.json describes an export; it is not the EPUB/PDF/TXT/ZIP content. '
                'Metadata-only work is a limited SUBCOMPONENT, not preservation of the website bytes.'}


def prepare(api):
    from .research_tasks import gate
    idea_id = api.agent.get('research_assignment', {}).get('target_id')
    if api.agent.get('work_kind') != 'LOCAL' or not idea_id:
        raise ValueError('Prepare input only for an assigned LOCAL idea')
    issue = gate(api, idea_id)
    if issue:
        return issue
    candidates = choices(api.engine.state, api.agent, api.idea(idea_id))
    if not candidates:
        return {'status': 'BLOCKED', 'reason': 'NO_CAPTURED_PAYLOAD_EXPORT', **view(api.engine.state, api.agent)}
    chosen = candidates[0]
    # The existing importer validates source confinement, byte limits and hashes.
    destination = 'inputs/' + chosen['sha256'][:12] + '-' + PurePosixPath(chosen['path']).name
    old = next((m for m in api.agent.get('materialized_exports', []) if m['path'] == destination
                and m['sha256'] == chosen['sha256'] and m['bytes'] == chosen['bytes']), None)
    if old:
        api.export_source(chosen['path'])
        info = api.workspace.file_info(destination)
        if info['sha256'] == chosen['sha256'] and info['bytes'] == chosen['bytes']:
            return dict(old, input_kind='PAYLOAD', replayed=True)
    result = api.materialize_export(chosen['path'], destination)
    return dict(result, input_kind='PAYLOAD',
                next_action='Read binary formats with read_bytes in Docker. Use this returned path as input_path '
                    'and in the script; emit independently recovered content bytes for full recovery claims.')


def action(api):
    from .research_tasks import enabled
    if not enabled(api.engine.state) or api.agent.get('work_kind') != 'LOCAL':
        return None
    task = api.agent.get('research_assignment', {})
    if task.get('kind') != 'LOCAL_IDEA' or api.agent.get('prototype_plans', {}).get(task.get('target_id')):
        return None
    has_payload = any(not descriptor(m['export']) for m in api.agent.get('materialized_exports', []))
    if not has_payload and choices(api.engine.state, api.agent):
        return {'tool': 'prepare_prototype_input',
                'next_action': 'Copy the recommended actual captured web export before planning. '
                    'This reads only the isolated run input, not production or credentials.'}
    return None


def plan_issue(api, export, scope):
    from .research_tasks import enabled
    if enabled(api.engine.state) and scope == 'FULL_MECHANISM' and descriptor(export['export']):
        return {'status': 'DEFERRED', 'reason': 'PAYLOAD_EXPORT_REQUIRED', 'inputs': view(api.engine.state, api.agent),
                'next_action': 'A manifest-only input cannot certify preservation of the web export. '
                    'Use prepare_prototype_input and implement the operation on actual content bytes; '
                    'or scope a useful metadata operation as SUBCOMPONENT with explicit limitations.'}
    return None
