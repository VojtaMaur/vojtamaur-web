"""Transport adapter for SDK Shell: every command runs in our networkless Docker.

The SDK supplies the shell tool and agent loop. The existing host owns the copied
workspace, credential exclusion, container limits, command receipts and cleanup.
"""
import asyncio
import io
import math
import uuid


def command_limit(state,agent):
    count=sum(r.get('agent_id')==agent['id'] for r in state.get('coding_commands',[]))
    maximum=state['config']['max_coding_commands_per_agent']
    return {'reason':'MAX_CODING_COMMANDS','used':count,'limit':maximum} if count>=maximum else None


def require_command_capacity(state,agent):
    issue=command_limit(state,agent)
    if issue:
        from .backend import BackendLimit
        raise BackendLimit(f"MAX_CODING_COMMANDS: {issue['used']}/{issue['limit']}; coding files retained, no further model/command dispatch")


def unresolved_cleanup(state,agent_id):
    return (any((r.get('status')=='RUNNING' and r.get('agent_id')==agent_id) or r.get('cleanup_ok') is False
                for r in state.get('coding_commands',[]))
            or any(r.get('validation_execution',{}).get('cleanup_ok') is False
                   for r in state.get('coding_validations',[]))
            or any(r.get('status') in {'RUNNING','UNKNOWN'} or r.get('cleanup_ok') is False for r in state.get('prototype_review_probes',[])))


def create_session(api):
    # Keep the offline core independent of the optional Agents SDK.
    from agents.sandbox import Manifest, LocalSnapshot
    from agents.sandbox.session import SandboxSessionState
    from agents.sandbox.session.base_sandbox_session import BaseSandboxSession
    from agents.sandbox.types import ExecResult
    from .workspace import DockerExecutor, _relative, _read_bytes
    from .storage import now

    class DockerWorkspaceSession(BaseSandboxSession):
        def __init__(self):
            self.state = SandboxSessionState(type='metaweb-docker',
                snapshot=LocalSnapshot(id=api.agent['id'], base_path=api.workspace.root),
                manifest=Manifest(root='/workspace'), workspace_root_ready=True)

        async def _exec_internal(self, *command, timeout=None):
            from .backend import BackendBlocked
            config = api.engine.state['config']
            if unresolved_cleanup(api.engine.state,api.agent['id']):
                raise BackendBlocked('CONTAINER_CLEANUP_UNRESOLVED: inspect the retained command receipt before continuing')
            if config['experiments'] != 'docker':
                return ExecResult(stdout=b'', stderr=b'EXPERIMENTS_DISABLED', exit_code=126)
            if (api.engine.store.run_dir/'PAUSE.flag').exists():
                return ExecResult(stdout=b'', stderr=b'OPERATOR_PAUSED', exit_code=126)
            idea_id = api.agent.get('research_assignment', {}).get('target_id', '')
            permission = api.implementation_allowed(idea_id)
            if permission:
                return ExecResult(stdout=b'', stderr=permission.encode(), exit_code=126)
            remaining = config['max_active_seconds']-api.engine.current_active_seconds()
            if remaining <= 0:
                return ExecResult(stdout=b'', stderr=b'MAX_ACTIVE_SECONDS', exit_code=124)
            require_command_capacity(api.engine.state,api.agent)
            requested = timeout if isinstance(timeout,(int,float)) and math.isfinite(timeout) and timeout>0 else config['experiment_timeout_seconds']
            seconds = max(1,int(min(remaining,requested,config['experiment_timeout_seconds'])))
            argv = [str(c) for c in command]
            record = {'id':'CODE-'+uuid.uuid4().hex[:16], 'agent_id':api.agent['id'],
                'idea_id':idea_id, 'argv':argv, 'status':'RUNNING', 'started_at':now(),
                'meaning':'Development command only, not an independently validated test.'}
            api.engine.state.setdefault('coding_commands', []).append(record)
            api.event('coding_command_started', record)
            # No host shell fallback, Docker socket mount, host HOME or API key.
            worker = asyncio.create_task(asyncio.to_thread(
                DockerExecutor(config['docker_image'],seconds).run,api.workspace.root,argv))
            cancelled = None
            try:
                result = await asyncio.shield(worker)
            except asyncio.CancelledError as error:
                cancelled = error
                while not worker.done():
                    try: await asyncio.shield(worker)
                    except asyncio.CancelledError: continue
                result = worker.result()
            record.update(result, finished_at=now())
            api.event('coding_command_finished', record)
            if cancelled: raise cancelled
            code = result.get('returncode')
            code = code if type(code) is int else 126
            text = result.get('output','')
            if result.get('cleanup_ok') is False:
                raise BackendBlocked('CONTAINER_CLEANUP_UNRESOLVED: '+str(result.get('cleanup_error','')))
            return ExecResult(stdout=text.encode('utf-8'),stderr=b'',exit_code=code)

        def relative(self,path):
            value=str(path).replace('\\','/')
            if value.startswith('/workspace/'):
                value=value[len('/workspace/'):]
            elif value.startswith('/'):
                raise ValueError('SDK workspace I/O is confined to /workspace')
            return _relative(value)

        async def read(self,path,*,user=None):
            return io.BytesIO(_read_bytes(api.workspace.root,self.relative(path),
                api.engine.state['config']['max_file_bytes']))

        async def write(self,path,data,*,user=None):
            body=data.read(api.engine.state['config']['max_file_bytes']+1)
            if len(body)>api.engine.state['config']['max_file_bytes']:
                raise ValueError('MAX_FILE_BYTES')
            api.workspace.write_file(self.relative(path),body)

        async def running(self): return True

        async def persist_workspace(self):
            raise NotImplementedError('Workspace/checkpoint persistence belongs to the swarm host')

        async def hydrate_workspace(self,data):
            raise NotImplementedError('Restore only through the swarm host')

    return DockerWorkspaceSession()
