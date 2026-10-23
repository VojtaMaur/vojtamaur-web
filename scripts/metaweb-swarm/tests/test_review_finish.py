"""Actual SDK dispatch and queue relevance, without paid inference."""
import copy
import unittest
from metaweb_swarm.review_dispatch import action,schedule
from metaweb_swarm.research_tasks import local_candidates,revision
from metaweb_swarm.prototype_focus import plan_issue
from metaweb_swarm.backend import OpenAIBackend,BackendLimit
from tests import test_prototype_review as fixture
from tests import test_evidence_contract as outputs
from tests.test_backend import SDK_AVAILABLE,FINAL

class ReviewFinishTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.PrototypeScopeTests.setUp
    tearDown=fixture.PrototypeScopeTests.tearDown
    for_agent=fixture.PrototypeScopeTests.for_agent
    prepare=fixture.PrototypeScopeTests.prepare
    plan=fixture.PrototypeScopeTests.plan
    artifacts=fixture.PrototypeScopeTests.artifacts
    executed=fixture.PrototypeScopeTests.executed
    evidence=fixture.PrototypeScopeTests.evidence
    with_report=outputs.EvidenceContractTests.with_report

    async def test_next_action_pages_remaining_output_then_requires_verdict(self):
        t=await self.with_report('round_trip=True\n'+'x'*30000)
        self.evidence(t)
        self.auditor['prototype_artifact_reads'][t['id']]['prototype/report.txt']=[[0,12000]]
        required=action(self.review)
        self.assertEqual(required['tool'],'read_test_artifact')
        self.assertEqual(required['arguments'],{'test_id':t['id'],'path':'prototype/report.txt','offset':12000,'limit':16000})
        self.review.read_test_artifact(**required['arguments'])
        required=action(self.review)
        self.assertEqual(required['arguments']['offset'],28000)
        self.review.read_test_artifact(**required['arguments'])
        self.assertEqual(action(self.review)['tool'],'get_prototype_review_facts')
        self.review.get_prototype_review_facts(t['id'])
        self.assertEqual(action(self.review)['tool'],'review_prototype_test')
        self.review.review_prototype_test(t['id'],'REVISE','Output assertions do not yet prove the complete mechanism',
            observed_recovery='MATCHES_INPUT',recovered_path='prototype/recovered.bin',review_basis='LOCAL_DEFECT')
        self.assertIsNone(action(self.review))

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_real_sdk_forces_reads_then_verdict_after_tool_choice_reset(self):
        from tests.test_backend import FakeProvider,tool_response,final_response
        t=await self.executed()
        calls=[tool_response('read_test_artifact',{'test_id':t['id'],'path':a['path'],'offset':0,'limit':16000},ident=f'read-{n}') for n,a in enumerate(t['artifacts'])]
        calls+=[tool_response('get_prototype_review_facts',{'test_id':t['id']},ident='facts'),tool_response('review_prototype_test',{'test_id':t['id'],'verdict':'REVISE',
            'reason':'The actual script still needs a mechanism-specific test, retain the hypothesis',
            'positive_refs':[],'negative_refs':[]},ident='stored-review'),final_response()]
        provider=FakeProvider(calls)
        self.engine.backend=OpenAIBackend(provider)
        await self.engine.step(self.auditor)
        choices=[]
        for args,kwargs in provider.model.calls:
            setting=kwargs.get('model_settings',args[2] if len(args)>2 else None)
            choices.append(setting.tool_choice)
            system=kwargs.get('system_instructions',args[0] if args else '')
            if setting.tool_choice: self.assertIn('HOST REVIEW ACTION',system)
        self.assertEqual(choices,['read_test_artifact']*len(t['artifacts'])+['get_prototype_review_facts','review_prototype_test',None])
        self.assertEqual(t['prototype_review']['verdict'],'REVISE')
        self.assertNotEqual(self.idea['status'],'REJECTED')
        self.assertFalse(self.engine.state['external_actions'])
        self.assertTrue(self.engine.state['budget_settlements'])

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_forced_review_still_obeys_token_budget_before_model(self):
        from tests.test_backend import FakeProvider
        await self.executed()
        self.engine.state['usage']['total_tokens']=self.engine.state['config']['max_total_tokens']
        provider=FakeProvider([])
        with self.assertRaises(BackendLimit):
            await OpenAIBackend(provider).step(self.auditor,'Review current test',[],self.review,self.engine.state['config'])
        self.assertEqual(provider.model.calls,[])

    def test_focus_defer_retains_idea_without_dispatching_placeholder(self):
        self.prepare()
        self.engine.state['config']['require_prototype_focus']=True
        result=self.review.record_critique(self.idea['id'],'REVISE','This institutional service has no verified deposit or retrieval protocol',
            local_test_scope='DEFER',local_test_goal='Read concrete institutional eligibility and repository deposit/download documentation first')
        self.assertIn('prototype_focus',result)
        self.assertEqual(local_candidates(self.engine.state,self.proto),[])
        self.assertNotEqual(self.idea['status'],'REJECTED')
        self.assertEqual(plan_issue(self.local,self.idea,'FULL_MECHANISM')['reason'],'CURRENT_MECHANISM_TEST_FOCUS_REQUIRED')

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_sdk_critique_stores_selected_mechanism_focus(self):
        import agents,json
        from agents.tool_context import ToolContext
        from metaweb_swarm.backend import _make_sdk_tools
        self.prepare()
        self.engine.state['config']['require_prototype_focus']=True
        tool=next(t for t in _make_sdk_tools(agents,self.review)[0] if t.name=='record_critique')
        args=json.dumps({'idea_id':self.idea['id'],'verdict':'REVISE','reason':'Exercise the actual encoded object rather than copying input fields',
            'local_test_scope':'SUBCOMPONENT','local_test_goal':'Encode a real specimen, decode that specimen, verify recovery and reject altered bytes'})
        result=json.loads(await tool.on_invoke_tool(ToolContext(context=None,tool_name=tool.name,tool_call_id='focus-fixture',tool_arguments=args),args))
        self.assertEqual(result['prototype_focus']['scope'],'SUBCOMPONENT')
        self.assertEqual(self.idea['prototype_focus']['agent_id'],self.auditor['id'])

    def test_focus_selects_real_inverse_and_prevents_scope_inflation(self):
        self.prepare()
        self.engine.state['config']['require_prototype_focus']=True
        result=self.review.record_critique(self.idea['id'],'REVISE','Test a documented source-metadata extraction component first',
            local_test_scope='SUBCOMPONENT',local_test_goal='Generate SVG metadata, parse XML, extract the embedded payload and reject malformed XML')
        self.assertIn('prototype_focus',result)
        self.assertEqual([i['id'] for i in local_candidates(self.engine.state,self.proto)],[self.idea['id']])
        self.assertEqual(plan_issue(self.local,self.idea,'FULL_MECHANISM')['reason'],'FOCUS_SCOPE_REQUIRED')
        self.assertIsNone(plan_issue(self.local,self.idea,'SUBCOMPONENT'))
        self.idea['mechanism']='Changed claim requiring new relevance assessment'
        self.assertEqual(local_candidates(self.engine.state,self.proto),[])

    def test_required_focus_does_not_silently_store_incomplete_critique(self):
        self.prepare()
        self.engine.state['config']['require_prototype_focus']=True
        result=self.review.record_critique(self.idea['id'],'REVISE','No actual carrier or format test has been selected')
        self.assertEqual(result['reason'],'MECHANISM_TEST_FOCUS_REQUIRED')
        self.assertEqual(self.engine.state['critiques'],[])

    async def test_scheduler_closes_recorded_test_before_next_local_experiment(self):
        await self.executed()
        self.auditor.update(status='PENDING',rounds=4)
        self.proto.update(status='PENDING',rounds=1)
        self.reporter.update(status='PENDING',rounds=0)
        batch=schedule(self.engine.state,[self.proto,self.reporter,self.auditor],7,1)
        self.assertEqual(batch,[self.auditor])
        self.assertEqual(schedule(self.engine.state,[self.proto,self.reporter,self.auditor],1,1),[self.reporter])

    def test_review_queue_is_reserved_before_another_discovery_round(self):
        self.prepare(two=True)
        discovery=copy.deepcopy(self.agent)
        discovery.update(status='PENDING',rounds=3,phase=1)
        self.auditor.update(status='PENDING',rounds=0)
        self.reporter.update(status='PENDING',rounds=0)
        self.assertEqual(schedule(self.engine.state,[discovery,self.auditor,self.reporter],3,1),[self.auditor])

    async def test_report_receipt_counts_pending_tests_instead_of_confirming_coverage(self):
        await self.executed()
        reporter=self.for_agent(self.reporter)
        reporter.get_research_task()
        result=reporter.record_research_report([self.idea['id']],
            'One execution receipt is pending independent review; no certified mechanism coverage',[])
        self.assertEqual(result['facts']['pending_test_reviews'],1)
        self.assertEqual(result['facts']['full_mechanism_reviews'],0)
