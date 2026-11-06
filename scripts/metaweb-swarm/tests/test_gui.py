"""Operator GUI orchestration and HTTP boundary without inference or remote I/O."""
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from metaweb_swarm.gui import GUIService,make_server
from metaweb_swarm.config import load_config,PACKAGE_ROOT
from metaweb_swarm.roles import seed_agents
from metaweb_swarm.storage import Store


class GUITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.project=self.root/'project';self.project.mkdir()
        self.runs_root=self.root/'runs';self.runs_root.mkdir()
        self.run_id='20261103-test-run';self.path=self.runs_root/self.run_id
        self.settings_path=self.root/'user-settings'/'gui-settings.json'
        self.service=GUIService(self.project,self.runs_root,self.settings_path)
        config=load_config(PACKAGE_ROOT/'config.research.json')
        self.state={'schema_version':1,'run_id':self.run_id,'status':'PAUSED','config':config,
            'objective':'Known research objective','agents':seed_agents(config),'ideas':[],
            'approvals':[],'usage':{'total_tokens':42},'steps':1,'active_seconds':3,
            'backend':'demo','created_at':'2026-11-03','updated_at':'2026-11-03'}
        store=Store(self.path);store.commit(self.state,'run_initialized',{'fixture':True});store.close()
    def tearDown(self):
        if self.service._job:self.service._job['active']=False
        self.tmp.cleanup()

    def test_bootstrap_is_readonly_and_profiles_have_effective_models_and_rounds(self):
        before=(self.path/'state.sqlite3').read_bytes()
        bootstrap=self.service.bootstrap()
        self.assertEqual({p['id'] for p in bootstrap['profiles']},{'research','cheap','experimental'})
        self.assertEqual(bootstrap['profiles'][0]['roles'][0]['model_tier'],'flag')
        self.assertTrue(bootstrap['profiles'][0]['roles'][0]['round_limit'])
        self.assertEqual(self.service.runs()['runs'][0]['id'],self.run_id)
        run=self.service.run(self.run_id)
        self.assertEqual(run['backend'],'demo')
        self.assertEqual(run['usage']['total_tokens'],42)
        self.assertNotIn('history',run['agents'][0]);self.assertNotIn('http_credentials',run['config'])
        self.assertEqual(before,(self.path/'state.sqlite3').read_bytes())

    def test_project_and_runs_root_must_be_separate_and_ids_cannot_escape(self):
        with self.assertRaises(ValueError):GUIService(self.project,self.project/'runs')
        for ident in ('../project','..','C:\\Windows','x/y','x\\y'):
            with self.assertRaises(ValueError):self.service.run_path(ident)

    def test_start_config_is_external_task_appends_to_mission_and_models_are_editable(self):
        payload={'profile':'research','task':'Only digital storage, no physical media.',
                 'backend':'demo','fetch_live':False,
                 'overrides':{'max_total_tokens':1234567,'model_tiers':{'cheap':'x','strong':'y','flag':'z'}}}
        with patch.object(self.service,'launch',return_value={'ok':True}) as launch:
            self.service.start(payload)
        args=launch.call_args.args[0]
        draft=Path(args[args.index('--config')+1])
        self.assertTrue(draft.is_relative_to(self.runs_root))
        self.assertFalse(draft.is_relative_to(self.project))
        config=json.loads(draft.read_text(encoding='utf-8'))
        self.assertIn('Research and brainstorm',config['operator_objective'])
        self.assertIn('Only digital storage',config['operator_objective'])
        self.assertEqual(config['model_tiers']['flag'],'z')
        self.assertNotIn('--fetch-live',args)
        self.assertEqual(json.loads((PACKAGE_ROOT/'config.research.json').read_text())['max_total_tokens'],3000000)

    def test_artifact_folders_do_not_hide_initialized_runs(self):
        for n in range(65):(self.runs_root/f'20261104-artifacts-{n}').mkdir()
        self.assertEqual([r['id'] for r in self.service.runs()['runs']],[self.run_id])

    def test_start_refuses_unknown_capability_overrides(self):
        with self.assertRaisesRegex(ValueError,'Nepodporovaná'):
            self.service.start({'overrides':{'external_resources':[{'unsafe':'grant'}]}})

    def test_key_is_saved_across_gui_restart_and_can_be_forgotten(self):
        key='fixture-key-for-restart'
        self.service.settings({'api_key':key,'remember_api_key':True})
        restarted=GUIService(self.project,self.runs_root,self.settings_path)
        self.assertEqual(restarted._key,key)
        self.assertTrue(restarted.bootstrap()['api_key_saved'])
        self.assertNotIn(key,json.dumps(restarted.bootstrap()))
        self.assertNotIn(key,json.dumps(restarted.runs()))
        restarted.settings({'forget_api_key':True})
        self.assertFalse(self.settings_path.exists())
        self.assertFalse(restarted.bootstrap()['api_key_present'])

    def test_unchecking_remember_removes_saved_copy_but_keeps_session_key(self):
        key='fixture-key-for-session'
        self.service.settings({'api_key':key,'remember_api_key':True})
        self.service.settings({'remember_api_key':False})
        self.assertEqual(self.service._key,key)
        self.assertFalse(self.settings_path.exists())
        with patch.dict(os.environ,{'OPENAI_API_KEY':''}):
            restarted=GUIService(self.project,self.runs_root,self.settings_path)
        self.assertFalse(restarted.bootstrap()['api_key_present'])

    def test_subprocess_is_argv_only_key_is_env_only_and_log_redacts(self):
        key='sk-proj-'+('A'*45);self.service.settings({'api_key':key})
        class Process:
            stdout=iter(['line '+key+'\n'])
            def wait(self):return 0
        with patch('metaweb_swarm.gui.subprocess.Popen',return_value=Process()) as popen:
            self.service.launch(['doctor','--format','text'],'doctor')
            self.service._thread.join(2)
        args,kwargs=popen.call_args
        self.assertNotIn(key,str(args));self.assertEqual(kwargs['env']['OPENAI_API_KEY'],key)
        self.assertFalse(kwargs['shell'])
        self.assertNotIn(key,json.dumps(self.service.job()))
        self.assertFalse(self.service.job()['job']['active'])

    def test_resume_uses_saved_backend_and_explicit_limits_only(self):
        with patch.object(self.service,'launch',return_value={'ok':True}) as launch:
            self.service.resume({'run_id':self.run_id,'extend_tokens':99})
        args=launch.call_args.args[0]
        self.assertEqual(args[:4],['resume',str(self.path),'--backend','demo'])
        self.assertEqual(args[-2:],['--extend-tokens','99'])
        with self.assertRaises(ValueError):self.service.resume({'run_id':self.run_id,'extend_seconds':-1})

    def test_pause_and_comment_do_not_require_mutating_live_sqlite(self):
        before=(self.path/'state.sqlite3').read_bytes()
        self.service._job={'active':True,'run_id':self.run_id}
        self.service.pause(self.run_id)
        self.assertTrue((self.path/'PAUSE.flag').is_file())
        result=self.service.comment({'run_id':self.run_id,'text':'Pouze digitální nosiče.'})
        self.assertTrue(result['ok'])
        view=self.service.run(self.run_id)
        self.assertEqual(view['operator_comments'][0]['status'],'QUEUED')
        self.assertEqual(before,(self.path/'state.sqlite3').read_bytes())

    def test_shutdown_requests_pause_and_does_not_kill_child(self):
        self.service._job={'active':True,'run_id':self.run_id}
        with patch('builtins.print'):
            self.service.shutdown()
        self.assertTrue((self.path/'PAUSE.flag').is_file())

    def test_stale_running_checkpoint_does_not_disable_resume_and_external_writer_is_detected(self):
        from metaweb_swarm.storage import run_lock
        self.state['status']='RUNNING'
        store=Store(self.path);store.commit(self.state,'fixture_stale_running');store.close()
        view=self.service.run(self.run_id)
        self.assertFalse(view['running']);self.assertTrue(view['interrupted'])
        with run_lock(self.path):self.assertTrue(self.service.run(self.run_id)['running'])
        self.assertFalse(self.service.run(self.run_id)['running'])

    def test_console_supports_cli_without_general_shell(self):
        with patch.object(self.service,'launch',return_value={'ok':True}) as launch:
            self.service.command('swarm.py doctor --format text')
        self.assertEqual(launch.call_args.args[0],['doctor','--format','text'])
        for command in ('cmd /c del x','powershell Remove-Item x','swarm.py unknown','echo hi'):
            with self.assertRaises(ValueError):self.service.command(command)


