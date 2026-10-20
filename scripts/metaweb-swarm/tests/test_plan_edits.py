"""Draft edits, semantic stalls and strict SDK tools without paid requests."""
import copy
import json
import unittest
from unittest.mock import patch
from metaweb_swarm.deposit_plan import PlanValidationError
from metaweb_swarm.planning_recovery import begin_round, complete
from metaweb_swarm.deposit_handoff import recover
from metaweb_swarm.engine import Engine
from metaweb_swarm.demo import DemoBackend
from tests import test_planning_recovery as fixture
from tests.test_backend import SDK_AVAILABLE


class EditTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.PlanningTests.setUp
    tearDown=fixture.PlanningTests.tearDown
    for_agent=fixture.PlanningTests.for_agent
    candidate=fixture.PlanningTests.candidate

    def bad_binding(self):
        steps=copy.deepcopy(self.steps)
        steps[1]['url']='{{nonexistent:/url}}'
        return steps

    def reject(self,steps):
        with self.assertRaises(PlanValidationError) as caught:
            self.planner.record_deposit_execution_plan(self.idea['id'],steps)
        return caught.exception.problem

    def finish(self):
        return complete(self.planner,dict(status='COMPLETED',unexplored_leads=[],handoff_leads=[]))

    async def test_cosmetic_edits_and_interleaved_issues_cannot_reset_stall(self):
        await self.candidate()
        steps=self.bad_binding()
        first=self.reject(steps)
        self.assertEqual(first['issue']['missing_source_ids'],['nonexistent'])
        self.assertEqual(first['issue']['available_source_ids'],['reserve'])
        steps[1]['purpose']='Unrelated cosmetic description changed'
        second=self.reject(steps)
        self.assertNotEqual(first['fingerprint'],second['fingerprint'])
        self.assertEqual(second['same_attempts'],2)
        other=copy.deepcopy(steps);other[0]['body_json']='{}';other[0]['max_body_bytes']=0
        self.reject(other)
        steps[1]['id']='renamed_send'
        third=self.reject(steps)
        self.assertEqual(third['same_attempts'],3)
        self.assertEqual(self.finish()['status'],'BLOCKED')
        self.local.update(status='BLOCKED',rounds=1)
        recover(self.engine)
        self.assertEqual(self.local['status'],'BLOCKED')

    async def test_field_edit_preserves_other_steps_and_gets_new_qualification(self):
        await self.candidate()
        self.reject(self.bad_binding())
        view=self.planner.read_deposit_plan_draft(self.idea['id'],'send')
        self.assertEqual(view['step_ids'],['reserve','send','finish','verify'])
        result=self.planner.edit_deposit_plan_step(self.idea['id'],view['draft_sha256'],'send',json.dumps({'url':self.steps[1]['url']}))
        q=next(q for q in self.engine.state['deposit_qualifications'] if q['id']==result['qualification_id'])
        self.assertEqual(q['plan']['execution_steps'],self.steps)
        self.assertNotIn('planning_repair',self.local)
        self.assertNotIn('deposit_plan_draft',self.local)
        self.assertEqual(self.finish()['status'],'COMPLETED')
        response=await self.planner.execute_deposit_plan(self.idea['id'])
        self.assertEqual(response['status'],'BLOCKED')
        self.assertFalse(self.engine.state['approvals']);self.assertFalse(self.engine.state['external_actions'])
        self.assertEqual(self.server.calls,['/docs','/terms'])
        self.engine.store.verify()

    async def test_edit_revalidates_entire_plan_and_stale_hash_cannot_overwrite(self):
        await self.candidate()
        steps=self.bad_binding();steps[2]['body_json']='{}'
        self.reject(steps)
        draft=self.planner.read_deposit_plan_draft(self.idea['id'])
        with self.assertRaises(PlanValidationError) as caught:
            self.planner.edit_deposit_plan_step(self.idea['id'],draft['draft_sha256'],'send',json.dumps({'url':self.steps[1]['url']}))
        self.assertEqual(caught.exception.problem['issue']['code'],'BODY_CEILING_REQUIRED')
        current=self.planner.read_deposit_plan_draft(self.idea['id'])
        self.assertNotEqual(draft['draft_sha256'],current['draft_sha256'])
        with self.assertRaisesRegex(ValueError,'STALE_DRAFT'):
            self.planner.edit_deposit_plan_step(self.idea['id'],draft['draft_sha256'],'finish','{"body_json":""}')
        self.assertEqual(self.planner.read_deposit_plan_draft(self.idea['id'])['draft_sha256'],current['draft_sha256'])
        self.assertEqual(self.idea['qualification_id'],self.q['id'])
        self.assertFalse(self.engine.state['approvals'])

    async def test_no_edit_rounds_stop_after_two_and_recovery_leaves_blocked(self):
        await self.candidate();self.reject(self.bad_binding())
        for count in (1,2):
            begin_round(self.local)
            self.planner.read_deposit_plan_draft(self.idea['id'])  # Reading is not an edit.
            result=self.finish()
            self.assertEqual(self.local['planning_repair']['idle_rounds'],count)
        self.assertEqual(result['status'],'BLOCKED')
        self.local.update(status='BLOCKED',rounds=1)
        recover(self.engine);self.assertEqual(self.local['status'],'BLOCKED')

    async def test_checkpoint_restores_private_draft_and_issue_counts(self):
        await self.candidate();self.reject(self.bad_binding())
        before=self.planner.read_deposit_plan_draft(self.idea['id'])
        self.engine.close();self.engine=Engine(self.run,DemoBackend(),'demo')
        self.local=self.engine.state['agents'][2];self.planner=self.for_agent(self.local)
        after=self.planner.read_deposit_plan_draft(self.idea['id'])
        self.assertEqual(after['draft_sha256'],before['draft_sha256'])
        steps=self.bad_binding();steps[1]['purpose']='Changed after resume'
        self.assertEqual(self.reject(steps)['same_attempts'],2)
        self.engine.store.verify()

    async def test_legacy_raw_recovery_requires_exact_existing_failure_hash(self):
        from metaweb_swarm.plan_drafts import hydrate_legacy
        await self.candidate();steps=self.bad_binding();self.reject(steps)
        self.local.pop('deposit_plan_draft')
        repair=self.local['planning_repair'];repair.pop('draft_available');repair.pop('draft_sha256')
        self.local.update(rounds=1,history=[])
        raw=self.run/'raw/AGENT-003-round-1.json'
        call={'type':'function_call','name':'record_deposit_execution_plan',
              'arguments':json.dumps({'idea_id':self.idea['id'],'steps':self.steps})}
        raw.write_text(json.dumps({'responses':[{'output':[call]}]}),encoding='utf-8')
        hydrate_legacy(self.planner)
        self.assertFalse(self.local['planning_repair']['draft_available'])
        repair.pop('draft_recovery_checked')
        call['arguments']=json.dumps({'idea_id':self.idea['id'],'steps':steps})
        raw.write_text(json.dumps({'responses':[{'output':[call]}]}),encoding='utf-8')
        before=copy.deepcopy(self.engine.state['config'])
        hydrate_legacy(self.planner)
        view=self.planner.read_deposit_plan_draft(self.idea['id'],'send')
        self.assertEqual(view['draft_sha256'],self.local['deposit_plan_draft']['receipt']['sha256'])
        self.assertEqual(view['step']['url'],steps[1]['url'])
        self.assertEqual(before,self.engine.state['config'])
        self.assertEqual(self.server.calls,['/docs','/terms'])
        self.assertFalse(self.engine.state['approvals'])

    async def test_sdk_turn_yield_without_edit_cannot_bypass_idle_guard(self):
        from metaweb_swarm.backend import BackendYield
        await self.candidate();self.reject(self.bad_binding())
        class YieldOnly:
            async def step(*args): raise BackendYield('Max turns exceeded')
        self.engine.backend=YieldOnly()
        for _ in range(2): await self.engine.step(self.local)
        self.assertEqual(self.local['status'],'BLOCKED')
        self.assertEqual(self.local['planning_repair']['idle_rounds'],2)
        recover(self.engine);self.assertEqual(self.local['status'],'BLOCKED')

    async def test_malformed_json_is_a_typed_issue_not_a_guessed_correction(self):
        await self.candidate();steps=copy.deepcopy(self.steps)
        steps[2]['body_json']='{"object_key":{$response:"reserve","pointer":"/object_key"}}'
        error=self.reject(steps)
        self.assertEqual(error['issue']['code'],'JSON_TEXT_INVALID')
        view=self.planner.read_deposit_plan_draft(self.idea['id'],'finish')
        self.assertIn('INVALID JSON',view['step']['body_json'])
        self.assertFalse(self.engine.state['external_actions'])

    async def test_draft_secrets_not_in_checkpoint_or_step_view(self):
        await self.candidate()
        secret='dedicated-do-not-expose-12345'
        steps=copy.deepcopy(self.steps);steps[0]['headers_json']=json.dumps({'Authorization':'Bearer '+secret})
        with patch.dict('os.environ',{'OPENAI_API_KEY':secret}):
            self.reject(steps)
            view=self.planner.read_deposit_plan_draft(self.idea['id'],'reserve')
            self.assertNotIn(secret,json.dumps(view))
            self.assertNotIn(secret,(self.run/'checkpoint.json').read_text(encoding='utf-8'))
            self.assertNotIn(secret,(self.run/'raw/events.jsonl').read_text(encoding='utf-8'))

    async def test_inactive_flow_stale_qualification_and_other_role_cannot_edit(self):
        await self.candidate();self.reject(self.bad_binding())
        draft=self.planner.read_deposit_plan_draft(self.idea['id'])
        with self.assertRaises(ValueError):self.api.read_deposit_plan_draft(self.idea['id'])
        with self.assertRaises(ValueError):
            self.planner.edit_deposit_plan_step(self.idea['id'],draft['draft_sha256'],'send','{"id":"new"}')
        self.engine.state['deposit_executions']=[{'idea_id':self.idea['id']}]
        with self.assertRaises(ValueError):self.planner.read_deposit_plan_draft(self.idea['id'])
        self.engine.state['deposit_executions']=[]
        self.idea['qualification_id']='different'
        with self.assertRaises(ValueError):self.planner.read_deposit_plan_draft(self.idea['id'])

    @unittest.skipUnless(SDK_AVAILABLE,'SDK not installed')
    async def test_real_sdk_step_edit_and_complete_without_account_or_upload(self):
        from metaweb_swarm.backend import OpenAIBackend
        from tests.test_backend import FakeProvider,tool_response,final_response,FINAL
        await self.candidate();self.reject(self.bad_binding())
        draft=self.planner.read_deposit_plan_draft(self.idea['id'])
        args=dict(idea_id=self.idea['id'],draft_sha256=draft['draft_sha256'],step_id='send',changes_json=json.dumps({'url':self.steps[1]['url']}))
        self.engine.backend=OpenAIBackend(FakeProvider([
            tool_response('edit_deposit_plan_step',args),final_response(output=dict(FINAL,status='BLOCKED',reason_for_stopping='Credential missing'))]))
        await self.engine.step(self.local)
        self.assertEqual(self.local['status'],'COMPLETED')
        self.assertFalse(self.engine.state['external_actions']);self.assertFalse(self.engine.state['approvals'])
        self.engine.store.verify()
