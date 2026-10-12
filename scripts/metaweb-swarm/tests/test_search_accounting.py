"""Replay the captured provider response locally; no inference or network."""
import copy
import json
import unittest
from pathlib import Path
from metaweb_swarm.backend import _Progress
from metaweb_swarm.budget import reserve
from metaweb_swarm.hosted_search import classify, unfinished_at_cap
from tests import test_focused_tasking as focused

def response():
    return {
        "output":[
            {"id":"ws-complete","type":"web_search_call","status":"completed",
             "action":{"type":"search","query":"FilePost docs","sources":[{"type":"url","url":"https://filepost.dev/docs"}]}},
            {"id":"ws-pending","type":"web_search_call","status":"searching",
             "action":{"type":"search","query":"other carriers","sources":[{"type":"url","url":"https://filepost.dev/terms?utm_source=openai"}]}}],
        "usage":{"input_tokens":14154,"output_tokens":694,"total_tokens":14848},
        "raw_usage":{"input_tokens":14154,"output_tokens":694,"total_tokens":14848}}

class AccountingTests(unittest.IsolatedAsyncioTestCase):
    setUp=focused.FocusedTests.setUp
    tearDown=focused.FocusedTests.tearDown
    for_agent=focused.FocusedTests.for_agent

    def replay(self, data, **bounds):
        reservation=reserve(self.engine.state,self.agent['id'],bounds.get('input_tokens',161191),4000,1,self.agent['model'])
        if 'usd' in bounds:self.engine.state['budget_reservations'][reservation['id']]['usd_upper']=bounds['usd']
        progress=_Progress([],self.api,100000,1)
        class Response:
            def model_dump(inner,**kwargs):return data
        progress.add_response(Response())
        return reservation,progress

    def test_ambiguous_attempt_with_sources_remains_conservatively_counted(self):
        data=response()
        self.assertEqual(len(classify(data['output'],1)[0]),2)
        self.assertEqual(len(unfinished_at_cap(data['output'],1)),1)
        reservation,progress=self.replay(data)
        self.assertFalse(self.engine.state['budget_reservations'])
        closed=self.engine.state['budget_settlements'][reservation['id']]
        note=closed['search_accounting_overage']
        self.assertEqual(closed['status'],'SETTLED')
        self.assertEqual(note['unfinished_attempts'],1)
        self.assertLess(float(note['conservative_actual_usd']),float(note['reserved_usd']))
        self.assertEqual(progress.usage()['web_search_calls'],2)
        self.assertEqual(self.engine.state['usage']['web_search_calls'],2)
        self.assertEqual(self.engine.state['usage']['total_tokens'],14848)
        from metaweb_swarm.engine import refresh_reports
        refresh_reports(self.engine.store,self.engine.state)
        manifest=json.loads((self.run/'manifest.json').read_text(encoding='utf-8'))
        self.assertIn('search_accounting_overage',manifest['budget_settlements'][reservation['id']])
        self.assertIn('provider billing',(self.run/'SWARM_REPORT.md').read_text(encoding='utf-8'))
        self.engine.store.verify()

    def test_completed_overage_is_still_blocked(self):
        data=response();data['output'][1]['status']='completed'
        reservation,progress=self.replay(data)
        self.assertEqual(self.engine.state['budget_reservations'][reservation['id']]['status'],'UNKNOWN')
        self.assertIn('RESERVATION_BOUND_EXCEEDED',self.api.model_settlement_issue())

    def test_unknown_nonsearch_status_is_still_blocked(self):
        for shape in ({'status':'failed'}, {'status':'in_progress'}, {'status':'searching','action':{'type':'open_page','url':'https://example.org'}}):
            data=response();data['output'][1].update(shape)
            self.assertEqual(unfinished_at_cap(data['output'],1),[])

    def test_pending_before_cap_is_not_accepted(self):
        data=response();data['output'].reverse()
        self.assertEqual(unfinished_at_cap(data['output'],1),[])
        reservation,progress=self.replay(data)
        self.assertEqual(self.engine.state['budget_reservations'][reservation['id']]['status'],'UNKNOWN')

    def test_actual_usd_over_reservation_is_still_blocked(self):
        reservation,progress=self.replay(response(),usd='0.01')
        self.assertEqual(self.engine.state['budget_reservations'][reservation['id']]['status'],'UNKNOWN')

    def test_token_over_reservation_is_still_blocked(self):
        reservation,progress=self.replay(response(),input_tokens=100)
        self.assertEqual(self.engine.state['budget_reservations'][reservation['id']]['status'],'UNKNOWN')

    def test_no_price_bound_is_still_blocked(self):
        reservation,progress=self.replay(response(),usd=None)
        self.assertEqual(self.engine.state['budget_reservations'][reservation['id']]['status'],'UNKNOWN')

    def test_missing_usage_is_still_blocked(self):
        data=response();data['raw_usage']=None;data['usage']={}
        reservation,progress=self.replay(data)
        self.assertEqual(self.engine.state['budget_reservations'][reservation['id']]['status'],'UNKNOWN')
        self.assertIn('RECONCILIATION',self.api.model_settlement_issue())

    def test_unknown_existing_hold_is_not_automatically_reconciled(self):
        from metaweb_swarm.budget import settle
        reservation=reserve(self.engine.state,self.agent['id'],161191,4000,1,self.agent['model'])
        self.engine.state['budget_reservations'][reservation['id']]['status']='UNKNOWN'
        outcome=settle(self.engine.state,reservation['id'],dict(response()['usage'],web_search_calls=2,unfinished_search_attempts_at_cap=1))
        self.assertEqual(outcome,'HUMAN_BUDGET_RECONCILIATION_REQUIRED')
        self.assertIn(reservation['id'],self.engine.state['budget_reservations'])

    @unittest.skipUnless(__import__('tests.test_backend',fromlist=['SDK_AVAILABLE']).SDK_AVAILABLE,'SDK optional')
    async def test_actual_sdk_hooks_settle_ambiguous_search_and_return_output(self):
        from metaweb_swarm.backend import OpenAIBackend
        from tests.test_backend import FakeProvider,final_response
        from openai.types.responses import ResponseFunctionWebSearch
        from agents.usage import Usage
        model_response=final_response()
        model_response.output[:0]=[ResponseFunctionWebSearch(**item) for item in response()['output']]
        model_response.usage=Usage(requests=1,input_tokens=14154,output_tokens=694,total_tokens=14848)
        provider=FakeProvider([model_response])
        result=await OpenAIBackend(provider).step(self.agent,self.engine.prompt(self.agent),[],self.api,self.config)
        self.assertEqual(result['output']['status'],'COMPLETED')
        self.assertFalse(self.engine.state['budget_reservations'])
        self.assertEqual(result['usage']['web_search_calls'],2)
        self.assertTrue(any(r.get('search_accounting_overage') for r in self.engine.state['budget_settlements'].values()))
