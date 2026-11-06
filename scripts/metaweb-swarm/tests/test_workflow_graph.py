"""The dashboard graph must describe recorded links, never invent handoffs."""
import copy
import json
import threading
import urllib.request
import urllib.error
import unittest
from metaweb_swarm.workflow_graph import build_workflow,MAX_NODES
from metaweb_swarm.gui import make_server
from tests import test_gui as fixtures

class WorkflowGraphTests(unittest.TestCase):
    def fixture(self):
        return {'run_id':'example','status':'RUNNING','updated_at':'2026-11-04','config':{},'agents':[
            {'id':'A1','role':'Meta-Archivist / Orchestrator','work_kind':'COORDINATION','status':'COMPLETED'},
            {'id':'A2','role':'Scout','display_name':'Průzkumník','work_kind':'DISCOVERY','status':'COMPLETED','parent_id':'A1','history':['SECRET_HISTORY']},
            {'id':'A3','role':'Evidence Auditor','work_kind':'REVIEW','status':'RUNNING','review_assignment':{'kind':'RESEARCH_IDEA','target_id':'I1'}},
            {'id':'A4','role':'Reporter','work_kind':'SYNTHESIS','status':'PENDING','research_report_receipt':{'agent_id':'A4','idea_ids':['I1'],'conclusion':'Conclusion'}}],
            'brainstorm_hypotheses':[{'id':'H1','title':'Draft','contributors':['A2'],'mechanism':'Some hypothesis'}],
            'hypothesis_reviews':[{'agent_id':'A3','hypothesis_id':'H1','verdict':'PROMISING','reason':'Needs evidence'}],
            'hypothesis_development':{'jobs':[{'agent_id':'A2','hypothesis_id':'H1','idea_id':'I1','status':'IDEA_CREATED'}]},
            'ideas':[{'id':'I1','title':'Idea','status':'INVESTIGATING','agent_id':'A2','contributors':['A2']}],
            'critiques':[{'agent_id':'A3','idea_id':'I1','id':'C1','verdict':'REVISE','reason':'Missing evidence'}],
            'tests':[{'id':'T1','idea_id':'I1','agent_id':'A2','status':'COMPLETED','prototype_review':{'agent_id':'A3','verdict':'SUBCOMPONENT'}}],
            'approvals':[{'id':'P1','idea_id':'I1','status':'PENDING','action':{'credentials':'DO_NOT_PROJECT'}}]}
    def test_provenance_review_development_receipts_and_assignments(self):
        state=self.fixture();before=copy.deepcopy(state);g=build_workflow(state,running=True,activity=[{'agent_id':'A3','text':'Čte dokumentaci'}])
        nodes={n['id']:n for n in g['nodes']};edges={(e['source'],e['target'],e['kind']):e for e in g['edges']}
        self.assertEqual(nodes['agent:A2']['label'],'Průzkumník')
        self.assertEqual(nodes['agent:A3']['details']['activity'],'Čte dokumentaci')
        for key in [('agent:A1','agent:A2','spawn'),('agent:A2','hypothesis:H1','contribution'),
            ('agent:A3','hypothesis:H1','review'),('hypothesis:H1','idea:I1','promotion'),
            ('agent:A3','idea:I1','review'),('idea:I1','test:T1','evidence'),
            ('agent:A3','test:T1','review'),('agent:A4','report:SWARM_REPORT.md','report'),('idea:I1','report:SWARM_REPORT.md','report')]:self.assertIn(key,edges)
        self.assertTrue(edges['agent:A3','idea:I1','assignment']['active'])
        self.assertEqual(edges['hypothesis:H1','idea:I1','promotion']['count'],1)
        self.assertEqual(state,before)
        self.assertNotIn('SECRET_HISTORY',json.dumps(g));self.assertNotIn('DO_NOT_PROJECT',json.dumps(g))
    def test_stopped_writer_never_has_active_or_running_nodes(self):
        g=build_workflow(self.fixture(),running=False)
        self.assertFalse(any(e['active'] for e in g['edges']))
        auditor=next(n for n in g['nodes'] if n['id']=='agent:A3');self.assertEqual(auditor['status'],'INTERRUPTED')
        self.assertFalse(any(s['active'] for s in g['stages']))
    def test_no_fabricated_coordination_or_report_coverage(self):
        state=self.fixture();state['agents'][-1].pop('research_report_receipt');state['agents'][1].pop('parent_id')
        g=build_workflow(state,report_exists=True)
        self.assertTrue(any(n['kind']=='report' for n in g['nodes']))
        self.assertFalse(any(e['kind'] in {'report','spawn'} for e in g['edges']))
        self.assertFalse(any(e['source']=='agent:A1' for e in g['edges']))
    def test_missing_endpoints_duplicates_and_bounded_old_runs(self):
        state=self.fixture();state['critiques'].append(dict(state['critiques'][0],id='C2'));state['critiques'].append({'agent_id':'missing','idea_id':'nope'})
        g=build_workflow(state)
        edge=next(e for e in g['edges'] if (e['source'],e['target'],e['kind'])==('agent:A3','idea:I1','review'))
        self.assertEqual(edge['count'],2)
        ids={n['id'] for n in g['nodes']};self.assertTrue(all(e['source'] in ids and e['target'] in ids for e in g['edges']))
        self.assertEqual(build_workflow({})['nodes'],[])
        large={'brainstorm_hypotheses':[{'id':f'H{i}','title':'Hypothesis'} for i in range(MAX_NODES+20)]}
        g=build_workflow(large);self.assertEqual(len(g['nodes']),MAX_NODES);self.assertEqual(g['omitted_nodes'],20)
    def test_hypothesis_fallback_parameter_and_current_developer(self):
        state={'agents':[{'id':'A','role':'Candidate Developer','work_kind':'DISCOVERY','status':'RUNNING','development_assignment':'H'}]}
        g=build_workflow(state,running=True,hypotheses=[{'id':'H','title':'Old audit hypothesis'}])
        self.assertEqual(g['nodes'][0]['stage'],'review');self.assertTrue(g['edges'][0]['active'])

class WorkflowGUITests(unittest.TestCase):
    setUp=fixtures.GUITests.setUp
    tearDown=fixtures.GUITests.tearDown
    def test_run_projects_workflow_without_writing_database(self):
        before=(self.path/'state.sqlite3').read_bytes();run=self.service.run(self.run_id)
        self.assertIn('workflow',run);self.assertEqual(run['workflow']['schema_version'],1)
        self.assertTrue(run['workflow']['nodes']);self.assertEqual(before,(self.path/'state.sqlite3').read_bytes())

    def test_http_graph_uses_existing_auth_and_serves_local_javascript(self):
        server=make_server(self.service);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        origin='http://127.0.0.1:'+str(server.server_port)
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(origin+'/api/run?id='+self.run_id,timeout=3)
            self.assertEqual(error.exception.code,403)
            req=urllib.request.Request(origin+'/api/run?id='+self.run_id,headers={'X-Swarm-Token':self.service.token})
            with urllib.request.urlopen(req,timeout=3) as response:data=json.load(response)
            self.assertIn('workflow',data);self.assertFalse(data['workflow']['running'])
            with urllib.request.urlopen(origin+'/workflow.js',timeout=3) as response:
                self.assertIn('javascript',response.headers['Content-Type'])
                self.assertIn(b'class SwarmWorkflow',response.read())
        finally:server.shutdown();server.server_close();thread.join(2)
