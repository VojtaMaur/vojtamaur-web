import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from metaweb_swarm.config import load_config,PACKAGE_ROOT
from metaweb_swarm.engine import Engine,initialize
from metaweb_swarm.demo import DemoBackend
from metaweb_swarm.operator_comments import enqueue_comment,apply_pending


class OperatorCommentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.project=self.root/'project';self.project.mkdir()
        self.config=load_config(PACKAGE_ROOT/'config.research.json')
        self.run=initialize(self.project,self.root/'runs',self.config)
        self.engine=Engine(self.run,DemoBackend(),'demo')
    def tearDown(self):self.engine.close();self.temp.cleanup()

    def test_queued_then_applied_once_with_immutable_permissions(self):
        before=copy.deepcopy(self.engine.state['config'])
        item=enqueue_comment(self.run,'Pouze digitální možnosti, žádné fyzické nosiče.')
        self.assertEqual(item['status'],'QUEUED');self.assertNotIn('operator_comments',self.engine.state)
        apply_pending(self.engine);apply_pending(self.engine)
        self.assertEqual(len(self.engine.state['operator_comments']),1)
        self.assertEqual(self.engine.state['config'],before)
        self.assertIn('Pouze digitální',self.engine.prompt(self.engine.state['agents'][1]))
        self.assertEqual(list((self.run/'operator-inbox').glob('*.json')),[])
        self.engine.store.verify()

    def test_crash_after_commit_before_unlink_does_not_duplicate_message(self):
        enqueue_comment(self.run,'Restrict research to openly documented services.')
        with patch.object(Path,'unlink',side_effect=OSError('simulated crash')):
            with self.assertRaises(OSError):apply_pending(self.engine)
        self.assertEqual(len(self.engine.state['operator_comments']),1)
        apply_pending(self.engine)
        self.assertEqual(len(self.engine.state['operator_comments']),1)

    def test_queue_order_is_posting_order_not_random_uuid_order(self):
        with patch('metaweb_swarm.operator_comments.uuid.uuid4') as unique:
            unique.return_value.hex='f'*32;enqueue_comment(self.run,'First instruction')
            unique.return_value.hex='0'*32;enqueue_comment(self.run,'Later correction')
        apply_pending(self.engine)
        self.assertEqual([c['text'] for c in self.engine.state['operator_comments']],['First instruction','Later correction'])

    def test_comment_size_and_schema_are_checked(self):
        for text in ['', ' ', 'x'*1801, None]:
            with self.assertRaises(ValueError):enqueue_comment(self.run,text)
        item=enqueue_comment(self.run,'A valid comment')
        p=self.run/'operator-inbox'/(item['id']+'.json')
        p.write_text(json.dumps(dict(item,id='different')),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Invalid'):apply_pending(self.engine)

    def test_recent_comments_do_not_overflow_normal_brainstorm_prompt(self):
        for n in range(3):enqueue_comment(self.run,str(n)+'x'*1799)
        apply_pending(self.engine)
        for agent in self.engine.state['agents']:
            self.assertLessEqual(len(self.engine.prompt(agent)),self.config['prompt_chars'])
