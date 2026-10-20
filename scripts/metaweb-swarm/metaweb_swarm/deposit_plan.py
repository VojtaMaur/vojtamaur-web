"""Data-only HTTP sequences: JSON pointers and templates, never executable code."""
import copy
import hashlib
import json
import re
from urllib.parse import urlsplit, quote
from .storage import canonical
from .http_transport import _url, _origin, _protected, _deny_git_write, _headers, _SECRET_FIELD, READ_METHODS, METHODS

REF = re.compile(r'\{\{([A-Za-z][A-Za-z0-9_-]{0,39}):(/[^{}]*|)\}\}')
KEYS = {'id','method','purpose','url','allowed_origins','credential_id','headers_json',
        'body_json','sends_export','max_body_bytes','success_codes','max_age_seconds'}


class PlanValidationError(ValueError):
    def __init__(self, code, step_id, correction, **details):
        super().__init__(correction)
        self.issue = {'code':code, 'step_id':step_id, 'next_action':correction, **details}

def references(value):
    found=[]
    if isinstance(value,str):
        found.extend(m.group(1) for m in REF.finditer(value))
    elif isinstance(value,list):
        for v in value: found.extend(references(v))
    elif isinstance(value,dict):
        if '$response' in value:
            if set(value)!={'$response','pointer'} or not isinstance(value['$response'],str) or not isinstance(value['pointer'],str) or (value['pointer'] and not value['pointer'].startswith('/')):
                raise ValueError('Response binding needs $response and an RFC6901 pointer')
            found.append(value['$response'])
        elif '$export' in value:
            if set(value)!={'$export'} or not isinstance(value['$export'],str) or value['$export'] not in {'filename','bytes','sha256'}:
                raise ValueError('Export binding supports filename, bytes, sha256')
        else:
            for v in value.values(): found.extend(references(v))
    return found

