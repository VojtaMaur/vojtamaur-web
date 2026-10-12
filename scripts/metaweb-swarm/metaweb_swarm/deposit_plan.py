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

def validate(steps, config, export):
    steps=copy.deepcopy(steps)
    if not isinstance(steps,list) or not 2<=len(steps)<=20 or len(canonical(steps))>100000:
        raise ValueError('Executable deposit needs 2..20 bounded steps, including final public GET')
    seen=set(); file_count=0; actions=0
    for s in steps:
        if not isinstance(s,dict) or set(s)!=KEYS:
            raise ValueError('Invalid executable step fields: '+', '.join(sorted(KEYS)))
        if not isinstance(s['id'],str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,39}',s['id']) or s['id'] in seen:
            raise ValueError('Step IDs must be simple unique names')
        if s['method'] not in METHODS or not isinstance(s['purpose'],str) or not 5<=len(s['purpose'])<=1500:
            raise ValueError('Invalid step method/purpose')
        if type(s['sends_export']) is not bool or not isinstance(s['credential_id'],str):
            raise ValueError('Invalid step export/credential')
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
            if not grant or any(urlsplit(o).hostname not in grant['hosts'] for o in origins):
                raise ValueError('Step credential must have an exact grant for every allowed origin')
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
        except (ValueError,TypeError): raise ValueError('headers_json/body_json must be JSON text')
        if not isinstance(headers,dict): raise ValueError('Headers must resolve to an object')
        refs=references(s['url'])+references(headers)+references(body)
        if not references(headers): _headers(headers)
        if not full:
            from urllib.parse import parse_qsl
            if any(_SECRET_FIELD.search(k) for k,v in parse_qsl(urlsplit(s['url']).query)):
                raise ValueError('Literal plan URLs must not contain credentials/signatures; use private response bindings')
        if any(r not in seen for r in refs): raise ValueError('Bindings may only reference earlier steps')
        if s['method'] in READ_METHODS and (s['sends_export'] or body is not None or s['max_body_bytes']):
            raise ValueError('Read steps cannot carry bodies')
        if s['sends_export']:
            file_count+=1
            if body is not None or s['max_body_bytes']!=export['bytes']:
                raise ValueError('Payload step sends only exact export, with its exact byte ceiling')
        elif body is not None and not references(body) and not ('$export' in canonical(body)):
            encoded=json.dumps(body,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
            if len(encoded)>s['max_body_bytes']: raise ValueError('Literal body exceeds its step ceiling')
        actions+=int(s['method'] not in READ_METHODS or bool(s['credential_id']))
        seen.add(s['id'])
    if file_count!=1 or steps[-1]['method']!='GET' or steps[-1]['credential_id']:
        raise ValueError('Send export exactly once and finish with an anonymous GET')
    if steps[0]['method'] in READ_METHODS:
        raise ValueError('Sequence must begin with the qualified write endpoint')
    return {'steps':steps,'actions':actions,'sha256':hashlib.sha256(canonical(steps).encode()).hexdigest()}

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
