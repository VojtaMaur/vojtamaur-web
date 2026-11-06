import asyncio,json,unittest
from types import SimpleNamespace as N
from unittest.mock import patch
from metaweb_swarm.config import load_config,round_allowance
from metaweb_swarm.roles import seed_agents
from metaweb_swarm.backend import _run_public_stream
from tests.test_gui import GUITests

class CustomTests(unittest.TestCase):
    def test_custom_mission_model_and_rounds_survive_seed_creation(self):
        c=load_config();c['seed_roles']=['Loophole Archivist'];c['role_assignments']={'Loophole Archivist':'Changed mission'}
        c['custom_agents']=[{'role':'Digital specialist','mission':'Only digital custody','model_tier':'cheap','rounds':5}]
        agents=seed_agents(c)
        self.assertEqual(agents[0]['mission'],'Changed mission')
        self.assertEqual(agents[1]['work_kind'],'DISCOVERY')
        self.assertEqual(agents[1]['model_tier'],'cheap')
        self.assertEqual(round_allowance(c,agents[1]),5)
        self.assertIsNone(agents[1]['parent_id'])
        c['max_agents']=1
        with self.assertRaises(ValueError):seed_agents(c)
        c['max_agents']=5;c['custom_agents'][0]['role']='Loophole Archivist'
        with self.assertRaises(ValueError):seed_agents(c)

class ObjectiveTests(GUITests):
    def test_objective_replaces_default_and_comment_appends(self):
        with patch.object(self.service,'launch',return_value={'ok':True}) as launch:
            self.service.start({'profile':'cheap','objective':'A completely different research question','task':'A comment','backend':'demo'})
        args=launch.call_args.args[0]
        from pathlib import Path
        c=json.loads(Path(args[args.index('--config')+1]).read_text())
        self.assertEqual(c['operator_objective'],'A completely different research question\n\nOPERATOR COMMENT:\nA comment')
        self.assertTrue(c['live_output_preview'])

    def test_live_preview_is_public_event_only(self):
        from metaweb_swarm.storage import Store
        store=Store(self.path)
        store.commit(self.state,'sdk_output_preview',{'text':'Visible response','partial':True},'AGENT-001');store.close()
        self.assertEqual(self.service.run(self.run_id)['live_output']['data']['text'],'Visible response')

class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_sdk_stream_with_local_model_and_no_network(self):
        from agents import Agent,Runner,RunConfig
        from openai.types.responses import Response,ResponseCreatedEvent,ResponseCompletedEvent,ResponseTextDeltaEvent
        from tests.test_backend import FakeModel,final_response
        output=final_response()
        response=Response.model_construct(id='local-stream-proof',created_at=0,model='local',object='response',
            output=output.output,usage=None,status='completed',parallel_tool_calls=False,tool_choice='auto',tools=[])
        class Model(FakeModel):
            async def stream_response(self,*args,**kwargs):
                yield ResponseCreatedEvent(type='response.created',response=response,sequence_number=0)
                yield ResponseTextDeltaEvent(type='response.output_text.delta',delta='Public preview',item_id='item',content_index=0,output_index=0,sequence_number=1,logprobs=[])
                yield ResponseCompletedEvent(type='response.completed',response=response,sequence_number=2)
        records=[]
        agent=Agent(name='Local fixture',model=Model([]))
        result=await _run_public_stream(N(Runner=Runner),agent,'offline',{},RunConfig(tracing_disabled=True),N(record=lambda k,v:records.append((k,v))),hooks=__import__('agents').RunHooks())
        self.assertTrue(result.is_complete)
        self.assertEqual(records[-1][1]['text'],'Public preview')

    async def test_only_output_text_is_previewed_and_hooks_remain_attached(self):
        records=[]
        class Stream:
            is_complete=False
            async def stream_events(self):
                for kind,delta in [('response.created',''),('response.reasoning_text.delta','PRIVATE'),('response.output_text.delta','PUBLIC'),('response.completed','')]:
                    yield N(type='raw_response_event',data=N(type=kind,delta=delta))
                self.is_complete=True
            def cancel(self,mode):raise AssertionError('Finished run was cancelled')
        stream=Stream();runner=N(run_streamed=lambda *a,**k:stream)
        with patch('metaweb_swarm.backend._make_hooks',return_value=object()):
            result=await _run_public_stream(N(Runner=runner),None,[],{},None,N(record=lambda k,v:records.append((k,v))))
        self.assertIs(result,stream);self.assertEqual(records[-1][1],{'text':'PUBLIC','partial':False})
        self.assertNotIn('PRIVATE',str(records))

    async def test_cancel_stops_stream_and_drains(self):
        class Stream:
            is_complete=False;cancelled=False;drained=False
            async def stream_events(self):
                if self.cancelled:self.drained=True;return
                await asyncio.sleep(10)
                yield None
            def cancel(self,mode):self.cancelled=True;self.is_complete=True
        stream=Stream()
        with patch('metaweb_swarm.backend._make_hooks',return_value=object()):
            task=asyncio.create_task(_run_public_stream(N(Runner=N(run_streamed=lambda *a,**k:stream)),None,[],{},None,N(record=lambda *a:None)))
            await asyncio.sleep(.01);task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(stream.cancelled and stream.drained)