def validate(steps, config, export, *, planning=False):
    steps=copy.deepcopy(steps)
    if not isinstance(steps,list) or not 2<=len(steps)<=20 or len(canonical(steps))>100000:
        raise ValueError('Executable deposit needs 2..20 bounded steps, including final public GET')
    seen=set(); prior=[]; file_count=0; actions=0; missing=[]
    for index, s in enumerate(steps):
        if not isinstance(s,dict) or set(s)!=KEYS:
            raise ValueError('Invalid executable step fields: '+', '.join(sorted(KEYS)))
        if not isinstance(s['id'],str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,39}',s['id']) or s['id'] in seen:
            raise ValueError('Step IDs must be simple unique names')
        if s['method'] not in METHODS or not isinstance(s['purpose'],str) or not 5<=len(s['purpose'])<=1500:
            raise ValueError('Invalid step method/purpose')
        if type(s['sends_export']) is not bool or not isinstance(s['credential_id'],str):
            raise ValueError('Invalid step export/credential')
        if s['credential_id'] and not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,79}', s['credential_id']):
            raise PlanValidationError('CREDENTIAL_ID_INVALID',s['id'],'Use a simple credential_id name, never a secret or credential template.')
        if type(s['max_body_bytes']) is not int or not 0<=s['max_body_bytes']<=config['max_http_request_bytes']:
            raise ValueError('Step body ceiling exceeds request limit')
        if type(s['max_age_seconds']) is not int or not 0<=s['max_age_seconds']<=86400:
            raise ValueError('Step expiry must be 0..86400 seconds')
        if not isinstance(s['success_codes'],list) or not s['success_codes'] or any(type(c) is not int or not 200<=c<300 for c in s['success_codes']):
            raise ValueError('Specify successful 2xx HTTP codes; redirects are not followed')
        origins=s['allowed_origins']
        if not isinstance(origins,list) or not 1<=len(origins)<=8:
            raise ValueError('Each step needs exact allowed origins; no wildcard')
        for origin in origins:
            parts=urlsplit(origin)
            normalized,host,_,_=_url(origin,config)
            if _origin(parts)!=origin or parts.path or parts.query or parts.fragment:
                raise ValueError('Origin must be canonical scheme://host[:port], without path')
            _deny_git_write(origin)
            if _protected(host):
                raise ValueError('Protected production/forge hosts cannot be deposit origins')
        if s['credential_id']:
            grant=next((c for c in config.get('http_credentials',[]) if c['id']==s['credential_id']),None)
            if not grant:
                if not planning:
                    raise PlanValidationError('CREDENTIAL_GRANT_REQUIRED',s['id'],'Step credential must have an exact grant for every allowed origin before execution.')
                missing.append({'credential_id':s['credential_id'],'allowed_origins':origins,'step_id':s['id']})
            elif any(urlsplit(o).hostname not in grant['hosts'] for o in origins):
                raise PlanValidationError('CREDENTIAL_ORIGIN_MISMATCH',s['id'],'Existing credential grant does not cover every allowed origin. Do not forward credentials to other hosts.')
        if not isinstance(s['url'],str) or len(s['url'])>16384:
            raise ValueError('Invalid URL template')
        full=REF.fullmatch(s['url'])
        if not full:
            # Interpolation is restricted to path/query, never the authority.
            authority=s['url'].split('://',1)[-1].split('/',1)[0].split('?',1)[0]
            if '{{' in authority: raise ValueError('Dynamic authority requires a whole-URL response binding')
            probe=REF.sub('bound',s['url'])
            normalized,_,_,_=_url(probe,config); _deny_git_write(probe)
            if _origin(urlsplit(normalized)) not in origins:
                raise ValueError('Literal endpoint is outside the allowed origins')
        if '{{' in REF.sub('',s['url']) or '}}' in REF.sub('',s['url']):
            raise ValueError('Malformed URL binding')
        try:
            if not isinstance(s['headers_json'],str) or not isinstance(s['body_json'],str): raise ValueError()
            headers=json.loads(s['headers_json'] or '{}')
            body=json.loads(s['body_json']) if s['body_json'] else None
        except (ValueError,TypeError):
            raise PlanValidationError('JSON_TEXT_INVALID',s['id'],
                'headers_json/body_json must be valid JSON text. A response object is {"$response":"earlier_step_id","pointer":"/documented/path"}; quote all keys. Empty raw body is "".',step_index=index)
        if not isinstance(headers,dict): raise ValueError('Headers must resolve to an object')
        refs=references(s['url'])+references(headers)+references(body)
        if set(headers)!={'$response','pointer'}:
            try: _headers({k:'bound' for k in headers} if references(headers) else headers)
            except ValueError as error:
                raise PlanValidationError('HEADERS_INVALID',s['id'],
                    'Remove agent-supplied Authorization, cookies, Host, Content-Length and framing headers. '
                    'Use credential_id for authentication (a symbolic missing grant is allowed only in planning). '
                    'Use permitted static headers or a documented response binding; never {$credential}.') from error
        if not full:
            from urllib.parse import parse_qsl
            if any(_SECRET_FIELD.search(k) for k,v in parse_qsl(urlsplit(s['url']).query)):
                raise ValueError('Literal plan URLs must not contain credentials/signatures; use private response bindings')
        absent=sorted(set(refs)-seen)
        if absent:
            raise PlanValidationError('BINDING_SOURCE_REQUIRED',s['id'],
                'Bindings may only reference earlier steps. Missing source IDs: '+', '.join(absent)+
                '. Available earlier IDs: '+(', '.join(prior) or '(none)')+
                '. Correct the named source using actual docs; the host does not infer which response or JSON pointer is intended.',
                step_index=index,missing_source_ids=absent,available_source_ids=list(prior))
        if s['method'] in READ_METHODS and (s['sends_export'] or body is not None or s['max_body_bytes']):
            raise ValueError('Read steps cannot carry bodies')
        if s['sends_export']:
            file_count+=1
            if body is not None or s['max_body_bytes']!=export['bytes']:
                raise PlanValidationError('EXACT_EXPORT_BODY_REQUIRED',s['id'],
                    'Payload step sends only exact export, with its exact byte ceiling. Set sends_export=true, '
                    'body_json="" and max_body_bytes=the retained export byte size. The host supplies raw bytes; never {$export} or JSON file wrappers.')
        elif body is not None and not references(body) and not ('$export' in canonical(body)):
            encoded=json.dumps(body,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
            if len(encoded)>s['max_body_bytes']:
                raise PlanValidationError('BODY_CEILING_REQUIRED',s['id'],'Literal body exceeds its step ceiling. Empty body is body_json=""; JSON {} still sends two bytes and needs a positive ceiling.',
                    required_body_bytes=len(encoded),configured_body_bytes=s['max_body_bytes'],step_index=index)
        actions+=int(s['method'] not in READ_METHODS or bool(s['credential_id']))
        seen.add(s['id'])
        prior.append(s['id'])
    if file_count!=1 or steps[-1]['method']!='GET' or steps[-1]['credential_id']:
        raise ValueError('Send export exactly once and finish with an anonymous GET')
    if steps[0]['method'] in READ_METHODS:
        raise ValueError('Sequence must begin with the qualified write endpoint')
    return {'steps':steps,'actions':actions,'missing_credentials':missing,'sha256':hashlib.sha256(canonical(steps).encode()).hexdigest()}

def pointer(value, path):
    for part in path.split('/')[1:] if path else []:
        part=part.replace('~1','/').replace('~0','~')
        if isinstance(value,list):
            if not re.fullmatch(r'0|[1-9][0-9]*',part): raise ValueError('Invalid JSON array pointer')
            value=value[int(part)]
        elif isinstance(value,dict): value=value[part]
        else: raise ValueError('JSON pointer does not address an object')
    return copy.deepcopy(value)

def resolve(value, responses, export):
    if isinstance(value,dict):
        if '$response' in value: return pointer(responses[value['$response']],value['pointer'])
        if '$export' in value: return export[value['$export']]
        return {k:resolve(v,responses,export) for k,v in value.items()}
    if isinstance(value,list): return [resolve(v,responses,export) for v in value]
    return value

def resolve_url(template,responses):
    full=REF.fullmatch(template)
    if full:
        value=pointer(responses[full.group(1)],full.group(2))
        if not isinstance(value,str): raise ValueError('Returned URL is not a string')
        return value
    def substitute(m):
        value=pointer(responses[m.group(1)],m.group(2))
        if type(value) not in {str,int}: raise ValueError('URL path binding must be string/integer')
        return quote(str(value),safe='')
    return REF.sub(substitute,template)
