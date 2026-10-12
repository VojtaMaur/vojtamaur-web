"""Read-only, hash-checked public HTTP evidence shared within one run."""
import hashlib
import re
from .workspace import _read_bytes, _relative, _confined, _atomic_write
from .documents import readable


def public_get(record):
    payload = record.get('action', {}).get('payload', {})
    response = record.get('response', {})
    return (record.get('status') == 'COMPLETED' and payload.get('method') == 'GET'
            and not payload.get('credential_id') and not record.get('privileged')
            and isinstance(response.get('status'), int) and 200 <= response['status'] < 300
            and not response.get('truncated'))


def capture(api, record, body):
    if not public_get(record):
        return
    if not re.fullmatch(r'HTTP-[0-9a-f]{16}', record['id']):
        raise ValueError('Invalid recorded HTTP identity')
    expected = record['response'].get('stored_sha256')
    if hashlib.sha256(body).hexdigest() != expected:
        raise ValueError('HTTP body differs from response receipt')
    path = 'audit/http/' + record['id'] + '.bin'
    target = _confined(api.engine.store.run_dir, path)
    if target.exists():
        if hashlib.sha256(_read_bytes(api.engine.store.run_dir, _relative(path))).hexdigest() != expected:
            raise ValueError('Shared HTTP evidence changed; refusing to overwrite')
    else:
        _atomic_write(target, body)
    record['audit_artifact'] = {'path': path, 'sha256': expected, 'bytes': len(body)}


def read(api, request_id, offset=0, limit=8000):
    if not isinstance(request_id, str) or not re.fullmatch(r'HTTP-[0-9a-f]{16}', request_id):
        raise ValueError('Use a recorded HTTP request ID, never a file path')
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 16000:
        raise ValueError('offset must be nonnegative; limit must be 1..16000')
    state = api.engine.state
    record = next((r for r in state.get('http_requests', []) if r['id'] == request_id), None)
    if not record:
        return {'status': 'BLOCKED', 'reason': 'AUDIT_REQUEST_NOT_FOUND'}
    if not public_get(record):
        return {'status': 'BLOCKED', 'reason': 'AUDIT_PUBLIC_GET_REQUIRED', 'request_id': request_id}
    owner = next((a for a in state['agents'] if a['id'] == record['agent_id']), None)
    if not owner or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', owner['id']):
        return {'status': 'BLOCKED', 'reason': 'AUDIT_OWNER_NOT_FOUND'}
    response = record['response']; artifact = record.get('audit_artifact')
    # Old checkpoints retain their original own-workspace receipts. Never create
    # another workspace or fetch again merely to inspect an older response.
    if artifact and artifact.get('path') != 'audit/http/' + request_id + '.bin':
        return {'status': 'BLOCKED', 'reason': 'AUDIT_ARTIFACT_PATH_MISMATCH'}
    path = artifact['path'] if artifact else 'agents/' + owner['id'] + '/workspace/' + _relative(response['path']).as_posix()
    try:
        body = _read_bytes(api.engine.store.run_dir, _relative(path), 2_000_000)
        expected = response['stored_sha256']
        if hashlib.sha256(body).hexdigest() != expected or (artifact and artifact['sha256'] != expected):
            return {'status': 'BLOCKED', 'reason': 'AUDIT_ARTIFACT_CHANGED', 'request_id': request_id}
        source = body.decode('utf-8')
        kind = next((v for k, v in response.get('headers', {}).items() if k.lower() == 'content-type'), '')
        text, links, representation = readable(source, kind, record['action']['payload']['url'])
    except (ValueError, OSError, UnicodeError) as error:
        return {'status': 'BLOCKED', 'reason': 'AUDIT_ARTIFACT_UNAVAILABLE', 'request_id': request_id,
                'detail': str(error)[:400]}
    excerpt = text[offset:offset+limit]; end = offset+len(excerpt)
    result = {'status': 'COMPLETED', 'request_id': request_id, 'owner_agent_id': owner['id'],
              'url': record['action']['payload']['url'], 'sha256': expected,
              'artifact_path': path, 'legacy_workspace_source': not bool(artifact), 'representation': representation,
              'offset': offset, 'end': end, 'total_chars': len(text), 'next_offset': end if end < len(text) else None,
              'text': excerpt, 'links': links,
              'meaning': 'Shared recorded evidence only; not this reader\'s independent HTTP/document observation or a semantic certification.'}
    api.event('audit_artifact_read', {k: result[k] for k in ('request_id','owner_agent_id','url','sha256','offset','end','legacy_workspace_source')})
    return result
