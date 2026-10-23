"""Fresh report facts and context across handoffs; no paid inference or Docker."""
import copy
import json
import unittest
from metaweb_swarm.backend import OpenAIBackend
from metaweb_swarm.deposit_handoff import report_revision
from metaweb_swarm.research_tasks import prepare_task_context,complete
from metaweb_swarm.research_report import current
from tests import test_prototype_review as fixture
from tests.test_backend import SDK_AVAILABLE,FakeProvider,tool_response,final_response


class ReporterRefreshTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.PrototypeScopeTests.setUp
    tearDown=fixture.PrototypeScopeTests.tearDown
    for_agent=fixture.PrototypeScopeTests.for_agent
    prepare=fixture.PrototypeScopeTests.prepare

    def old_report(self):
        self.prepare();api=self.for_agent(self.reporter)
        api.get_research_task()
        receipt=api.record_research_report([self.idea['id']],
            'STALE_REPORT_SENTINEL: no successful acceptance result exists yet.',
            ['No successful acceptance at the time of this historical fixture.'])
        self.assertEqual(receipt['status'],'COMPLETED')
        self.reporter.update(rounds=1,summary=receipt['conclusion'],
            history=[{'role':'assistant','content':'STALE_MODEL_CONTEXT: previous report already finished'}])
        return api

    def test_reporter_revision_archives_old_context_and_preserves_receipt(self):
        api=self.old_report();previous=copy.deepcopy(self.reporter['research_report_receipt'])
        prepare_task_context(self.engine,self.reporter,api.workspace)
        self.reporter['history']=[{'role':'assistant','content':'Old report based on no acceptance'}]
        self.reporter['rounds']=2
        self.engine.state['coding_validations']=[{'id':'VALID-fixture','passed':True}]
        prepare_task_context(self.engine,self.reporter,api.workspace)
        self.assertEqual(self.reporter['history'],[])
        self.assertIn('CURRENT_RUN_REPORT',self.reporter['active_task_key'])
        self.assertEqual(self.reporter['research_report_receipt'],previous)
        self.assertEqual(self.reporter['research_report_revision'],report_revision(self.engine.state))
        self.assertFalse(current(self.engine.state,self.reporter))
        self.assertTrue((self.run/'raw'/f"{self.reporter['id']}-task-history-before-round-2.json").is_file())

    def test_report_fingerprint_tracks_new_evidence_but_not_reporter_activity(self):
        self.old_report();state=self.engine.state;base=report_revision(state)
        for section in ['coding_validations','coding_commands','package_installations','prototype_reviews','external_actions','approvals']:
            other=copy.deepcopy(state);other.setdefault(section,[]).append({'id':'new-receipt','status':'COMPLETED'})
            self.assertNotEqual(report_revision(other),base,section)
        self.reporter.update(rounds=99,summary='Current report being written',history=[])
        state['active_seconds']=123
        self.assertEqual(report_revision(state),base)

    def test_dispatch_prompt_contains_current_counts_and_accepts_direct_report(self):
        api=self.old_report();self.engine.state['coding_validations']=[{'id':'VALID-new','passed':True}]
        prepare_task_context(self.engine,self.reporter,api.workspace)
        prompt=self.engine.prompt(self.reporter)
        self.assertIn('"coding_acceptance_passes":1',prompt)
        self.assertNotIn('STALE_REPORT_SENTINEL',prompt)
        self.assertLess(len(prompt),self.engine.state['config']['prompt_chars'])
        receipt=api.record_research_report([self.idea['id']],
            'The current host facts contain one successful acceptance validation; no executed test is claimed by this unit fixture.',
            ['Fixture checks report freshness only, not scientific prototype correctness.'])
        self.assertEqual(receipt['status'],'COMPLETED')
        self.assertEqual(receipt['facts']['coding_acceptance_passes'],1)
        self.assertTrue(current(self.engine.state,self.reporter))
        result=complete(self.engine.state,self.reporter,{'status':'COMPLETED','unexplored_leads':[],'handoff_leads':[]})
        self.assertEqual(result['status'],'COMPLETED')

    def test_generated_report_labels_stale_synthesis_instead_of_presenting_it_as_current(self):
        self.old_report();self.engine.state['coding_validations']=[{'id':'VALID-new','passed':True}]
        from metaweb_swarm.reporting import generate_reports
        generate_reports(self.run,self.engine.state)
        overview=(self.run/'SWARM_REPORT.md').read_text(encoding='utf-8').split('## Skutečné aktivity')[0]
        self.assertIn('Syntéza reportovacího agenta je neaktuální',overview)
        self.assertNotIn('STALE_REPORT_SENTINEL',overview)

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_actual_sdk_reporter_finishes_after_new_results_without_research_or_experiments(self):
        self.old_report();self.engine.state['coding_validations']=[{'id':'VALID-new','passed':True}]
        provider=FakeProvider([tool_response('record_research_report',{
            'idea_ids':[self.idea['id']],
            'conclusion':'The current host packet contains one passed acceptance validation. No full mechanism or external deposit is established by this fixture.',
            'limitations':['The provider is scripted; no live inference or experiment occurs in this test.']}),final_response()])
        self.engine.backend=OpenAIBackend(provider)
        self.reporter['status']='PENDING'
        await self.engine.step(self.reporter)
        self.assertEqual(self.reporter['status'],'COMPLETED')
        self.assertTrue(current(self.engine.state,self.reporter))
        self.assertEqual(self.reporter['research_report_receipt']['facts']['coding_acceptance_passes'],1)
        self.assertNotIn('STALE_MODEL_CONTEXT',str(provider.model.calls))
        self.assertEqual(len(provider.model.calls),2)
        self.assertFalse(self.engine.state['experiments'])
        self.assertFalse(self.engine.state['external_actions'])
