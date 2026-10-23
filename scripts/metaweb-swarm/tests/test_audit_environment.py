"""An audit import failure never becomes a prototype repair request."""
import json,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from metaweb_swarm.probe_runtime import launcher,forbidden_imports
from metaweb_swarm.review_probe import run
from metaweb_swarm.review_dispatch import action
from tests import test_local_contract as fixture


class RunnerTests(unittest.TestCase):
    def test_model_summary_keeps_diagnostics_without_package_file_list_or_code_replay(self):
        from metaweb_swarm.probe_runtime import summary
        record={'id':'PROBE-1','outcome':'PASSED','code':'x'*16000,'staged_paths':['x'*200]*1000,'output':'x'*16000}
        small=summary(record)
        self.assertEqual(small['staged_path_count'],1000);self.assertLess(len(json.dumps(small)),6000)
        self.assertEqual(len(record['staged_paths']),1000)
    def test_runtime_distinguishes_import_assertion_and_unexpected_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for code,expected in [('assert 1==1','PASSED'),('assert 1==2','ASSERTION_FAILED'),
                                  ('import no_such_review_dependency','SETUP_ERROR'),('1/0','RUNTIME_ERROR')]:
                (root/'probe.py').write_text(code)
                (root/'runner.py').write_text(launcher('probe.py','result.json',[]))
                result=subprocess.run([sys.executable,'-I','runner.py'],cwd=root,capture_output=True,timeout=10)
                diagnostic=json.loads((root/'result.json').read_text())
                self.assertEqual(diagnostic['outcome'],expected)
                self.assertEqual(result.returncode,0 if expected=='PASSED' else 1)
    def test_author_source_folder_is_added_without_copying_source_to_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'prototype').mkdir()
            (root/'prototype/codec.py').write_text('def decode(): return b"source-bound"\n')
            (root/'probe.py').write_text('from codec import decode\nassert decode()==b"source-bound"')
            (root/'runner.py').write_text(launcher('probe.py','result.json',['prototype']))
            result=subprocess.run([sys.executable,'-I','runner.py'],cwd=root,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
    def test_clean_mode_rejects_author_imports_but_not_standard_library(self):
        paths={'prototype/codec.py','prototype/json.py'}
        self.assertEqual(forbidden_imports('from codec import decode\nimport json',paths),['codec'])


class AuditEnvironmentTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.LocalContractReviewTests.setUp
    tearDown=fixture.LocalContractReviewTests.tearDown
    for_agent=fixture.LocalContractReviewTests.for_agent
    prepare=fixture.LocalContractReviewTests.prepare
    plan=fixture.LocalContractReviewTests.plan
    artifacts=fixture.LocalContractReviewTests.artifacts
    executed=fixture.LocalContractReviewTests.executed
    evidence=fixture.LocalContractReviewTests.evidence
    captured=fixture.LocalContractReviewTests.captured

    async def test_forbidden_clean_import_is_deferred_without_docker_or_code_revision(self):
        test=await self.captured();self.engine.state['config']['independent_review_probes']=True
        with patch('metaweb_swarm.review_probe.DockerExecutor') as docker:
            result=await run(self.review,test['id'],'from test import decode\nassert decode() is not None',['prototype/specimen.bin'])
            docker.assert_not_called()
        self.assertEqual(result['reason'],'AUTHOR_IMPORT_IN_SPECIMEN_READER')
        self.assertFalse(self.engine.state.get('prototype_review_probes'))
        rejected=self.review.review_prototype_test(test['id'],'REVISE','The probe could not import the author module; change the prototype code',
            negative_code='encoded=base64.b64encode(data)',defect_code=None,required_local_change='Change code to fix the reviewer import',observed_recovery=None,review_basis=None)
        self.assertEqual(rejected['reason'],'AUDIT_PROBE_REPAIR_REQUIRED');self.assertNotIn('prototype_review',test)
        self.assertNotIn('review_prototype_test',action(self.review)['allowed_tools'])
    async def test_syntax_failure_stays_with_reviewer_and_preserves_execution_cap(self):
        test=await self.captured()
        with patch('metaweb_swarm.review_probe.DockerExecutor') as docker:
            result=await run(self.review,test['id'],'def invalid( # reviewer typo\nassert True')
            docker.assert_not_called()
        self.assertEqual(result['reason'],'PROBE_SYNTAX_ERROR');self.assertNotIn('prototype_review',test)
    async def test_reviewer_libraries_are_staged_in_clean_mode_author_libraries_are_absent(self):
        test=await self.captured()
        for agent,name in ((self.auditor,'review_lib'),(self.proto,'author_lib')):
            package=self.run/'agents'/agent['id']/'workspace/.packages';package.mkdir(parents=True,exist_ok=True)
            (package/(name+'.py')).write_text('VALUE=3\n')
        def execute(root,argv):
            self.assertTrue((root/'.review-packages/review_lib.py').is_file())
            self.assertFalse((root/'.packages').exists());self.assertFalse((root/'prototype/test.py').exists())
            self.assertIn('.review-packages',(root/argv[-1]).read_text())
            return {'status':'COMPLETED','returncode':0,'cleanup_ok':True,'output':'mock transport only'}
        with patch('metaweb_swarm.review_probe.DockerExecutor') as docker:
            docker.return_value.run.side_effect=execute
            result=await run(self.review,test['id'],'import review_lib\nassert review_lib.VALUE==3',['prototype/specimen.bin'])
        self.assertEqual(result['outcome'],'PASSED');self.assertEqual(result['dependency_owners'][0]['agent_id'],self.auditor['id'])
    async def test_runtime_setup_diagnostic_blocks_verdict_and_offers_package_install(self):
        test=await self.captured();self.engine.state['config'].update(independent_review_probes=True,package_installation='pypi')
        def execute(root,argv):
            # Simulate the fixed wrapper's diagnostic, not model-authored claims.
            runner=(root/argv[-1]).read_text();name=next(p.name for p in root.iterdir() if p.name.startswith('__review_runner'))
            diagnostic=runner.split("pathlib.Path(",1)[1].split(').write_text',1)[0].strip("'\"")
            (root/diagnostic).write_text(json.dumps({'outcome':'SETUP_ERROR','error_type':'ModuleNotFoundError','missing_module':'PIL','detail':'PIL missing'}))
            return {'status':'BLOCKED','returncode':1,'cleanup_ok':True,'output':'PIL missing'}
        with patch('metaweb_swarm.review_probe.DockerExecutor') as docker:
            docker.return_value.run.side_effect=execute
            result=await run(self.review,test['id'],'from PIL import Image\nassert Image is not None',['prototype/specimen.bin'])
        self.assertEqual(result['outcome'],'SETUP_ERROR');self.assertEqual(result['status'],'DEFERRED')
        self.assertIn('install_packages',action(self.review)['allowed_tools']);self.assertNotIn('prototype_review',test)
    async def test_review_can_install_own_dependencies_in_supervised_mode(self):
        test=await self.captured();self.engine.state['config'].update(run_mode='supervised',package_installation='pypi')
        with patch('metaweb_swarm.packages.PackageInstaller') as installer:
            installer.return_value.install.return_value={'status':'COMPLETED','distributions':[]}
            result=await self.review.install_packages(['Pillow'])
            self.assertEqual(installer.return_value.install.call_args.args[0],self.review.workspace.root)
        self.assertEqual(result['status'],'COMPLETED')
        self.assertEqual(self.engine.state['package_installations'][-1]['purpose'],'INDEPENDENT_REVIEW')
        self.assertFalse(self.engine.state['external_actions'])
    async def test_review_install_keeps_existing_resource_limits(self):
        await self.captured();self.engine.state['config'].update(package_installation='pypi',max_package_installs_per_agent=1)
        self.auditor['package_install_attempts']=1
        with patch('metaweb_swarm.packages.PackageInstaller') as installer:
            result=await self.review.install_packages(['Pillow']);installer.assert_not_called()
        self.assertEqual(result['reason'],'MAX_PACKAGE_INSTALLS_PER_AGENT')

    async def test_repeated_setup_error_blocks_audit_without_inventing_code_repair(self):
        from metaweb_swarm.backend import BackendBlocked
        test=await self.captured()
        code='from test import decode\nassert decode() is not None'
        for _ in range(2):
            result=await run(self.review,test['id'],code,['prototype/specimen.bin'])
            self.assertEqual(result['reason'],'AUTHOR_IMPORT_IN_SPECIMEN_READER')
        with self.assertRaisesRegex(BackendBlocked,'AUDIT_PROBE_SETUP_STALLED'):
            await run(self.review,test['id'],code,['prototype/specimen.bin'])
        self.assertNotIn('prototype_review',test);self.assertFalse(self.proto.get('research_task_blocks'))

    async def test_sdk_routes_setup_to_own_install_then_probe_then_judgment(self):
        from tests.test_backend import SDK_AVAILABLE,FakeProvider,tool_response,final_response
        if not SDK_AVAILABLE:self.skipTest('SDK optional')
        from metaweb_swarm.backend import OpenAIBackend
        test=await self.captured();self.engine.state['config'].update(independent_review_probes=True,package_installation='pypi')
        self.auditor['prototype_probe_setup_issues']={test['id']:{'reason':'REVIEW_PROBE_SETUP_ERROR','missing_module':'PIL'}}
        provider=FakeProvider([
            tool_response('install_packages',{'packages':['Pillow']},ident='audit-install'),
            tool_response('run_review_probe',{'test_id':test['id'],'code':'actual=3; assert actual==3',
                'specimen_paths':['prototype/specimen.bin']},ident='audit-fixed-probe'),
            tool_response('review_prototype_test',{'test_id':test['id'],'verdict':'HELPER_ONLY',
                'reason':'Generic captured fixture remains a helper; mocked assertions are not mechanism certification',
                'positive_refs':[{'path':'prototype/test.py','start_line':4,'end_line':4}],
                'negative_refs':[],'required_local_change':''},ident='audit-judgment'),final_response()])
        with patch('metaweb_swarm.packages.PackageInstaller') as installer,patch('metaweb_swarm.review_probe.DockerExecutor') as docker:
            installer.return_value.install.return_value={'status':'COMPLETED','distributions':[]}
            docker.return_value.run.return_value={'status':'COMPLETED','returncode':0,'cleanup_ok':True,'output':'mock transport'}
            await OpenAIBackend(provider).step(self.auditor,self.engine.prompt(self.auditor),[],self.review,self.engine.state['config'])
        first_args,first_kwargs=provider.model.calls[0]
        tools=first_kwargs.get('tools',first_args[3] if len(first_args)>3 else [])
        self.assertEqual({tool.name for tool in tools},{'run_review_probe','install_packages'})
        self.assertEqual(test['prototype_review']['verdict'],'HELPER_ONLY')
        self.assertFalse(self.auditor.get('prototype_probe_setup_issues',{}))
