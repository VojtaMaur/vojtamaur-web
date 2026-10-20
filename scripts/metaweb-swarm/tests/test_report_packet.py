"""Reporter context excludes recursive provenance, with paged original evidence."""
import copy
import json
import unittest
from metaweb_swarm.report_packet import build
from metaweb_swarm.backend import OpenAIBackend
from tests import test_research_handoffs as fixture
from tests.test_backend import SDK_AVAILABLE


class ReportPacketTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixture.ResearchHandoffTests.setUp
    tearDown = fixture.ResearchHandoffTests.tearDown
    for_agent = fixture.ResearchHandoffTests.for_agent
    prepare = fixture.ResearchHandoffTests.prepare

    def inflate(self):
        self.prepare()
        self.idea.update(revisions=[{'old': 'HISTORICAL-DUPLICATE-'*10000}],
                         submissions=[{'payload': 'OLD-SUBMISSION-'*10000}], summary='Current concise hypothesis')
        self.engine.state['http_requests'] = [{'id': 'HTTP-LARGE', 'agent_id': 'OTHER', 'status': 'COMPLETED',
            'response': {'status': 200, 'headers': {'content-security-policy': 'HEADER-NOISE-'*10000}}}]

    def test_recursive_provenance_and_headers_do_not_reach_overview(self):
        self.inflate()
        before = copy.deepcopy(self.engine.state)
        report = build(self.engine.state)
        body = json.dumps(report, ensure_ascii=False)
        self.assertLess(len(body), 10000)
        self.assertNotIn('HISTORICAL-DUPLICATE', body)
        self.assertNotIn('OLD-SUBMISSION', body)
        self.assertNotIn('HEADER-NOISE', body)
        self.assertEqual(report['idea_ids'], [self.idea['id']])
        self.assertEqual(report['counts']['http_requests'], 1)
        self.assertEqual(self.engine.state, before)

    def test_bounded_detail_retains_original_evidence_and_pagination(self):
        self.inflate()
        api = self.for_agent(self.reporter)
        result = api.read_report_detail('ideas', self.idea['id'], limit=1000)
        self.assertEqual(result['next_offset'], 1000)
        self.assertEqual(len(result['text']), 1000)
        original = json.dumps(self.idea, ensure_ascii=False, indent=2)
        self.assertEqual(result['text'], original[:1000])
        self.assertEqual(result['total_chars'], len(original))
        with self.assertRaises(ValueError):
            self.for_agent(self.proto).read_report_detail('ideas', self.idea['id'])
        with self.assertRaises(ValueError):
            api.read_report_detail('ideas', self.idea['id'], limit=8001)
        with self.assertRaises(ValueError):
            api.read_report_detail('credentials')

    def test_large_inventory_preserves_exact_counts_and_all_ids_with_explicit_omissions(self):
        self.inflate()
        self.engine.state['ideas'] = [dict(self.idea, id=f'IDEA-{n:04}', title='Long title '*100)
                                      for n in range(80)]
        packet = build(self.engine.state)
        self.assertLessEqual(len(json.dumps(packet, ensure_ascii=False)), 10000)
        self.assertEqual(packet['counts']['candidates'], 80)
        self.assertEqual(len(packet['idea_ids']), 80)
        self.assertGreater(packet['omitted_idea_summaries'], 0)

    @unittest.skipUnless(SDK_AVAILABLE, 'SDK optional')
    async def test_actual_sdk_reporter_can_close_after_large_original_state(self):
        from tests.test_backend import FakeProvider, tool_response, final_response
        self.inflate()
        self.reporter.update(status='PENDING', rounds=0)
        provider = FakeProvider([
            tool_response('get_research_task', {}),
            tool_response('record_research_report', {'idea_ids': [self.idea['id']],
                'conclusion': 'The current hypothesis remains untested; no new functional prototype or external preservation deposit was verified.',
                'limitations': ['Old submissions and HTTP headers remain available as paged audit evidence']}, ident='report'),
            final_response()])
        self.engine.backend = OpenAIBackend(provider)
        await self.engine.step(self.reporter)
        self.assertEqual(self.reporter['status'], 'COMPLETED')
        self.assertEqual(len(provider.model.calls), 3)
        self.assertLess(len(json.dumps(self.reporter['history'], ensure_ascii=False)), 40000)
        self.assertEqual(self.engine.state['http_requests'][0]['response']['headers']['content-security-policy'], 'HEADER-NOISE-'*10000)
