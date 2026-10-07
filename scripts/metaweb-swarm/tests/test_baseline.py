import tempfile
import unittest
from pathlib import Path

from metaweb_swarm.baseline import BaselineCorpus, mechanism_identity
from metaweb_swarm.baseline import candidate_terms
from metaweb_swarm.memory import compact_history, concise_state
from metaweb_swarm.policy import normalize_idea
from metaweb_swarm.config import load_config
from metaweb_swarm.demo import DemoBackend
from metaweb_swarm.engine import Engine, ToolAPI, initialize
from metaweb_swarm.policy import normalize_output
from metaweb_swarm.research import requires_external
from metaweb_swarm.research import research_brief
from metaweb_swarm.workspace import Workspace


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        project = root / 'project'
        (project / 'public').mkdir(parents=True)
        # Beyond any normal read_file/prompt excerpt, yet searchable in full.
        (project / 'public' / 'ARCHIVE.txt').write_text('padding\n' * 2000 + 'Software Heritage archives our source.\nZenodo hosts our snapshot.\n', encoding='utf-8')
        self.run = initialize(project, root / 'runs', load_config())
        self.engine = Engine(self.run, DemoBackend(), 'openai')
        agent = self.engine.state['agents'][0]
        self.api = ToolAPI(self.engine, agent, Workspace(self.run / 'snapshot', self.run / 'agents' / agent['id'] / 'workspace'))

    def tearDown(self):
        self.engine.close()
        self.temp.cleanup()

    def candidate(self, provider, title='Snapshot', status='DISCOVERED'):
        data = DemoBackend.idea(title, 'Durable copy', 'FREE', status)
        data.update(provider=provider, novelty_class='POTENTIALLY_NEW')
        return data

    def test_archive_priority_deep_line_and_hashed_receipt(self):
        result = self.api.check_baseline(['Software Heritage'])
        hit = result['matches'][0]
        self.assertIn('ARCHIVE.txt', hit['path'])
        self.assertEqual(hit['line'], 2001)
        self.assertEqual(len(hit['document_sha256']), 64)
        self.assertTrue(hit['id'].startswith('BASE-'))
        self.assertTrue(result['coverage']['archive_captured'])

    def test_osf_absence_is_not_proof_of_novelty(self):
        result = self.api.check_baseline(['OSF', 'osf.io'])
        self.assertEqual(result['total_matches'], 0)
        self.assertIn('not proof', result['coverage']['absence_meaning'])

    def test_existing_carrier_cannot_claim_novel_without_comparison(self):
        result = self.api.submit_idea(self.candidate('Software Heritage'))
        self.assertEqual(result['novelty_class'], 'UNASSESSED')
        self.assertEqual(result['novelty_assessment'], 'MENTIONED_NEEDS_COMPARISON')

    def test_osf_unsupported_duplicate_rejection_preserves_candidate(self):
        data = self.candidate('OSF', status='REJECTED')
        data.update(novelty_class='DUPLICATE', rejection_reason='Already in owner baseline', baseline_evidence_ids=['BASE-invented'])
        result = self.api.submit_idea(data)
        self.assertEqual(result['status'], 'INVESTIGATING')
        self.assertEqual(result['novelty_assessment'], 'UNSUPPORTED_KNOWN_CLAIM')
        self.assertEqual(result['baseline_evidence_ids'], [])

    def test_matching_baseline_receipt_supports_known_classification(self):
        hit = self.api.check_baseline(['Software Heritage'])['matches'][0]
        data = self.candidate('Software Heritage')
        data.update(novelty_class='KNOWN_CARRIER', baseline_evidence_ids=[hit['id']])
        result = self.api.submit_idea(data)
        self.assertEqual(result['novelty_class'], 'KNOWN_CARRIER')
        self.assertEqual(result['baseline_evidence_ids'], [hit['id']])
        self.assertEqual(result['status'], 'REJECTED')
        self.assertIn('DUPLICATE_BASELINE', result['rejection_reason'])

    def test_unsupported_known_rejection_cannot_bypass_with_default_class(self):
        data = self.candidate('OSF', status='REJECTED')
        data.pop('novelty_class')
        data['rejection_reason'] = 'Already implemented in baseline'
        self.assertEqual(self.api.submit_idea(data)['status'], 'INVESTIGATING')

    def test_same_zenodo_mechanism_different_titles_has_one_id(self):
        first = self.api.submit_idea(self.candidate('Zenodo', 'DOI frozen deposit'))
        second = self.api.submit_idea(self.candidate('Zenodo repository', 'Persistent public ZIP'))
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(len(self.engine.state['ideas']), 1)

    def test_distinct_improvement_is_not_merged_into_existing_carrier(self):
        first = self.api.submit_idea(self.candidate('Zenodo'))
        data = self.candidate('Zenodo', 'Independent reconstruction index')
        data.update(novelty_class='IMPROVEMENT', novelty_delta='Add a self-describing recovery index with measured decoding test')
        second = self.api.submit_idea(data)
        self.assertNotEqual(first['id'], second['id'])

    def test_unobserved_citations_cannot_be_verified_by_reviewer(self):
        data = self.candidate('OSF', status='VERIFIED')
        data['evidence'] = [{'url': 'https://osf.io/registrations', 'claim': 'Frozen registration', 'verified': True}, {'url': 'https://help.osf.io/article/330-welcome-to-registrations', 'claim': 'Registration details', 'verified': True}]
        result = self.api.submit_idea(data)
        self.assertEqual(result['status'], 'INVESTIGATING')
        self.assertTrue(all(not e['verified'] for e in result['evidence']))

    def test_emergent_discovery_requires_external_research(self):
        self.assertTrue(requires_external({'role': 'Institutional Deposit Scout', 'parent_id': 'AGENT-001'}))
        self.assertFalse(requires_external({'role': 'Local decoder', 'parent_id': 'AGENT-001', 'work_kind': 'LOCAL'}))

    def test_future_handoff_does_not_force_completed_role_to_repeat(self):
        result = normalize_output({'status': 'COMPLETED', 'reason_for_stopping': 'Assigned task done', 'unexplored_leads': [], 'handoff_leads': ['Future eligibility audit'], 'blind_spots': []})
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertEqual(result['handoff_leads'], ['Future eligibility audit'])

    def test_literal_search_does_not_match_osf_inside_other_word(self):
        path = self.run / 'context' / 'CURRENT_STATE.md'
        path.write_text('An unrelated osfishing token', encoding='utf-8')
        self.assertEqual(BaselineCorpus(self.run).search(['OSF'])['total_matches'], 0)

    def test_distinct_explicit_mechanism_kind_not_collapsed(self):
        a = {'provider': 'OSF', 'mechanism_kind': 'REGISTRATION'}
        b = {'provider': 'OSF', 'mechanism_kind': 'DISTRIBUTION'}
        self.assertNotEqual(mechanism_identity(a), mechanism_identity(b))

    def test_last_active_round_is_workable_and_uses_extended_allowance(self):
        agent = self.api.agent
        agent['rounds'] = 4
        prompt = self.engine.prompt(agent)
        self.assertNotIn('Remaining rounds:', prompt)
        self.assertIn('THIS ROUND IS ACTIVE', prompt)
        self.assertIn('AFTER this active round: 0', prompt)
        agent['round_limit'] = 6
        self.assertIn('AFTER this active round: 2', self.engine.prompt(agent))

    def test_wacz_owner_rejection_is_enforced_on_submission(self):
        result = self.api.submit_idea(self.candidate('Webrecorder', 'WACZ portable capture'))
        self.assertEqual(result['status'], 'REJECTED')
        self.assertIn('OWNER_REJECTED', result['rejection_reason'])
        self.assertNotEqual(self.api.submit_idea(self.candidate('WARC', 'WARC storage'))['status'], 'REJECTED')

    def test_declined_direction_cannot_spawn(self):
        result = self.api.spawn_agent({'role': 'WACZ specialist', 'mission': 'Build WACZ', 'question': 'How to package?'})
        self.assertEqual(result['status'], 'REJECTED')

    def test_long_perma_provider_extracts_short_alias(self):
        self.assertIn('Perma.cc', candidate_terms({'provider': 'Harvard Library Innovation Lab / Perma.cc'}))
        self.assertIn('BagIt', candidate_terms({'provider': 'BagIt / Library of Congress'}))

    def test_generic_features_do_not_promote_improvement_to_verified(self):
        data = self.candidate('Zenodo', status='VERIFIED')
        data.update(novelty_class='IMPROVEMENT', novelty_delta='It has a DOI')
        self.assertEqual(self.api.submit_idea(data)['status'], 'INVESTIGATING')

    def test_structured_improvement_preserves_a_distinct_proposal(self):
        data = self.candidate('Zenodo')
        data.update(novelty_class='IMPROVEMENT', novelty_delta='Add independently recoverable shards', baseline_behavior='Whole ZIP deposits', proposed_change='Recovery from incomplete shard sets', validation_plan='Delete shards and compare rebuilt SHA256')
        result = self.api.submit_idea(data)
        self.assertEqual(result['status'], 'DISCOVERED')
        self.assertEqual(result['proposed_change'], data['proposed_change'])

    def test_old_stop_messages_are_not_replayed_as_current_budget(self):
        stop = {'type': 'message', 'role': 'assistant', 'content': [{'text': '{"status":"LIMIT_REACHED","reason_for_stopping":"No rounds remain"}'}]}
        self.assertEqual(compact_history([stop], 'archive.json'), [])

    def test_coordinator_observations_cannot_be_candidates(self):
        for title, mechanism in [('Metaweb preservation coverage baseline map', 'Coverage map'), ('Need for a custody-first specialist', 'Organizational gap analysis')]:
            with self.assertRaisesRegex(ValueError, 'use note'):
                normalize_idea(self.candidate('Coordination', title) | {'mechanism': mechanism})

    def test_loophole_assignment_is_not_repository_scouting(self):
        brief = research_brief({'role': 'Loophole Archivist'})
        self.assertIn('Zenodo and ordinary repositories do not satisfy', brief)
        self.assertIn('three unrelated families', brief)
        self.assertIn('LAWFUL', brief)

    def test_atproto_different_titles_merge_same_mechanism(self):
        a = self.api.submit_idea(self.candidate('AT Protocol / Bluesky PDS ecosystem', 'Public repository recovery pointer'))
        b = self.api.submit_idea(self.candidate('AT Protocol', 'Self-describing signed record pointer'))
        self.assertEqual(a['id'], b['id'])

    def test_binary_tool_writes_exact_confined_bytes(self):
        import base64
        payload = b'\xd9\xd9\xf7\x00'
        result = self.api.write_binary('artifacts/specimen.cbor', base64.b64encode(payload).decode())
        self.assertTrue(result['binary'])
        self.assertEqual((self.api.workspace.root / 'artifacts/specimen.cbor').read_bytes(), payload)
        with self.assertRaises(ValueError):
            self.api.write_binary('artifacts/bad.bin', 'not-valid-@@@')
        with self.assertRaises(ValueError):
            self.api.write_binary('../escape.bin', 'AA==')

    def test_renewable_contract_cannot_claim_one_time_payment(self):
        data = self.candidate('Example host', 'Renewable storage contract')
        data.update(payment='ONE_TIME', requires_ongoing_payments=True)
        result = self.api.submit_idea(data)
        self.assertEqual(result['payment'], 'RECURRING')
        self.assertEqual(result['status'], 'REJECTED')
