import asyncio
import json
import tempfile
import errno
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from metaweb_swarm.config import load_config, validate_config
from metaweb_swarm.demo import DemoBackend
from metaweb_swarm.engine import Engine, ToolAPI, initialize, refresh_reports
from metaweb_swarm.packages import PackageInstaller, requirements, PACKAGE_DRIVER
from metaweb_swarm.workspace import DockerExecutor, Workspace, export_patch


class PackageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.project = self.root / 'project'; self.project.mkdir()
        (self.project/'owner.txt').write_text('Production sentinel')
        self.config = load_config()
        self.config.update(run_mode='autonomous', experiments='docker', package_installation='pypi')
        self.run = initialize(self.project, self.root/'runs', self.config)
        self.engine = Engine(self.run, DemoBackend(), 'demo'); self.agent = self.engine.state['agents'][0]
        self.workspace = Workspace(self.run/'snapshot', self.run/'agents'/self.agent['id']/'workspace')
        self.api = ToolAPI(self.engine, self.agent, self.workspace)

    def tearDown(self):
        self.engine.close(); self.temp.cleanup()

    def test_any_package_versions_extras_without_allowlist(self):
        specs = ['Pillow', 'qrcode[pil]', 'cbor2>=5,<6', 'unknown-name_xyz==1.2.3', 'foo[bar,baz]~=2.1']
        self.assertEqual(requirements(specs), specs)
        self.assertEqual(requirements(['Pillow', 'Pillow']), ['Pillow'])
        for spec in ('--index-url', '../escape', 'git+https://host/repo', 'foo @ https://host/x', '-r file', 'x;echo secret', 'x\n--target=G:\\web'):
            with self.subTest(spec=spec), self.assertRaises(ValueError): requirements([spec])

    def run_fixed_driver_fixture(self, copy_fails=False):
        # Only the trusted export helper executes here. pip is replaced by a
        # fixture writer; package build/install code is never run on the host.
        native=self.root/'native'; native.mkdir()
        mounted=self.root/'mounted'; mounted.mkdir()
        text=PACKAGE_DRIVER.replace('/package-tmp',native.as_posix()).replace('/workspace',mounted.as_posix())
        calls=[]
        def pip_fixture(command):
            calls.append(command)
            (native/'result'/'fixture.whl').write_bytes(b'wheel bytes')
            return 0
        with patch.object(sys,'argv',['driver','fetch','["cbor2"]']), patch('subprocess.call',side_effect=pip_fixture), patch('os.chmod',side_effect=PermissionError(errno.EPERM,'POSIX mode unsupported')):
            if copy_fails:
                with patch('shutil.copyfile',side_effect=PermissionError(errno.EACCES,'write denied')):
                    exec(compile(text,'trusted-package-driver','exec'),{})
            else:
                exec(compile(text,'trusted-package-driver','exec'),{})
        return mounted,calls

    def test_unsupported_posix_modes_do_not_fail_wheel_byte_export(self):
        mounted,calls=self.run_fixed_driver_fixture()
        self.assertEqual((mounted/'wheels'/'fixture.whl').read_bytes(),b'wheel bytes')
        self.assertIn(str(self.root/'native'/'result'),calls[0])
        self.assertNotIn(str(mounted/'wheels'),calls[0])

    def test_actual_copy_permission_failure_is_not_hidden(self):
        with self.assertRaises(PermissionError) as caught: self.run_fixed_driver_fixture(copy_fails=True)
        self.assertEqual(caught.exception.errno,errno.EACCES)

    def test_online_fetch_has_no_project_offline_install_has_readonly_wheels(self):
        with tempfile.TemporaryDirectory(dir=self.root) as temp:
            build = Path(temp); (build/'.metaweb-workspace.json').write_text(json.dumps({'root':str(build)}))
            (build/'wheels').mkdir(); (build/'.build-tmp').mkdir(); calls = []
            def fake(executor, argv, environment, timeout):
                calls.append(argv)
                out = 'linux' if 'info' in argv else json.dumps({'Running':False,'ExitCode':0}) if '{{json .State}}' in argv else ''
                return dict(returncode=0,output=out,timed_out=False,output_truncated=False)
            with patch.object(DockerExecutor,'_call',autospec=True,side_effect=fake):
                executor = DockerExecutor()
                executor.fetch_packages(build,['Pillow'])
                executor.install_packages(self.workspace.root,build/'wheels',['Pillow'])
                executor.run(self.workspace.root,['python','-c','import PIL'])
            online, offline, experiment = [a for a in calls if 'create' in a]
            self.assertEqual(online[online.index('--network')+1],'bridge')
            self.assertEqual(online.count('--mount'),1)
            self.assertIn('/package-tmp:rw,nosuid,nodev,size=512m,mode=1777', online)
            self.assertIn('TMPDIR=/package-tmp', online)
            self.assertNotIn(str(self.workspace.root),' '.join(online))
            self.assertNotIn(str(self.project),' '.join(online))
            self.assertEqual(offline[offline.index('--network')+1],'none')
            self.assertIn(f'type=bind,src={build / "wheels"},dst=/wheels,readonly',offline)
            self.assertIn('/package-tmp:rw,nosuid,nodev,size=512m,mode=1777', offline)
            self.assertNotIn('/package-tmp:rw,nosuid,nodev,size=512m,mode=1777', experiment)
            self.assertIn('PYTHONPATH=/workspace/.packages',experiment)
            self.assertEqual(experiment[experiment.index('--network')+1],'none')

    def fetch(self, executor, build, specs):
        (build/'wheels'/'example-1.0-py3-none-any.whl').write_bytes(b'wheel fixture')
        return dict(status='COMPLETED',returncode=0,output='Fetched',cleanup_ok=True)

    def install(self, executor, root, wheels, specs):
        dist = root/'.packages/example-1.0.dist-info'; dist.mkdir(parents=True,exist_ok=True)
        (dist/'METADATA').write_text('Name: example\nVersion: 1.0\n')
        return dict(status='COMPLETED',returncode=0,output='Installed',cleanup_ok=True)

    async def test_receipts_persist_across_resume_and_production_is_unchanged(self):
        with patch.object(DockerExecutor,'fetch_packages',autospec=True,side_effect=self.fetch), patch.object(DockerExecutor,'install_packages',autospec=True,side_effect=self.install):
            result = await self.api.install_packages(['example'])
        self.assertEqual(result['status'],'COMPLETED')
        self.assertEqual(result['distributions'],[{'name':'example','version':'1.0'}])
        state = self.engine.store.load()
        self.assertEqual(len(state['package_installations'][0]['wheel_receipts'][0]['sha256']),64)
        refresh_reports(self.engine.store, self.engine.state)
        manifest = json.loads((self.run/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['package_installations'][0]['status'], 'COMPLETED')
        self.assertIn('example', (self.run/'SWARM_REPORT.md').read_text(encoding='utf-8'))
        self.assertEqual((self.project/'owner.txt').read_text(),'Production sentinel')
        exported = export_patch(self.run/'snapshot', self.workspace.root, self.root/'review')
        self.assertFalse(any(p['path'].startswith('.packages/') for p in exported['files']))
        self.engine.store.verify(); self.engine.close(); self.engine = Engine(self.run,DemoBackend(),'demo')
        self.assertEqual(self.engine.state['agents'][0]['installed_packages'],result['distributions'])
        self.assertTrue((self.workspace.root/'.packages/example-1.0.dist-info/METADATA').exists())

    async def test_supervised_disabled_attempt_and_runtime_limits(self):
        config = self.engine.state['config']; config['package_installation']='disabled'
        self.assertEqual((await self.api.install_packages(['Pillow']))['reason'],'PACKAGE_INSTALLATION_DISABLED')
        config.update(package_installation='pypi',run_mode='supervised')
        self.assertEqual((await self.api.install_packages(['Pillow']))['status'],'DEFERRED')
        config['run_mode']='autonomous'; self.agent['package_install_attempts']=config['max_package_installs_per_agent']
        self.assertEqual((await self.api.install_packages(['Pillow']))['status'],'LIMIT_REACHED')
        self.agent['package_install_attempts']=0; self.engine.state['active_seconds']=config['max_active_seconds']
        self.assertEqual((await self.api.install_packages(['Pillow']))['reason'],'MAX_ACTIVE_SECONDS')

    async def test_cancellation_waits_for_cleanup_then_records_receipt(self):
        import threading
        ready = threading.Event(); release = threading.Event()
        def install(root,specs):
            ready.set(); release.wait(2)
            return dict(status='COMPLETED',requirements=specs,distributions=[],phases=[])
        with patch('metaweb_swarm.packages.PackageInstaller') as installer:
            installer.return_value.install.side_effect=install
            task=asyncio.create_task(self.api.install_packages(['Pillow']))
            await asyncio.to_thread(ready.wait,2); task.cancel(); release.set()
            with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(self.engine.store.load()['package_installations'][0]['status'],'COMPLETED')

    async def test_failed_worker_after_cancel_is_audited_and_unfinished_work_blocks_retry(self):
        import threading
        ready = threading.Event(); release = threading.Event()
        def install(root, specs):
            ready.set(); release.wait(2)
            raise OSError('Fixture worker failure')
        with patch('metaweb_swarm.packages.PackageInstaller') as installer:
            installer.return_value.install.side_effect = install
            task = asyncio.create_task(self.api.install_packages(['Pillow']))
            await asyncio.to_thread(ready.wait, 2); task.cancel(); release.set()
            with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(self.engine.store.load()['package_installations'][0]['status'], 'BLOCKED')
        self.engine.state['package_installations'][0]['status'] = 'RUNNING'
        result = await self.api.install_packages(['Pillow'])
        self.assertTrue(result['reason'].startswith('PREVIOUS_PACKAGE_INSTALL_UNFINISHED'))

    async def test_failed_fetch_is_bounded_and_never_starts_install(self):
        with patch.object(DockerExecutor,'fetch_packages',return_value={'status':'BLOCKED','output':'x'*100000}), patch.object(DockerExecutor,'install_packages') as install:
            result=await self.api.install_packages(['missing'])
        self.assertEqual(result['status'],'BLOCKED'); self.assertLess(len(json.dumps(result)),4000)
        install.assert_not_called()

    def test_wheel_byte_limit_stops_before_install(self):
        with patch.object(DockerExecutor,'fetch_packages',autospec=True,side_effect=self.fetch), patch.object(DockerExecutor,'install_packages') as install:
            result=PackageInstaller(self.config['docker_image'],60,1).install(self.workspace.root,['example'])
        self.assertEqual(result['status'],'LIMIT_REACHED'); install.assert_not_called()

    def test_configuration_validation(self):
        for change in ({'package_installation':'all'},{'max_package_installs_per_agent':True},{'max_package_bytes':0},{'package_install_timeout_seconds':3601}):
            with self.subTest(change=change), self.assertRaises(ValueError): validate_config(self.config|change)
