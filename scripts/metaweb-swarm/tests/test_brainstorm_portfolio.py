"""Early ideas survive without being promoted to verified candidates."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch

from metaweb_swarm.brainstorm_portfolio import record,capture_screen,from_audit
from metaweb_swarm.config import load_config,PACKAGE_ROOT
from metaweb_swarm.demo import DemoBackend
from metaweb_swarm.engine import Engine,ToolAPI
from metaweb_swarm.engine import initialize


class PortfolioTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        project=root/'project';project.mkdir()
        config=load_config(PACKAGE_ROOT/'config.research.json');config['semantic_dedupe']=False
        self.path=initialize(project,root/'runs',config)
        self.engine=Engine(self.path,DemoBackend(),'demo')
        self.agent=next(a for a in self.engine.state['agents'] if a['work_kind']=='DISCOVERY')
        self.api=ToolAPI(self.engine,self.agent,None)

    def tearDown(self):
        self.engine.close();self.tmp.cleanup()

    def test_multiple_hypotheses_and_provenance_do_not_inflate_candidates(self):
        from metaweb_swarm.deposit_handoff import report_revision
        before=report_revision(self.engine.state)
        first=record(self.api,'Institution deposit','Offer an EPUB to an independent custodian',['Eligibility unknown'])
        other=next(a for a in self.engine.state['agents'] if a['work_kind']=='DISCOVERY' and a!=self.agent)
        duplicate=record(ToolAPI(self.engine,other,None),'Institution deposit','Offer an EPUB to an independent custodian',[])
        record(self.api,'Signal encoding','Encode recovery data in a public signal artifact',['Capacity unknown'])
        self.assertEqual(first['id'],duplicate['id'])
        self.assertEqual(first['contributors'],[self.agent['id'],other['id']])
        self.assertEqual(len(self.engine.state['brainstorm_hypotheses']),2)
        self.assertNotEqual(before,report_revision(self.engine.state))
        self.assertEqual(self.engine.state['ideas'],[])
        self.assertTrue(all(h['status']=='UNREVIEWED' for h in self.engine.state['brainstorm_hypotheses']))
        self.engine.store.verify()

    def test_screen_capture_and_historical_projection_remove_url_secrets(self):
        args={'provider':'Known carrier','service_url':'https://user:password@example.org/docs?token=secret#secret',
              'proposed_change':'Store an exact export in a public artifact'}
        self.engine.store.commit(self.engine.state,'sdk_tool_started',{'name':'screen_carrier','arguments':json.dumps(args)},self.agent['id'])
        before=self.engine.store.db.execute('SELECT count(*) FROM events').fetchone()[0]
        items=from_audit(self.engine.store.db)
        self.assertEqual(self.engine.store.db.execute('SELECT count(*) FROM events').fetchone()[0],before)
        self.assertEqual(items[0]['source_urls'],['https://example.org/docs'])
        capture_screen(self.api,**args,result={'status':'EXISTING_ARCHIVE_LAYER'})
        capture_screen(self.api,'Carrier','','',{})
        hypothesis=self.engine.state['brainstorm_hypotheses'][0]
        self.assertEqual(hypothesis['screen_status'],'EXISTING_ARCHIVE_LAYER')
        self.assertEqual(hypothesis['status'],'UNREVIEWED')
        self.assertFalse(self.engine.state['ideas'])

    def test_report_only_retains_screened_directions_even_with_one_existing_idea(self):
        from metaweb_swarm.research_closure import prepare,report_packet
        from metaweb_swarm.report_packet import build,read
        from metaweb_swarm.reporting import generate_reports
        self.engine.state['ideas']=[{'id':'IDEA-0001','title':'Existing candidate','status':'DISCOVERED','summary':'Already submitted'}]
        for provider in ['Custodian A','Custodian B']:
            self.engine.store.commit(self.engine.state,'sdk_tool_started',{'name':'screen_carrier','arguments':json.dumps({
                'provider':provider,'proposed_change':'Independent custody proposal '+provider})},self.agent['id'])
        prepare(self.engine,'Close existing research only',report_only=True)
        self.assertEqual(len(self.engine.state['ideas']),1)
        self.assertEqual(len(self.engine.state['brainstorm_hypotheses']),2)
        self.assertEqual(len(report_packet(self.engine.state)['unreviewed_hypotheses']),2)
        packet=build(self.engine.state)
        self.assertEqual(packet['hypothesis_count'],2)
        reporter=next(a for a in self.engine.state['agents'] if a['work_kind']=='SYNTHESIS')
        index=read(ToolAPI(self.engine,reporter,None),'brainstorm_hypotheses')
        self.assertEqual(len(json.loads(index['text'])),2)
        generate_reports(self.path,self.engine.state)
        self.assertIn('Pracovní hypotézy (neověřené)',(self.path/'SWARM_REPORT.md').read_text(encoding='utf-8'))
        self.assertEqual(len(json.loads((self.path/'manifest.json').read_text())['brainstorm_hypotheses']),2)

    def test_hypothesis_tool_not_available_to_reviews_or_experimental_roles(self):
        import agents
        from metaweb_swarm.backend import _make_sdk_tools
        names={t.name for t in _make_sdk_tools(agents,self.api)[0]}
        self.assertIn('record_hypothesis',names)
        reviewer=next(a for a in self.engine.state['agents'] if a['work_kind']=='REVIEW')
        names={t.name for t in _make_sdk_tools(agents,ToolAPI(self.engine,reviewer,None))[0]}
        self.assertNotIn('record_hypothesis',names)
        self.engine.state['config']['task_style']='general'
        with self.assertRaisesRegex(ValueError,'brainstorming'):
            record(self.api,'Sketch','A new idea',[])

    async def test_real_sdk_records_two_early_hypotheses_without_network(self):
        from metaweb_swarm.backend import OpenAIBackend
        from tests.test_backend import FakeProvider,tool_response,final_response
        responses=[]
        for n in range(2):
            responses.append(tool_response('record_hypothesis',{'title':f'Direction {n}','mechanism':f'Different preservation route {n}',
                'unknowns':['Requires primary verification'],'provider':'','source_urls':[]},ident=f'hyp{n}'))
        provider=FakeProvider(responses+[final_response()])
        config=self.engine.state['config']
        await OpenAIBackend(provider).step(self.agent,self.engine.prompt(self.agent),[],self.api,config)
        self.assertEqual(len(self.engine.state['brainstorm_hypotheses']),2)
        self.assertFalse(self.engine.state['ideas'])


class PublicActivityStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_and_search_progress_visible_without_reasoning_or_argument_buffers(self):
        from metaweb_swarm.backend import _run_public_stream
        records=[]
        class Stream:
            is_complete=False
            async def stream_events(self):
                for data in [N(type='response.created'),N(type='response.reasoning_text.delta',delta='PRIVATE'),
                             N(type='response.function_call_arguments.delta',delta='SECRET_ARGS'),
                             N(type='response.output_item.added',item=N(type='function_call',name='read_document')),
                             N(type='response.web_search_call.searching'),N(type='response.web_search_call.completed')]:
                    yield N(type='raw_response_event',data=data)
                self.is_complete=True
            def cancel(self,mode):raise AssertionError('Completed stream cancelled')
        stream=Stream()
        with patch('metaweb_swarm.backend._make_hooks',return_value=object()):
            await _run_public_stream(N(Runner=N(run_streamed=lambda *a,**k:stream)),None,[],{},None,N(record=lambda k,v:records.append((k,v))))
        self.assertEqual([v['phase'] for k,v in records],['generating','tool','search','search'])
        self.assertIn('read_document',str(records))
        self.assertNotIn('PRIVATE',str(records));self.assertNotIn('SECRET_ARGS',str(records))
