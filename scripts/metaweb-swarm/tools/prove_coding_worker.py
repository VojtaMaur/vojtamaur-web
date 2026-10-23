"""Opt-in real Docker/PyPI proof with scripted SDK responses, NEVER paid inference.

Run from this checkout: python tools/prove_coding_worker.py --export PUBLIC.epub
--output-root OUTSIDE_PROJECT. Scripted code is a transport/contract fixture,
not evidence that a live model can solve the task. The paid launcher tests that.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from metaweb_swarm.backend import OpenAIBackend
from metaweb_swarm.config import load_config
from metaweb_swarm.engine import initialize,Engine
from tests.test_backend import FakeProvider,tool_response,response,FINAL

CODEC = r'''
import base64,hashlib,json,pathlib,sys
import cbor2
def metadata(source):
    source=pathlib.Path(source);data=source.read_bytes()
    return dict(export=source.name,sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),decoder='metaweb-cbor-seed-v1')
def decode(source,specimen,out):
    body=pathlib.Path(specimen).read_bytes()
    if body.startswith(b'METAWEB-CBOR-1\n'):
        body=base64.b64decode(b''.join(body.split(b'\n',1)[1].split()),validate=True)
    if not body.startswith(bytes.fromhex('d9d9f7')):raise ValueError('Missing CBOR tag')
    actual=cbor2.loads(body)
    if actual!=metadata(source):raise ValueError('Wrong source metadata/digest')
    pathlib.Path(out).write_text(json.dumps(actual),encoding='utf-8')
if __name__=='__main__':
    if len(sys.argv)!=5 or sys.argv[1]!='decode':raise SystemExit('decode SOURCE SPECIMEN OUTPUT')
    decode(*sys.argv[2:])
'''

TEST = r'''
import base64,json,pathlib,subprocess,sys
import cbor2
from codec import metadata
source=sys.argv[1]
expected=metadata(source)
root=pathlib.Path('prototype')
binary=cbor2.dumps(cbor2.CBORTag(55799,expected),canonical=True)
(root/'seed.cbor').write_bytes(binary)
(root/'mirror.txt').write_text('METAWEB-CBOR-1\n'+base64.b64encode(binary).decode()+'\n',encoding='utf-8')
for specimen in ('seed.cbor','mirror.txt'):
    out=root/'decoded.json'
    subprocess.run([sys.executable,'prototype/codec.py','decode',source,str(root/specimen),str(out)],check=True)
    assert json.loads(out.read_text()) == expected
wrong=dict(expected,sha256='0'*64)
(root/'wrong.cbor').write_bytes(cbor2.dumps(cbor2.CBORTag(55799,wrong),canonical=True))
(root/'invalid.txt').write_text('METAWEB-CBOR-1\n!invalid!\n')
for invalid in ('wrong.cbor','invalid.txt'):
    rejected=subprocess.run([sys.executable,'prototype/codec.py','decode',source,str(root/invalid),str(root/'must-not-emit.json')],capture_output=True)
    assert rejected.returncode != 0
print('Saved binary + text decoded; valid CBOR with wrong digest and invalid envelope rejected')
'''


class ProofBackend:
    """Only LOCAL uses the real SDK Runner; review/report decisions are scripted."""
    def __init__(self):self.provider=None
    async def step(self,agent,prompt,history,api,config):
        kind=agent.get('work_kind')
        if kind=='LOCAL':
            source=api.prepare_prototype_input()['path']
            write=('from pathlib import Path\nPath("prototype").mkdir(exist_ok=True)\n'
                'Path("prototype/codec.py").write_text('+repr(CODEC)+',encoding="utf-8")\n'
                'Path("prototype/test.py").write_text('+repr(TEST)+',encoding="utf-8")\n')
            cmd="python - <<'PY'\n"+write+"PY\npython prototype/test.py '"+source+"'"
            repair="python - <<'PY'\nfrom pathlib import Path\np=Path('prototype/codec.py')\np.write_text(p.read_text().replace('json.dumps(actual)','json.dumps(dict(actual))'))\nPY\npython prototype/test.py '"+source+"'"
            final={'status':'READY','summary':'Scripted SDK proof regenerated CBOR, decoded saved binary/text and rejected semantic corruption',
                'script_path':'prototype/test.py','argv':['python','prototype/test.py',source],
                'output_paths':['prototype/seed.cbor','prototype/mirror.txt','prototype/decoded.json'],
                'source_paths':['prototype/codec.py'],
                'positive_assertion':'Decode saved binary and text; assert decoded fields equal the actual source metadata',
                'negative_assertion':'Reject valid CBOR with incorrect digest and invalid Base64 envelope with nonzero exit',
                'limitations':'Known local bootstrap component only. Scripted decisions/code; no live model performance, new discovery, whole export recovery or deposit claim.'}
            self.provider=FakeProvider([
                tool_response('install_packages',{'packages':['cbor2==6.1.5']}),
                tool_response('exec_command',{'cmd':cmd,'yield_time_ms':10000},ident='initial'),
                tool_response('exec_command',{'cmd':repair,'yield_time_ms':10000},ident='repair'),
                response([{'type':'message','id':'final','role':'assistant','status':'completed',
                    'content':[{'type':'output_text','text':json.dumps(final),'annotations':[]}]}])])
            return await OpenAIBackend(self.provider).step(agent,prompt,history,api,config)
        if kind=='REVIEW':
            test=api.get_review_task()['test_receipt']
            api.get_prototype_review_facts(test['id'])
            for artifact in test['artifacts']:
                page=api.read_test_artifact(test['id'],artifact['path'])
                while page.get('next_offset') is not None:
                    page=api.read_test_artifact(test['id'],artifact['path'],page['next_offset'])
            reviewed=api.review_prototype_test(test['id'],'SUBCOMPONENT',
                'Scripted independent scope verdict: actual CBOR/text and corruption checks passed; only a metadata bootstrap component, no complete export preservation.',
                positive_code='assert json.loads(out.read_text()) == expected',
                negative_code='assert rejected.returncode != 0',observed_recovery='NO_RECOVERED_OUTPUT',review_basis='UNSPECIFIED')
            assert reviewed.get('verdict')=='SUBCOMPONENT',reviewed
        elif kind=='SYNTHESIS':
            api.get_research_task()
            api.record_research_report([i['id'] for i in api.engine.state['ideas']],
                'Scripted SDK/Docker/PyPI integration proof passed a known CBOR component contract after one intentional failed development command. Independent host checks decoded actual artifacts and tested corruption rejection.',
                ['No paid inference. Code/model responses and scope verdict are scripted fixtures; no new discovery, full export recovery or external deposit.'])
        return {'output':dict(FINAL,summary='Scripted fixture role completed'),'history':[],
                'usage':{},'raw':{'usage_complete':True,'requests_attempted':0}}


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,required=True)
    args=parser.parse_args()
    source=args.export.resolve();root=args.output_root.resolve()
    root.mkdir(parents=True,exist_ok=False)
    original=hashlib.sha256(source.read_bytes()).hexdigest()
    project=root/'public-fixture';(project/'exports').mkdir(parents=True)
    shutil.copyfile(source,project/'exports'/source.name)
    config=load_config(Path(__file__).resolve().parents[1]/'config.prototype.json')
    config['export_filenames']=[source.name]
    run=initialize(project,root/'runs',config)
    backend=ProofBackend();engine=Engine(run,backend,'openai')
    try:
        await engine.run()
        state=engine.state
        assert state['status']=='COMPLETED',state['stop_reason']
        assert [c['returncode'] for c in state['coding_commands']]==[1,0]
        assert state['coding_validations'][-1]['passed'],state['coding_validations'][-1]
        assert state['package_installations'][0]['status']=='COMPLETED'
        assert len(state['tests'])==1 and state['prototype_reviews'][0]['verdict']=='SUBCOMPONENT'
        assert 'prototype/codec.py' in [a['path'] for a in state['tests'][0]['artifacts']]
        assert not state.get('external_actions') and not state.get('budget_reservations')
        engine.store.verify()
        proof={'paid_api_calls':0,'model_responses':'scripted, not live inference','code':'scripted fixture',
            'review_verdict':'scripted SUBCOMPONENT, not a live LLM assessment','run':str(run),
            'source_export':source.name,'source_sha256':original,'source_unchanged':hashlib.sha256(source.read_bytes()).hexdigest()==original,
            'development_exit_codes':[r['returncode'] for r in state['coding_commands']],
            'package_installation':state['package_installations'][0]['status'],
            'coding_validation':state['coding_validations'][-1],
            'test_count':len(state['tests']),'helper_code_captured':True,'report_exists':(run/'SWARM_REPORT.md').is_file(),
            'external_actions':len(state.get('external_actions',[])),'status':state['status']}
        (root/'proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'status':state['status'],'run':str(run),'proof':str(root/'proof.json'),'paid_api_calls':0}))
    finally:engine.close()

if __name__=='__main__':asyncio.run(main())
