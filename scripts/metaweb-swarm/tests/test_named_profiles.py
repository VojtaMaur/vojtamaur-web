"""Named operator presets retain configuration without changing dispatch identities."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error
from metaweb_swarm.config import load_config, validate_config
from metaweb_swarm.gui import GUIService, make_server
from metaweb_swarm.profile_defaults import (create_profile, delete_profile, profile_config,
    profile_details, profile_ids, save_defaults, reset_defaults)
from metaweb_swarm.roles import seed_agents

class NamedProfilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.project=self.root/'project';self.project.mkdir()
        self.files=self.root/'files'
        self.env=patch.dict(os.environ,{'SWARM_FILES_ROOT':str(self.files)});self.env.start()
    def tearDown(self):
        self.env.stop();self.tmp.cleanup()
    def service(self):return GUIService(self.project,self.root/'runs',self.root/'settings.json')
    def test_create_clone_update_rename_delete_and_restart(self):
        save_defaults(self.project,'research',{'max_steps':66},objective='Digital only')
        key=create_profile(self.project,'research','Digitální / široký záběr',{'max_steps':72})
        self.assertRegex(key,r'^user-[0-9a-f]{32}$')
        profiles=self.service().bootstrap()['profiles'];self.assertEqual(len(profiles),4)
        custom=profiles[-1];self.assertEqual(custom['name'],'Digitální / široký záběr')
        self.assertTrue(custom['custom']);self.assertEqual(custom['base_profile'],'research')
        self.assertEqual(custom['config']['max_steps'],72)
        save_defaults(self.project,'research',{'max_steps':77},objective='Changed base')
        self.assertEqual(profile_config(self.project,key)[0]['operator_objective'],'Digital only')
        save_defaults(self.project,key,{'max_steps':80},name='Přejmenovaný')
        self.assertEqual(profile_details(self.project,key)['name'],'Přejmenovaný')
        self.assertEqual(profile_config(self.project,key)[0]['max_steps'],80)
        copy=create_profile(self.project,key,'Kopie');self.assertEqual(profile_details(self.project,copy)['base_profile'],'research')
        self.assertEqual(delete_profile(self.project,key),'research')
        self.assertNotIn(key,profile_ids(self.project))
        with self.assertRaises(ValueError):profile_config(self.project,key)
        self.assertEqual(profile_config(self.project,copy)[0]['max_steps'],80)
    def test_validation_and_capabilities(self):
        for name in ('',None,'x'*101,'bad\nname'):
            with self.assertRaises(ValueError):create_profile(self.project,'research',name)
        key=create_profile(self.project,'research','Test')
        with self.assertRaises(ValueError):create_profile(self.project,'cheap','TEST')
        with self.assertRaises(ValueError):create_profile(self.project,'research','Oops',{'http_access':'enabled'})
        with self.assertRaises(ValueError):save_defaults(self.project,key,{},name='')
        with self.assertRaises(ValueError):reset_defaults(self.project,key)
        for key in ('research','cheap','experimental','../../outside','user-bad',None):
            with self.assertRaises(ValueError):delete_profile(self.project,key)
        config=profile_config(self.project,profile_ids(self.project)[-1])[0]
        self.assertEqual(config['http_access'],'read-only');self.assertEqual(config['experiments'],'disabled')
    def test_names_never_become_paths_and_links_are_rejected(self):
        key=create_profile(self.project,'research','../outside/a.json')
        target=self.files/'defaults'/(key+'.json')
        self.assertTrue(target.is_file());self.assertFalse((self.root/'outside').exists())
        with patch('metaweb_swarm.profile_defaults._is_link',side_effect=lambda path:Path(path)==target):
            with self.assertRaises(ValueError):profile_config(self.project,key)
            with self.assertRaises(ValueError):delete_profile(self.project,key)
        self.assertTrue(target.is_file())
    def test_agent_names_preserve_role_tier_mission_and_work_kind(self):
        config=load_config();role='Evidence Auditor';config['role_display_names']={role:'Detektiv důkazů'}
        validate_config(config);agents=seed_agents(config)
        auditor=next(a for a in agents if a['role']==role)
        self.assertEqual(auditor['display_name'],'Detektiv důkazů')
        self.assertEqual(auditor['work_kind'],'REVIEW')
        unchanged=seed_agents(load_config());old=next(a for a in unchanged if a['role']==role)
        self.assertEqual(auditor['model_tier'],old['model_tier']);self.assertEqual(auditor['mission'],old['mission'])
        for invalid in ({role:''},{role:'a\nb'},{'Not a seed':'Hi'},[]):
            config['role_display_names']=invalid
            with self.assertRaises(ValueError):validate_config(config)
    def test_gui_start_captures_names_and_delete_does_not_change_run_config(self):
        service=self.service()
        with patch.object(service,'launch',return_value={'ok':True}) as launch:
            profile=service.create_profile({'profile':'cheap','name':'Můj tým','overrides':{'role_display_names':{'Loophole Archivist':'Drzej archivář'}}})['profile']
            launch.assert_not_called()
            service.start({'profile':profile['id'],'backend':'demo'})
        args=launch.call_args.args[0];draft=Path(args[args.index('--config')+1]);before=draft.read_bytes()
        config=load_config(draft);self.assertEqual(config['role_display_names']['Loophole Archivist'],'Drzej archivář')
        service.delete_profile({'profile':profile['id']});self.assertEqual(draft.read_bytes(),before)
    def test_http_crud_requires_gui_token_and_never_launches(self):
        service=self.service();server=make_server(service)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        origin='http://127.0.0.1:'+str(server.server_port)
        def post(path,payload,token=None):
            request=urllib.request.Request(origin+path,data=json.dumps(payload).encode(),headers={
                'Content-Type':'application/json','Origin':origin,'X-Swarm-Token':token or service.token})
            with urllib.request.urlopen(request,timeout=3) as response:return json.load(response)
        try:
            with patch.object(service,'launch') as launch:
                with self.assertRaises(urllib.error.HTTPError) as error:post('/api/profiles',{'name':'Forbidden'},'wrong')
                self.assertEqual(error.exception.code,403)
                p=post('/api/profiles',{'profile':'research','name':'Saved'})['profile']
                changed=post('/api/defaults',{'profile':p['id'],'name':'Renamed','overrides':{'max_steps':55}})['profile']
                self.assertEqual(changed['name'],'Renamed');self.assertEqual(changed['config']['max_steps'],55)
                self.assertEqual(post('/api/profiles/delete',{'profile':p['id']})['base_profile'],'research')
                self.assertEqual(len(service.bootstrap()['profiles']),3)
                launch.assert_not_called()
        finally:server.shutdown();server.server_close();thread.join(2)
