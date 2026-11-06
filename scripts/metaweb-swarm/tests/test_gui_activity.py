"""Useful, bounded activity survives SDK checkpoint noise without secrets."""
import json
import sqlite3
import unittest
from contextlib import closing

from tests import test_gui as gui_fixture
from metaweb_swarm.gui import ACTIVITY_LIMIT
from metaweb_swarm.storage import Store


class ActivityTests(unittest.TestCase):
    setUp=gui_fixture.GUITests.setUp
    tearDown=gui_fixture.GUITests.tearDown

    def event(self,kind,data,agent_id='AGENT-002'):
        store=Store(self.path)
        try:return store.commit(self.state,kind,data,agent_id)
        finally:store.close()

    def flood(self,kind='sdk_history_checkpoint',count=250):
        with closing(sqlite3.connect(self.path/'state.sqlite3')) as db,db:
            first=db.execute('SELECT max(seq) FROM events').fetchone()[0]+1
            db.executemany('INSERT INTO events(seq,body) VALUES (?,?)',[
                (seq,json.dumps({'seq':seq,'kind':kind,'time':'2026-11-04T09:00:00Z','agent_id':'AGENT-001',
                                 'data':{'history':[{'content':'PRIVATE CHECKPOINT'}],'text':'noise note'}}))
                for seq in range(first,first+count)])

    def test_checkpoint_flood_cannot_hide_tool_detail_note_or_latest_public_output(self):
        self.event('sdk_tool_started',{'name':'read_document','arguments':json.dumps({
            'url':'https://user:password@example.org/docs?signature=PRIVATE#token',
            'purpose':'Check preservation terms','headers':{'Authorization':'PRIVATE HEADER'},
            'body':'PRIVATE BODY'})})
        self.event('sdk_tool_finished',{'name':'read_document','result':json.dumps({
            'status':'COMPLETED','text':'Free public preservation; deletion after 30 days.',
            'headers':{'Set-Cookie':'PRIVATE COOKIE'},'body':'PRIVATE BODY',
            'history':'PRIVATE HISTORY','reasoning':'PRIVATE THOUGHT'})})
        self.event('agent_note',{'text':'Comparing independent custody domains.'})
        self.event('sdk_output_preview',{'text':'Public final response','partial':False})
        self.flood()
        view=self.service.run(self.run_id)
        self.assertEqual(view['live_output']['data']['text'],'Public final response')
        self.assertEqual(len(view['activity']),3)
        self.assertTrue(any('Free public preservation' in e['detail'] for e in view['activity']))
        start=next(e for e in view['activity'] if e['kind']=='sdk_tool_started')
        self.assertIn('https://example.org/docs',start['detail'])
        self.assertIn('Check preservation terms',start['detail'])
        self.assertNotIn('PRIVATE',json.dumps(view['activity']))
        self.assertNotIn('password',json.dumps(view['activity']))
        self.assertNotIn('signature',json.dumps(view['activity']))

    def test_current_activity_keeps_quieter_agents_after_another_fills_recent_window(self):
        self.event('agent_note',{'text':'Quieter role finished a concrete review.'},'AGENT-002')
        self.flood(kind='agent_note',count=ACTIVITY_LIMIT+20)
        view=self.service.run(self.run_id)
        self.assertEqual(len(view['activity']),ACTIVITY_LIMIT)
        current={e['agent_id']:e for e in view['current_activity']}
        self.assertIn('Quieter role',current['AGENT-002']['text'])
        agent=next(a for a in view['agents'] if a['id']=='AGENT-002')
        self.assertIn('Quieter role',agent['last_action'])
        self.assertEqual(agent['activity'],current['AGENT-002'])

    def test_search_file_http_and_lifecycle_have_specific_safe_descriptions(self):
        samples=[('sdk_model_request_started',{'attempt':1}),
                 ('sdk_web_search_call',{'action':{'type':'search','queries':['free deposit EPUB','independent custody']}}),
                 ('file_read',{'path':'context/ARCHIVE.txt','offset':200,'characters':600}),
                 ('file_searched',{'path':'context/ARCHIVE.txt','query':'Zenodo'}),
                 ('http_document_read',{'url':'https://example.org/docs?key=hidden','offset':0,'end':1400}),
                 ('research_task_assigned',{'kind':'RESEARCH_IDEA','target_id':'IDEA-0001'}),
                 ('sdk_activity',{'phase':'generating','text':'Připravuje odpověď'}),
                 ('agent_round_finished',{'status':'COMPLETED','reason':'Research complete.'})]
        for kind,data in samples:self.event(kind,data)
        view=self.service.run(self.run_id)
        self.assertEqual(len(view['activity']),len(samples))
        text=json.dumps(view['activity'],ensure_ascii=False)
        for phrase in ('Čeká na odpověď modelu','free deposit EPUB','context/ARCHIVE.txt','Zenodo',
                       'https://example.org/docs','IDEA-0001','Připravuje odpověď','Research complete.'):
            self.assertIn(phrase,text)
        self.assertNotIn('hidden',text)

    def test_response_excerpts_are_bounded_clean_and_exclude_http_body_and_headers(self):
        key='fixture-secret-value';self.service._secrets.append(key)
        self.event('sdk_tool_finished',{'name':'http_request','result':json.dumps({
            'status':'COMPLETED','reason':'Authorization: PRIVATE AUTH VALUE',
            'response':{'status':200,'response_bytes':124,'path':'http/response.bin',
            'headers':{'Authorization':key},'body':'PRIVATE RESPONSE BODY'},'reasoning':'PRIVATE THOUGHT'})})
        self.event('sdk_tool_finished',{'name':'read_file','result':key+' '+'Public source excerpt '*200})
        self.event('sdk_tool_started',{'name':'submit_idea','arguments':json.dumps({
            'idea_id':'IDEA-0007','body':'PRIVATE BODY','api_key':key,'headers':{'Authorization':key}})})
        self.event('sdk_tool_finished',{'name':'unknown_tool','result':'PRIVATE UNKNOWN OUTPUT'})
        view=self.service.run(self.run_id);text=json.dumps(view['activity'])
        self.assertNotIn(key,text);self.assertNotIn('PRIVATE',text)
        self.assertIn('response.status: 200',text)
        self.assertIn('IDEA-0007',text)
        self.assertTrue(all(len(item['detail'])<=1600 for item in view['activity']))
        self.assertTrue(all(set(item)=={'seq','time','agent_id','kind','text','detail'} for item in view['activity']))

    def test_hypotheses_are_visible_as_unreviewed_distinct_from_ideas_without_private_data(self):
        self.state['brainstorm_hypotheses']=[{'id':'HYP-0001','title':'Unusual legitimate carrier',
            'mechanism':'Retain an exported build','status':'UNREVIEWED','contributors':['AGENT-002'],
            'unknowns':['Need exact retention terms'],'history':['PRIVATE']}]
        self.event('agent_note',{'text':'Saved an early hypothesis.'})
        view=self.service.run(self.run_id)
        self.assertEqual(view['hypotheses'][0]['id'],'HYP-0001')
        self.assertEqual(view['hypotheses'][0]['status'],'UNREVIEWED')
        self.assertNotIn('history',view['hypotheses'][0])
        self.assertEqual(view['ideas'],[])

    def test_historical_screen_proposal_is_visible_without_mutating_old_run(self):
        self.event('sdk_tool_started',{'name':'screen_carrier','arguments':json.dumps({
            'provider':'Historical service','service_url':'https://example.org/api?signature=private',
            'proposed_change':'Keep a self-describing public export in the service.'})})
        before=(self.path/'state.sqlite3').read_bytes()
        view=self.service.run(self.run_id)
        self.assertEqual(len(view['hypotheses']),1)
        item=view['hypotheses'][0]
        self.assertEqual(item['status'],'UNREVIEWED')
        self.assertIn('self-describing public export',item['mechanism'])
        self.assertEqual(item['source_urls'],['https://example.org/api'])
        self.assertTrue(item['source_event_seq'])
        self.assertEqual(before,(self.path/'state.sqlite3').read_bytes())
        self.assertNotIn('brainstorm_hypotheses',self.service._state(self.run_id))

