"""Bounded repairs for data-only research mistakes; never retry external actions."""
import hashlib
from .storage import canonical


def matches(record, agent, idea, phase):
    from .research_tasks import revision
    return (not record.get('resolved') and record.get('idea_id') == idea['id'] and record.get('phase') == phase
            and record.get('revision') == revision(idea)
            and record.get('operator_notes_count') == len(agent.get('operator_notes', [])))


def blocked(agent, idea, phase):
    return next((r for r in agent.get('research_task_blocks', []) if matches(r, agent, idea, phase)), None)


def current(agent, idea, phase):
    record = agent.get('research_repairs', {}).get(phase)
    return record if record and matches(record, agent, idea, phase) else None


def active_blocks(state, agent, phase):
    return [r for r in agent.get('research_task_blocks', [])
            if any(matches(r, agent, idea, phase) for idea in state['ideas'])]


def defer(api, idea_id, phase, code, details, next_action):
    """Three identical unresolved validations stop this task, not other candidates."""
    from .research_tasks import revision
    idea = api.idea(idea_id)
    stopped = blocked(api.agent, idea, phase)
    if stopped:
        return stopped
    identity = {'idea_id': idea_id, 'phase': phase, 'revision': revision(idea),
                'operator_notes_count': len(api.agent.get('operator_notes', []))}
    progress = {k:v for k,v in details.items() if k not in {'own_read_urls','experiment_id'}}
    fingerprint = hashlib.sha256(canonical(dict(identity, code=code, details=progress)).encode()).hexdigest()
    previous = current(api.agent, idea, phase) or {}
    attempts = previous.get('same_attempts', 0) + 1 if previous.get('fingerprint') == fingerprint else 1
    result = dict(identity, status='DEFERRED' if attempts < 3 else 'BLOCKED',
                  reason=code if attempts < 3 else 'RESEARCH_REPAIR_STALLED', code=code,
                  fingerprint=fingerprint, same_attempts=attempts, details=details,
                  next_action=next_action if attempts < 3 else
                      'This assignment is retained without a verdict/test. Take the next host task in the next round; operator notes or a changed candidate revision can reopen it.',
                  meaning='Data-only validation failure, not scientific rejection or evidence of implementation.')
    api.agent.setdefault('research_repairs', {})[phase] = result
    if attempts >= 3:
        api.agent.setdefault('research_task_blocks', []).append(result)
    api.event('research_repair_required' if attempts < 3 else 'research_repair_stalled', result)
    return result


def clear(agent, phase):
    agent.get('research_repairs', {}).pop(phase, None)


def source_key(url):
    # Strip only a document fragment. Path slash/query differences are not aliases.
    return url.split('#', 1)[0] if isinstance(url, str) else ''


def evidence_gap(agent, idea):
    """Own reads and own validated redirect observations, never inferred URL aliases."""
    from .review_tasks import aliases
    reads = {source_key(r.get('url')) for r in agent.get('http_document_reads', {}).values()
             if r.get('end', 0) > r.get('offset', 0)}
    sources = list(dict.fromkeys(e.get('url') for e in idea.get('evidence', [])
                                if isinstance(e, dict) and isinstance(e.get('url'), str) and e['url']))
    missing = []
    for url in sources:
        targets = aliases(agent, url)
        if not any(source_key(t) in reads for t in targets):
            missing.append({'url': targets[-1], 'original_url': url, 'offset': 0, 'limit': 12000})
    return {'source_count': len(sources), 'missing_documents': missing,
            'own_read_urls': sorted(reads), 'empty_evidence': not sources}


def input_hint(export, path):
    suffix = export.lower().rsplit('.', 1)[-1]
    formats = {'json': 'JSON text: inspect fields and use json.loads; cbor2.loads cannot decode JSON. To test CBOR, encode with cbor2.dumps first.',
               'epub': 'EPUB/ZIP binary export; use actual bytes or inspect the archive in Docker.',
               'pdf': 'PDF binary export; use actual bytes or an appropriate PDF parser.',
               'txt': 'Text export; inspect encoding/content before parsing.'}
    return {'export': export, 'path': path,
            'format_hint': formats.get(suffix, 'Inspect actual bytes before choosing a parser.'),
            'meaning': 'Hint from original filename, not validation of its contents. Use path in the script and prototype plan.'}


def materialized_inputs(agent):
    # Re-materializing the same bytes/path is not progress in resolving a mistake.
    inputs = {e['path']: e for e in agent.get('materialized_exports', [])}
    return [dict(e, **input_hint(e['export'], e['path'])) for e in inputs.values()]
