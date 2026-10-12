import asyncio
import copy
import hashlib
import json
import os
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from tests import test_deposit_qualification as fixture
from tests.test_backend import SDK_AVAILABLE
from metaweb_swarm.engine import Engine, decide, refresh_reports
from metaweb_swarm.demo import DemoBackend
from metaweb_swarm import deposit_execution, flow_vault

class Protocol(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def reply(self,code,data,kind='application/json'):
        data=json.dumps(data).encode() if isinstance(data,dict) else data
        self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_POST(self):
        data=self.rfile.read(int(self.headers.get('Content-Length',0)))
        self.server.calls.append(('POST',self.path,dict(self.headers),data))
        if self.path=='/reserve':
            self.reply(201,{'id':'abc','upload':{'signedUrl':self.server.signed_url,'headers':{'Content-Type':'application/epub+zip','X-Upload-Code':'opaque-header-capability'}},'echo':self.headers.get('Authorization','')})
            if self.server.pause_after_reserve: (self.server.run/'PAUSE.flag').touch()
        elif self.path=='/complete/abc':
            self.server.finalized=True;self.reply(200,{'publicUrl':self.server.origin+'/public/abc'})
        else: self.reply(400,b'bad')
    def do_PUT(self):
        data=self.rfile.read(int(self.headers.get('Content-Length',0)))
        self.server.calls.append(('PUT',self.path,dict(self.headers),data))
        self.server.data=data
        if self.server.uncertain:
            self.close_connection=True;return
        self.reply(self.server.put_status,b'')
    def do_GET(self):
        self.server.calls.append(('GET',self.path,dict(self.headers),b''))
        if self.path=='/public/abc':
            self.reply(200,self.server.data+(b'x' if self.server.corrupt else b''),'application/epub+zip')
        else: self.reply(404,b'bad')

class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.QualificationTests.setUp
    tearDown=fixture.QualificationTests.tearDown
    for_agent=fixture.QualificationTests.for_agent
    plan=fixture.QualificationTests.plan
    idea=fixture.QualificationTests.idea
    observe=fixture.QualificationTests.observe

    async def setup_flow(self,approval=False,credential=False):
        await self.observe(self.api)
        self.protocol=ThreadingHTTPServer(('127.0.0.1',0),Protocol)
        p=self.protocol;p.origin=f'http://127.0.0.1:{p.server_port}';p.run=self.run
        p.calls=[];p.data=b'';p.pause_after_reserve=False;p.finalized=False;p.uncertain=False;p.corrupt=False;p.put_status=200
        p.signed_url=p.origin+'/opaque-path-capability?X-Amz-Signature=private-signature&X-Amz-Credential=temporary-grant'
        self.pt=threading.Thread(target=p.serve_forever,daemon=True);self.pt.start()
        self.addCleanup(self.pt.join);self.addCleanup(p.server_close);self.addCleanup(p.shutdown)
        cfg=self.engine.state['config'];cfg.update(approval_required=approval,max_external_actions=3)
        cfg['http_test_origins'].append(p.origin)
        if credential:
            cfg['http_credentials']=[{'id':'dedicated','env':'META_SWARM_CRED_FIXTURE','hosts':['127.0.0.1'],'header':'Authorization','scheme':'Bearer'}]
        self.q=self.api.check_deposit_target(self.plan(upload_url=p.origin+'/reserve',credential_id='dedicated' if credential else '',authentication='DEDICATED_CREDENTIAL' if credential else 'ANONYMOUS'))
        self.i=self.api.submit_idea(self.idea(self.q));self.ii=self.i['id']
        size=self.engine.state['exports']['files'][0]['bytes']
        def step(ident,method,url,**kw):
            data=dict(id=ident,method=method,purpose='Perform '+ident+' for reviewed export',url=url,allowed_origins=[p.origin],credential_id='',
                      headers_json='{}',body_json='',sends_export=False,max_body_bytes=0,success_codes=[200],max_age_seconds=0)
            data.update(kw);return data
        self.steps=[step('reserve','POST',p.origin+'/reserve',credential_id='dedicated' if credential else '',body_json=json.dumps({'filename':{'$export':'filename'},'fileSize':{'$export':'bytes'}}),max_body_bytes=2048,success_codes=[201]),
                    step('upload','PUT','{{reserve:/upload/signedUrl}}',headers_json=json.dumps({'$response':'reserve','pointer':'/upload/headers'}),sends_export=True,max_body_bytes=size,max_age_seconds=240),
                    step('finish','POST',p.origin+'/complete/{{reserve:/id}}',credential_id='dedicated' if credential else ''),
                    step('verify','GET','{{finish:/publicUrl}}')]
        recorded=self.api.record_deposit_execution_plan(self.ii,self.steps)
        self.assertEqual(recorded['status'],'READY_FOR_AUDIT')
        self.review=self.for_agent(self.auditor);await self.observe(self.review)
        review=self.review.record_critique(self.ii,'PASS','Primary docs support this exact free bounded sequence and public byte verification')
        self.assertEqual(review['verdict'],'PASS')
        self.executor=self.for_agent(self.prototyper)

    async def test_real_http_roundtrip_private_bindings_and_no_connector(self):
        with patch.dict(os.environ,{'META_SWARM_CRED_FIXTURE':'dedicated-fixture-key'}):
            await self.setup_flow(credential=True)
            result=await self.executor.execute_deposit_plan(self.ii)
        self.assertEqual(result['status'],'COMPLETED');self.assertTrue(self.protocol.finalized)
        self.assertEqual(result['receipt']['sha256'],hashlib.sha256(self.protocol.data).hexdigest())
        self.assertEqual(len(self.engine.state['external_actions']),3)
        self.assertEqual([m for m,*_ in self.protocol.calls],['POST','PUT','POST','GET'])
        self.assertEqual(self.protocol.calls[0][2]['Authorization'],'Bearer dedicated-fixture-key')
        self.assertNotIn('Authorization',self.protocol.calls[1][2]);self.assertNotIn('Authorization',self.protocol.calls[-1][2])
        replay=await self.executor.execute_deposit_plan(self.ii)
        self.assertEqual(replay['id'],result['id']);self.assertEqual(len(self.protocol.calls),4)
        refresh_reports(self.engine.store,self.engine.state)
        for path in [self.run/'checkpoint.json',self.run/'raw/events.jsonl',self.run/'manifest.json',self.run/'SWARM_REPORT.md',*self.executor.workspace.root.rglob('*.bin')]:
            text=path.read_bytes();self.assertNotIn(b'dedicated-fixture-key',text);self.assertNotIn(b'private-signature',text);self.assertNotIn(b'temporary-grant',text)
            self.assertNotIn(b'opaque-path-capability',text);self.assertNotIn(b'opaque-header-capability',text)
        self.assertTrue(self.engine.store.verify()['events'])
        if os.name=='nt':
            for path in (self.run/'private-flow').glob('*.bin'): self.assertNotIn(b'private-signature',path.read_bytes())

    async def test_one_plan_approval_then_resume_without_model(self):
        await self.setup_flow(approval=True)
        result=await self.executor.execute_deposit_plan(self.ii)
        self.assertEqual(result['status'],'AWAITING_APPROVAL');self.assertFalse(self.protocol.calls)
        self.assertEqual(len(self.engine.state['approvals']),1)
        decide(self.engine.store,self.engine.state,result['approval_id'],'approve','Approve local exact sequence')
        self.engine.close();self.engine=Engine(self.run,DemoBackend(),'demo')
        await deposit_execution.resume(self.engine)
        flow=self.engine.state['deposit_executions'][0]
        self.assertEqual(flow['status'],'COMPLETED');self.assertEqual(len(self.engine.state['approvals']),1)
        self.assertEqual(self.engine.state['usage']['requests'],0)

    async def test_pause_resume_skips_completed_reservation_and_reserves_future_capacity(self):
        await self.setup_flow();self.protocol.pause_after_reserve=True
        result=await self.executor.execute_deposit_plan(self.ii)
        self.assertEqual(result['status'],'PAUSED');self.assertEqual(result['completed_steps'],['reserve'])
        self.assertEqual(deposit_execution.lease_totals(self.engine.state)['actions'],2)
        (self.run/'PAUSE.flag').unlink()
        self.engine.close();self.engine=Engine(self.run,DemoBackend(),'demo')
        await deposit_execution.resume(self.engine)
        self.assertEqual(self.engine.state['deposit_executions'][0]['status'],'COMPLETED')
        self.assertEqual(sum(m=='POST' and path=='/reserve' for m,path,*_ in self.protocol.calls),1)

    async def test_unknown_write_is_never_retried_or_finalized(self):
        await self.setup_flow();self.protocol.uncertain=True
        first=await self.executor.execute_deposit_plan(self.ii)
        self.assertEqual(first['status'],'UNKNOWN');self.assertFalse(self.protocol.finalized)
        second=await self.executor.execute_deposit_plan(self.ii)
        self.assertEqual(second['status'],'UNKNOWN');self.assertEqual(len(self.protocol.calls),2)

    async def test_crash_between_http_receipt_and_flow_checkpoint_recovers_exactly_once(self):
        await self.setup_flow();original=self.executor.event
        def crash(kind,data):
            if kind=='deposit_step_completed' and data['step']=='reserve': raise RuntimeError('fixture process interruption')
            return original(kind,data)
        self.executor.event=crash
        with self.assertRaises(RuntimeError): await self.executor.execute_deposit_plan(self.ii)
        self.engine.close();self.engine=Engine(self.run,DemoBackend(),'demo')
        await deposit_execution.resume(self.engine)
        self.assertEqual(self.engine.state['deposit_executions'][0]['status'],'COMPLETED')
        self.assertEqual(len(self.protocol.calls),4)

    async def test_wrong_origin_stops_before_payload(self):
        await self.setup_flow();self.protocol.signed_url='https://gitlab.com/api/files?token=evil'
        result=await self.executor.execute_deposit_plan(self.ii)
        self.assertEqual(result['reason'],'RESPONSE_BINDING_OR_POLICY_FAILED');self.assertEqual(len(self.protocol.calls),1)

    async def test_expired_signed_response_requires_resolution_not_new_reservation(self):
        await self.setup_flow();self.protocol.pause_after_reserve=True
        await self.executor.execute_deposit_plan(self.ii)
        r=self.engine.state['http_requests'][-1];r['finished_at']=(datetime.now(timezone.utc)-timedelta(seconds=500)).isoformat()
        (self.run/'PAUSE.flag').unlink()
        result=await self.executor.execute_deposit_plan(self.ii)
        self.assertEqual(result['reason'],'RESPONSE_CAPABILITY_EXPIRED');self.assertEqual(len(self.protocol.calls),1)

    async def test_action_limit_stops_entire_sequence_before_first_send(self):
        await self.setup_flow();self.engine.state['config']['max_external_actions']=2
        result=await self.executor.execute_deposit_plan(self.ii)
        self.assertEqual(result['reason'],'MAX_EXTERNAL_ACTIONS');self.assertFalse(self.protocol.calls)
        self.assertFalse(self.engine.state['approvals'])

    async def test_hash_failure_is_failed_execution_not_scientific_rejection(self):
        await self.setup_flow();self.protocol.corrupt=True
        result=await self.executor.execute_deposit_plan(self.ii)
        self.assertEqual(result['status'],'FAILED');self.assertEqual(self.executor.idea(self.ii)['status'],'BLOCKED')
        self.assertFalse(self.executor.idea(self.ii).get('completion_receipts'))

    async def test_changed_plan_invalidates_review_and_prevents_unqualified_direct_request(self):
        await self.setup_flow()
        direct=await self.executor.http_request({'url':self.protocol.origin+'/reserve','method':'POST'},self.ii,'Bypass data-only sequence')
        self.assertEqual(direct['reason'],'EXECUTION_SEQUENCE_REQUIRED')
        changed=copy.deepcopy(self.steps);changed[0]['purpose']='Revised reservation description'
        self.api.record_deposit_execution_plan(self.ii,changed)
        result=await self.executor.execute_deposit_plan(self.ii)
        self.assertEqual(result['reason'],'QUALIFIED_PLAN_NEEDS_INDEPENDENT_AUDIT');self.assertFalse(self.protocol.calls)

    async def test_failed_known_http_step_does_not_continue(self):
        await self.setup_flow();self.protocol.put_status=403
        result=await self.executor.execute_deposit_plan(self.ii)
        self.assertEqual(result['status'],'FAILED');self.assertFalse(self.protocol.finalized)
        self.assertFalse(self.engine.state['deposit_executions'][0]['lease_active'])

    @unittest.skipUnless(SDK_AVAILABLE,'SDK required')
    async def test_actual_sdk_typed_plan_and_executor_without_paid_api(self):
        from tests.test_backend import FakeProvider, tool_response, final_response
        from metaweb_swarm.backend import OpenAIBackend
        await self.setup_flow()
        provider=FakeProvider([tool_response('execute_deposit_plan',{'idea_id':self.ii}),final_response()])
        result=await OpenAIBackend(provider).step(self.prototyper,self.engine.prompt(self.prototyper),[],self.executor,self.engine.state['config'])
        self.assertEqual(result['output']['status'],'COMPLETED')
        self.assertEqual(self.engine.state['deposit_executions'][0]['status'],'COMPLETED')

    async def test_plan_validation_rejects_forward_refs_wildcard_and_credential_forwarding(self):
        await self.setup_flow()
        for change in [{'url':'{{finish:/url}}'},{'allowed_origins':['https://*.example.org']},{'credential_id':'unassigned'}]:
            steps=copy.deepcopy(self.steps);steps[0].update(change)
            with self.assertRaises(ValueError): self.api.record_deposit_execution_plan(self.ii,steps)

    async def test_private_vault_tampering_stops_resume(self):
        await self.setup_flow();self.protocol.pause_after_reserve=True
        await self.executor.execute_deposit_plan(self.ii)
        r=self.engine.state['http_requests'][-1];receipt=dict(r['private_response']);receipt['sha256']='0'*64
        with self.assertRaises(ValueError): flow_vault.load(self.run,receipt)

    async def test_operator_cli_executes_without_openai_key_or_model_requests(self):
        import contextlib, io
        from metaweb_swarm.cli import main
        await self.setup_flow(approval=True)
        pending=await self.executor.execute_deposit_plan(self.ii)
        decide(self.engine.store,self.engine.state,pending['approval_id'],'approve','Approve local operator execution')
        self.engine.close()
        output=io.StringIO()
        with patch.dict(os.environ,{'OPENAI_API_KEY':''}),contextlib.redirect_stdout(output):
            code=await asyncio.to_thread(main,['deposit-execute',str(self.run),self.ii])
        self.engine=Engine(self.run,DemoBackend(),'demo')
        self.assertEqual(code,0);self.assertEqual(self.engine.state['deposit_executions'][0]['status'],'COMPLETED')
        self.assertEqual(self.engine.state['usage']['requests'],0)
        self.assertGreater(self.engine.state['active_seconds'],0)

    @unittest.skipUnless(SDK_AVAILABLE,'SDK required')
    async def test_actual_sdk_records_typed_sequence_without_executing_it(self):
        from tests.test_backend import FakeProvider, tool_response, final_response
        from metaweb_swarm.backend import OpenAIBackend
        await self.setup_flow()
        provider=FakeProvider([tool_response('record_deposit_execution_plan',{'idea_id':self.ii,'steps':self.steps}),final_response()])
        await OpenAIBackend(provider).step(self.discovery,self.engine.prompt(self.discovery),[],self.api,self.engine.state['config'])
        self.assertTrue(any(e['kind']=='deposit_execution_plan_recorded' for e in map(json.loads,(self.run/'raw/events.jsonl').read_text(encoding='utf-8').splitlines())))
        self.assertFalse(self.protocol.calls)

    async def test_whole_sequence_http_bytes_and_runtime_limits_precede_side_effects(self):
        await self.setup_flow();cfg=self.engine.state['config'];original=copy.deepcopy(cfg)
        for key,value,reason in [('max_http_requests',len(self.engine.state['http_requests'])+3,'MAX_HTTP_REQUESTS'),
                ('max_external_bytes',self.engine.state['exports']['files'][0]['bytes'],'MAX_EXTERNAL_BYTES'),
                ('max_http_total_bytes',4096,'MAX_HTTP_TOTAL_BYTES'),('max_active_seconds',1,'MAX_ACTIVE_SECONDS')]:
            cfg.clear();cfg.update(copy.deepcopy(original));cfg[key]=value
            if key=='max_active_seconds': self.engine.state['active_seconds']=2
            result=await self.executor.execute_deposit_plan(self.ii)
            self.assertTrue(result['reason'].startswith(reason));self.assertFalse(self.protocol.calls)

    async def test_own_reservation_cannot_be_spent_by_an_unrelated_request_during_pause(self):
        await self.setup_flow();self.protocol.pause_after_reserve=True
        await self.executor.execute_deposit_plan(self.ii)
        (self.run/'PAUSE.flag').unlink()
        self.engine.state['config']['require_deposit_qualification']=False
        self.engine.state['config']['require_independent_http_review']=False
        attempt=await self.executor.http_request({'url':self.protocol.origin+'/unrelated','method':'POST'},self.ii,'Try an unrelated side effect while sequence holds slots')
        self.assertEqual(attempt['reason'],'MAX_EXTERNAL_ACTIONS');self.assertEqual(len(self.protocol.calls),1)

    async def test_local_planner_wakes_after_new_independent_review(self):
        from metaweb_swarm.deposit_handoff import recover
        await self.setup_flow()
        self.executor.record_deposit_execution_plan(self.ii,self.steps)
        self.prototyper.update(status='COMPLETED',rounds=1)
        recover(self.engine)
        self.assertEqual(self.prototyper['status'],'PENDING')

    async def test_static_auth_header_and_literal_secret_url_are_rejected_during_planning(self):
        await self.setup_flow()
        for changes in [{'headers_json':json.dumps({'Authorization':'Bearer unassigned'})},{'url':self.protocol.origin+'/reserve?token=plaintext'}]:
            steps=copy.deepcopy(self.steps);steps[0].update(changes)
            with self.assertRaises(ValueError): self.api.record_deposit_execution_plan(self.ii,steps)

