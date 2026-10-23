"""Operator-defined worker task and independent checks, separate from novelty research."""
import base64
import asyncio
import hashlib
import json
import uuid
from pathlib import PurePosixPath
from .storage import now

CONTRACT = {
    'task':'Implement a CBOR bootstrap seed transported through a transcribable text envelope. This is a known format task, not a novel preservation discovery.',
    'artifacts':['prototype/seed.cbor','prototype/mirror.txt','prototype/decoded.json'],
    'codec':'prototype/codec.py',
    'decode_cli':'python prototype/codec.py decode SOURCE_EXPORT SEED_OR_MIRROR OUTPUT_JSON',
    'fields':{'export':'original export basename, exactly as expected_fields.export; never a workspace-added prefix','sha256':'SHA256 of the actual supplied export bytes',
              'bytes':'actual byte count','decoder':'metaweb-cbor-seed-v1'},
    'binary':'Real self-described CBOR, tag 55799 (d9d9f7), followed by the seed map. Use an actual encoder/decoder such as cbor2.',
    'text':'METAWEB-CBOR-1 followed by a newline and Base64 of the entire tagged CBOR specimen. ASCII whitespace in the encoded body may be ignored.',
    'decoder':'Read the saved binary or text specimen, decode its fields and verify sha256/bytes/export against SOURCE_EXPORT. Emit OUTPUT_JSON only for a verified seed. Invalid input or a syntactically valid seed with a wrong digest must return a nonzero exit code.',
    'test':'Write and execute a real test script that regenerates artifacts, decodes BOTH saved representations and asserts exact metadata equality. Include a syntactically valid CBOR seed whose digest field was changed and assert it is rejected. Also reject an invalid text envelope. Return that test script and its argv as your final result.',
    'scope':'Useful local bootstrap/transcription component. No full export encoding, QR image, EPUB copy, internet upload or storage-durability claim is requested.'}


def expected_fields(source):
    return {'export':PurePosixPath(source['export']).name,'sha256':source['sha256'],
            'bytes':source['bytes'],'decoder':'metaweb-cbor-seed-v1'}


def contract(source):
    return dict(CONTRACT,expected_fields=expected_fields(source),
        workflow='This is a known implementation task. No baseline/prior-run research or parsing EPUB contents is required. Hash the actual input bytes; regenerate the three persistent artifacts at the exact stated paths. Use expected_fields for exact field values. Report decoder exceptions instead of repeatedly guessing from a bare exit code.',
        library_hint='cbor2 may consume the self-described tag and return a Mapping (including frozendict), not CBORTag or dict. Inspect the installed behavior; the tag is independently observable in the encoded bytes.')


def seed(state):
    from .policy import normalize_idea
    from .research_tasks import revision
    if state['ideas']: raise ValueError('Acceptance starts with an empty candidate registry')
    idea=normalize_idea({'title':'CBOR bootstrap transcription — coding worker acceptance',
        'mechanism':'A self-described CBOR seed carries the retained export name, hash, length and decoder version inside a Base64 text envelope; decoding verifies the fields against the original export.',
        'summary':'Operator-defined coding task for a known local component, with independent validation. No novelty or external preservation claim.',
        'provider':'Local format task','status':'INVESTIGATING','payment':'FREE','requires_ongoing_payments':False,
        'novelty':'KNOWN WORKER ACCEPTANCE TASK','mechanism_kind':'RECOVERY_FORMAT','novelty_class':'KNOWN_CARRIER',
        'evidence':[],'artifacts':[],'failure_domains':['local format/transcription'],
        'validation_plan':CONTRACT['test'],'next_action':'Implement and independently test the supplied coding contract.'})
    idea.update(id='IDEA-0001',agent_id='OPERATOR',created_at=now(),updated_at=now(),
                prototype_tested=False,submissions=[],revisions=[])
    idea['prototype_focus']={'scope':'SUBCOMPONENT','goal':CONTRACT['test'],
        'research_revision':revision(idea),'agent_id':'OPERATOR',
        'meaning':'Fixed operator acceptance task; no discovery review or claim of novelty.'}
    state['ideas'].append(idea)
    state['coding_acceptance_contract']=CONTRACT
    for agent in state['agents']:
        if agent.get('work_kind')=='REVIEW':
            agent.update(status='COMPLETED',summary='Known worker task; independent code/output review opens after execution.',
                         reason_for_stopping='Waiting for a captured worker test; no discovery critique needed')


