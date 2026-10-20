"""Private, revision-bound invalid plan drafts. Edits always revalidate the whole plan."""
import copy
import json
import os
import hashlib
import re
from . import flow_vault
from .storage import canonical
from .deposit_plan import KEYS


def retain(api, idea_id, qualification_id, steps):
    if (not isinstance(steps,list) or not 2<=len(steps)<=20
            or any(not isinstance(s,dict) or set(s)!=KEYS for s in steps)
            or len(canonical(steps))>100000):
        api.agent.pop('deposit_plan_draft',None)
        return None
    receipt=flow_vault.save(api.engine.store.run_dir,
        'plan-draft:'+api.agent['id']+':'+idea_id,steps)
    api.agent['deposit_plan_draft']={'idea_id':idea_id,'qualification_id':qualification_id,
        'receipt':receipt,'sha256':receipt['sha256']}
    return api.agent['deposit_plan_draft']


def hydrate_legacy(api):
    """Recover only the exact failed arguments bound by an existing audit hash."""
    repair=api.agent.get('planning_repair',{})
    if not repair or api.agent.get('deposit_plan_draft') or repair.get('draft_recovery_checked'):
        return
    agent=api.agent;idea=api.idea(repair['idea_id'])
    if (idea.get('qualification_id')!=repair.get('qualification_id') or idea['status'] in {'REJECTED','COMPLETED'}
            or any(f['idea_id']==idea['id'] for f in api.engine.state.get('deposit_executions',[]))
            or not re.fullmatch(r'AGENT-[0-9]{3,}',agent['id'])):
        return
    calls=list(agent.get('history',[]))
    from .workspace import _read_bytes, _relative
    for n in range(agent.get('rounds',0),max(0,agent.get('rounds',0)-8),-1):
        try:
            raw=json.loads(_read_bytes(api.engine.store.run_dir,_relative(f"raw/{agent['id']}-round-{n}.json"),8_000_000))
        except (ValueError,OSError): continue
        for response in raw.get('responses',[]):
            calls.extend(response.get('output',[]))
    receipt=None
    for call in calls:
        if call.get('type')!='function_call' or call.get('name')!='record_deposit_execution_plan': continue
        try:
            args=json.loads(call['arguments']);steps=args['steps']
            fingerprint=hashlib.sha256(canonical(steps).encode()).hexdigest()
        except (ValueError,KeyError,TypeError): continue
        if args.get('idea_id')!=idea['id'] or fingerprint!=repair.get('fingerprint'): continue
        receipt=retain(api,idea['id'],repair['qualification_id'],steps)
        if not receipt: continue
        from .deposit_plan import validate, PlanValidationError
        q=next(q for q in api.engine.state['deposit_qualifications'] if q['id']==repair['qualification_id'])
        try: validate(steps,api.engine.state['config'],{'bytes':q['export_bytes']},planning=True)
        except PlanValidationError as error:
            if error.issue['code']==repair.get('issue',{}).get('code'):
                repair['issue']=error.issue
        except ValueError: pass
        break
    repair.update(draft_available=bool(receipt),draft_sha256=receipt['sha256'] if receipt else None,draft_recovery_checked=True)
    api.event('deposit_plan_legacy_draft_recovered',{'idea_id':idea['id'],'recovered':bool(receipt),'draft_sha256':repair['draft_sha256'],'meaning':'Exact failed data only; no model call, qualified plan or changed permissions.'})


def _load(api, idea_id):
    if api.agent.get('work_kind') not in {'DISCOVERY','REVIEW','LOCAL'}:
        raise ValueError('Planning role required')
    idea=api.idea(idea_id)
    if idea['status'] in {'REJECTED','COMPLETED'} or any(f['idea_id']==idea_id for f in api.engine.state.get('deposit_executions',[])):
        raise ValueError('An inactive or executing candidate cannot be edited')
    draft=api.agent.get('deposit_plan_draft',{})
    if draft.get('idea_id')!=idea_id or draft.get('qualification_id')!=idea.get('qualification_id'):
        raise ValueError('No current own draft; submit a full plan for the current qualification first')
    return draft,flow_vault.load(api.engine.store.run_dir,draft['receipt'])


