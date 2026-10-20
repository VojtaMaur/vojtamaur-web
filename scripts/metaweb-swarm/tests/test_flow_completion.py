"""Fix observed delegation, generated-output, pricing and report handoffs."""
import copy
import unittest
from unittest.mock import patch
from metaweb_swarm.baseline import delegation_rejection, owner_rejection
from metaweb_swarm.research_tasks import assign, complete, local_candidates, recover
from metaweb_swarm.review_tasks import assign as review_assign
from tests import test_research_handoffs as fixture
from tests.test_backend import SDK_AVAILABLE, FINAL


class FlowCompletionTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixture.ResearchHandoffTests.setUp
    tearDown = fixture.ResearchHandoffTests.tearDown
    for_agent = fixture.ResearchHandoffTests.for_agent
    prepare = fixture.ResearchHandoffTests.prepare
    normalized = fixture.ResearchHandoffTests.normalized

    def setup_plan(self, output='outputs/result.bin', negative='Corrupted data must fail integrity verification'):
        self.local.materialize_export('build.epub','exports/input.epub')
        self.local.write_file('prototype/test.py', 'assert recover(encode(payload)) == payload\n')
        return self.local.record_prototype_plan(self.idea['id'],'Recover exact export bytes through the proposed encoding',
            'exports/input.epub','prototype/test.py',[output], 'Recovered payload must equal the original bytes',
            negative, 'SUBCOMPONENT','Remote carrier custody, publication and retention remain untested')

    async def execution(self, write=True):
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            def run(*args):
                if write: self.local.workspace.write_file('outputs/result.bin',b'generated simulated encoded export')
                return {'status':'COMPLETED','returncode':0,'output':'simulated assertion execution, not real model/Docker proof'}
            docker.return_value.run.side_effect=run
            result=await self.local.run_experiment(['python','prototype/test.py'],self.idea['id'])
            self.assertEqual(docker.return_value.run.call_count,1)
            return result

    def test_delegation_exclusions_do_not_become_positive_prohibited_tasks(self):
        rules=[{'id':'OWNER-001','aliases':['WACZ','WARCZ'],'reason':'Owner does not want this direction'}]
        request={'role':'External discovery specialist','mission':'Explore unrelated carriers. Do not propose WACZ/WARCZ or recurring-payment-dependent options.',
                 'question':'Which independent carrier stores the captured export?'}
        self.assertIsNone(delegation_rejection(request,rules))
        for field, text in [('question','Prototype WACZ for this export'),
                            ('mission','Do not propose WACZ unless necessary. Implement WARCZ now.'),
                            ('unique_expertise','WACZ encoding'),('role','WACZ specialist')]:
            self.assertEqual(delegation_rejection(dict(request,**{field:text}),rules)['id'],'OWNER-001')
        self.assertIsNotNone(owner_rejection({'title':'Use WACZ as a carrier'},rules))

    async def test_successful_planned_outputs_need_only_one_execution_and_record_test(self):
        self.prepare()
        self.review.record_critique(self.idea['id'],'REVISE','The claimed format still needs a real executed prototype and independent scope review')
        self.setup_plan()
        result=await self.execution()
        self.assertEqual(result['prototype_readiness']['status'],'READY_FOR_TEST_RECEIPT')
        self.assertIn('outputs/result.bin',result['generated_outputs'])
        self.assertFalse(self.idea['artifact_checks'])
        receipt=self.local.record_test(self.idea['id'],result['experiment_id'],'Generated specimen captured with linked execution')
        self.assertEqual(len(self.engine.state['tests']),1)
        self.assertTrue(receipt['prototype_review_required'])
        self.assertFalse(self.idea['prototype_tested'])
        self.assertEqual(len(self.engine.state['experiments']),1)
        review_assign(self.engine,self.auditor)
        self.assertEqual(self.review.get_review_task()['kind'],'PROTOTYPE_TEST')

    async def test_missing_output_is_concrete_repair_then_corrected_script_succeeds(self):
        self.prepare()
        self.setup_plan()
        first=await self.execution(write=False)
        missing=first['prototype_readiness']
        self.assertEqual(missing['reason'],'PROTOTYPE_OUTPUTS_REQUIRED')
        self.assertEqual(missing['details']['missing_paths'],['outputs/result.bin'])
        self.assertEqual(self.local.record_test(self.idea['id'],first['experiment_id'],'Cannot certify stdout without specimen')['reason'],'PROTOTYPE_OUTPUTS_REQUIRED')
        # A false bookkeeping blocker does not close the required script repair.
        refused=self.local.record_research_blocker(self.idea['id'],'Host bookkeeping requires a generated output I have not written')
        self.assertEqual(refused['status'],'DEFERRED')
        self.assertFalse(self.proto.get('research_blockers'))
        self.local.write_file('prototype/test.py','write_encoded_specimen(); assert decode(specimen)==payload\n')
        plan=self.local.record_prototype_plan(self.idea['id'],'Recover actual retained bytes and reject corruption',
            'exports/input.epub','prototype/test.py',['outputs/result.bin'],
            'Recover complete original bytes','Reject deliberately altered encoded bytes','SUBCOMPONENT','Remote carrier behavior remains untested')
        self.assertIn('id',plan)
        second=await self.execution()
        receipt=self.local.record_test(self.idea['id'],second['experiment_id'],'Corrected planned output execution captured')
        self.assertIn('id',receipt)

    async def test_prewritten_placeholder_is_not_a_generated_specimen(self):
        self.prepare()
        self.setup_plan()
        self.local.workspace.write_file('outputs/result.bin',b'placeholder written by model before execution')
        result=await self.execution(write=False)
        self.assertEqual(result['prototype_readiness']['details']['unchanged_outputs'],['outputs/result.bin'])
        self.assertEqual(self.local.record_test(self.idea['id'],result['experiment_id'],'Only stdout; output unchanged')['status'],'DEFERRED')
        self.assertFalse(self.engine.state['tests'])

    async def test_modified_captured_specimen_never_receives_test_receipt(self):
        self.prepare()
        self.setup_plan()
        result=await self.execution()
        self.local.workspace.write_file('outputs/result.bin',b'modified after execution')
        self.assertEqual(self.local.record_test(self.idea['id'],result['experiment_id'],'Changed outputs cannot use old execution')['reason'],'EXECUTED_ARTIFACT_CHANGED')
        self.assertFalse(self.engine.state['tests'])

    def test_limitations_are_not_a_negative_test(self):
        self.prepare()
        result=self.setup_plan(negative='The script does not test any external publication, retention or pricing behavior')
        self.assertEqual(result['reason'],'NEGATIVE_TEST_REQUIRED')
        self.assertNotIn('prototype_plans',self.proto)

    async def test_unknown_pricing_retained_for_research_but_not_prototyped(self):
        self.prepare()
        config=copy.deepcopy(self.engine.state['config'])
        self.idea['payment']='UNKNOWN'
        assign(self.engine,self.proto)
        self.assertEqual(self.proto['research_assignment']['kind'],'NONE')
        self.assertEqual(local_candidates(self.engine.state,self.proto),[])
        self.proto['work_kind']='DISCOVERY'
        result=await self.local.run_experiment(['python','prototype/test.py'],self.idea['id'])
        self.assertEqual(result['reason'],'PAYMENT_INDEPENDENCE_REQUIRED')
        self.assertFalse(self.engine.state['experiments'])
        self.assertNotEqual(self.idea['status'],'REJECTED')
        self.assertEqual(config,self.engine.state['config'])
        self.idea.update(payment='ONE_TIME',requires_ongoing_payments=False)
        self.proto['work_kind']='LOCAL'
        self.assertIn(self.idea,local_candidates(self.engine.state,self.proto))

    def test_recorded_report_completes_reporter_with_unfinished_ideas_and_no_tests(self):
        self.prepare(two=True)
        report=self.for_agent(self.reporter)
        self.assertEqual(report.record_research_report([self.idea['id'],self.other['id']],
            'Both current ideas remain unverified; no execution test or deposit has been recorded.',[])['reason'],'CURRENT_REPORT_PACKET_REQUIRED')
        report.get_research_task()
        self.assertEqual(report.record_research_report([self.idea['id']],
            'Only one of the current ideas is described in this incomplete report.',[])['reason'],'ALL_CURRENT_IDEAS_REQUIRED')
        receipt=report.record_research_report([self.idea['id'],self.other['id']],
            'Both ideas remain hypotheses. No recorded tests or deposits; further research is a handoff.',
            ['No host-verified storage or independent prototype assessment'])
        output=complete(self.engine.state,self.reporter,dict(self.normalized(),status='CONTINUE',unexplored_leads=['Research future storage providers']))
        self.assertEqual(output['status'],'COMPLETED')
        self.assertIn('Research future storage providers',output['handoff_leads'])
        self.assertEqual(receipt['facts']['recorded_tests'],0)
        self.assertNotEqual(self.idea['status'],'COMPLETED')
        self.reporter.update(output,rounds=1)
        self.engine.state['experiments'].append({'experiment_id':'future-evidence','idea_id':self.idea['id']})
        recover(self.engine)
        self.assertEqual(self.reporter['status'],'PENDING')

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_sdk_reporter_finishes_without_requiring_a_successful_preservation(self):
        import agents
        from metaweb_swarm.backend import OpenAIBackend,_make_sdk_tools
        from tests.test_backend import FakeProvider,tool_response,final_response
        self.prepare()
        names={t.name for t in _make_sdk_tools(agents,self.for_agent(self.reporter))[0]}
        self.assertIn('record_research_report',names)
        self.assertNotIn('record_research_report',{t.name for t in _make_sdk_tools(agents,self.local)[0]})
        self.engine.backend=OpenAIBackend(FakeProvider([
            tool_response('get_research_task',{},ident='report-read'),
            tool_response('record_research_report',{'idea_ids':[self.idea['id']],
                'conclusion':'The current candidate remains unverified; zero recorded tests and zero deposits.',
                'limitations':['Local mechanism and external retention remain unverified']},ident='report-finish'),
            final_response(output=dict(FINAL,status='CONTINUE',unexplored_leads=['Research candidate later']))]))
        await self.engine.step(self.reporter)
        self.assertEqual(self.reporter['status'],'COMPLETED')
        self.assertFalse(self.engine.state['tests'])
        self.assertFalse(self.engine.state['external_actions'])
