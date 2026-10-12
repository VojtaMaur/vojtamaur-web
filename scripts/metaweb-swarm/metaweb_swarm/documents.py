"""Read public documentation through the existing audited HTTP transport."""
import hashlib
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, parse_qsl
from .storage import now


class DocumentParser(HTMLParser):
    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url, self.parts, self.links, self.hidden = url, [], [], []
    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'head', 'svg', 'template'}:
            self.hidden.append(tag)
        if self.hidden:
            return
        if tag in {'p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'pre'}:
            self.parts.append('\n')
        if tag == 'a':
            href = dict(attrs).get('href', '')
            target = urljoin(self.url, href)
            if href and urlsplit(target).scheme in {'http', 'https'} and len(target) <= 2000 and target not in self.links:
                if len(self.links) < 80:
                    self.links.append(target)
    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
            return
        if tag in {'p', 'div', 'li', 'tr', 'pre'}:
            self.parts.append('\n')
    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def readable(text, content_type, url):
    kind = content_type.split(';')[0].strip().lower()
    if kind in {'text/html', 'application/xhtml+xml'} or (not kind and text.lstrip().lower().startswith(('<!doctype html', '<html'))):
        parser = DocumentParser(url); parser.feed(text); parser.close()
        lines = [re.sub(r'[ \t\r\f\v]+', ' ', line).strip() for line in ''.join(parser.parts).split('\n')]
        return '\n'.join(line for line in lines if line), parser.links, 'extracted HTML text; scripts/styles/head omitted'
    if kind.startswith('text/') or kind in {'application/json', 'application/xml', 'application/ld+json', 'application/javascript'} or kind.endswith(('+json', '+xml')) or not kind:
        return text, [], 'UTF-8 source text'
    raise ValueError('Unsupported document content type; use response artifact, no PDF/browser conversion available')


async def read_document(api, url, purpose, offset=0, limit=12000):
    if not isinstance(url, str) or not 1 <= len(url) <= 8000:
        raise ValueError('Document URL must be text up to 8000 characters')
    if not isinstance(purpose, str) or not 5 <= len(purpose) <= 2000:
        raise ValueError('Describe why you need this document (5..2000 characters)')
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 16000:
        raise ValueError('offset must be nonnegative; limit must be 1..16000')
    from .carrier_screening import document_gate
    gate = document_gate(api, url)
    if gate:
        from .http_transport import _redact_url, _url
        safe_url, _, _, _ = _url(url,api.engine.state['config'])
        api.event('carrier_document_deferred',dict(gate,url=_redact_url(safe_url)))
        return gate
    if api.engine.state['config'].get('http_access') == 'disabled':
        return {'status': 'BLOCKED', 'reason': 'HTTP_DISABLED'}
    # Reuse only this agent's own complete GET, never another role's review.
    candidates = [r for r in api.engine.state.get('http_requests', [])
                  if r.get('agent_id') == api.agent['id'] and r.get('status') == 'COMPLETED'
                  and r.get('action', {}).get('payload', {}).get('method') == 'GET'
                  and r['action']['payload'].get('url') == url
                  and 200 <= (r.get('response', {}).get('status') or 0) < 300
                  and not r['response'].get('truncated')]
    record, cached = None, False
    for candidate in reversed(candidates):
        try:
            if api.workspace.file_info(candidate['response']['path'])['sha256'] == candidate['response'].get('stored_sha256'):
                record, cached = candidate, True; break
        except (ValueError, OSError):
            pass
    if record is None:
        record = await api.http_request({'url': url, 'method': 'GET'}, purpose=purpose)
    response = record.get('response', {})
    if record.get('status') == 'COMPLETED' and response.get('status') in {301, 302, 303, 307, 308}:
        from .http_transport import _url, HttpPolicyError
        location = next((v for k, v in response.get('headers', {}).items() if k.lower() == 'location'), '')
        hint = {'status':'DEFERRED', 'reason':'DOCUMENT_REDIRECT_REQUIRES_GET', 'request_id':record['id'],
                'http_status':response['status'], 'redirect_url':None,
                'meaning':'No redirect followed and no document-read claim recorded.'}
        try:
            if not isinstance(location, str) or not location or len(location) > 8000:
                raise ValueError('Missing or oversized Location')
            target = urljoin(record['action']['payload']['url'], location)
            parts = urlsplit(target)
            if parts.username or parts.password or any(re.search(r'token|password|secret|api[_-]?key|credential|signature', key, re.I) for key, _ in parse_qsl(parts.query)):
                raise ValueError('Credential-bearing redirect is not a public document hint')
            target, _, _, _ = _url(target.split('#', 1)[0], api.engine.state['config'])
            if target == record['action']['payload']['url']:
                raise ValueError('Redirect loops to the same URL')
            hint['redirect_url'] = target
            hint['next_action'] = 'Call read_document on redirect_url explicitly. No credentials/cookies are forwarded; full HTTP validation runs again.'
        except (ValueError, HttpPolicyError):
            hint.update(status='BLOCKED', reason='DOCUMENT_REDIRECT_TARGET_UNAVAILABLE',
                        next_action='Find a safe canonical public docs URL; do not disable TLS or URL checks.')
        api.event('document_redirect_hint', {k:v for k,v in hint.items() if k != 'next_action'})
        return hint
    if record.get('status') != 'COMPLETED' or not 200 <= (response.get('status') or 0) < 300 or response.get('truncated'):
        return {'status': record.get('status', 'BLOCKED') if record.get('status') != 'COMPLETED' else 'BLOCKED',
                'reason': record.get('reason') or 'DOCUMENT_HTTP_RESPONSE_NOT_SUCCESSFUL_OR_COMPLETE',
                'request_id': record.get('id'), 'http_status': response.get('status'), 'response_path': response.get('path'),
                'next_action': 'Inspect HTTP receipt; redirects are not automatically followed; no document-read claim recorded.'}
    try:
        source = api.workspace.read_file(response['path'])
        if hashlib.sha256(source.encode('utf-8')).hexdigest() != response.get('stored_sha256'):
            raise ValueError('Document response changed since GET')
        content_type = next((v for k, v in response.get('headers', {}).items() if k.lower() == 'content-type'), '')
        text, links, representation = readable(source, content_type, record['action']['payload']['url'])
    except (ValueError, OSError) as error:
        return {'status': 'BLOCKED', 'reason': 'DOCUMENT_TEXT_UNAVAILABLE', 'detail': str(error)[:500],
                'request_id': record['id'], 'response_path': response.get('path')}
    excerpt = text[offset:offset+limit]; end = offset + len(excerpt)
    result = {'status': 'COMPLETED', 'url': record['action']['payload']['url'], 'request_id': record['id'],
              'response_path': response['path'], 'sha256': response['stored_sha256'], 'cached': cached,
              'representation': representation, 'offset': offset, 'end': end, 'total_chars': len(text),
              'next_offset': end if end < len(text) else None, 'text': excerpt, 'links': links,
              'meaning': 'Untrusted document excerpt, not proof of semantic understanding, terms compliance or retention.'}
    receipt = {k: result[k] for k in ('url', 'sha256', 'offset', 'end', 'representation', 'total_chars')}
    receipt.update(read_at=now(), excerpt_sha256=hashlib.sha256(excerpt.encode('utf-8')).hexdigest())
    if excerpt.strip():
        api.agent.setdefault('http_document_reads', {})[record['id']] = receipt
        api.event('http_document_read', dict(receipt, request_id=record['id'], cached=cached, response_path=response['path']))
    return result
