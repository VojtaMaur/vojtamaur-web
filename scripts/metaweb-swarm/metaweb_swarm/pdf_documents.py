"""Hash-checked derived PDF text, separate from immutable HTTP source bytes."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from .workspace import _read_bytes, _relative, _confined, _atomic_write

MAX_PDF_BYTES = 8_000_000
TIMEOUT_SECONDS = 20


class PdfDocumentError(ValueError):
    pass


def extract(data):
    if len(data) > MAX_PDF_BYTES:
        raise PdfDocumentError('PDF_BYTE_LIMIT')
    # Credentials, PYTHONPATH, proxy variables and user site packages are absent.
    environment = {k: os.environ[k] for k in ('SYSTEMROOT', 'WINDIR') if k in os.environ}
    try:
        result = subprocess.run([sys.executable, '-I', str(Path(__file__).with_name('pdf_worker.py'))],
                    input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    env=environment, shell=False, timeout=TIMEOUT_SECONDS,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    except subprocess.TimeoutExpired as error:
        raise PdfDocumentError('PDF_EXTRACTION_TIMEOUT') from error
    if result.returncode or len(result.stdout) > 8_000_000:
        raise PdfDocumentError('PDF_WORKER_FAILED_OR_OUTPUT_LIMIT')
    try:
        parsed = json.loads(result.stdout)
    except (ValueError, UnicodeError) as error:
        raise PdfDocumentError('PDF_WORKER_INVALID_OUTPUT') from error
    if parsed.get('error'):
        raise PdfDocumentError(parsed['error'])
    return parsed


def load(api, record, data):
    source_hash = hashlib.sha256(data).hexdigest()
    if source_hash != record['response']['stored_sha256']:
        raise PdfDocumentError('PDF_SOURCE_CHANGED')
    if not re.fullmatch(r'HTTP-[0-9a-f]{16}', record['id']):
        raise PdfDocumentError('PDF_REQUEST_ID_INVALID')
    cache_path = 'audit/pdf/' + record['id'] + '.json'
    metadata = record.get('pdf_extraction', {})
    parsed = None
    if metadata.get('source_sha256') == source_hash and metadata.get('path') == cache_path:
        try:
            cached = _read_bytes(api.engine.store.run_dir, _relative(cache_path), 8_000_000)
            if hashlib.sha256(cached).hexdigest() == metadata.get('artifact_sha256'):
                parsed = json.loads(cached)
        except (ValueError, OSError, UnicodeError):
            pass
    if parsed is None:
        parsed = extract(data)
        from .http_transport import redact
        config = api.engine.state['config']
        secrets = [os.environ.get('OPENAI_API_KEY', '')] + [os.environ.get(c['env'], '') for c in config.get('http_credentials', [])]
        parsed['pages'] = redact(parsed['pages'], secrets)
        content = json.dumps(parsed, ensure_ascii=False).encode('utf-8')
        _atomic_write(_confined(api.engine.store.run_dir, cache_path), content)
        metadata = {'path': cache_path, 'source_sha256': source_hash,
                    'artifact_sha256': hashlib.sha256(content).hexdigest(),
                    'parser': parsed['parser'], 'parser_version': parsed['parser_version'],
                    'page_count': len(parsed['pages']), 'representation_redacted': True}
        record['pdf_extraction'] = metadata
        api.event('pdf_document_extracted', {'request_id': record['id'], **metadata})
    parts, spans, position = [], [], 0
    for number, body in enumerate(parsed['pages'], 1):
        header = f'[PDF page {number}]\n'
        part = header + body + '\n'
        spans.append({'page': number, 'start': position + len(header),
                      'end': position + len(header) + len(body), 'has_text': bool(body.strip())})
        parts.append(part)
        position += len(part)
    text = ''.join(parts)
    return text, [], 'extracted PDF text; page order, no OCR, no scripts or links followed', {
        **metadata, 'text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(), 'page_spans': spans}


def source_document(api, record, data):
    if hashlib.sha256(data).hexdigest() != record['response']['stored_sha256']:
        raise ValueError('Document response changed since GET')
    kind = next((v for k, v in record['response'].get('headers', {}).items() if k.lower() == 'content-type'), '')
    if kind.split(';')[0].strip().lower() == 'application/pdf' or data.startswith(b'%PDF-'):
        return load(api, record, data)
    from .documents import readable
    if b'\x00' in data:
        raise ValueError('Unsupported binary document content')
    text, links, representation = readable(data.decode('utf-8'), kind, record['action']['payload']['url'])
    return text, links, representation, {}


def excerpt_metadata(metadata, offset, end):
    if not metadata:
        return {}
    return {'pdf': {k: metadata[k] for k in ('source_sha256', 'artifact_sha256', 'text_sha256',
                       'parser', 'parser_version', 'page_count', 'path')},
            'pages': [p['page'] for p in metadata['page_spans']
                      if p['has_text'] and p['start'] < end and p['end'] > offset]}
