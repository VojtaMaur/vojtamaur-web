"""Generic HTTP smoke: actual service, production SDK dispatch, no paid inference."""
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from metaweb_swarm.config import load_config, validate_config
from metaweb_swarm.engine import Engine, ToolAPI, initialize, refresh_reports
from metaweb_swarm.http_smoke import service, INPUT_PATH, INPUT_TEXT
from metaweb_swarm.workspace import Workspace
from tests.test_backend import SDK_AVAILABLE, FINAL

class FixtureBackend:
    def __init__(self, mode='complete'):
        self.mode = mode
    async def step(self, agent, prompt, history, api, config):
        self.assert_no_discovery = 'HTTP INTEGRATION TEST' in prompt and 'Piql' not in prompt
        if agent['role'] == 'Prototyper' and self.mode not in {'skip', 'blocked'}:
            origin = api.engine.state['http_smoke']['origin']
            docs = await api.http_request({'method':'GET', 'url':origin+'/guide'}, purpose='Discover byte service protocol')
            schema = json.loads(api.read_file(docs['response']['path']))
            upload = await api.http_request({'method':schema['upload']['method'], 'url':origin+schema['upload']['path'],
                'upload_path':INPUT_PATH}, purpose='Upload harmless integration specimen')
            download = await api.http_request({'method':schema['download']['method'], 'url':origin+schema['download']['path']},
                purpose='Download object to verify exact bytes')
            api.verify_http_copy(upload['id'], download['id'], INPUT_PATH)
        output = dict(FINAL)
        if self.mode == 'blocked' and agent['role'] == 'Prototyper':
            output.update(status='BLOCKED', reason_for_stopping='Specific fixture failure')
        return {'output':output, 'history':[], 'usage':{}, 'raw':{}}

class SmokeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        project=self.root/'project'; project.mkdir(); (project/'site.txt').write_text('keep unchanged')
        self.project=project
        self.config=load_config(Path(__file__).resolve().parent.parent/'config.http-smoke.json')
        self.run_dir=initialize(project,self.root/'runs',self.config)
        self.backend=FixtureBackend()
        self.engine=Engine(self.run_dir,self.backend,'demo')
        self.agent=self.engine.state['agents'][0]
    def tearDown(self):
        self.engine.close()
        self.temp.cleanup()
    def api(self):
        ws=Workspace(self.run_dir/'snapshot',self.run_dir/'agents'/self.agent['id']/'workspace')
        ws.write_file(INPUT_PATH, INPUT_TEXT)
        return ToolAPI(self.engine,self.agent,ws)

    async def test_full_round_trip_and_report_not_preservation_deposit(self):
        state=await self.engine.run()
        self.assertEqual(state['status'],'COMPLETED')
        self.assertTrue(state['http_smoke']['passed'])
        self.assertFalse(state['http_smoke']['running'])
        self.assertTrue(self.backend.assert_no_discovery)
        self.assertEqual(len(state['http_requests']),3)
        self.assertEqual(state['http_smoke']['receipt']['sha256'],hashlib.sha256(INPUT_TEXT.encode()).hexdigest())
        self.assertFalse(state['ideas'])
        self.assertFalse(state['approvals'])
        self.assertFalse(state['experiments'])
        report=(self.run_dir/'SWARM_REPORT.md').read_text(encoding='utf-8')
        self.assertIn('Ověřená uložení: 0',report)
        self.assertIn('HTTP integrační test lokální služby',report)
        self.assertFalse(json.loads((self.run_dir/'manifest.json').read_text(encoding='utf-8'))['http_smoke']['running'])
        self.assertEqual((self.project/'site.txt').read_text(),'keep unchanged')
        self.engine.store.verify()

    async def test_missing_receipt_cannot_claim_complete_and_real_blockers_remain(self):
        self.backend.mode='skip'
        state=await self.engine.run()
        self.assertEqual(state['status'],'LIMIT_REACHED')
        self.assertFalse(state['http_smoke']['passed'])
        self.assertEqual(self.agent['rounds'],3)
        self.assertEqual(state['agents'][1]['status'],'COMPLETED')
        self.engine.close()
        self.run_dir=initialize(self.project,self.root/'runs',load_config(Path(__file__).resolve().parent.parent/'config.http-smoke.json'))
        self.engine=Engine(self.run_dir,FixtureBackend('blocked'),'demo')
        state=await self.engine.run()
        self.assertEqual(state['status'],'BLOCKED')
        self.assertFalse(state['http_smoke']['passed'])

    async def test_only_fixture_origin_and_profile_constraints(self):
        with service(self.engine):
            api=self.api()
            for url in ('https://example.com','http://127.0.0.1:1','http://localhost:8080'):
                result=await api.http_request({'method':'POST','url':url,'upload_path':INPUT_PATH},purpose='Rejected scope test')
                self.assertEqual(result['reason'],'HTTP_SMOKE_FIXTURE_ONLY')
            self.assertFalse(self.engine.state.get('http_requests'))
        for override in ({'http_credentials':[{}]}, {'external_resources':[{}]}, {'experiments':'docker'}, {'run_mode':'supervised'}):
            config=dict(self.config,**override)
            with self.assertRaises(ValueError):
                validate_config(config)

    async def test_documentation_read_and_byte_evidence_are_mandatory(self):
        with service(self.engine):
            api=self.api(); fixture=self.engine.state['http_smoke']
            origin=fixture['origin']; route=fixture['object_path']
            docs=await api.http_request({'method':'GET','url':origin+'/guide'},purpose='Fetch protocol')
            upload=await api.http_request({'method':'POST','url':origin+route,'upload_path':INPUT_PATH},purpose='Upload specimen')
            download=await api.http_request({'method':'GET','url':origin+route},purpose='Read specimen back')
            with self.assertRaises(ValueError):
                api.verify_http_copy(upload['id'],download['id'],INPUT_PATH)
            api.read_file(docs['response']['path']) # Too late; cannot certify protocol discovery.
            with self.assertRaises(ValueError):
                api.verify_http_copy(upload['id'],download['id'],INPUT_PATH)
            self.assertFalse(fixture['passed'])
            api.workspace.write_file(download['response']['path'],b'wrong')
            with self.assertRaises(ValueError):
                api.verify_http_copy(upload['id'],download['id'],INPUT_PATH)

    async def test_restart_keeps_object_and_pause_blocks_network(self):
        with service(self.engine):
            api=self.api(); f=self.engine.state['http_smoke']; origin=f['origin']
            docs=await api.http_request({'method':'GET','url':origin+'/guide'},purpose='Fetch protocol')
            api.read_file(docs['response']['path'])
            upload=await api.http_request({'method':'POST','url':origin+f['object_path'],'upload_path':INPUT_PATH},purpose='Upload specimen')
            self.engine.store.commit(self.engine.state,'test_checkpoint',{})
        self.engine.close(); self.engine=Engine(self.run_dir,FixtureBackend(),'demo')
        self.agent=self.engine.state['agents'][0]
        with service(self.engine):
            api=self.api(); f=self.engine.state['http_smoke']
            self.assertEqual(f['origin'],origin)
            (self.run_dir/'PAUSE.flag').write_text('pause')
            result=await api.http_request({'method':'GET','url':origin+f['object_path']},purpose='Paused download')
            self.assertEqual(result['reason'],'PAUSE_REQUESTED')
            (self.run_dir/'PAUSE.flag').unlink()
            download=await api.http_request({'method':'GET','url':origin+f['object_path']},purpose='Resume download')
            self.assertTrue(api.verify_http_copy(upload['id'],download['id'],INPUT_PATH)['host_verified'])
        self.engine.store.verify()

    @unittest.skipUnless(SDK_AVAILABLE,'optional SDK not installed')
    async def test_actual_sdk_tools_and_service_through_full_engine(self):
        from metaweb_swarm.backend import OpenAIBackend, _make_sdk_tools
        from tests.test_backend import FakeProvider, FakeModel, tool_response, final_response
        import agents as sdk
        engine=self.engine
        class ProtocolModel(FakeModel):
            def __init__(self):
                super().__init__([]); self.index=0
            async def get_response(self,*args,**kwargs):
                self.calls.append((args,kwargs))
                f=engine.state['http_smoke']; ledger=engine.state.get('http_requests',[])
                index=self.index; self.index+=1
                if index==0:
                    name='http_request'; argspec={'request_json':json.dumps({'method':'GET','url':f['origin']+'/guide'}),'idea_id':'','purpose':'Discover fixture API protocol'}
                elif index==1:
                    name='read_file'; argspec={'path':ledger[0]['response']['path'],'offset':0,'limit':8000}
                elif index==2:
                    api_schema=json.loads((engine.store.run_dir/'agents'/engine.state['agents'][0]['id']/'workspace'/ledger[0]['response']['path']).read_text())
                    name='http_request'; argspec={'request_json':json.dumps({'method':api_schema['upload']['method'],'url':f['origin']+api_schema['upload']['path'],'upload_path':INPUT_PATH}),'idea_id':'','purpose':'Upload integration specimen'}
                elif index==3:
                    name='http_request'; argspec={'request_json':json.dumps({'method':'GET','url':ledger[1]['action']['payload']['url']}),'idea_id':'','purpose':'Download integration object'}
                elif index==4:
                    name='verify_http_copy'; argspec={'upload_request_id':ledger[1]['id'],'download_request_id':ledger[2]['id'],'source_path':INPUT_PATH}
                else:
                    return final_response('final-'+str(index))
                return tool_response(name,argspec,'smoke-'+str(index))
        provider=FakeProvider([]); provider.model=ProtocolModel()
        engine.backend=OpenAIBackend(model_provider=provider); engine.backend_name='openai'; engine.state['backend']='openai'
        tools,_=_make_sdk_tools(sdk,self.api())
        self.assertEqual({t.name for t in tools},{'read_file','note','http_request','verify_http_copy'})
        state=await engine.run()
        self.assertEqual(state['status'],'COMPLETED',state['stop_reason'])
        self.assertTrue(state['http_smoke']['passed'])
        self.assertEqual(state['usage']['web_search_calls'],0)
        self.assertEqual(len(provider.model.calls),7) # docs/read/upload/download/verify/final + reporter
        self.engine.store.verify()
