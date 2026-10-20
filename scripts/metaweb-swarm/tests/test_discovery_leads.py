"""Unqualified discovery survives tool mistakes, triage and checkpointing."""
import json
import unittest
from metaweb_swarm.demo import DemoBackend
from metaweb_swarm.engine import Engine
from metaweb_swarm.discovery_leads import awaiting_review, revision
from metaweb_swarm.deposit_handoff import recover, report_revision
from metaweb_swarm.review_contract import complete_review
from metaweb_swarm.reporting import generate_reports
from tests import test_focused_tasking as fixture
from tests.test_backend import SDK_AVAILABLE


class LeadTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixture.FocusedTests.setUp
    tearDown = fixture.FocusedTests.tearDown
    for_agent = fixture.FocusedTests.for_agent

    async def documented(self):
        self.engine.state['config']['carrier_screening'] = True
        self.screen = self.api.screen_carrier('Independent fixture', self.origin + '/docs')
        self.doc = await self.api.read_document(self.origin + '/docs', 'Read actual upload capability')
        return self.engine.state['discovery_leads'][0]

    async def test_allowed_screen_and_docs_retained_without_candidate_or_fake_proof(self):
        lead = await self.documented()
        self.assertEqual(self.screen['lead_id'], lead['id'])
        self.assertEqual(self.doc['lead_id'], lead['id'])
        self.assertEqual(lead['documents'][0]['sha256'], self.doc['sha256'])
        self.assertEqual(lead['status'], 'NEEDS_EVIDENCE')
        self.assertEqual(len(awaiting_review(self.engine.state)), 1)
        self.assertEqual(self.engine.state['ideas'], [])
        self.assertFalse(self.engine.state.get('deposit_qualifications'))
        self.assertFalse(self.engine.state['external_actions'])
        self.assertFalse(self.engine.state['approvals'])
        repeat = self.api.screen_carrier('Independent fixture', self.origin + '/terms')
        self.assertEqual(repeat['lead_id'], lead['id'])
        self.assertEqual(len(self.engine.state['discovery_leads']), 1)
        await self.api.read_document(self.origin + '/docs', 'Read same retained document')
        self.assertEqual(len(lead['documents']), 1)

    async def test_fabricated_qualification_defers_and_existing_lead_can_continue(self):
        lead = await self.documented()
        r = self.api.record_deposit_flow('QUAL-AGENT-001-DROPBOX-001', [], 'Missing upload details')
        self.assertEqual(r['status'], 'DEFERRED')
        self.assertEqual(r['reason'], 'EXISTING_QUALIFICATION_REQUIRED')
        self.assertEqual(r['state']['own_admissible_qualifications'], [])
        self.assertEqual(r['state']['leads'][0]['id'], lead['id'])
        r = self.api.record_discovery_lead(lead['id'], 'Static hosting may allow an unchanged EPUB asset.',
                      ['Verify permitted file extensions and retention.'], 'Read API and supported assets before qualification.')
        self.assertEqual(r['id'], lead['id'])
        self.assertFalse(self.engine.state.get('deposit_qualifications'))

    async def test_only_documented_lead_reopens_auditor_but_never_prototyper(self):
        self.engine.state['config']['carrier_screening'] = True
        self.api.screen_carrier('Independent fixture', self.origin + '/docs')
        auditor = self.engine.state['agents'][1]
        local = self.engine.state['agents'][2]
        auditor.update(status='BLOCKED', reason_for_stopping='NO_ADMITTED_DISCOVERY_CANDIDATE')
        local.update(status='BLOCKED', reason_for_stopping='NO_INDEPENDENTLY_APPROVED_DEPOSIT_PLAN')
        recover(self.engine)
        self.assertEqual(auditor['status'], 'BLOCKED')
        await self.api.read_document(self.origin + '/docs', 'Read primary source')
        recover(self.engine)
        self.assertEqual(auditor['status'], 'PENDING')
        self.assertEqual(local['status'], 'BLOCKED')

    async def test_independent_triage_needs_own_reads_and_negative_quote(self):
        lead = await self.documented()
        review = self.for_agent(self.engine.state['agents'][1])
        r = review.record_lead_review(lead['id'], 'NOT_SUITABLE', 'Format not supported',
                   'Try another service', 'EPUB is forbidden', [self.origin + '/docs'])
        self.assertEqual(r['reason'], 'INDEPENDENT_LEAD_DOCUMENTS_REQUIRED')
        await review.read_document(self.origin + '/docs', 'Independently verify file acceptance')
        r = review.record_lead_review(lead['id'], 'NOT_SUITABLE', 'Format not listed',
                   'Find explicit format limits', 'EPUB is forbidden', [self.origin + '/docs'])
        self.assertEqual(r['disposition'], 'NEEDS_EVIDENCE')
        self.assertEqual(awaiting_review(self.engine.state), [])
        self.assertNotIn('qualification_id', lead)
        self.assertFalse(self.engine.state['ideas'])
        with self.assertRaises(ValueError):
            self.api.record_lead_review(lead['id'], 'QUALIFY', 'Claimed readiness', 'Upload now', '', [self.origin + '/docs'])

    async def test_review_completion_and_new_evidence_reopen_only_within_rounds(self):
        lead = await self.documented()
        auditor = self.engine.state['agents'][1]
        api = self.for_agent(auditor)
        raw = {'status': 'COMPLETED'}
        normalized = {'status': 'COMPLETED', 'handoff_leads': [], 'unexplored_leads': []}
        r, _ = complete_review(self.engine.state, auditor, raw, dict(normalized))
        self.assertEqual(r['status'], 'BLOCKED')
        await api.read_document(self.origin + '/docs', 'Independently read API source')
        api.record_lead_review(lead['id'], 'SETUP_REQUIRED', 'Dedicated account is needed',
                              'Operator must grant a dedicated account', '', [self.origin + '/docs'])
        r, _ = complete_review(self.engine.state, auditor, raw, dict(normalized))
        self.assertEqual(r['status'], 'COMPLETED')
        auditor.update(status='COMPLETED', rounds=1)
        recover(self.engine)
        self.assertEqual(auditor['status'], 'COMPLETED')
        await self.api.read_document(self.origin + '/terms', 'Read newly found retention terms')
        recover(self.engine)
        self.assertEqual(auditor['status'], 'PENDING')

    async def test_grounded_negative_triage_retained_in_reports_and_restart(self):
        lead = await self.documented()
        reviewer = self.for_agent(self.engine.state['agents'][1])
        await reviewer.read_document(self.origin + '/terms', 'Independently read actual terms')
        reviewer.record_lead_review(lead['id'], 'NOT_SUITABLE', 'Operator objective may require other custody',
                        'Review the concrete retention requirement', 'retained until requested deletion', [self.origin + '/terms'])
        self.assertEqual(lead['status'], 'NOT_SUITABLE')  # Quote existence != host endorsement of reasoning.
        self.engine.close()
        self.engine = Engine(self.run, DemoBackend(), 'demo')
        self.assertEqual(self.engine.state['discovery_leads'][0]['review']['disposition'], 'NOT_SUITABLE')
        generate_reports(self.run, self.engine.state)
        manifest = json.loads((self.run / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['discovery_leads'][0]['id'], lead['id'])
        self.assertIn(lead['id'], (self.run / 'SWARM_REPORT.md').read_text(encoding='utf-8'))
        self.assertEqual(json.loads((self.run / 'discovery_leads.jsonl').read_text(encoding='utf-8'))['id'], lead['id'])
        self.engine.store.verify()

    async def test_screen_forbidden_never_creates_lead_and_other_origin_not_auto_screened(self):
        self.engine.state['config']['carrier_screening'] = True
        r = self.api.screen_carrier('GitHub', 'https://github.com')
        self.assertEqual(r['status'], 'POLICY_FORBIDDEN')
        self.assertNotIn('lead_id', r)
        self.assertFalse(self.engine.state.get('discovery_leads'))
        lead = await self.documented()
        r = await self.api.read_document('https://different.example.org/docs', 'Read unrelated docs')
        self.assertEqual(r['status'], 'DEFERRED')
        self.assertEqual(len(lead['documents']), 1)

    async def test_full_scheduler_discovers_retains_triages_and_reports_without_upload(self):
        from tests.test_backend import FINAL
        calls = []
        origin = self.origin
        self.engine.state['config']['carrier_screening'] = True

        class DiscoveryAndTriage:
            async def step(inner, agent, prompt, history, api, config):
                calls.append(agent['role'])
                if agent['work_kind'] == 'DISCOVERY':
                    screen = api.screen_carrier('Independent fixture', origin + '/docs')
                    await api.read_document(origin + '/docs', 'Read file upload documentation')
                    deferred = api.record_deposit_flow('QUAL-fabricated', [], 'Unknown upload protocol')
                    assert deferred['status'] == 'DEFERRED'
                    api.record_discovery_lead(screen['lead_id'], 'Possible exact-byte carrier; grant details missing.',
                          ['Confirm authentication and retention.'], 'Independent review of docs, then qualify with actual account needs.')
                elif agent['role'] == 'Evidence Auditor':
                    lead = api.list_discovery_state()['leads'][0]
                    await api.read_document(origin + '/docs', 'Independently inspect upload requirements')
                    api.record_lead_review(lead['id'], 'SETUP_REQUIRED', 'Authentication not documented in retained excerpt.',
                          'Read actual authentication reference before qualification.', '', [origin + '/docs'])
                return {'output': dict(FINAL), 'history': history, 'usage': {}, 'raw': {'usage_complete': True}}

        self.engine.backend = DiscoveryAndTriage()
        await self.engine.run()
        self.assertEqual(calls, ['Loophole Archivist', 'Evidence Auditor', 'Synthesizer / Reporter'])
        self.assertEqual(self.engine.state['agents'][1]['status'], 'COMPLETED')
        self.assertEqual(self.engine.state['agents'][2]['status'], 'BLOCKED')
        self.assertEqual(self.engine.state['discovery_leads'][0]['review']['disposition'], 'SETUP_REQUIRED')
        self.assertEqual(self.engine.state['ideas'], [])
        self.assertFalse(self.engine.state['external_actions'])
        calls.clear()
        await self.engine.run()
        self.assertEqual(calls, [])  # Completed triage is not retried unchanged.
        self.engine.store.verify()

    async def test_completion_cannot_drop_findings_and_reused_id_keeps_provenance(self):
        from metaweb_swarm.discovery_leads import complete_discovery
        from tests.test_backend import FINAL
        lead = await self.documented()
        out = complete_discovery(self.engine.state, self.agent, dict(FINAL))
        self.assertEqual(out['status'], 'CONTINUE')
        self.assertIn(lead['id'], out['unexplored_leads'][0])
        self.api.record_discovery_lead(lead['id'], 'Protocol is unresolved; preserve partial evidence.',
                        ['Read exact upload endpoint.'], 'Read API reference before qualification.')
        out = complete_discovery(self.engine.state, self.agent, dict(FINAL))
        self.assertEqual(out['status'], 'COMPLETED')
        second = dict(self.agent, id='OTHER-DISCOVERY')
        other = self.for_agent(second)
        same = other.screen_carrier('Independent fixture', self.origin + '/terms')
        self.assertEqual(same['lead_id'], lead['id'])
        self.assertEqual(lead['contributors'], [self.agent['id'], 'OTHER-DISCOVERY'])

    async def test_independent_followup_once_and_existing_round_limit_preserved(self):
        lead = await self.documented()
        reviewer = self.for_agent(self.engine.state['agents'][1])
        await reviewer.read_document(self.origin + '/docs', 'Independently check primary docs')
        reviewer.record_lead_review(lead['id'], 'QUALIFY', 'Actual upload API can be qualified next.',
                        'Use check_deposit_target with the documented exact endpoint.', '', [self.origin + '/docs'])
        self.agent.update(status='COMPLETED', rounds=1)
        recover(self.engine)
        self.assertEqual(self.agent['status'], 'PENDING')
        self.agent['status'] = 'COMPLETED'
        recover(self.engine)
        self.assertEqual(self.agent['status'], 'COMPLETED')
        self.assertFalse(self.engine.state.get('deposit_qualifications'))
        self.assertFalse(self.engine.state['external_actions'])

    async def test_qualification_promotes_only_admitted_candidate_and_keeps_same_lead(self):
        from tests.test_carrier_scope import ScopeTests
        lead = await self.documented()
        await self.api.read_document(self.origin + '/terms', 'Read payment and retention terms')
        plan = ScopeTests.candidate_plan(self)
        q = self.api.check_deposit_target(plan)
        self.assertTrue(q['admissible'])
        self.assertEqual(lead['target_assessments'][0]['id'], q['id'])
        recover(self.engine)
        self.assertEqual(lead['idea_id'], self.engine.state['ideas'][0]['id'])
        self.assertEqual(lead['status'], 'ADMITTED')
        self.assertEqual(len(self.engine.state['discovery_leads']), 1)
        self.assertEqual(awaiting_review(self.engine.state), [])
        self.assertFalse(self.engine.state['external_actions'])

    @unittest.skipUnless(SDK_AVAILABLE, 'SDK not installed')
    async def test_real_sdk_tools_keep_strict_schemas_and_recover_fake_ids(self):
        import agents
        from metaweb_swarm.backend import _make_sdk_tools
        lead = await self.documented()
        tools, _ = _make_sdk_tools(agents, self.api)
        by_name = {t.name: t for t in tools}
        from agents.tool_context import ToolContext
        context = ToolContext(context=None, tool_name='record_deposit_flow', tool_call_id='flow-fixture', tool_arguments='{}')
        for name in ('list_discovery_state', 'record_discovery_lead'):
            self.assertFalse(by_name[name].params_json_schema['additionalProperties'])
        result = await by_name['record_deposit_flow'].on_invoke_tool(context, json.dumps({
            'qualification_id': 'QUAL-fake', 'operation_steps': [], 'unknown_reason': 'Unknown actual protocol'}))
        self.assertEqual(json.loads(result)['status'], 'DEFERRED')
        context = ToolContext(context=None, tool_name='list_discovery_state', tool_call_id='list-fixture', tool_arguments='{}')
        result = await by_name['list_discovery_state'].on_invoke_tool(context, '{}')
        self.assertEqual(json.loads(result)['leads'][0]['id'], lead['id'])
