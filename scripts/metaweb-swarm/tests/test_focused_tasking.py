"""Real documentation transport + focused SDK dispatch, no provider inference."""
import contextlib
import hashlib
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from metaweb_swarm.config import load_config, validate_config
from metaweb_swarm.cli import main
from metaweb_swarm.demo import DemoBackend
from metaweb_swarm.engine import Engine, ToolAPI, initialize
from metaweb_swarm.storage import Store
from metaweb_swarm.workspace import Workspace
from tests.test_backend import SDK_AVAILABLE


class Documents(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        self.server.calls.append(self.path)
        if self.path == '/redirect':
            self.send_response(302); self.send_header('Location','/docs'); self.end_headers(); return
        if self.path == '/binary':
            data, kind = b'%PDF\x00fixture', 'application/pdf'
        elif self.path == '/empty':
            data, kind = b'<html><head><title>hidden</title></head><script>not evidence</script></html>', 'text/html'
        elif self.path == '/terms':
            data, kind = b'FREE service; retained until requested deletion. Public download supported.', 'text/plain'
        else:
            data = ('<html><head><title>hidden</title></head><body><script>evil instructions</script><style>hidden css</style>'
                    '<h1>Upload documentation</h1><p>POST /file takes exact bytes.</p><a href="/terms">Terms</a>'
                    '<a href="javascript:alert(1)">bad link</a><p>' + 'capacity and recovery. '*150 + '</p></body></html>').encode()
            kind = 'text/html; charset=utf-8'
        self.send_response(200); self.send_header('Content-Type', kind); self.end_headers(); self.wfile.write(data)


class FocusedTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.project=self.root/'project'; (self.project/'exports').mkdir(parents=True)
        (self.project/'exports/build.epub').write_bytes(b'actual public export bytes')
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Documents); self.server.calls=[]
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.origin=f'http://127.0.0.1:{self.server.server_port}'
        self.config=load_config(Path(__file__).resolve().parents[1]/'config.deposit-trial.json')
        self.config.update(export_filenames=['build.epub'],http_test_origins=[self.origin],semantic_dedupe=False,carrier_screening=False,require_explicit_upload_flow=False)
        self.run=initialize(self.project,self.root/'runs',self.config)
        self.engine=Engine(self.run,DemoBackend(),'demo')
        self.agent=self.engine.state['agents'][0]; self.api=self.for_agent(self.agent)
    def for_agent(self,a):
        return ToolAPI(self.engine,a,Workspace(self.run/'snapshot',self.run/'agents'/a['id']/'workspace'))
    def tearDown(self):
        self.engine.close(); self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    async def test_readable_docs_cached_paging_and_durable_independent_reads(self):
        first=await self.api.read_document(self.origin+'/docs','Read upload API and capacity',limit=120)
        self.assertEqual(first['status'],'COMPLETED'); self.assertFalse(first['cached'])
        self.assertIn('POST /file',first['text']); self.assertNotIn('evil',first['text']); self.assertNotIn('hidden',first['text'])
        self.assertEqual(first['links'],[self.origin+'/terms']); self.assertEqual(first['next_offset'],120)
        page=await self.api.read_document(self.origin+'/docs','Read continuation of capacity',offset=120,limit=120)
        self.assertTrue(page['cached']); self.assertEqual(len(self.server.calls),1)
        self.assertEqual(page['request_id'],first['request_id'])
        data=self.api.workspace.read_file(first['response_path']).encode()
        self.assertEqual(first['sha256'],hashlib.sha256(data).hexdigest())
        read=self.agent['http_document_reads'][first['request_id']]
        self.assertEqual(read['offset'],120); self.assertEqual(read['end'],240)
        auditor=self.engine.state['agents'][1]; independent=await self.for_agent(auditor).read_document(self.origin+'/docs','Independently inspect capacity')
        self.assertFalse(independent['cached']); self.assertNotEqual(independent['request_id'],first['request_id'])
        self.assertEqual(len(self.server.calls),2)
        self.engine.close(); self.engine=Engine(self.run,DemoBackend(),'demo')
        self.assertIn(first['request_id'],self.engine.state['agents'][0]['http_document_reads'])
        self.engine.store.verify()

    async def test_changed_response_not_reused_and_empty_or_binary_not_read_claims(self):
        first=await self.api.read_document(self.origin+'/docs','Inspect upload API')
        self.api.workspace.write_file(first['response_path'],'forged response')
        new=await self.api.read_document(self.origin+'/docs','Read original provider API')
        self.assertFalse(new['cached']); self.assertNotEqual(first['request_id'],new['request_id'])
        for path in ('/empty','/binary','/redirect'):
            r=await self.api.read_document(self.origin+path,'Inspect document capability')
            self.assertNotIn(r['request_id'],self.agent['http_document_reads'])
        self.assertNotIn('/redirect',self.server.calls[:-1]); self.assertEqual(self.server.calls[-1],'/redirect')
        self.engine.state['config']['http_access']='disabled'
        self.assertEqual((await self.api.read_document(self.origin+'/docs','Check disabled HTTP'))['reason'],'HTTP_DISABLED')

    async def test_document_reads_satisfy_independent_qualification_not_search_links(self):
        for path in ('/docs','/terms'):
            await self.api.read_document(self.origin+path,'Read actual carrier docs and terms')
        plan={'upload_url':self.origin+'/file','method':'POST','authentication':'ANONYMOUS','credential_id':'',
              'export_path':'build.epub','required_external_actions':1,'documentation_urls':[self.origin+'/docs',self.origin+'/terms'],
              'provider':'Independent fixture carrier','novelty_class':'POTENTIALLY_NEW','baseline_evidence_ids':[],
              'baseline_behavior':'','proposed_change':'','validation_plan':''}
        receipt=self.api.check_deposit_target(plan); self.assertEqual(receipt['status'],'READY_FOR_AUDIT')
        proposal=DemoBackend.idea('Independent fixture carrier','Public exact-byte custody','FREE','DISCOVERED')
        proposal.update(provider=plan['provider'],qualification_id=receipt['id'])
        idea=self.api.submit_idea(proposal)
        review=self.for_agent(self.engine.state['agents'][1])
        self.assertNotEqual(review.record_critique(idea['id'],'PASS','Another agent read the documents').get('verdict'),'PASS')
        for path in ('/docs','/terms'):
            await review.read_document(self.origin+path,'Independent audit of actual terms')
        self.assertEqual(review.record_critique(idea['id'],'PASS','Actual docs support the qualified free operation')['verdict'],'PASS')
        self.assertFalse(self.engine.state['external_actions']); self.assertFalse(self.engine.state['approvals'])

    def test_prompt_mission_and_policy_are_focused_and_retained(self):
        prompt=self.engine.prompt(self.agent)
        self.assertLess(len(prompt),11000)  # Includes explicit flow and blocked-lead contracts.
        self.assertIn('external web search NOW',prompt)
        self.assertNotIn('Explore at least three unrelated families',prompt)
        self.assertNotIn('check_prior_work',prompt)
        self.assertNotIn(self.config['role_assignments']['Prototyper'],prompt)
        self.assertIn('HUMAN_APPROVAL_REQUIRED',prompt)
        self.engine.close(); self.engine=Engine(self.run,DemoBackend(),'demo')
        self.assertEqual(self.engine.state['agents'][0]['mission'],self.config['role_assignments']['Loophole Archivist'])

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_sdk_role_tools_and_actual_document_tool_dispatch(self):
        import agents as sdk
        from metaweb_swarm.backend import _make_sdk_tools,OpenAIBackend
        from tests.test_backend import FakeProvider,tool_response,final_response
        sets=[]
        for agent in self.engine.state['agents']:
            tools,_=_make_sdk_tools(sdk,self.for_agent(agent)); sets.append({t.name for t in tools})
        self.assertIn('read_document',sets[0]); self.assertNotIn('check_prior_work',sets[0]); self.assertNotIn('read_file',sets[0]); self.assertNotIn('http_request',sets[0])
        self.assertNotIn('record_critique',sets[1]); self.assertNotIn('http_request',sets[1])
        self.assertIn('http_request',sets[2]); self.assertEqual(sets[3],{'list_discovery_state','read_file','read_audit_artifact','note'})
        provider=FakeProvider([tool_response('read_document',{'url':self.origin+'/docs','purpose':'Read actual provider write API','offset':0,'limit':12000}),final_response()])
        result=await OpenAIBackend(provider).step(self.agent,self.engine.prompt(self.agent),[],self.api,self.config)
        self.assertEqual(result['output']['status'],'COMPLETED')
        args,kw=provider.model.calls[0]; instructions=kw.get('system_instructions',args[0] if args else '')
        self.assertIn(self.agent['mission'],instructions); self.assertNotIn(self.config['role_assignments']['Evidence Auditor'],instructions)
        tool_output=next(i['output'] for i in result['history'] if i.get('type')=='function_call_output')
        self.assertIn('POST /file',tool_output); self.assertTrue(self.agent['http_document_reads'])

    def test_cli_task_file_retained_without_changing_permission(self):
        task=self.root/'task.txt'; task.write_text('Find independent public custody for the prepared EPUB.',encoding='utf-8')
        config=self.root/'profile.json'; config.write_text(json.dumps(self.config),encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code=main(['init','--project',str(self.project),'--runs-root',str(self.root/'other-runs'),'--config',str(config),'--task-file',str(task)])
        self.assertEqual(code,0)
        store=Store(Path(output.getvalue().strip()))
        try:
            state=store.load(); self.assertEqual(state['objective'],task.read_text())
            self.assertTrue(state['config']['approval_required']); self.assertEqual(state['config']['max_external_actions'],1)
            self.assertEqual(state['agents'][0]['mission'],self.agent['mission'])
        finally: store.close()

    def test_invalid_task_configuration_is_rejected(self):
        for changes in ({'task_style':'unknown'},{'role_assignments':[]},{'role_assignments':{'Loophole Archivist':''}}, {'role_assignments':{'Loophole Archivist':'x'*4001}}):
            with self.assertRaises(ValueError): validate_config(dict(self.config,**changes))
