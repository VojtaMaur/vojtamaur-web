import copy
import unittest
from tests import test_focused_tasking as fixture
from metaweb_swarm.memory import concise_state
from metaweb_swarm.deposit_handoff import recover


class PromptTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.FocusedTests.setUp
    tearDown=fixture.FocusedTests.tearDown
    for_agent=fixture.FocusedTests.for_agent

    def test_narrative_previews_bounded_without_mutating_full_plans_or_grants(self):
        state=self.engine.state
        for agent in state['agents']:
            agent['handoff_leads']=['Large untrusted narrative '+('x'*2000)]*20
        state['ideas']=[dict(id='IDEA-0001',deposit_plan={'execution_steps':[{'credential_id':'required','allowed_origins':['https://example.org'],'url':'{{previous:/url}}'}]})]
        before=copy.deepcopy(state)
        summary=concise_state(state)
        self.assertEqual(summary['ideas'][0]['deposit_plan'],state['ideas'][0]['deposit_plan'])
        self.assertTrue(all(len(r['handoff_leads'])==3 for r in summary['roles']))
        self.assertTrue(all(len(x)<=300 for r in summary['roles'] for x in r['handoff_leads']))
        self.assertEqual(state,before)

    async def test_host_prompt_failure_reserves_no_round_and_calls_no_backend(self):
        self.engine.state['config']['prompt_chars']=5000
        class NoCalls:
            async def step(*args):raise AssertionError('Preflight must precede backend')
        self.engine.backend=NoCalls()
        agent=self.engine.state['agents'][2]
        before=(self.engine.state['steps'],agent['rounds'],copy.deepcopy(self.engine.state['usage']))
        await self.engine.step(agent)
        self.assertEqual(agent['status'],'BLOCKED')
        self.assertEqual((self.engine.state['steps'],agent['rounds'],self.engine.state['usage']),before)
        self.engine.store.verify()

    async def test_planning_recovery_does_not_reopen_unchanged_oversized_prompt(self):
        from tests.test_planning_recovery import PlanningTests
        from metaweb_swarm.deposit_plan import PlanValidationError
        await PlanningTests.candidate(self)
        bad=copy.deepcopy(self.steps);bad[0]['headers_json']='{"Authorization":"invalid"}'
        with self.assertRaises(PlanValidationError):self.planner.record_deposit_execution_plan(self.idea['id'],bad)
        self.local['status']='BLOCKED'
        self.engine.state['config']['prompt_chars']=5000
        before=self.engine.state['steps']
        recover(self.engine);recover(self.engine)
        self.assertEqual(self.local['status'],'BLOCKED');self.assertEqual(self.engine.state['steps'],before)
        self.engine.state['config']['prompt_chars']=30000
        recover(self.engine)
        self.assertEqual(self.local['status'],'PENDING')

    def test_many_full_handoffs_fit_original_prompt_limit(self):
        for agent in self.engine.state['agents']:
            agent['handoff_leads']=['Detailed handoff '+('x'*2000)]*20
        config=copy.deepcopy(self.engine.state['config'])
        prompt=self.engine.prompt(self.engine.state['agents'][2])
        self.assertLess(len(prompt),config['prompt_chars'])
        self.assertEqual(config,self.engine.state['config'])