class HTTPTests(GUITests):
    def setUp(self):
        super().setUp()
        self.server=make_server(self.service)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.origin='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(2)
        super().tearDown()
    def request(self,path='/api/bootstrap',data=None,**headers):
        defaults={'X-Swarm-Token':self.service.token}
        if data is not None:defaults['Content-Type']='application/json'
        defaults.update(headers)
        req=urllib.request.Request(self.origin+path,data=json.dumps(data).encode() if data is not None else None,headers=defaults)
        return urllib.request.urlopen(req,timeout=3)
    def test_api_requires_secret_and_same_origin_and_host(self):
        for headers in ({'X-Swarm-Token':'wrong'},{'Origin':'https://evil.example'},{'Host':'evil.example'}):
            with self.assertRaises(urllib.error.HTTPError) as error:self.request(**headers)
            self.assertEqual(error.exception.code,403)
        with self.request() as response:
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            self.assertIn('profiles',json.load(response))
    def test_control_endpoint_auth_and_no_arbitrary_file_route(self):
        with self.request('/api/pause',{'run_id':self.run_id},Origin=self.origin) as response:
            self.assertTrue(json.load(response)['ok'])
        with self.assertRaises(urllib.error.HTTPError) as error:self.request('/../../config.json')
        self.assertEqual(error.exception.code,404)
        with self.assertRaises(urllib.error.HTTPError) as error:self.request('/api/run?id=..')
        self.assertEqual(error.exception.code,400)
    def test_assets_are_fixed_local_files(self):
        with urllib.request.urlopen(self.origin+'/',timeout=3) as response:
            self.assertIn('text/html',response.headers['Content-Type'])
            self.assertIn(b'Metaweb',response.read())
