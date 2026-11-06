import asyncio,copy,json,tempfile,unittest
from pathlib import Path
from metaweb_swarm.engine import Engine,ToolAPI,initialize
from metaweb_swarm.config import load_config,PACKAGE_ROOT
from metaweb_swarm.brainstorm_portfolio import record
from metaweb_swarm.portfolio_workflow import prepare,pending,prompt
from metaweb_swarm.backend import OpenAIBackend
from tests.test_backend import FakeProvider,final_response,FINAL

class PortfolioWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name);project=root/'project';project.mkdir()
        self.path=initialize(project,root/'runs',load_config(PACKAGE_ROOT/'config.research.json'))
        self.engine=Engine(self.path,None,'openai')
        self.discovery=next(a for a in self.engine.state['agents'] if a['work_kind']=='DISCOVERY')
        for n in range(32):record(ToolAPI(self.engine,self.discovery,None),f'Direction {n}',f'Preservation mechanism {n}',['Capacity unknown'])
    def tearDown(self):self.engine.close();self.tmp.cleanup()

    async def test_32_sketches_reach_two_independent_critiques_and_one_request_report(self):
        reviewers=[a for a in self.engine.state['agents'] if a['work_kind']=='REVIEW']
        calls=0
        for agent in reviewers:
            while pending(self.engine.state,agent):
                prepare(self.engine.state,agent)
                output=dict(FINAL,assessments=[{'hypothesis_id':ident,'verdict':'NEEDS_EVIDENCE','reason':'Capacity is not established.',
                    'unknowns':['Capacity'],'next_action':'Read provider terms.','duplicate_of':''} for ident in agent['portfolio_task']['ids']])
                provider=FakeProvider([final_response(output=output)]);self.engine.backend=OpenAIBackend(provider)
                await self.engine.step(agent);calls+=len(provider.model.calls)
                self.assertNotEqual(agent['status'],'BLOCKED',agent.get('reason_for_stopping'))
                self.assertEqual(provider.model.calls[0][1]['tools'],[])
            self.assertEqual(agent['status'],'COMPLETED');self.assertEqual(agent['rounds'],6)
        self.assertEqual(len(self.engine.state['hypothesis_reviews']),64)
        reporter=next(a for a in self.engine.state['agents'] if a['work_kind']=='SYNTHESIS')
        provider=FakeProvider([final_response(output=dict(FINAL,summary='All 32 retained directions remain preliminary; validation is handed to the human.',assessments=[],covered_hypothesis_ids=[h['id'] for h in self.engine.state['brainstorm_hypotheses']]))])
        self.engine.backend=OpenAIBackend(provider);await self.engine.step(reporter)
        self.assertEqual(reporter['status'],'COMPLETED',reporter.get('reason_for_stopping'))
        self.assertEqual(len(provider.model.calls),1);self.assertEqual(calls,12)
        self.assertEqual(reporter['research_report_receipt']['idea_ids'],[])
        self.assertFalse(self.engine.state['ideas']);self.assertFalse(self.engine.state['external_actions'])
        self.engine.store.verify()

    async def test_invalid_partial_judgment_never_marks_batch_reviewed(self):
        agent=next(a for a in self.engine.state['agents'] if a['work_kind']=='REVIEW')
        self.engine.backend=OpenAIBackend(FakeProvider([final_response(output=dict(FINAL,assessments=[]))]))
        await self.engine.step(agent)
        self.assertEqual(agent['status'],'BLOCKED');self.assertFalse(self.engine.state.get('hypothesis_reviews'))

    async def test_synthesis_missing_coverage_does_not_receive_completion_receipt(self):
        agent=next(a for a in self.engine.state['agents'] if a['work_kind']=='SYNTHESIS')
        self.engine.backend=OpenAIBackend(FakeProvider([final_response(output=dict(FINAL,assessments=[],covered_hypothesis_ids=[]))]))
        await self.engine.step(agent)
        self.assertEqual(agent['status'],'BLOCKED')
        self.assertFalse(agent.get('research_report_receipt'))

    async def test_scheduler_dispatches_portfolio_until_critique_then_closes_report(self):
        state=self.engine.state
        for agent in state['agents']:
            if agent['work_kind'] not in {'REVIEW','SYNTHESIS'}:agent['status']='COMPLETED'
        class Backend:
            async def step(inner,agent,prompt,history,api,config):
                task=agent['portfolio_task'];assessments=[]
                for ident in task.get('ids',[]):assessments.append({'hypothesis_id':ident,'verdict':'NEEDS_EVIDENCE',
                    'reason':'Need capacity evidence','unknowns':['Capacity'],'next_action':'Check terms','duplicate_of':''})
                return {'output':dict(FINAL,summary='Retained concepts need human validation.',assessments=assessments,covered_hypothesis_ids=[h['id'] for h in state['brainstorm_hypotheses']] if task['kind']=='SYNTHESIS' else []),'history':[],'usage':{},'raw':{}}
        self.engine.backend=Backend()
        result=await asyncio.wait_for(self.engine.run(),10)
        self.assertEqual(result['status'],'COMPLETED',result['stop_reason'])
        self.assertEqual(len(result['hypothesis_reviews']),64)
        self.assertEqual(result['steps'],13)

    def test_memory_is_explicitly_preliminary_and_cannot_trigger_novelty_rejection(self):
        from metaweb_swarm.run_memory import summarize_run,prior_candidates,matching_prior,search_prior
        state=self.engine.state;state['status']='LIMIT_REACHED'
        summary=summarize_run(state,state['run_id'],'fixture','hash')
        self.assertEqual(len(summary['hypotheses']),32);self.assertFalse(summary['candidates'])
        candidates=prior_candidates({'entries':[summary]})
        self.assertEqual(candidates[0]['record_kind'],'PRELIMINARY_HYPOTHESIS')
        self.assertFalse(candidates[0]['verified'])
        self.assertFalse(matching_prior(candidates,dict(state['brainstorm_hypotheses'][0],mechanism_key='')))
        self.assertTrue(search_prior(candidates,['Direction 0'])['matches'])

    def test_all_ids_fit_in_synthesis_prompt_and_results_precede_technical_audit(self):
        from metaweb_swarm.reporting import generate_reports
        agent=next(a for a in self.engine.state['agents'] if a['work_kind']=='SYNTHESIS')
        prepare(self.engine.state,agent);text=prompt(self.engine,agent)
        for h in self.engine.state['brainstorm_hypotheses']:self.assertIn(h['id'],text)
        self.assertLessEqual(len(text),self.engine.state['config']['prompt_chars'])
        generate_reports(self.path,self.engine.state)
        report=(self.path/'SWARM_REPORT.md').read_text(encoding='utf-8')
        self.assertLess(report.index('Direction 31'),report.index('Technický audit a podklady'))
        self.assertIn('Předběžné náměty: 32',report)
