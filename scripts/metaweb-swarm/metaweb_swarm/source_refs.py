"""Resolve reviewer-selected line ranges in immutable, independently read source."""
import hashlib


def page(text, offset, end):
    """Number complete lines only: partial pages cannot authorize unseen text."""
    result=[];start=0
    for number,line in enumerate(text.splitlines(keepends=True),1):
        stop=start+len(line)
        if start>=offset and stop<=end:
            result.append({'line':number,'text':line.rstrip('\r\n')})
        start=stop
    return result


def resolve(api,test,refs):
    from .prototype_review import artifact_bytes
    from .review_tasks import _subtract
    if not isinstance(refs,list) or not 1<=len(refs)<=8:raise ValueError('Select 1..8 source ranges')
    execution=next((e for e in api.engine.state.get('experiments',[]) if e.get('experiment_id')==test['experiment_id']),{})
    paths={test['prototype_plan']['script']['path'],*[a['path'] for a in execution.get('coding_sources',[])]}
    reads=api.agent.get('prototype_artifact_reads',{}).get(test['id'],{})
    result=[];size=0
    for ref in refs:
        if not isinstance(ref,dict) or set(ref)!={'path','start_line','end_line'}:raise ValueError('Use path/start_line/end_line')
        path=ref['path'];lo=ref['start_line'];hi=ref['end_line']
        if path not in paths or type(lo) is not int or type(hi) is not int or lo<1 or hi<lo:raise ValueError('Invalid executed source range')
        artifact=next((a for a in test['artifacts'] if a['path']==path),None)
        if not artifact:raise ValueError('Source is not captured')
        body=artifact_bytes(api,test,artifact)
        if hashlib.sha256(body).hexdigest()!=artifact['sha256']:raise ValueError('Captured source hash changed')
        text=body.decode('utf-8');lines=text.splitlines(keepends=True)
        if hi>len(lines):raise ValueError('Range exceeds captured source')
        start=sum(map(len,lines[:lo-1]));stop=sum(map(len,lines[:hi]))
        if _subtract([[start,stop]],reads.get(path,[])):raise ValueError('Read these source lines independently first')
        quote=''.join(lines[lo-1:hi]).strip().replace('\r\n','\n');size+=len(quote)
        if not quote or size>8000:raise ValueError('Selected source is empty or exceeds 8000 characters')
        result.append(dict(ref,sha256=artifact['sha256'],quote=quote))
    return result


def checked(api,test,refs,field):
    if refs is None or refs==[]:return None,None
    try:return resolve(api,test,refs),None
    except (ValueError,UnicodeError,TypeError) as error:
        return None,{'status':'DEFERRED','reason':'SOURCE_RANGE_INVALID','field':field,'detail':str(error),
                     'next_action':'Select complete numbered lines returned by read_test_artifact; do not reconstruct or paste code.'}
