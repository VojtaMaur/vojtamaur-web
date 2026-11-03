import copy,json,unittest
from metaweb_swarm.research_closure import prepare
from metaweb_swarm.models import search_allowance
from tests.test_brainstorming import BrainstormingRunTests

class ClosureTests(BrainstormingRunTests):
    async def test_report_only_real_sdk_finishes_in_one_call_without_tools_or_fake_reviews(self):
        from tests.test_backend import SDK_AVAILABLE,FakeProvider,final_response,FINAL
        from metaweb_swarm.backend import OpenAIBackend
        if not SDK_AVAILABLE:self.skipTest('SDK optional')
        state=self.engine.state
        idea={'id':'IDEA-0001','provider':'Unreviewed institution','status':'INVESTIGATING','summary':'Existing unverified custody proposal','agent_id':state['agents'][1]['id']}
        state['ideas']=[idea]
        prepare(self.engine,'Synthesize only',report_only=True)
        self.assertTrue(all(a['status']=='COMPLETED' for a in state['agents'] if a['work_kind']!='SYNTHESIS'))
        output=dict(FINAL,summary='IDEA-0001: deferred for human evaluation. This proposal has no independent review and remains unverified; no implementation occurred.')
        provider=FakeProvider([final_response(output=output)])
        self.engine.backend=OpenAIBackend(provider)
        final=await self.engine.run()
        self.assertEqual(final['status'],'COMPLETED')
        self.assertEqual(len(provider.model.calls),1)
        args,kwargs=provider.model.calls[0]
        self.assertEqual(kwargs.get('tools',args[3] if len(args)>3 else []),[])
        self.assertEqual(final['critiques'],[])
        self.assertEqual(final['ideas'][0]['status'],'INVESTIGATING')
        reporter=next(a for a in final['agents'] if a['work_kind']=='SYNTHESIS')
        self.assertEqual(reporter['research_report_receipt']['idea_ids'],['IDEA-0001'])
        self.engine.store.verify()

    async def test_openai_semantic_gate_retains_provisional_sketches_without_model_calls(self):
        state=self.engine.state;state['backend']='openai';state['config']['semantic_dedupe']=True
        for provider in ['Institution A','Institution B']:
            self.engine.store.commit(state,'sdk_tool_started',{'name':'screen_carrier','arguments':json.dumps({
                'provider':provider,'proposed_change':'Existing offline custody proposal for '+provider})},state['agents'][1]['id'])
        prepare(self.engine,'Close prior sketches')
        self.assertEqual(len(state['ideas']),2)
        self.assertTrue(all(i['closure_provisional'] for i in state['ideas']))
        self.assertEqual(state['usage']['requests'],0)
        self.assertTrue(state['config']['semantic_dedupe'])

    async def test_closure_captures_existing_only_then_finishes_without_discovery(self):
        state=self.engine.state;agent=state['agents'][1]
        for wording in ['Existing physical archive proposal','A different wording of the same carrier']:
            self.engine.store.commit(state,'sdk_tool_started',{'name':'screen_carrier','arguments':json.dumps({
                'provider':'Research fixture institution','proposed_change':wording,'validation_plan':'Ask the institution to assess a public build donation.'})},agent['id'])
        old=copy.deepcopy(state['config'])
        result=prepare(self.engine,'Close only existing research',100000,300,10)
        self.assertEqual(len(state['ideas']),1);self.assertEqual(len(result['sketches']),2)
        self.assertEqual(state['ideas'][0]['status'],'INVESTIGATING')
        self.assertEqual(state['ideas'][0]['payment'],'UNKNOWN')
        self.assertTrue(all(a['status']=='COMPLETED' for a in state['agents'] if a['work_kind']=='DISCOVERY'))
        self.assertTrue(all(search_allowance(state['config'],a)==0 for a in state['agents']))
        self.assertEqual(state['config']['max_total_tokens'],old['max_total_tokens']+100000)
        prepare(self.engine,'Repeated request',100000,300,10)
        self.assertEqual(len(state['ideas']),1)
        self.assertEqual(state['config']['max_total_tokens'],old['max_total_tokens']+100000)
        final=await self.engine.run()
        self.assertEqual(final['status'],'COMPLETED')
        self.assertEqual(len(final['critiques']),2)
        self.assertEqual(len(final['ideas']),1)
        self.assertFalse(final['external_actions']);self.engine.store.verify()

    async def test_unknown_request_prevents_preparation_without_mutation(self):
        state=self.engine.state;state['budget_reservations']={'unknown':{'status':'UNKNOWN'}}
        before=copy.deepcopy(state)
        with self.assertRaisesRegex(ValueError,'outstanding'):
            prepare(self.engine,'Close only',10,20,30)
        self.assertEqual(state,before)
