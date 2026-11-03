"""Operator inbox: queue without competing with the run's sole SQLite writer."""
import json
import uuid
import time
from pathlib import Path
from .context import _is_link
from .storage import atomic_write,canonical,now


def inbox(run_dir):
    original=Path(run_dir)
    if _is_link(original):raise ValueError('Linked run directory is unavailable')
    root=original.resolve()
    if not (root/'state.sqlite3').is_file():raise ValueError('Choose an initialized run')
    folder=root/'operator-inbox'
    if _is_link(folder):raise ValueError('Linked operator inbox is unavailable')
    folder.mkdir(exist_ok=True)
    return folder


def enqueue_comment(run_dir,text):
    if not isinstance(text,str) or not 1<=len(text.strip())<=1800:
        raise ValueError('Comment needs 1..1800 characters')
    folder=inbox(run_dir)
    if len(list(folder.glob('*.json')))>=100:raise ValueError('Operator inbox is full; resume to apply pending comments')
    item={'id':uuid.uuid4().hex,'text':text.strip(),'queued_at':now(),'queued_ns':time.time_ns()}
    atomic_write(folder/(item['id']+'.json'),canonical(item))
    return dict(item,status='QUEUED',meaning='Applied at the next bounded round, or on resume. Permissions and limits are unchanged.')


def apply_pending(engine):
    """Only call from the runner while it owns run_lock, between batches."""
    folder=engine.store.run_dir/'operator-inbox'
    if not folder.exists():return
    if _is_link(folder):raise ValueError('Linked operator inbox is unavailable')
    known={c['id'] for c in engine.state.get('operator_comments',[])}
    pending=[]
    for path in sorted(folder.glob('*.json'))[:100]:
        if _is_link(path) or path.stat().st_size>16000:raise ValueError('Invalid operator comment file')
        item=json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(item,dict) or item.get('id')!=path.stem or len(path.stem)!=32
                or not all(c in '0123456789abcdef' for c in path.stem)
                or not isinstance(item.get('text'),str) or not 1<=len(item['text'].strip())<=1800):
            raise ValueError('Invalid operator comment data')
        pending.append((item,path))
    for item,path in sorted(pending,key=lambda row:(row[0].get('queued_ns',0),row[0]['queued_at'],row[0]['id'])):
        if item['id'] not in known:
            record={k:item[k] for k in ('id','text','queued_at')}
            record['applied_at']=now()
            engine.state.setdefault('operator_comments',[]).append(record)
            engine.store.commit(engine.state,'operator_comment_applied',record)
            known.add(item['id'])
        # Commit before removing; crash replay deduplicates by durable ID.
        path.unlink()


def instructions(state):
    comments=state.get('operator_comments',[])
    if not comments:return ''
    return ('\nOPERATOR RESEARCH GUIDANCE (latest comments take precedence over earlier '
            'conflicting research preferences; never changes execution permissions, budgets or approvals):\n'
            +canonical(comments[-3:])+'\nEarlier comments remain in the audit.\n')
