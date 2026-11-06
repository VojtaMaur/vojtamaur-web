"""Persistent operator preferences never grant capabilities or rewrite runs."""
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from metaweb_swarm.config import PACKAGE_ROOT, load_config
from metaweb_swarm.gui import GUIService,make_server
from metaweb_swarm.profile_defaults import (profile_config, save_defaults,
    reset_defaults, load_new_run_config, MAX_DEFAULT_BYTES)


class ProfileDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.project=self.root/'project';self.project.mkdir()
        self.files=self.root/'files'
        self.env=patch.dict(os.environ,{'SWARM_FILES_ROOT':str(self.files)})
        self.env.start()

    def tearDown(self):
        self.env.stop();self.tmp.cleanup()

    def service(self):
        return GUIService(self.project,self.root/'runs',self.root/'settings.json')

    def test_source_profile_is_readonly_and_no_defaults_are_created_by_bootstrap(self):
        source=(PACKAGE_ROOT/'config.research.json').read_bytes()
        profile=self.service().bootstrap()['profiles'][0]
        self.assertFalse(profile['has_saved_defaults'])
        self.assertEqual(profile['objective'],profile['config']['operator_objective'])
        self.assertEqual((PACKAGE_ROOT/'config.research.json').read_bytes(),source)
        self.assertFalse((self.files/'defaults').exists())

    def test_missions_models_roles_custom_agents_and_budget_survive_restart(self):
        overrides={'seed_roles':['Loophole Archivist','Synthesizer / Reporter'],
            'role_assignments':{'Loophole Archivist':'Only digital custody, no physical media.'},
            'role_model_tiers':{'Loophole Archivist':'strong'},
            'model_tiers':{'cheap':'small','strong':'middle','flag':'large'},
            'role_round_limits':{'Loophole Archivist':8},'max_total_tokens':7654321,
            'max_steps':70,'max_concurrent_agents':2,'estimated_budget_usd':None,
            'custom_agents':[{'role':'Odd formats','mission':'Explore unconventional lawful hosts.',
                              'model_tier':'cheap','rounds':5}]}
        service=self.service()
        with patch.object(service,'launch') as launch:
            result=service.defaults({'profile':'research','overrides':overrides,'objective':'An operator-defined preservation mission.'})
        launch.assert_not_called()
        self.assertTrue(result['profile']['has_saved_defaults'])
        restarted=self.service();profile=restarted.bootstrap()['profiles'][0]
        self.assertEqual(profile['objective'],'An operator-defined preservation mission.')
        self.assertEqual(profile['config']['max_total_tokens'],7654321)
        self.assertEqual(len(profile['agents']),3)
        self.assertEqual(profile['agents'][0]['mission'],overrides['role_assignments']['Loophole Archivist'])
        self.assertEqual(profile['agents'][0]['model'],'middle')
        self.assertEqual(profile['agents'][0]['round_limit'],8)
        self.assertEqual(profile['agents'][-1]['role'],'Odd formats')
        self.assertEqual(profile['agents'][-1]['round_limit'],5)
        path=self.files/'defaults'/'research.json'
        saved=json.loads(path.read_text(encoding='utf-8'))
        self.assertNotIn('http_credentials',saved['overrides'])
        self.assertFalse((self.project/'defaults').exists())

    def test_defaults_are_separate_for_each_profile_and_reset_restores_source(self):
        original=load_config(PACKAGE_ROOT/'config.research.json')
        save_defaults(self.project,'research',{'max_steps':77},objective='Saved task')
        self.assertEqual(profile_config(self.project,'research')[0]['max_steps'],77)
        self.assertEqual(profile_config(self.project,'cheap')[0]['max_steps'],48)
        result=self.service().defaults({'profile':'research'},reset=True)
        self.assertFalse(result['profile']['has_saved_defaults'])
        self.assertEqual(result['profile']['config']['max_steps'],original['max_steps'])
        self.assertEqual(result['profile']['objective'],original['operator_objective'])
        self.assertFalse((self.files/'defaults'/'research.json').exists())

    def test_start_uses_saved_defaults_and_explicit_new_run_edits_do_not_change_them(self):
        save_defaults(self.project,'cheap',{'max_steps':77},objective='Saved task')
        service=self.service()
        with patch.object(service,'launch',return_value={'ok':True}) as launch:
            service.start({'profile':'cheap','backend':'demo','overrides':{'max_steps':79},'task':'Just this run.'})
        args=launch.call_args.args[0];draft=Path(args[args.index('--config')+1])
        config=json.loads(draft.read_text(encoding='utf-8'))
        self.assertEqual(config['max_steps'],79)
        self.assertEqual(config['operator_objective'],'Saved task\n\nOPERATOR COMMENT:\nJust this run.')
        self.assertEqual(profile_config(self.project,'cheap')[0]['max_steps'],77)

    def test_cli_exact_bundled_profiles_reuse_defaults_but_unrelated_config_does_not(self):
        save_defaults(self.project,'research',{'max_steps':77},objective='Saved task')
        bundled=PACKAGE_ROOT/'config.research.json'
        self.assertEqual(load_new_run_config(self.project,bundled)['max_steps'],77)
        unrelated=self.root/'config.research.json'
        unrelated.write_bytes(bundled.read_bytes())
        self.assertEqual(load_new_run_config(self.project,unrelated)['max_steps'],48)
        from metaweb_swarm.cli import main
        with patch('metaweb_swarm.cli.initialize',return_value=self.root/'new-run') as initialize,patch('sys.stdout',io.StringIO()):
            code=main(['init','--project',str(self.project),'--runs-root',str(self.root/'runs')])
        self.assertEqual(code,0)
        self.assertEqual(initialize.call_args.args[2]['operator_objective'],'Saved task')
        with patch('metaweb_swarm.cli.initialize',side_effect=ValueError('Fixture: no run needed')) as initialize,patch('sys.stdout',io.StringIO()),patch('sys.stderr',io.StringIO()):
            code=main(['start','--project',str(self.project),'--runs-root',str(self.root/'runs'),'--backend','demo','--task','Explicit CLI task'])
        self.assertEqual(code,2)
        self.assertEqual(initialize.call_args.args[2]['max_steps'],77)
        self.assertEqual(initialize.call_args.args[2]['operator_objective'],'Explicit CLI task')

    def test_partial_updates_preserve_previous_mission_and_other_parameters(self):
        save_defaults(self.project,'research',{'max_steps':77},objective='Keep this task')
        save_defaults(self.project,'research',{'max_total_tokens':4567890})
        config,_=profile_config(self.project,'research')
        self.assertEqual(config['max_steps'],77)
        self.assertEqual(config['max_total_tokens'],4567890)
        self.assertEqual(config['operator_objective'],'Keep this task')

    def test_capability_override_empty_roles_and_invalid_roster_are_refused_before_writing(self):
        for overrides in ({'approval_required':False},{'http_credentials':[]},{'experiments':'docker'},
                          {'external_scope':'external'},{'seed_roles':[]},{'max_agents':1}):
            with self.subTest(overrides=overrides),self.assertRaises(ValueError):
                save_defaults(self.project,'research',overrides)
        self.assertFalse((self.files/'defaults'/'research.json').exists())
        with self.assertRaises(ValueError):save_defaults(self.project,'research',{},objective='')
        with self.assertRaises(ValueError):save_defaults(self.project,'../escape',{})
        with self.assertRaises(ValueError):self.service().defaults({'profile':[]})

    def test_runtime_files_inside_production_are_rejected(self):
        with patch.dict(os.environ,{'SWARM_FILES_ROOT':str(self.project/'files')}):
            for operation in (lambda:save_defaults(self.project,'research',{}),
                              lambda:profile_config(self.project,'research'),
                              lambda:reset_defaults(self.project,'research')):
                with self.assertRaises(ValueError):operation()
        self.assertFalse((self.project/'files').exists())

    def test_tampered_saved_defaults_cannot_grant_capabilities(self):
        directory=self.files/'defaults';directory.mkdir(parents=True)
        path=directory/'research.json'
        path.write_text(json.dumps({'schema_version':1,'profile':'research','overrides':{'approval_required':False}}))
        with self.assertRaises(ValueError):profile_config(self.project,'research')
        path.write_text('x'*(MAX_DEFAULT_BYTES+1))
        with self.assertRaisesRegex(ValueError,'velký'):profile_config(self.project,'research')

    def test_linked_defaults_and_atomic_temporary_leaf_are_rejected(self):
        directory=self.files/'defaults';directory.mkdir(parents=True)
        outside=self.root/'outside.json';outside.write_text('untouched')
        for name in ('research.json','research.json.tmp'):
            link=directory/name
            with patch('metaweb_swarm.profile_defaults._is_link',side_effect=lambda path:Path(path)==link):
                with self.assertRaises(ValueError):save_defaults(self.project,'research',{})
        self.assertEqual(outside.read_text(),'untouched')

    def test_http_defaults_save_and_reset_share_existing_token_boundary(self):
        service=self.service();server=make_server(service)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        origin='http://127.0.0.1:'+str(server.server_port)
        def post(path,payload,token=None):
            request=urllib.request.Request(origin+path,data=json.dumps(payload).encode(),
                headers={'Content-Type':'application/json','Origin':origin,
                         'X-Swarm-Token':token or service.token})
            with urllib.request.urlopen(request,timeout=3) as response:return json.load(response)
        try:
            with urllib.request.urlopen(origin+'/favicon.ico',timeout=3) as response:
                self.assertEqual(response.headers['Content-Type'],'image/x-icon')
                self.assertEqual(response.read(),(PACKAGE_ROOT/'metaweb_swarm'/'gui_static'/'favicon.ico').read_bytes())
            with self.assertRaises(urllib.error.HTTPError) as error:
                post('/api/defaults',{'profile':'research','overrides':{'max_steps':77}},'wrong')
            self.assertEqual(error.exception.code,403)
            self.assertFalse((self.files/'defaults').exists())
            with patch.object(service,'launch') as launch:
                result=post('/api/defaults',{'profile':'research','overrides':{'max_steps':77},'objective':'HTTP-saved mission'})
                self.assertTrue(result['profile']['has_saved_defaults'])
                self.assertEqual(result['profile']['config']['max_steps'],77)
                result=post('/api/defaults/reset',{'profile':'research'})
                self.assertFalse(result['profile']['has_saved_defaults'])
            launch.assert_not_called()
        finally:
            server.shutdown();server.server_close();thread.join(2)