CHECK = r'''
import base64,json,pathlib,subprocess,sys,tempfile
codec,source,seed,mirror,expected_json,bad_base64=sys.argv[1:]
expected=json.loads(expected_json)
with tempfile.TemporaryDirectory(prefix='metaweb-oracle-') as tmp:
    tmp=pathlib.Path(tmp)
    def decode(specimen,name,success):
        out=tmp/name
        run=subprocess.run([sys.executable,codec,'decode',source,str(specimen),str(out)],capture_output=True,text=True,timeout=30)
        if success:
            assert run.returncode==0, 'Decoder failed: '+run.stderr[-1000:]
            assert json.loads(out.read_text(encoding='utf-8'))==expected, 'Decoder output metadata mismatch'
        else:
            assert run.returncode!=0, 'Decoder accepted invalid or semantically corrupted input'
    decode(seed,'binary.json',True)
    decode(mirror,'text.json',True)
    wrong=tmp/'wrong-digest.cbor';wrong.write_bytes(base64.b64decode(bad_base64))
    decode(wrong,'must-not-accept.json',False)
    invalid=tmp/'invalid-envelope.txt';invalid.write_text('METAWEB-CBOR-1\n!invalid base64!\n',encoding='utf-8')
    decode(invalid,'must-not-accept-text.json',False)
print(json.dumps({'passed':True,'checks':['saved CBOR metadata','saved text transcription','binary decoder','text decoder','valid CBOR with wrong digest rejected','invalid envelope rejected']}))
'''


async def validate(api,current,experiment):
    # Decode with a trusted host dependency, not a package editable by the worker.
    import cbor2
    from .workspace import DockerExecutor,_read_bytes,_relative
    source=current['input'];expected=expected_fields(source)
    record={'id':'CODING-VALIDATION-'+uuid.uuid4().hex[:16],'idea_id':current['idea_id'],
        'agent_id':api.agent['id'],'experiment_id':experiment['experiment_id'],'passed':False,'time':now()}
    try:
        def body(path):return _read_bytes(api.workspace.root,_relative(path),2_000_000)
        binary=body('prototype/seed.cbor')
        if not binary.startswith(bytes.fromhex('d9d9f7')):raise ValueError('Missing self-described CBOR tag 55799')
        decoded=cbor2.loads(binary)
        if decoded!=expected:
            record.update(expected=expected,actual={k:repr(decoded.get(k))[:500] for k in expected} if hasattr(decoded,'get') else repr(decoded)[:500],
                mismatched_fields=[k for k in expected if not hasattr(decoded,'get') or decoded.get(k)!=expected[k]])
            raise ValueError('CBOR metadata mismatch in '+', '.join(record['mismatched_fields'])+'; compare expected/actual in this diagnostic')
        text=body('prototype/mirror.txt').decode('utf-8')
        header,encoded=text.split('\n',1)
        if header.strip()!='METAWEB-CBOR-1':raise ValueError('Text envelope header mismatch')
        if base64.b64decode(''.join(encoded.split()),validate=True)!=binary:raise ValueError('Text transcription did not recover the exact tagged CBOR specimen')
        if json.loads(body('prototype/decoded.json'))!=expected:raise ValueError('Saved decoded JSON mismatch')
        wrong=dict(expected,sha256='0'*64)
        bad=base64.b64encode(cbor2.dumps(cbor2.CBORTag(55799,wrong),canonical=True)).decode('ascii')
        remaining=api.engine.state['config']['max_active_seconds']-api.engine.current_active_seconds()
        if remaining<1:raise ValueError('MAX_ACTIVE_SECONDS before independent validation')
        argv=['python','-I','-c',CHECK,'prototype/codec.py',source['path'],'prototype/seed.cbor',
            'prototype/mirror.txt',json.dumps(expected),bad]
        worker=asyncio.create_task(asyncio.to_thread(
            DockerExecutor(api.engine.state['config']['docker_image'],max(1,min(120,int(remaining)))).run,api.workspace.root,argv))
        cancelled=None
        try:result=await asyncio.shield(worker)
        except asyncio.CancelledError as error:
            cancelled=error
            while not worker.done():
                try:await asyncio.shield(worker)
                except asyncio.CancelledError:continue
            result=worker.result()
        record.update(validation_execution=result)
        if cancelled:raise cancelled
        if result.get('status')!='COMPLETED' or result.get('returncode')!=0 or result.get('cleanup_ok') is False:
            raise ValueError('Independent decoder/negative checks failed: '+result.get('output','')[-4000:])
        record.update(passed=True,reason='Host-decoded artifacts and independent decoder checks passed',
            expected=expected,artifact_hashes={p:hashlib.sha256(body(p)).hexdigest() for p in CONTRACT['artifacts']},
            meaning='Known local coding contract passed. No novel mechanism, full export preservation or external deposit certified.')
    except asyncio.CancelledError:
        record['reason']='Operator cancellation; execution outcome retained without awarding acceptance'
        api.engine.state.setdefault('coding_validations',[]).append(record)
        api.event('coding_acceptance_validation',record)
        raise
    except Exception as error:
        record['reason']=type(error).__name__+': '+str(error)[:5000]
    api.engine.state.setdefault('coding_validations',[]).append(record)
    api.event('coding_acceptance_validation',record)
    return record
