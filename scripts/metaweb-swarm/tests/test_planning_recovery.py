"""Recover invalid planning data while all execution controls remain closed."""
import copy
import json
import unittest
from metaweb_swarm.demo import DemoBackend
from metaweb_swarm.deposit_plan import validate, PlanValidationError
from metaweb_swarm.deposit_handoff import recover
from metaweb_swarm.planning_recovery import complete, legacy_problem
from metaweb_swarm.backend import OpenAIBackend
from tests import test_focused_tasking as fixture
from tests.test_backend import SDK_AVAILABLE


class PlanningTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.FocusedTests.setUp
    tearDown=fixture.FocusedTests.tearDown
    for_agent=fixture.FocusedTests.for_agent

    async def candidate(self):
        for path in ('/docs','/terms'):
            await self.api.read_document(self.origin+path,'Read primary API and payment docs')
        self.q=self.api.check_deposit_target(dict(provider='Independent fixture', export_path='build.epub',
            documentation_urls=[self.origin+'/docs',self.origin+'/terms'],upload_url=self.origin+'/file',
            method='POST',authentication='DEDICATED_CREDENTIAL',credential_id='',required_external_actions=1,
            novelty_class='POTENTIALLY_NEW',baseline_evidence_ids=[],baseline_behavior='',proposed_change='',validation_plan='',operation_steps=[]))
        data=DemoBackend.idea('Independent candidate','Exact-byte public file custody','FREE','DISCOVERED')
        data.update(provider='Independent fixture',qualification_id=self.q['id'])
        self.idea=self.api.submit_idea(data)
        self.local=self.engine.state['agents'][2]
        self.local['execution_plan_only']=True
        self.planner=self.for_agent(self.local)
        size=self.q['export_bytes']
        def step(ident,method,url,**kw):
            value=dict(id=ident,method=method,purpose='Perform '+ident+' for retained export',url=url,
                allowed_origins=[self.origin],credential_id='',headers_json='{}',body_json='',sends_export=False,
                max_body_bytes=0,success_codes=[200,201],max_age_seconds=0)
            value.update(kw);return value
        self.steps=[step('reserve','POST',self.origin+'/file',credential_id='REQUIRED_CARRIER_KEY',
                           body_json=json.dumps({'filename':{'$export':'filename'},'size':{'$export':'bytes'}}),max_body_bytes=1024),
                    step('send','PUT','{{reserve:/upload/signedUrl}}',sends_export=True,max_body_bytes=size),
                    step('finish','POST',self.origin+'/complete/{{reserve:/id}}',credential_id='REQUIRED_CARRIER_KEY'),
                    step('verify','GET','{{finish:/publicUrl}}')]

    async def test_missing_grant_plan_saved_without_any_execution_or_approval(self):
        await self.candidate()
        result=self.planner.record_deposit_execution_plan(self.idea['id'],self.steps)
        self.assertEqual(result['external_actions'],3)
        self.assertEqual(result['missing_credentials'][0]['credential_id'],'REQUIRED_CARRIER_KEY')
        q=next(q for q in self.engine.state['deposit_qualifications'] if q['id']==result['qualification_id'])
        self.assertIn('RESOURCE_LIMIT',q['reasons']);self.assertIn('ACCOUNT_SETUP_REQUIRED',q['reasons'])
        self.assertNotIn('EXECUTABLE_FLOW_REQUIRED',q['reasons'])
        self.assertTrue(q['admissible']);self.assertFalse(q['execution_ready'])
        with self.assertRaises(PlanValidationError):validate(self.steps,self.config,{'bytes':self.q['export_bytes']})
        response=await self.planner.execute_deposit_plan(self.idea['id'])
        self.assertEqual(response['status'],'BLOCKED')
        self.assertFalse(self.engine.state['approvals']);self.assertFalse(self.engine.state['external_actions'])
        self.assertFalse(self.engine.state.get('deposit_executions'))
        self.assertEqual(self.server.calls,['/docs','/terms'])

    async def test_same_bad_plan_has_typed_repair_then_valid_save_clears_it(self):
        await self.candidate()
        bad=copy.deepcopy(self.steps)
        bad[0]['headers_json']='{"Authorization":"Bearer {$credential}"}'
        with self.assertRaises(PlanValidationError) as caught:
            self.planner.record_deposit_execution_plan(self.idea['id'],bad)
        self.assertEqual(caught.exception.problem['status'],'DEFERRED')
        self.assertEqual(caught.exception.problem['issue']['step_id'],'reserve')
        self.assertEqual(caught.exception.problem['issue']['code'],'HEADERS_INVALID')
        output=complete(self.planner,dict(status='BLOCKED',unexplored_leads=[],handoff_leads=[]))
        self.assertEqual(output['status'],'CONTINUE')
        self.planner.record_deposit_execution_plan(self.idea['id'],self.steps)
        self.assertNotIn('planning_repair',self.local)
        output=complete(self.planner,dict(status='BLOCKED',unexplored_leads=['Supply credentials'],handoff_leads=[]))
        self.assertEqual(output['status'],'COMPLETED')
        self.assertFalse(self.engine.state['external_actions'])

    async def test_forward_reference_raw_body_and_json_ceiling_corrections(self):
        await self.candidate()
        for index,change,code in [(3,{'url':'{{not_created:/url}}'},'BINDING_SOURCE_REQUIRED'),
              (1,{'body_json':'{"file":"{$export}"}'},'EXACT_EXPORT_BODY_REQUIRED'),
              (2,{'body_json':'{}'},'BODY_CEILING_REQUIRED')]:
            steps=copy.deepcopy(self.steps);steps[index].update(change)
            with self.assertRaises(PlanValidationError) as caught:self.planner.record_deposit_execution_plan(self.idea['id'],steps)
            self.assertEqual(caught.exception.problem['issue']['code'],code)
        self.assertFalse(self.engine.state['external_actions'])

    async def test_identical_bad_arguments_stop_after_three_without_spending_permissions(self):
        await self.candidate()
        bad=copy.deepcopy(self.steps);bad[0]['headers_json']='{"Host":"forbidden.example"}'
        for count in range(3):
            with self.assertRaises(PlanValidationError):self.planner.record_deposit_execution_plan(self.idea['id'],bad)
        output=complete(self.planner,dict(status='COMPLETED',unexplored_leads=[],handoff_leads=[]))
        self.assertEqual(output['status'],'BLOCKED')
        self.assertIn('PLAN_REPAIR_STALLED',output['reason_for_stopping'])
        self.local.update(status='BLOCKED',rounds=1)
        recover(self.engine)
        self.assertEqual(self.local['status'],'BLOCKED')
        self.assertFalse(self.engine.state['approvals'])

    async def test_existing_grant_wrong_origin_rejected_even_during_planning(self):
        await self.candidate()
        self.engine.state['config']['http_credentials']=[dict(id='REQUIRED_CARRIER_KEY',env='META_SWARM_CRED_FIXTURE',hosts=['other.example.org'],header='Authorization',scheme='Bearer')]
        with self.assertRaises(PlanValidationError) as caught:self.planner.record_deposit_execution_plan(self.idea['id'],self.steps)
        self.assertEqual(caught.exception.issue['code'],'CREDENTIAL_ORIGIN_MISMATCH')
        self.assertFalse(self.engine.state['external_actions'])

    async def test_legacy_error_recognized_from_tool_receipt_not_narrative(self):
        await self.candidate()
        args=json.dumps({'idea_id':self.idea['id'],'steps':self.steps})
        self.local['history']=[{'type':'function_call','name':'record_deposit_execution_plan','call_id':'old','arguments':args},
            {'type':'function_call_output','call_id':'old','output':json.dumps(dict(status='BLOCKED',error_type='HttpPolicyError',reason='Authentication, routing and framing headers must not be supplied by an agent'))}]
        self.local.update(status='BLOCKED',rounds=1)
        self.assertEqual(legacy_problem(self.engine.state,self.local)['idea_id'],self.idea['id'])
        recover(self.engine);self.assertEqual(self.local['status'],'PENDING')
        self.planner.record_deposit_execution_plan(self.idea['id'],self.steps)
        self.assertIsNone(legacy_problem(self.engine.state,self.local))
        self.assertFalse(self.engine.state['external_actions'])

    async def test_predeployment_missing_receipt_is_repaired_but_setup_review_is_valid(self):
        await self.candidate()
        review=self.for_agent(self.engine.state['agents'][1])
        r=review.record_critique(self.idea['id'],'REVISE','Missing credentials and no completed deposit evidence.',decision_basis='SETUP_GAP')
        self.assertEqual(r['status'],'DEFERRED')
        self.assertEqual(r['reason'],'PRE_DEPLOYMENT_REVIEW_NO_EXECUTION_REQUIRED')
        self.assertFalse(self.engine.state['critiques'])
        r=review.record_critique(self.idea['id'],'REVISE','Dedicated credential grant and request bindings are missing.',decision_basis='SETUP_GAP')
        self.assertEqual(r['verdict'],'REVISE')
        self.assertEqual(r['review_stage'],'PRE_DEPLOYMENT')
        self.assertFalse(r['execution_receipt_required'])
        self.assertNotIn('predeployment_review_repair',review.agent)
        self.assertFalse(self.engine.state['external_actions'])

    @unittest.skipUnless(SDK_AVAILABLE,'SDK not installed')
    async def test_actual_sdk_repairs_headers_and_finishes_planning_even_without_key(self):
        from tests.test_backend import FakeProvider,tool_response,final_response,FINAL
        await self.candidate()
        bad=copy.deepcopy(self.steps);bad[0]['headers_json']='{"Authorization":"Bearer {$credential}"}'
        provider=FakeProvider([tool_response('record_deposit_execution_plan',{'idea_id':self.idea['id'],'steps':bad}),
            tool_response('record_deposit_execution_plan',{'idea_id':self.idea['id'],'steps':self.steps},ident='corrected-plan'),
            final_response(output=dict(FINAL,status='BLOCKED',reason_for_stopping='Account key missing'))])
        self.engine.backend=OpenAIBackend(provider)
        await self.engine.step(self.local)
        self.assertEqual(self.local['status'],'COMPLETED')
        q=next(q for q in self.engine.state['deposit_qualifications'] if q['id']==self.idea['qualification_id'])
        self.assertEqual(len(q['plan']['execution_steps']),4)
        self.assertIn('ACCOUNT_SETUP_REQUIRED',q['reasons'])
        self.assertFalse(self.engine.state['external_actions']);self.assertFalse(self.engine.state['approvals'])
        self.engine.store.verify()

    async def test_checkpointed_repair_reopens_planning_without_credentials_or_extra_limits(self):
        from metaweb_swarm.engine import Engine
        await self.candidate()
        bad=copy.deepcopy(self.steps);bad[0]['headers_json']='{"Authorization":"Bearer {$credential}"}'
        with self.assertRaises(PlanValidationError):self.planner.record_deposit_execution_plan(self.idea['id'],bad)
        self.local.update(status='BLOCKED',rounds=1)
        self.planner.event('fixture_role_blocked',{})
        self.engine.close();self.engine=Engine(self.run,DemoBackend(),'demo')
        before=copy.deepcopy(self.engine.state['config'])
        recover(self.engine)
        self.assertEqual(self.engine.state['agents'][2]['status'],'PENDING')
        self.assertEqual(self.engine.state['config'],before)
        self.assertFalse(self.engine.state['approvals'])
        self.engine.store.verify()

    @unittest.skipUnless(SDK_AVAILABLE,'SDK not installed')
    async def test_actual_sdk_review_retries_inappropriate_execution_criterion(self):
        from tests.test_backend import FakeProvider,tool_response,final_response,FINAL
        await self.candidate()
        reviewer=self.engine.state['agents'][1]
        args=dict(idea_id=self.idea['id'],verdict='REVISE',reason='No completed deposit evidence.',
                  decision_basis='EVIDENCE_GAP',failure_kind='NONE',failure_fact='',negative_evidence_urls=[])
        valid=dict(args,reason='The dedicated credential grant and executable bindings are missing.',decision_basis='SETUP_GAP')
        provider=FakeProvider([tool_response('record_critique',args,ident='wrong-stage'),
                              tool_response('record_critique',valid,ident='valid-review'),final_response(output=FINAL)])
        self.engine.backend=OpenAIBackend(provider)
        await self.engine.step(reviewer)
        self.assertEqual(reviewer['status'],'COMPLETED')
        self.assertEqual(len(self.engine.state['critiques']),1)
        self.assertEqual(self.engine.state['critiques'][0]['review_stage'],'PRE_DEPLOYMENT')
        self.assertFalse(self.engine.state['external_actions'])
