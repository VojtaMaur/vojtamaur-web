import copy
import json
import unittest
from metaweb_swarm.review_tasks import assign,current
from metaweb_swarm.review_contract import complete_review
from metaweb_swarm.deposit_handoff import recover
from metaweb_swarm.engine import Engine
from metaweb_swarm.demo import DemoBackend
from tests import test_discovery_leads as fixture
from tests.test_backend import SDK_AVAILABLE


class ReviewTaskTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.LeadTests.setUp
    tearDown=fixture.LeadTests.tearDown
    for_agent=fixture.LeadTests.for_agent
    documented=fixture.LeadTests.documented

    async def prepare(self,two=False):
        self.lead=await self.documented()
        if two: await self.api.read_document(self.origin+'/terms','Read primary retention terms')
        self.auditor=self.engine.state['agents'][1];self.review=self.for_agent(self.auditor)
        assign(self.engine,self.auditor)

    def finish(self):
        return complete_review(self.engine.state,self.auditor,{'status':'COMPLETED'},
            {'status':'COMPLETED','unexplored_leads':[],'handoff_leads':[]})[0]

    async def test_exact_packet_rejects_unrelated_url_without_network_or_fake_review(self):
        await self.prepare(two=True)
        task=self.review.get_review_task()
        self.assertEqual(task['target_id'],self.lead['id']);self.assertEqual(task['stage'],'READ_DOCUMENTS')
        self.assertEqual([d['url'] for d in task['missing_documents']],[self.origin+'/docs',self.origin+'/terms'])
        before=list(self.server.calls)
        result=await self.review.read_document(self.origin+'/other-service','Try unrelated discovery source')
        self.assertEqual(result['reason'],'ASSIGNED_REVIEW_DOCUMENT_REQUIRED');self.assertEqual(before,self.server.calls)
        result=self.review.record_lead_review(self.lead['id'],'NEEDS_EVIDENCE','No upload protocol observed',
            'Discovery should find the actual upload protocol','',[self.origin+'/docs'])
        self.assertEqual(result['reason'],'ASSIGNED_LEAD_REVIEW_REQUIRED')
        self.assertNotIn('review',self.lead)

    async def test_partial_own_read_requires_remaining_ranges_and_receipt_completes_role(self):
        await self.prepare(two=True)
        await self.review.read_document(self.origin+'/docs','Independently read first portion',limit=20)
        task=self.review.get_review_task();self.assertEqual(task['stage'],'READ_DOCUMENTS')
        self.assertEqual(task['missing_documents'][0]['offset'],20)
        for _ in range(4):
            task=self.review.get_review_task()
            if task['stage']=='TRIAGE': break
            doc=task['missing_documents'][0]
            await self.review.read_document(doc['url'],'Read assigned primary document range',doc['offset'],doc['limit'])
        self.assertEqual(self.review.get_review_task()['stage'],'TRIAGE')
        self.review.record_lead_review(self.lead['id'],'NEEDS_EVIDENCE','Upload endpoint remains undocumented',
            'Discovery needs actual protocol before qualification','',[self.origin+'/docs',self.origin+'/terms'])
        self.assertEqual(self.review.get_review_task()['stage'],'DONE')
        self.assertEqual(self.finish()['status'],'COMPLETED')
        self.auditor.update(status='COMPLETED',rounds=1)
        recover(self.engine);self.assertEqual(self.auditor['status'],'COMPLETED')
        self.assertFalse(self.engine.state['ideas']);self.assertFalse(self.engine.state['approvals'])

    async def test_one_packet_at_a_time_and_changed_revision_needs_fresh_assignment(self):
        await self.prepare()
        self.api.record_discovery_lead(self.lead['id'],'New evidence question changed this lead.',
            ['Does the actual API accept this file type?'],'Independent review of the changed question.')
        self.assertEqual(self.review.get_review_task()['stage'],'STALE')
        result=self.review.record_lead_review(self.lead['id'],'QUALIFY','Enough protocol evidence claimed',
            'Discovery should qualify this source','',[self.origin+'/docs'])
        self.assertEqual(result['status'],'DEFERRED')
        assign(self.engine,self.auditor)
        self.assertEqual(self.review.get_review_task()['stage'],'READ_DOCUMENTS')

    async def test_failed_source_is_technical_block_not_rejection_or_retry_loop(self):
        await self.prepare()
        original=self.server.RequestHandlerClass
        class Unavailable(original):
            def do_GET(inner):
                if inner.path!='/404': return super().do_GET()
                inner.server.calls.append(inner.path)
                inner.send_response(404);inner.send_header('Content-Type','text/plain');inner.end_headers();inner.wfile.write(b'Not found')
        self.server.RequestHandlerClass=Unavailable
        self.lead['documents'][0]['url']=self.origin+'/404'
        assign(self.engine,self.auditor)
        result=await self.review.read_document(self.origin+'/404','Read assigned source which is unavailable')
        self.assertEqual(result['review_task']['stage'],'DOCUMENT_BLOCKED')
        output=self.finish();self.assertEqual(output['status'],'BLOCKED')
        self.auditor.update(output,rounds=1)
        recover(self.engine);self.assertEqual(self.auditor['status'],'BLOCKED')
        self.assertNotIn('review',self.lead);self.assertFalse(self.engine.state['ideas'])
        self.assertFalse(self.engine.state['external_actions'])

    async def test_checkpoint_preserves_packet_and_partial_document_coverage(self):
        await self.prepare()
        await self.review.read_document(self.origin+'/docs','Read first packet range',limit=20)
        before=self.review.get_review_task()
        self.engine.close();self.engine=Engine(self.run,DemoBackend(),'demo')
        self.auditor=self.engine.state['agents'][1];self.review=self.for_agent(self.auditor)
        self.assertEqual(self.review.get_review_task(),before)
        self.engine.store.verify()

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_sdk_reads_both_sources_then_records_triage_in_one_bounded_round(self):
        import agents
        from metaweb_swarm.backend import OpenAIBackend,_make_sdk_tools
        from tests.test_backend import FakeProvider,tool_response,final_response,FINAL
        await self.prepare(two=True)
        tools,_=_make_sdk_tools(agents,self.review);names={t.name for t in tools}
        self.assertEqual(names,{'get_review_task','read_document','record_lead_review','note'})
        self.assertNotIn('record_critique',names)
        schema=next(t for t in tools if t.name=='read_document').params_json_schema
        self.assertEqual(schema['properties']['url']['enum'],[self.origin+'/docs',self.origin+'/terms'])
        responses=[tool_response('get_review_task',{},ident='packet')]
        for path in ('/docs','/terms'):
            responses.append(tool_response('read_document',dict(url=self.origin+path,purpose='Independently read assigned primary source',offset=0,limit=16000),ident=path))
        responses += [tool_response('record_lead_review',dict(lead_id=self.lead['id'],disposition='NEEDS_EVIDENCE',
            reason='Upload protocol remains undocumented',next_action='Discovery should find actual upload and authentication protocol',
            failure_fact='',source_urls=[self.origin+'/docs',self.origin+'/terms']),ident='triage'),final_response(output=FINAL)]
        provider=FakeProvider(responses);self.engine.backend=OpenAIBackend(provider)
        await self.engine.step(self.auditor)
        self.assertEqual(self.auditor['status'],'COMPLETED')
        self.assertEqual(self.lead['review']['agent_id'],self.auditor['id'])
        self.assertEqual(self.server.calls,['/docs','/terms','/docs','/terms'])
        self.assertFalse(self.engine.state['approvals']);self.assertFalse(self.engine.state['external_actions'])
        self.engine.store.verify()

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_critique_returns_only_for_a_real_qualified_idea(self):
        import agents
        from metaweb_swarm.backend import _make_sdk_tools
        from tests.test_planning_recovery import PlanningTests
        await PlanningTests.candidate(self)
        self.auditor=self.engine.state['agents'][1];self.review=self.for_agent(self.auditor)
        assign(self.engine,self.auditor)
        self.assertEqual(self.review.get_review_task()['kind'],'IDEA')
        tools,_=_make_sdk_tools(agents,self.review)
        self.assertIn('record_critique',{t.name for t in tools})
