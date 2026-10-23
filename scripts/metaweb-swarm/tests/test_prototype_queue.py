"""Coding receipts wait for review; repair/review and budget boundaries survive resume."""
import copy
import unittest
import io
from contextlib import redirect_stdout
from unittest.mock import patch
from metaweb_swarm import prototype_queue as q
from metaweb_swarm.research_tasks import assign,local_candidates,complete
from metaweb_swarm.review_tasks import assign as assign_review
from metaweb_swarm.review_dispatch import schedule
from tests import test_prototype_review as fixture


class PrototypeQueueTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.PrototypeScopeTests.setUp
    tearDown=fixture.PrototypeScopeTests.tearDown
    for_agent=fixture.PrototypeScopeTests.for_agent
    prepare=fixture.PrototypeScopeTests.prepare
    plan=fixture.PrototypeScopeTests.plan
    artifacts=fixture.PrototypeScopeTests.artifacts
    executed=fixture.PrototypeScopeTests.executed

    def activate(self):
        self.state=self.engine.state
        self.state['config'].update(coding_backend='sdk_shell',max_steps=40,max_agent_rounds=4,
            role_round_limits={'Evidence Auditor':10,'Prototyper':8})
        self.state['steps']=0
        for a in self.state['agents']:a.update(status='PENDING',rounds=0)
        self.proto['rounds']=1

    def other(self):
        idea=copy.deepcopy(self.idea);idea.update(id='IDEA-NEXT',title='Next candidate')
        self.state['ideas'].append(idea)
        return idea

    def verdict(self,test,verdict):
        r=dict(id='REVIEW-'+test['id']+'-'+verdict,test_id=test['id'],verdict=verdict,
               reason='Independent test fixture verdict; not evidence of a real scientific result')
        test['prototype_review']=r;self.state.setdefault('prototype_reviews',[]).append(r)

    async def test_receipt_waits_and_preempts_other_discovery_and_research(self):
        test=await self.executed();self.activate();self.other()
        out=complete(self.state,self.proto,dict(status='COMPLETED',unexplored_leads=[],handoff_leads=[]))
        self.assertEqual(out['status'],'BLOCKED')
        self.proto.update(out);q.synchronize(self.engine)
        self.assertEqual(local_candidates(self.state,self.proto),[])
        pending=[a for a in self.state['agents'] if a['status']=='PENDING']
        self.assertEqual(schedule(self.state,pending,40,4),[self.auditor])
        assign_review(self.engine,self.auditor)
        self.assertEqual(self.auditor['review_assignment']['target_id'],test['id'])

    async def test_urgent_test_switches_old_unfinished_research_packet(self):
        test=await self.executed();self.activate();other=self.other()
        from metaweb_swarm.research_tasks import revision
        self.auditor['review_assignment']=dict(kind='RESEARCH_IDEA',target_id=other['id'],revision=revision(other))
        assign_review(self.engine,self.auditor)
        self.assertEqual(self.auditor['review_assignment']['kind'],'PROTOTYPE_TEST')
        self.assertEqual(self.auditor['review_assignment']['target_id'],test['id'])

    async def test_repair_receipt_returns_to_review_before_next_candidate(self):
        t=await self.executed();self.activate();self.other()
        self.verdict(t,'REVISE')
        self.proto.update(status='BLOCKED',prototype_queue_hold='AWAITING_INDEPENDENT_PROTOTYPE_REVIEW')
        q.synchronize(self.engine);assign(self.engine,self.proto)
        self.assertEqual(self.proto['status'],'PENDING')
        self.assertEqual(self.proto['research_assignment']['target_id'],self.idea['id'])
        second=copy.deepcopy(t);second.update(id='TEST-REPAIRED');second.pop('prototype_review')
        self.state['tests'].append(second)
        q.synchronize(self.engine)
        self.assertEqual(self.proto['status'],'BLOCKED')
        self.verdict(second,'REVISE');q.synchronize(self.engine)
        self.assertEqual([i['id'] for i in local_candidates(self.state,self.proto)],[self.idea['id']])
        self.verdict(second,'SUBCOMPONENT');q.synchronize(self.engine)
        self.assertEqual([i['id'] for i in local_candidates(self.state,self.proto)],['IDEA-NEXT'])

    async def test_exhausted_auditor_stops_new_code_and_discovery_then_reports(self):
        t=await self.executed();self.activate();self.other();self.verdict(t,'SUBCOMPONENT')
        self.auditor.update(rounds=10,status='LIMIT_REACHED')
        original=copy.deepcopy(self.state['config']);q.synchronize(self.engine)
        self.assertEqual(self.proto['prototype_queue_hold'],'PROTOTYPE_AUDIT_ROUNDS_REQUIRED')
        pending=[a for a in self.state['agents'] if a['status']=='PENDING']
        self.assertEqual(schedule(self.state,pending,40,4),[self.reporter])
        self.reporter['status']='COMPLETED'
        self.assertEqual(schedule(self.state,[a for a in pending if a is not self.reporter],40,4),[])
        self.assertEqual(self.state['config'],original)
        # Operator explicitly grants audit capacity, never the scheduler.
        self.auditor.update(round_limit=12,status='PENDING')
        q.synchronize(self.engine)
        self.assertEqual(self.proto['status'],'PENDING')
        self.assertNotIn('prototype_queue_hold',self.proto)

    async def test_three_remaining_steps_cannot_admit_new_candidate(self):
        await self.executed();self.activate();self.state['tests']=[]
        self.state['steps']=37;q.synchronize(self.engine)
        self.assertEqual(self.proto['prototype_queue_hold'],'PROTOTYPE_CLOSURE_STEPS_REQUIRED')
        pending=[a for a in self.state['agents'] if a['status']=='PENDING']
        self.assertEqual(schedule(self.state,pending,3,4),[self.reporter])
        self.state['config']['max_steps']=41;q.synchronize(self.engine)
        self.assertEqual(self.proto['status'],'PENDING')

    async def test_completed_auditor_can_be_reopened_but_unrelated_block_is_preserved(self):
        await self.executed();self.activate();self.state['tests']=[]
        self.auditor['status']='COMPLETED'
        self.assertIsNone(q.capacity(self.state,self.proto,self.idea))
        self.auditor.update(status='BLOCKED',reason_for_stopping='Transport credential failure')
        self.assertEqual(q.capacity(self.state,self.proto,self.idea),'PROTOTYPE_AUDIT_ROUNDS_REQUIRED')

    async def test_research_review_cannot_consume_last_two_audit_quanta(self):
        await self.executed();self.activate();self.state['tests']=[]
        self.auditor.update(rounds=8)
        # No runnable coding or discovery; research queue remains, but audit reserve is kept.
        self.assertEqual(schedule(self.state,[self.auditor,self.reporter],10,1),[self.reporter])
        self.state['config']['run_mode']='supervised'
        self.assertEqual(schedule(self.state,[self.auditor,self.reporter],10,1),[self.auditor])

    async def test_reviewed_last_candidate_finishes_without_paid_empty_local_round(self):
        t=await self.executed();self.activate()
        self.proto.update(status='BLOCKED',prototype_queue_hold='AWAITING_INDEPENDENT_PROTOTYPE_REVIEW')
        self.verdict(t,'SUBCOMPONENT');q.synchronize(self.engine)
        self.assertEqual(self.proto['status'],'COMPLETED')

    async def test_unresolved_review_does_not_release_more_prototypes(self):
        t=await self.executed();self.activate();self.other();self.verdict(t,'REVISE')
        t['prototype_review']['review_unresolved']=True
        q.synchronize(self.engine)
        self.assertEqual(self.proto['prototype_queue_hold'],'AWAITING_INDEPENDENT_PROTOTYPE_REVIEW')
        self.assertEqual(local_candidates(self.state,self.proto),[])

    async def test_failed_auditor_is_blocked_not_a_fictitious_global_budget_limit(self):
        await self.executed();self.activate()
        from metaweb_swarm.deposit_handoff import report_revision
        self.auditor.update(status='BLOCKED',reason_for_stopping='LOCAL_CONTRACT_REVIEW_STALLED')
        self.reporter.update(status='COMPLETED',research_report_revision=report_revision(self.state))
        before=self.state['steps']
        with patch.object(self.engine,'step') as dispatch,redirect_stdout(io.StringIO()):
            result=await self.engine.run();dispatch.assert_not_called()
        self.assertEqual(result['status'],'BLOCKED')
        self.assertTrue(result['stop_reason'].startswith('PROTOTYPE_REVIEW_BLOCKED'))
        self.assertEqual(result['steps'],before)

    async def test_no_pending_roles_reports_actual_review_block_before_unrelated_role_limit(self):
        await self.executed();self.activate()
        for a in self.state['agents']:a['status']='LIMIT_REACHED'
        self.auditor.update(status='BLOCKED',reason_for_stopping='PROTOTYPE_REVIEW_EVIDENCE_STALLED')
        self.proto.update(status='BLOCKED',prototype_queue_hold='AWAITING_INDEPENDENT_PROTOTYPE_REVIEW')
        before=self.state['steps']
        with patch.object(self.engine,'step') as dispatch,redirect_stdout(io.StringIO()):
            result=await self.engine.run();dispatch.assert_not_called()
        self.assertEqual(result['status'],'BLOCKED')
        self.assertTrue(result['stop_reason'].startswith('PROTOTYPE_REVIEW_BLOCKED'))
        self.assertEqual(result['steps'],before)

    async def test_real_scheduler_loop_finishes_repair_review_report_sequence(self):
        original=await self.executed();self.activate();self.state['tests']=[]
        from metaweb_swarm.research_tasks import revision
        from metaweb_swarm.deposit_handoff import report_revision
        self.state['critiques']=[dict(idea_id=self.idea['id'],agent_id=self.auditor['id'],
                                    research_revision=revision(self.idea))]
        for a in self.state['agents']:
            if a not in [self.auditor,self.proto,self.reporter]:a['status']='COMPLETED'
        calls=[]
        async def simulated_step(a):
            self.state['steps']+=1;a['rounds']+=1;calls.append(a['work_kind'])
            if a is self.proto:
                t=copy.deepcopy(original);t['id']='TEST-CYCLE-'+str(a['rounds']);t.pop('prototype_review',None)
                self.state['tests'].append(t)
                a.update(status='BLOCKED',prototype_queue_hold='AWAITING_INDEPENDENT_PROTOTYPE_REVIEW')
            elif a is self.auditor:
                test=q.awaiting(self.state)[0]
                self.verdict(test,'REVISE' if a['rounds']==1 else 'SUBCOMPONENT')
                a['status']='COMPLETED'
            else:
                a.update(status='COMPLETED',research_report_revision=report_revision(self.state))
        with patch.object(self.engine,'step',side_effect=simulated_step),redirect_stdout(io.StringIO()):
            result=await self.engine.run()
        self.assertEqual(calls,['LOCAL','REVIEW','LOCAL','REVIEW','SYNTHESIS'])
        self.assertEqual(result['status'],'COMPLETED')
        self.assertEqual(result['steps'],5)
        self.assertEqual(self.proto['status'],'COMPLETED')
