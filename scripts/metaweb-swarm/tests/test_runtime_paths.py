import os,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from metaweb_swarm.runtime_paths import files_root,runs_root
from metaweb_swarm.config import PACKAGE_ROOT

class RuntimeLayoutTests(unittest.TestCase):
    def test_default_is_a_single_sibling_directory(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{},clear=True):
            project=Path(directory)/'project'
            self.assertEqual(files_root(project),Path(directory)/'vojtamaur-metaweb-swarm-files')
            self.assertEqual(runs_root(project),files_root(project)/'runs')
            self.assertFalse(runs_root(project).is_relative_to(project))
    def test_overrides_are_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            project=Path(directory)/'project';custom=Path(directory)/'custom';runs=Path(directory)/'other-runs'
            with patch.dict(os.environ,{'SWARM_FILES_ROOT':str(custom),'SWARM_RUNS_ROOT':str(runs)}):
                self.assertEqual(files_root(project),custom.resolve());self.assertEqual(runs_root(project),runs.resolve())
    @unittest.skipUnless(os.name=='nt','CMD launchers are Windows-specific')
    def test_cmd_uses_shared_root_and_does_not_invoke_models(self):
        with tempfile.TemporaryDirectory() as directory:
            custom=Path(directory)/'files with spaces'
            env={k:v for k,v in os.environ.items() if k not in {'SWARM_PYTHON','SWARM_RUNS_ROOT','SWARM_FILES_ROOT'}}
            env['SWARM_FILES_ROOT']=str(custom)
            # Echo executes after runtime.cmd, so expansion sees its output.
            fixture=Path(directory)/'probe.cmd'
            fixture.write_text('@echo off\ncall "'+str(PACKAGE_ROOT/'runtime.cmd')+'"\necho %SWARM_FILES_ROOT%\necho %SWARM_RUNS_ROOT%\n',encoding='utf-8')
            result=subprocess.run(['cmd.exe','/d','/c',str(fixture)],env=env,capture_output=True,text=True,check=True)
            self.assertIn(str(custom),result.stdout);self.assertIn(str(custom/'runs'),result.stdout)
    @unittest.skipUnless(os.name=='nt','CMD launchers are Windows-specific')
    def test_gui_launcher_help_preserves_cli_and_argument_forwarding(self):
        env=dict(os.environ,SWARM_PYTHON=os.sys.executable)
        result=subprocess.run(['cmd.exe','/d','/c',str(PACKAGE_ROOT/'run-gui.cmd'),'--help'],env=env,capture_output=True,text=True,check=True)
        self.assertIn('--no-browser',result.stdout)
