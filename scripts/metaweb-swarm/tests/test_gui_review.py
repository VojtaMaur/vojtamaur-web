"""GUI console stays scoped even when the underlying CLI supports arbitrary paths."""
from pathlib import Path
import os
import subprocess
import unittest
from unittest.mock import patch

from tests import test_gui as gui_fixture
from metaweb_swarm.storage import Store


class GUIBoundaryReviewTests(unittest.TestCase):
    setUp=gui_fixture.GUITests.setUp
    tearDown=gui_fixture.GUITests.tearDown

    def command(self,*args):
        return subprocess.list2cmdline(['swarm.py',*map(str,args)])

    def test_console_cannot_create_run_under_production_using_another_project(self):
        other=self.root/'other-project';other.mkdir()
        with patch.object(self.service,'launch') as launch:
            for verb in ('init','start'):
                args=[verb,'--project',str(other),'--runs-root',str(self.project/'nested-runs')]
                if verb=='start':args+=['--backend','demo']
                with self.subTest(verb=verb),self.assertRaises(ValueError):
                    self.service.command(self.command(*args))
            launch.assert_not_called()
        self.assertFalse((self.project/'nested-runs').exists())

    def test_console_run_paths_cannot_escape_configured_runs_root(self):
        outside=self.root/'other-runs'/'20261103-other-run';outside.mkdir(parents=True)
        with patch.object(self.service,'launch') as launch:
            for verb,extra in [('status',[]),('resume',['--backend','demo']),
                               ('close-research',['--note','final report only'])]:
                with self.subTest(verb=verb),self.assertRaises(ValueError):
                    self.service.command(self.command(verb,outside,*extra))
            launch.assert_not_called()

    def test_scoped_console_can_still_launch_existing_cli_run(self):
        with patch.object(self.service,'launch',return_value={'ok':True}) as launch:
            result=self.service.command(self.command('resume',self.path,'--backend','demo'))
        self.assertTrue(result['ok'])
        self.assertEqual(launch.call_args.args[0],['resume',str(self.path),'--backend','demo'])

    def test_empty_selection_cannot_expand_to_all_seed_roles(self):
        with patch.object(self.service,'launch') as launch,self.assertRaises(ValueError):
            self.service.start({'profile':'research','backend':'demo','overrides':{'seed_roles':[]}})
        launch.assert_not_called()

    def test_model_activity_notes_are_available_in_readonly_view(self):
        store=Store(self.path)
        try:store.commit(self.state,'agent_note',{'text':'Inspecting a physical format; <not HTML>.'},'AGENT-002')
        finally:store.close()
        events=self.service.run(self.run_id)['events']
        self.assertTrue(any(e['kind']=='agent_note' and '<not HTML>' in e['text'] for e in events))

    def test_linked_run_leaf_is_rejected(self):
        link=self.runs_root/'20261103-linked-run'
        try:os.symlink(self.path,link,target_is_directory=True)
        except OSError as error:self.skipTest('Symlink creation unavailable: '+str(error))
        try:
            with self.assertRaises(ValueError):self.service.run_path(link.name)
        finally:link.unlink()
