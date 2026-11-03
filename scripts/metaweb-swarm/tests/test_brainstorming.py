"""Default research can finish honestly without implementation prerequisites."""
import asyncio,contextlib,copy,io,json,os,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from metaweb_swarm.config import load_config,validate_config,PACKAGE_ROOT
from metaweb_swarm.cli import main,parser
from metaweb_swarm.engine import Engine,initialize,ToolAPI
from metaweb_swarm.roles import seed_agents,new_agent
from metaweb_swarm.workspace import Workspace
from metaweb_swarm.demo import DemoBackend


class ProfileTests(unittest.TestCase):
    def test_default_cli_and_research_profile_are_brainstorming_tiered_models(self):
        for command in ('init','start'):
            args=[command,'--project','example','--runs-root','runs']
            if command=='start':args+=['--backend','openai']
            self.assertEqual(parser().parse_args(args).config,PACKAGE_ROOT/'config.research.json')
        config=load_config(PACKAGE_ROOT/'config.research.json')
        self.assertEqual(config['task_style'],'brainstorming')
        self.assertEqual(config['model_tiers'],{'cheap':'gpt-6-luna','strong':'gpt-6.1-terra','flag':'gpt-6.1-sol'})
        self.assertEqual(set(load_config(PACKAGE_ROOT/'config.cheap.json')['model_tiers'].values()),{'gpt-5.4-mini'})
        self.assertNotIn('Prototyper',[a['role'] for a in seed_agents(config)])
        self.assertNotIn('Prototyper',[a['role'] for a in seed_agents(dict(config,seed_roles=[]))])

    def test_brainstorming_cannot_be_silently_promoted_to_execution(self):
        config=load_config(PACKAGE_ROOT/'config.research.json')
        for name,value in [('experiments','docker'),('run_mode','autonomous'),('http_access','enabled'),
                           ('package_installation','pypi'),('coding_backend','sdk_shell'),
                           ('include_exports',True),('max_external_actions',1),
                           ('external_resources',[{}]),('http_credentials',[{}])]:
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'Brainstorming is research-only'):
                validate_config(dict(config,**{name:value}))

    def test_experimental_profiles_preserve_execution_and_smoke_capabilities(self):
        for path in PACKAGE_ROOT.glob('config*.json'):load_config(path)
        full=load_config(PACKAGE_ROOT/'config.http.json')
        self.assertEqual((full['experiments'],full['coding_backend'],full['http_access']),('docker','sdk_shell','enabled'))
        self.assertTrue(full['approval_required']);self.assertTrue(full['independent_review_probes'])
        self.assertIn('Prototyper',full['seed_roles'])
        self.assertIn('config.http.json',(PACKAGE_ROOT/'run-experimental.cmd').read_text())

    @unittest.skipUnless(os.name=='nt','Windows CMD launchers')
    def test_actual_cmd_aliases_select_research_and_explicit_experimental_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub=Path(tmp)/'python-stub.cmd'
            stub.write_text('@echo off\n echo %*\n exit /b 0\n')
            env=dict(os.environ,SWARM_PYTHON=str(stub))
            for launcher in ('run.cmd','run-http.cmd','run-research.cmd','run-supervised.cmd','run-experimental.cmd','run-sandbox.cmd'):
                result=subprocess.run(['cmd.exe','/d','/c',str(PACKAGE_ROOT/launcher)],env=env,
                                      capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                experimental=launcher in {'run-experimental.cmd','run-sandbox.cmd'}
                self.assertIn('config.http.json' if experimental else 'config.research.json',result.stdout)
                self.assertIn('--experiments docker' if experimental else '--experiments disabled',result.stdout)


class BrainstormingRunTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.project=self.root/'project';(self.project/'public').mkdir(parents=True)
        (self.project/'public/ARCHIVE.txt').write_text('Existing preservation layers: Zenodo, Piql/AWA.',encoding='utf-8')
        # A large export is irrelevant to a brainstorming run, even with a tiny intake limit.
        (self.project/'exports').mkdir();(self.project/'exports/build.zip').write_bytes(b'x'*1024)
        self.config=load_config(PACKAGE_ROOT/'config.research.json')
        self.config.update(semantic_dedupe=False,max_export_file_bytes=1)
        self.run=initialize(self.project,self.root/'runs',self.config)
        self.engine=Engine(self.run,DemoBackend(),'demo')
    def tearDown(self):self.engine.close();self.temp.cleanup()
    def api(self,agent):return ToolAPI(self.engine,agent,Workspace(self.run/'snapshot',self.run/'agents'/agent['id']/'workspace'))

    async def test_complete_research_pipeline_retains_idea_without_execution_or_approval(self):
        with (patch('metaweb_swarm.workspace.DockerExecutor.check_ready',side_effect=AssertionError('Docker requested')),
              patch('metaweb_swarm.workspace.DockerExecutor.run',side_effect=AssertionError('Docker requested'))):
            state=await self.engine.run()
        self.assertEqual(state['status'],'COMPLETED')
        self.assertEqual(len(state['ideas']),1)
        self.assertNotIn(state['ideas'][0]['status'],{'REJECTED','PROTOTYPED','COMPLETED'})
        self.assertEqual(len(state['critiques']),2)
        for field in ('experiments','package_installations','tests','external_actions','approvals'):
            self.assertFalse(state[field],field)
        self.assertFalse(state['exports']['files']);self.assertEqual(state['usage']['requests'],0)
        reporter=next(a for a in state['agents'] if a['work_kind']=='SYNTHESIS')
        self.assertEqual(reporter['research_report_receipt']['idea_ids'],[state['ideas'][0]['id']])
        for name in ('SWARM_REPORT.md','TIMELINE.md','ideas.jsonl','manifest.json'):
            self.assertTrue((self.run/name).is_file())
        report=(self.run/'SWARM_REPORT.md').read_text(encoding='utf-8')
        self.assertIn('Brainstorming / výzkum bez realizace',report)
        self.assertEqual((self.project/'public/ARCHIVE.txt').read_text(),'Existing preservation layers: Zenodo, Piql/AWA.')
        self.assertGreater(self.engine.store.verify()['events'],0)

    async def test_sdk_tool_surface_has_no_execution_for_any_seed_or_emergent_role(self):
        from tests.test_backend import SDK_AVAILABLE
        if not SDK_AVAILABLE:self.skipTest('SDK optional')
        import agents
        from metaweb_swarm.backend import _make_sdk_tools
        forbidden={'write_file','write_binary','install_packages','run_experiment','execute_prototype',
                   'run_review_probe','deposit_file','http_request','request_approval','list_http_credentials',
                   'execute_deposit_plan','record_prototype_plan','record_test','materialize_export'}
        for agent in self.engine.state['agents']+[new_agent('DYNAMIC','New research specialist','Research a new lawful carrier.')]:
            names={t.name for t in _make_sdk_tools(agents,self.api(agent))[0]}
            self.assertFalse(names & forbidden,(agent['role'],names & forbidden))
            self.assertIn('note',names)
            if agent['work_kind']=='DISCOVERY':self.assertTrue({'read_document','submit_idea','check_baseline'}<=names)
        # Even an operator selection does not turn this run into an implementation run.
        agent=self.engine.state['agents'][1];api=self.api(agent)
        self.assertEqual(api.implementation_allowed(''),'BRAINSTORMING_RESEARCH_ONLY')

    async def test_prompts_remove_execution_flow_and_keep_creative_research_and_current_report(self):
        for agent in self.engine.state['agents']:
            prompt=self.engine.prompt(agent)
            self.assertIn('BRAINSTORMING / RESEARCH ONLY',prompt)
            self.assertIn('check_baseline',prompt)
            self.assertIn('handoff_leads',prompt)
            self.assertNotIn('discover -> verify sources/payment/novelty ->',prompt)
            self.assertLessEqual(len(prompt),self.config['prompt_chars'])

    async def test_large_histories_never_enter_prompt_and_full_idea_remains_pageable(self):
        from metaweb_swarm.brainstorming import read_idea,compact_packet
        idea=DemoBackend.idea('Current hypothesis','Current mechanism','FREE','DISCOVERED')
        idea.update(id='IDEA-0001',submissions=[{'notes':'HISTORICAL_MARKER '*20000}],
                    revisions=[{'old':'older source'}],evidence=[{'url':'https://example.org/docs','claim':'Primary claim'}])
        self.engine.state['ideas']=[idea]
        for agent in self.engine.state['agents']:
            prompt=self.engine.prompt(agent)
            self.assertLessEqual(len(prompt),self.config['prompt_chars'])
            self.assertNotIn('HISTORICAL_MARKER',prompt)
        packet=compact_packet({'candidate':idea,'stage':'CRITIQUE','target_id':idea['id']})
        self.assertEqual(packet['candidate']['evidence'],idea['evidence'])
        self.assertNotIn('submissions',packet['candidate'])
        api=self.api(self.engine.state['agents'][1]);parts=[];offset=0
        while offset is not None:
            page=read_idea(api,idea['id'],offset,8000);parts.append(page['text']);offset=page['next_offset']
        self.assertEqual(json.loads(''.join(parts)),idea)

    async def test_real_sdk_runs_research_note_with_fake_model_without_execution_tools(self):
        from tests.test_backend import SDK_AVAILABLE,FakeProvider,tool_response,final_response
        from metaweb_swarm.backend import OpenAIBackend
        if not SDK_AVAILABLE:self.skipTest('SDK optional')
        agent=self.engine.state['agents'][1]
        provider=FakeProvider([tool_response('note',{'text':'Research proposal needs primary evidence; implementation is deferred.'}),final_response()])
        await OpenAIBackend(provider).step(agent,self.engine.prompt(agent),[],self.api(agent),self.config)
        args,kwargs=provider.model.calls[0]
        tools=kwargs.get('tools',args[3] if len(args)>3 else [])
        names={getattr(tool,'name',None) for tool in tools}
        self.assertIn('note',names);self.assertIn('submit_idea',names)
        self.assertFalse(names & {'run_experiment','execute_prototype','install_packages','http_request','write_file'})

    async def test_cli_default_offline_start_never_requires_docker(self):
        with (patch('metaweb_swarm.cli.initialize',wraps=initialize) as init,
              patch('metaweb_swarm.workspace.DockerExecutor.check_ready',side_effect=AssertionError('Docker requested')),
              contextlib.redirect_stdout(io.StringIO())):
            code=await asyncio.to_thread(main,['start','--project',str(self.project),'--runs-root',str(self.root/'cli-runs'),'--backend','demo'])
        self.assertEqual(code,0)
        self.assertEqual(init.call_args.args[2]['task_style'],'brainstorming')
