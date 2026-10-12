"""Real generic HTTP dispatch, policy/approval, read-back and durable limits."""
import asyncio
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from metaweb_swarm.config import load_config
from metaweb_swarm.demo import DemoBackend
from metaweb_swarm.engine import Engine, ToolAPI, initialize, decide
from metaweb_swarm.workspace import Workspace
from tests.test_backend import SDK_AVAILABLE


class Service(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        self.server.calls.append(('GET', self.path, dict(self.headers)))
        data = self.server.data if self.path == '/file' else b'{"documentation":"POST /file accepts raw bytes; GET /file returns them"}'
        self.send_response(200); self.send_header('Content-Type','application/octet-stream'); self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        self.server.calls.append(('POST', self.path, dict(self.headers)))
        self.server.data = self.rfile.read(int(self.headers['Content-Length']))
        self.send_response(201); self.end_headers(); self.wfile.write(b'{"location":"/file"}')


class HttpToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        project = self.root/'project'; project.mkdir(); (project/'site.txt').write_text('unchanged')
        self.server = ThreadingHTTPServer(('127.0.0.1',0), Service); self.server.calls=[]; self.server.data=b''
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.origin = f'http://127.0.0.1:{self.server.server_port}'
        config = load_config(); config.update(model='fixture-model', run_mode='autonomous', external_scope='external', approval_required=False,
            http_access='enabled', http_test_origins=[self.origin], max_http_response_bytes=4096, max_http_total_bytes=65536)
        self.run = initialize(project,self.root/'runs',config)
        self.engine = Engine(self.run,DemoBackend(),'demo'); self.agent=self.engine.state['agents'][1]
        self.workspace=Workspace(self.run/'snapshot',self.run/'agents'/self.agent['id']/'workspace')
        self.api=ToolAPI(self.engine,self.agent,self.workspace)
        self.idea=self.api.submit_idea(DemoBackend.idea('Unknown public byte service','Preserve export bytes using discovered generic API','FREE','INVESTIGATING'))
        self.api.write_file('prototype/build.txt','actual public build bytes')

    def tearDown(self):
        self.engine.close(); self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    async def request(self, method='GET', path='/docs', **extras):
        return await self.api.http_request(dict(method=method,url=self.origin+path,**extras),self.idea['id'],'Test discovered public service')

    async def test_discover_upload_download_verify_without_connector_or_approval(self):
        docs=await self.request(); self.assertEqual(docs['response']['status'],200)
        self.assertIn('POST /file',self.workspace.read_file(docs['response']['path']))
        upload=await self.request('POST','/file',upload_path='prototype/build.txt')
        self.assertEqual(upload['status'],'COMPLETED', upload)
        self.assertFalse(self.engine.state['approvals'])
        self.assertNotEqual(self.api.idea(self.idea['id'])['status'],'COMPLETED')
        download=await self.request('GET','/file')
        receipt=self.api.verify_http_copy(upload['id'],download['id'],'prototype/build.txt')
        self.assertTrue(receipt['host_verified']); self.assertEqual(self.api.idea(self.idea['id'])['status'],'COMPLETED')
        replay=await self.api.http_request({'method':'POST','url':self.origin+'/file','upload_path':'prototype/build.txt','response_path':'another.txt'},self.idea['id'],'Different phrasing same effect')
        self.assertTrue(replay['replayed']); self.assertEqual(len([x for x in self.server.calls if x[0]=='POST']),1)
        self.assertEqual(len(self.engine.state['external_actions']),1)
        self.engine.store.verify()

    async def test_scope_supervision_approval_binding_and_resume(self):
        c=self.engine.state['config']; c['external_scope']='sandbox-only'
        self.assertEqual((await self.request('POST','/file',body_text='x'))['reason'],'EXTERNAL_SCOPE_DISABLED')
        self.assertEqual((await self.request())['status'],'COMPLETED')
        c.update(external_scope='external',run_mode='supervised')
        self.assertEqual((await self.request('POST','/file',body_text='x'))['reason'],'AWAITING_IMPLEMENTATION_SELECTION')
        c['run_mode']='autonomous'; c['approval_required']=True
        first=await self.request('POST','/file',body_text='x'); self.assertEqual(first['status'],'DEFERRED')
        decide(self.engine.store,self.engine.state,first['approval_id'],'approve','Approve exact harmless fixture request')
        changed=await self.request('POST','/file',body_text='changed'); self.assertEqual(changed['status'],'DEFERRED')
        self.assertNotEqual(first['approval_id'],changed['approval_id'])
        result=await self.request('POST','/file',body_text='x'); self.assertEqual(result['response']['status'],201)
        self.assertEqual(len([x for x in self.server.calls if x[0]=='POST']),1)

    def test_dedicated_grant_availability_does_not_expose_secret(self):
        self.engine.state['config']['http_credentials'] = [{'id': 'swarm-only', 'env': 'META_SWARM_CRED_TEST',
            'hosts': ['example.org'], 'header': 'Authorization', 'scheme': 'Bearer'}]
        with patch.dict('os.environ', {}, clear=True):
            self.assertFalse(self.api.list_http_credentials()['credentials'][0]['available'])
        with patch.dict('os.environ', {'META_SWARM_CRED_TEST': 'dedicated-fixture-secret', 'GITHUB_TOKEN': 'host-fixture-secret'}, clear=True):
            result = self.api.list_http_credentials()
        self.assertTrue(result['credentials'][0]['available'])
        self.assertFalse(result['ambient_credentials_available'])
        self.assertNotIn('fixture-secret', json.dumps(result))
        self.assertNotIn('GITHUB_TOKEN', json.dumps(result))

    async def test_independent_review_required_before_approval_or_upload(self):
        config = self.engine.state['config']
        config['require_independent_http_review'] = True
        config['approval_required'] = True
        self.assertEqual(self.api.record_critique(self.idea['id'], 'PASS', 'Creator cannot pass itself')['reason'], 'INDEPENDENT_AUDITOR_REQUIRED')
        result = await self.request('POST', '/file', body_text='reviewed public bytes')
        self.assertEqual(result['reason'], 'INDEPENDENT_AUDIT_REQUIRED')
        self.assertFalse(self.engine.state['approvals'])
        self.assertFalse(self.server.calls)
        auditor = next(a for a in self.engine.state['agents'] if a['role'] == 'Evidence Auditor')
        review_api = ToolAPI(self.engine, auditor, Workspace(self.run/'snapshot', self.run/'agents'/auditor['id']/'workspace'))
        self.assertEqual(review_api.record_critique(self.idea['id'], 'PASS', 'No observed docs yet')['reason'], 'AUDITOR_PRIMARY_SOURCES_REQUIRED')
        for path in ['/docs', '/terms']:
            result = await review_api.http_request({'method': 'GET', 'url': self.origin+path}, self.idea['id'], 'Read independent service documentation')
            review_api.read_file(result['response']['path'])
        critique = review_api.record_critique(self.idea['id'], 'PASS', 'Independent review of public docs and terms supports free use')
        self.assertEqual(critique['verdict'], 'PASS')
        result = await self.request('POST', '/file', body_text='reviewed public bytes')
        self.assertEqual(result['reason'], 'HUMAN_APPROVAL_REQUIRED')
        self.assertFalse(any(method == 'POST' for method, *_ in self.server.calls))
        decide(self.engine.store, self.engine.state, result['approval_id'], 'approve', 'Approve reviewed exact upload')
        result = await self.request('POST', '/file', body_text='reviewed public bytes')
        self.assertEqual(result['response']['status'], 201)

    async def test_copy_receipt_does_not_resolve_unknown_payment_or_accept_delete(self):
        upload=await self.request('POST','/file',upload_path='prototype/build.txt')
        download=await self.request('GET','/file')
        self.api.idea(self.idea['id'])['payment']='UNKNOWN'
        self.api.verify_http_copy(upload['id'],download['id'],'prototype/build.txt')
        self.assertNotEqual(self.api.idea(self.idea['id'])['status'],'COMPLETED')
        upload['action']['payload']['method']='DELETE'
        with self.assertRaises(ValueError):
            self.api.verify_http_copy(upload['id'],download['id'],'prototype/build.txt')

    async def test_shared_limits_and_pause_are_enforced_without_network(self):
        self.engine.state['config']['max_external_actions']=0
        self.assertEqual((await self.request('POST','/file',body_text='x'))['reason'],'MAX_EXTERNAL_ACTIONS')
        self.engine.state['config']['max_http_total_bytes']=10
        self.assertEqual((await self.request())['reason'],'MAX_HTTP_TOTAL_BYTES')
        self.engine.state['config']['max_http_total_bytes']=65536
        (self.run/'PAUSE.flag').write_text('pause')
        self.assertEqual((await self.request())['reason'],'PAUSE_REQUESTED')
        self.assertFalse(self.server.calls)

    async def test_ambient_tokens_not_loaded_and_protected_writes_denied(self):
        with patch.dict('os.environ', {'GITHUB_TOKEN':'never-forward-this', 'GITLAB_TOKEN':'another-host-token','HTTP_PROXY':'http://127.0.0.1:1'}):
            await self.request()
        self.assertFalse(any(k.lower() in {'authorization','cookie','proxy-authorization'} for k in self.server.calls[0][2]))
        for host in ('api.github.com','gitlab.com','codeberg.org','vojtamaur.cz'):
            with self.assertRaises(ValueError):
                await self.api.http_request({'method':'POST','url':'https://'+host+'/anything'},self.idea['id'],'Try forbidden repository mutation')


    async def test_proven_before_send_error_is_failed_with_diagnostics(self):
        from metaweb_swarm.http_transport import HttpTransportError
        with patch('metaweb_swarm.http_transport.execute_request', side_effect=HttpTransportError('TLS handshake failed: CERTIFICATE_VERIFY_FAILED', stage='tls')):
            result = await self.request()
        self.assertEqual(result['status'], 'FAILED')
        self.assertTrue(result['request_not_sent'])
        self.assertEqual(result['error']['stage'], 'tls')
        self.assertIn('CERTIFICATE_VERIFY_FAILED', result['reason'])
        self.assertEqual(result['budget_bytes'], 0)
        self.assertFalse(self.server.calls)

    async def test_uncertain_attempt_does_not_repeat_after_crash_or_rewording(self):
        with patch('metaweb_swarm.http_transport.execute_request',side_effect=TimeoutError):
            first=await self.request('POST','/file',body_text='same')
        self.assertEqual(first['status'],'UNKNOWN')
        again=await self.api.http_request({'method':'POST','url':self.origin+'/file','body_text':'same'},self.idea['id'],'Reworded purpose after timeout')
        self.assertEqual(again['reason'],'PREVIOUS_HTTP_ATTEMPT_REQUIRES_RECONCILIATION')
        first['status']='RESERVED'; self.engine.store.commit(self.engine.state,'simulate_crash',{}); self.engine.close()
        self.engine=Engine(self.run,DemoBackend(),'demo')
        self.assertEqual(self.engine.state['http_requests'][0]['status'],'UNKNOWN')
        self.assertEqual(self.engine.state['external_actions'][0]['status'],'UNKNOWN')
        self.assertFalse(self.server.calls)

    @unittest.skipUnless(SDK_AVAILABLE,'SDK required')
    async def test_real_sdk_invokes_generic_http_tool(self):
        from tests.test_backend import FakeProvider,tool_response,final_response
        from metaweb_swarm.backend import OpenAIBackend
        provider=FakeProvider([tool_response('http_request',{'request_json':json.dumps({'url':self.origin+'/docs'}),'idea_id':self.idea['id'],'purpose':'Read unknown service documentation'}),final_response()])
        config=dict(self.engine.state['config'],max_web_search_calls_per_request=0)
        await OpenAIBackend(provider).step(self.agent,'Discover generic API',[],self.api,config)
        self.assertEqual(len(self.engine.state['http_requests']),1); self.assertEqual(self.server.calls[0][0],'GET')


if __name__ == '__main__': unittest.main()
