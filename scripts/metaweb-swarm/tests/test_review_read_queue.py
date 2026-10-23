"""Repeated model navigation cannot starve the mandatory evidence queue."""
import json,unittest
from metaweb_swarm.review_dispatch import read_assigned_artifact,action
from metaweb_swarm.prototype_evidence import reading_requirements
from tests import test_local_contract as fixture


class ReviewReadQueueTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.LocalContractReviewTests.setUp
    tearDown=fixture.LocalContractReviewTests.tearDown
    for_agent=fixture.LocalContractReviewTests.for_agent
    prepare=fixture.LocalContractReviewTests.prepare
    plan=fixture.LocalContractReviewTests.plan
    artifacts=fixture.LocalContractReviewTests.artifacts
    executed=fixture.LocalContractReviewTests.executed
    evidence=fixture.LocalContractReviewTests.evidence
    captured=fixture.LocalContractReviewTests.captured

    async def pending(self):
        test=await self.captured()
        for key in ('prototype_artifact_reads','prototype_artifact_checks','prototype_fact_reads'):
            self.auditor.pop(key,None)
        return test

    async def test_repeated_wrong_test_path_and_page_serve_exact_missing_evidence(self):
        test=await self.pending();served=[]
        for _ in range(20):
            required=action(self.review)
            if required['tool']!='read_test_artifact':break
            expected=required['arguments']
            result=read_assigned_artifact(self.review,'STALE-TEST','prototype/test.py',90000,1)
            self.assertEqual(result['path'],expected['path'])
            self.assertEqual(result['dispatch_binding']['served'],expected)
            served.append((result['path'],result.get('offset',0)))
        self.assertTrue(served);self.assertEqual(len(served),len(set(served)))
        self.assertFalse(reading_requirements(self.review,test)[1])
        self.assertEqual(action(self.review)['tool'],'get_prototype_review_facts')
        self.assertNotIn('prototype_review',test)
        self.assertFalse(self.engine.state['external_actions'])

    async def test_extra_reads_remain_explicit_after_mandatory_queue(self):
        test=await self.captured()
        result=read_assigned_artifact(self.review,test['id'],'prototype/test.py',5,9)
        self.assertEqual((result['offset'],result['end']),(5,14))
        self.assertNotIn('dispatch_binding',result)

    async def test_actual_sdk_repeated_same_file_moves_through_queue_to_facts(self):
        from tests.test_backend import SDK_AVAILABLE,FakeProvider,tool_response,final_response
        from metaweb_swarm.backend import OpenAIBackend
        if not SDK_AVAILABLE:self.skipTest('SDK optional')
        test=await self.pending()
        missing=reading_requirements(self.review,test)[1]
        responses=[tool_response('read_test_artifact',dict(test_id=test['id'],path='prototype/test.py',offset=0,limit=12000),
                                ident='repeated-read-'+str(i)) for i in range(len(missing))]
        responses.extend([tool_response('get_prototype_review_facts',{'test_id':test['id']},ident='read-facts'),final_response()])
        provider=FakeProvider(responses)
        await OpenAIBackend(provider).step(self.auditor,self.engine.prompt(self.auditor),[],self.review,self.engine.state['config'])
        self.assertFalse(reading_requirements(self.review,test)[1])
        from metaweb_swarm.review_facts import seen
        self.assertTrue(seen(self.review,test));self.assertNotIn('prototype_review',test)
        choices=[]
        for args,kwargs in provider.model.calls:
            settings=kwargs.get('model_settings',args[2] if len(args)>2 else None)
            choices.append(settings.tool_choice)
        self.assertEqual(choices[:len(missing)],['read_test_artifact']*len(missing))
        self.assertEqual(choices[len(missing)],'get_prototype_review_facts')
