"""Observable implementation reuse, distinct from mechanism identity or correctness."""
import ast,hashlib
from .storage import canonical


def normalized(body,path):
    if path.endswith('.py') and len(body)<=1_000_000:
        try:return ast.dump(ast.parse(body.decode('utf-8')),include_attributes=False)
        except (SyntaxError,UnicodeError,ValueError,RecursionError):pass
    return hashlib.sha256(body).hexdigest()


def signature(entries):
    # Names and comments do not make a new program; implementation constants do.
    return hashlib.sha256(canonical(sorted(normalized(body,path) for path,body in entries)).encode()).hexdigest()


def sources(api,test):
    from .prototype_review import artifact_bytes
    p=test['prototype_plan'];paths={p['script']['path']}
    e=next((e for e in api.engine.state.get('experiments',[]) if e.get('experiment_id')==test['experiment_id']),{})
    paths.update(a['path'] for a in e.get('coding_sources',[]))
    return [(a['path'],artifact_bytes(api,test,a)) for a in test['artifacts'] if a['path'] in paths]


def matches(api,entries,idea_id):
    digest=signature(entries);result=[]
    for t in api.engine.state.get('tests',[]):
        if t['idea_id']==idea_id or not t.get('host_execution_verified') or not t.get('prototype_plan'):continue
        if signature(sources(api,t))==digest:
            result.append({'test_id':t['id'],'idea_id':t['idea_id'],'implementation_signature':digest})
    return result


def submission_issue(api,result,helpers,idea_id):
    from .workspace import _relative,_read_bytes
    paths=[result['script_path'],*[a['path'] for a in helpers]]
    entries=[(p,_read_bytes(api.workspace.root,_relative(p),api.engine.state['config']['max_file_bytes'])) for p in paths]
    reused=matches(api,entries,idea_id)
    if not reused:return None
    reference={'idea_id':idea_id,'matches':reused,'implementation_signature':signature(entries)}
    refs=api.engine.state.setdefault('prototype_component_reuses',[])
    if reference not in refs:refs.append(reference)
    api.event('prototype_component_reused',reference)
    return {'status':'DEFERRED','reason':'EXISTING_IMPLEMENTATION_REUSE','existing_components':reused,
        'next_action':'This implementation is already captured under another IDEA. Reuse that receipt as a shared helper; do not rerun or relabel it as a new mechanism test. Implement THIS candidate primitive and a real failure case, or report the concrete missing capability. Changing comments, paths or prose is not implementation progress.'}