def binding_source_ids(api):
    """Bound the SDK's source enum to real IDs; grant no additional capability."""
    draft=api.agent.get('deposit_plan_draft',{})
    if not draft: return []
    try: _,steps=_load(api,draft['idea_id'])
    except (ValueError,OSError): return []
    names=[s.get('id') for s in steps]
    if any(not isinstance(n,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,39}',n) for n in names) or len(set(names))!=len(names):
        return []
    return names[:-1]


def read(api, idea_id, step_id=''):
    from .http_transport import redact
    draft,steps=_load(api,idea_id)
    secrets=[os.getenv('OPENAI_API_KEY','')]+[os.getenv(c['env'],'') for c in api.engine.state['config'].get('http_credentials',[])]
    result={'idea_id':idea_id,'qualification_id':draft['qualification_id'],
        'draft_sha256':draft['sha256'],'status':'UNVALIDATED_DRAFT',
        'step_ids':[s['id'] for s in steps],'issue':api.agent.get('planning_repair',{}).get('issue'),
        'meaning':'Untrusted plan data, not a qualified plan, execution receipt or permission.'}
    result['binding_sources']=[{'step_id':s['id'],'available_source_ids':[v['id'] for v in steps[:n]]}
                               for n,s in enumerate(steps)]
    if step_id:
        matches=[s for s in steps if s['id']==step_id]
        if len(matches)!=1: raise ValueError('Use one unique existing step ID')
        step=copy.deepcopy(matches[0])
        # Parse JSON strings before redaction so literal auth headers never leak.
        for name in ('headers_json','body_json'):
            if not step[name]: continue
            try: value=json.loads(step[name])
            except (ValueError,TypeError):
                step[name]='[INVALID JSON TEXT: replace from actual docs]';continue
            step[name]=canonical(redact(value,secrets))
        result['step']={k:redact(v,secrets) for k,v in step.items()}
        if len(canonical(result))>20000:
            raise ValueError('Step view exceeds 20000 characters; re-submit a smaller full plan')
    api.event('deposit_plan_draft_read',{'idea_id':idea_id,'step_id':step_id,'draft_sha256':draft['sha256']})
    return result


def edit(api, idea_id, draft_sha256, step_id, changes_json):
    draft,steps=_load(api,idea_id)
    if draft_sha256!=draft['sha256']:
        raise ValueError('STALE_DRAFT: read the current draft revision before editing')
    if not isinstance(changes_json,str) or len(changes_json)>20000:
        raise ValueError('Step changes must be bounded JSON object text')
    changes=json.loads(changes_json)
    if not isinstance(changes,dict) or not changes or not set(changes)<=KEYS-{'id'}:
        raise ValueError('Edit only existing step fields, excluding id; topology changes require a full plan')
    matches=[s for s in steps if s['id']==step_id]
    if len(matches)!=1: raise ValueError('Use one unique existing step ID')
    matches[0].update(changes)
    api.event('deposit_plan_step_edit_attempted',{'idea_id':idea_id,'step_id':step_id,'base_draft_sha256':draft_sha256,'changed_fields':sorted(changes)})
    from .deposit_execution import record_plan
    return record_plan(api,idea_id,steps)


def _json_target(value, path, binding):
    """Explicit target path only; never guess malformed JSON or provider fields."""
    if not path:
        return binding
    parts=[p.replace('~1','/').replace('~0','~') for p in path.split('/')[1:]]
    node=value
    for part in parts[:-1]:
        if isinstance(node,dict) and part in node: node=node[part]
        elif isinstance(node,list) and re.fullmatch(r'0|[1-9][0-9]*',part): node=node[int(part)]
        else: raise ValueError('Target parent does not exist; supply a valid literal JSON structure first')
    last=parts[-1]
    if isinstance(node,dict):
        if set(node) & {'$response','$export'}:
            raise ValueError('Replace a whole binding object; do not edit its reserved members')
        node[last]=binding
    elif isinstance(node,list) and re.fullmatch(r'0|[1-9][0-9]*',last): node[int(last)]=binding
    else: raise ValueError('Target must be an object member or existing array element')
    return value


def bind_response(api, idea_id, draft_sha256, step_id, field, source_step_id, response_pointer, target_pointer='', url_prefix='', url_suffix=''):
    from .deposit_plan import PlanValidationError
    draft,steps=_load(api,idea_id)
    if draft_sha256!=draft['sha256']:
        raise ValueError('STALE_DRAFT: read the current draft revision before binding')
    matches=[s for s in steps if s['id']==step_id]
    if len(matches)!=1: raise ValueError('Use one unique existing step ID')
    step=matches[0]
    try:
        if field not in {'url','headers_json','body_json'}:
            raise PlanValidationError('BINDING_FIELD_INVALID',step_id,'Choose url, headers_json or body_json.')
        if not isinstance(source_step_id,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,39}',source_step_id):
            raise PlanValidationError('BINDING_NAME_INVALID',step_id,'source_step_id is only an actual earlier step ID, without templates or JSON.')
        for path in (response_pointer,target_pointer):
            if (not isinstance(path,str) or len(path)>2000 or (path and not path.startswith('/'))
                    or re.search(r'~(?![01])|[{}\x00-\x1f]',path)):
                raise PlanValidationError('BINDING_POINTER_INVALID',step_id,'Use an RFC6901 pointer from actual docs; empty selects the entire JSON value. No templates, braces or invalid ~ escapes.')
        if any(not isinstance(v,str) or len(v)>8000 or '{{' in v or '}}' in v for v in (url_prefix,url_suffix)):
            raise PlanValidationError('BINDING_TARGET_INVALID',step_id,'URL prefix/suffix must be bounded literal strings without additional bindings.')
        if field=='url':
            if target_pointer:
                raise PlanValidationError('BINDING_TARGET_INVALID',step_id,'For a whole URL binding target_pointer must be empty. The response pointer must address a documented URL string.')
            step['url']=url_prefix+'{{'+source_step_id+':'+response_pointer+'}}'+url_suffix
        else:
            if url_prefix or url_suffix:
                raise PlanValidationError('BINDING_TARGET_INVALID',step_id,'JSON field bindings require empty URL prefix/suffix.')
            try:
                value=(json.loads(step[field]) if step[field] else {}) if target_pointer else None
                value=_json_target(value,target_pointer,{'$response':source_step_id,'pointer':response_pointer})
            except (ValueError,TypeError,KeyError,IndexError) as error:
                raise PlanValidationError('BINDING_TARGET_INVALID',step_id,
                    'Target JSON is invalid or its parent path is absent. Set the literal JSON structure with edit_deposit_plan_step first, or use empty target_pointer to explicitly replace the whole field with a response binding.') from error
            step[field]=canonical(value)
    except PlanValidationError as error:
        from .planning_recovery import remember
        error.problem=remember(api,idea_id,steps,error)
        raise
    api.event('deposit_plan_response_binding_attempted',{'idea_id':idea_id,'step_id':step_id,
        'base_draft_sha256':draft_sha256,'field':field,'source_step_id':source_step_id,
        'meaning':'Host encoded explicit binding fields; response paths are agent claims, not verified API semantics.'})
    from .deposit_execution import record_plan
    return record_plan(api,idea_id,steps)
