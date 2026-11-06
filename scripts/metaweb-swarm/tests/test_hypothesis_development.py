import asyncio,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from metaweb_swarm.engine import Engine,ToolAPI,initialize
from metaweb_swarm.config import load_config,PACKAGE_ROOT
from metaweb_swarm.brainstorm_portfolio import record
from metaweb_swarm.hypothesis_development import recover,current,shortlist,candidate,retain
from metaweb_swarm.portfolio_workflow import revision
from metaweb_swarm.backend import OpenAIBackend
from tests.test_backend import FakeProvider,tool_response,final_response,FINAL

class DevelopmentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name);project=root/'project';project.mkdir()
        config=load_config(PACKAGE_ROOT/'config.research.json');config['semantic_dedupe']=False
        self.path=initialize(project,root/'runs',config);self.engine=Engine(self.path,None,'openai')
        self.author=next(a for a in self.engine.state['agents'] if a['work_kind']=='DISCOVERY')
        for n in range(6):record(ToolAPI(self.engine,self.author,None),f'Carrier {n}',f'Unique custody mechanism {n}',['Need capacity evidence'],f'Carrier {n}')
        self.critics=[a for a in self.engine.state['agents'] if a['work_kind']=='REVIEW']
        for a in self.engine.state['agents']:a['status']='COMPLETED'
        self.engine.state['hypothesis_reviews']=[dict(hypothesis_id=h['id'],agent_id=a['id'],verdict='PROMISING',
            reason='Plausible mechanism',duplicate_of='',revision=revision(h)) for h in self.engine.state['brainstorm_hypotheses'] for a in self.critics]
    def tearDown(self):self.engine.close();self.tmp.cleanup()
    def worker(self):
        recover(self.engine)
        return next(a for a in self.engine.state['agents'] if a.get('development_worker'))
    def args(self):
        return {'outcome':'CANDIDATE','reason':'A concrete public carrier retains a recoverable archive with documented size.',
            'provider':'Unusual Carrier','mechanism':'One exact-byte public file with a self describing decoder and hash.',
            'novelty_delta':'No captured baseline carrier matches; historical novelty remains unverified.',
            'recovery_plan':'Download full file and compare checksum with retained export.','cost':'UNKNOWN',
            'evidence':[{'url':'https://fixture.example/docs','claim':'Documented public file retrieval.','verified':False}],
            'limitations':['Retention and actual publication remain untested.']}
    def test_selection_merges_explicit_duplicates_and_respects_limits(self):
        state=self.engine.state;h=state['brainstorm_hypotheses']
        for r in state['hypothesis_reviews']:
            if r['hypothesis_id']==h[1]['id']:r.update(verdict='DUPLICATE',duplicate_of=h[0]['id'])
        result=shortlist(state);self.assertEqual(len(result),3)
        self.assertNotIn(h[1]['id'],[s['id'] for s in result])
        before=dict(state['config']);worker=self.worker();self.assertEqual(state['config'],before)
        self.assertEqual(worker['operator_round_limit'],6)
        count=len(state['agents']);recover(self.engine);self.assertEqual(len(state['agents']),count)
    def test_no_automatic_promotion_without_observed_source(self):
        worker=self.worker();api=ToolAPI(self.engine,worker,None);args=self.args();args.pop('outcome')
        with self.assertRaisesRegex(ValueError,'read_document'):candidate(api,**args)
        self.assertFalse(self.engine.state['ideas'])
    def test_full_roster_retains_shortlist_limit_without_extending_budget(self):
        self.engine.state['config']['max_agents']=len(self.engine.state['agents'])
        recover(self.engine);self.assertEqual(self.engine.state['hypothesis_development']['status'],'LIMIT_REACHED')
        self.assertFalse(any(a.get('development_worker') for a in self.engine.state['agents']))
    async def test_real_sdk_development_creates_sourced_idea_then_yields_without_extra_paid_request(self):
        worker=self.worker();args=self.args()
        async def docs(api,url,purpose,offset=0,limit=12000):
            api.agent.setdefault('http_document_reads',{})['DOC']={'url':url,'sha256':'a'*64,'offset':0,'end':90}
            return {'status':'COMPLETED','url':url,'text':'Carrier supports public file download; retention not verified.'}
        provider=FakeProvider([tool_response('read_document',{'url':args['evidence'][0]['url'],'purpose':'Read primary provider docs','offset':0,'limit':12000}),
            tool_response('finish_development',args,ident='finish')])
        self.engine.backend=OpenAIBackend(provider)
        with patch.object(ToolAPI,'read_document',docs):await self.engine.step(worker)
        self.assertEqual(len(provider.model.calls),2)
        self.assertEqual(len(self.engine.state['ideas']),1,worker.get('reason_for_stopping'))
        idea=self.engine.state['ideas'][0]
        self.assertEqual(idea['status'],'INVESTIGATING');self.assertTrue(idea['source_hypotheses'])
        self.assertEqual(self.engine.state['hypothesis_development']['jobs'][0]['status'],'IDEA_CREATED')
        self.assertEqual(worker['status'],'PENDING')
        self.assertFalse(self.engine.state['external_actions']);self.engine.store.verify()
        names={t.name for t in provider.model.calls[0][1]['tools'] if hasattr(t,'name')}
        self.assertEqual(names,{'read_document','check_baseline','check_prior_work','finish_development','web_search'})
    async def test_sdk_can_record_honest_deferral_without_manufacturing_idea(self):
        worker=self.worker();args=self.args();args.update(outcome='DEFERRED',reason='No documented single-object capacity could be established.',evidence=[])
        self.engine.backend=OpenAIBackend(FakeProvider([tool_response('finish_development',args)]))
        await self.engine.step(worker)
        self.assertFalse(self.engine.state['ideas'])
        self.assertEqual(self.engine.state['hypothesis_development']['jobs'][0]['status'],'DEFERRED')

    async def test_two_real_rounds_allow_document_redirect_then_sourced_candidate(self):
        worker=self.worker();args=self.args()
        checkpoint=dict(args,outcome='CONTINUE',reason='Follow the canonical documentation redirect next round.',evidence=[])
        self.engine.backend=OpenAIBackend(FakeProvider([tool_response('finish_development',checkpoint)]))
        await self.engine.step(worker)
        job=self.engine.state['hypothesis_development']['jobs'][0]
        self.assertEqual(worker['rounds'],1);self.assertEqual(job['rounds'],1);self.assertEqual(job['status'],'PENDING')
        async def docs(api,url,purpose,offset=0,limit=12000):
            api.agent.setdefault('http_document_reads',{})['DOC']={'url':url,'sha256':'c'*64,'offset':0,'end':80}
            return {'status':'COMPLETED','text':'Primary public file retrieval documentation.'}
        self.engine.backend=OpenAIBackend(FakeProvider([tool_response('read_document',{'url':args['evidence'][0]['url'],'purpose':'Read canonical docs','offset':0,'limit':12000}),tool_response('finish_development',args,ident='finish')]))
        with patch.object(ToolAPI,'read_document',docs):await self.engine.step(worker)
        self.assertEqual(worker['rounds'],2);self.assertEqual(job['rounds'],2)
        self.assertEqual(job['status'],'IDEA_CREATED');self.assertEqual(len(self.engine.state['ideas']),1)

    def test_begin_is_idempotent_and_report_counts_explicitly_discussed_rejections(self):
        from metaweb_swarm.hypothesis_development import begin
        from metaweb_swarm.portfolio_workflow import prepare,finish
        worker=self.worker();worker['rounds']=1;api=ToolAPI(self.engine,worker,None)
        begin(api);begin(api)
        self.assertEqual(current(self.engine.state,worker)['rounds'],1)
        reporter=next(a for a in self.engine.state['agents'] if a['work_kind']=='SYNTHESIS');prepare(self.engine.state,reporter)
        ids=[h['id'] for h in self.engine.state['brainstorm_hypotheses']]
        raw=dict(FINAL,summary='Concepts require independent evidence. These last two are explicitly deferred: '+' '.join(ids[-2:]),covered_hypothesis_ids=ids[:-2])
        finish(ToolAPI(self.engine,reporter,None),raw,dict(FINAL))
        self.assertTrue(reporter.get('research_report_receipt'))
    async def test_semantic_comparator_remains_available_at_forced_development_finish(self):
        from metaweb_swarm.demo import DemoBackend
        api=ToolAPI(self.engine,self.author,None)
        api.submit_idea(DemoBackend.idea('Other custody route','Different artifact and independent custodian','FREE','DISCOVERED'))
        self.engine.state['config'].update(semantic_dedupe=True,max_turns=3)
        worker=self.worker();args=self.args()
        async def docs(api,url,purpose,offset=0,limit=12000):
            api.agent.setdefault('http_document_reads',{})['DOC']={'url':url,'sha256':'b'*64,'offset':0,'end':80}
            return {'status':'COMPLETED','text':'Documented public file custody.'}
        provider=FakeProvider([tool_response('read_document',{'url':args['evidence'][0]['url'],'purpose':'Read docs','offset':0,'limit':12000}),
            tool_response('finish_development',args,ident='finish'),final_response(output={'verdict':'DISTINCT','existing_id':'','reason':'Different independent custodian and payload storage.'})])
        self.engine.backend=OpenAIBackend(provider)
        with patch.object(ToolAPI,'read_document',docs):await self.engine.step(worker)
        self.assertEqual(len(self.engine.state['ideas']),2,worker.get('reason_for_stopping'))
        self.assertEqual(len(provider.model.calls),3)
        self.assertEqual(provider.model.calls[-1][1]['tools'],[])
    def test_round_and_token_pressure_route_to_closure_without_global_limit_extension(self):
        from metaweb_swarm.hypothesis_development import schedule,closing_reserve
        state=self.engine.state
        for critic in self.critics:critic['status']='PENDING'
        reporter=next(a for a in state['agents'] if a['work_kind']=='SYNTHESIS');reporter['status']='PENDING'
        before=dict(state['config']);pending=[self.author,*self.critics,reporter]
        result=schedule(state,pending,8,1)
        self.assertIn(result[0],self.critics)
        self.assertGreater(closing_reserve(state,self.author),0)
        self.assertEqual(closing_reserve(state,reporter),0)
        self.assertEqual(state['config'],before)
    async def test_scheduler_finishes_development_jobs_and_preserves_final_report(self):
        worker=self.worker();state=self.engine.state
        reporter=next(a for a in state['agents'] if a['work_kind']=='SYNTHESIS');reporter['status']='PENDING'
        class Backend:
            async def step(inner,agent,prompt,history,api,config):
                if agent.get('development_worker'):retain(api,'DEFERRED','Need documented primary capacity before a concrete candidate.',[])
                return {'output':dict(FINAL,summary='The shortlist was investigated; all three directions need documented capacity before promotion.',assessments=[],covered_hypothesis_ids=[h['id'] for h in state['brainstorm_hypotheses']]),'history':[],'usage':{},'raw':{}}
        self.engine.backend=Backend()
        result=await asyncio.wait_for(self.engine.run(),10)
        self.assertEqual(len(result['hypothesis_development']['jobs']),3)
        self.assertTrue(all(j['status']=='DEFERRED' for j in result['hypothesis_development']['jobs']))
        self.assertEqual(reporter['status'],'COMPLETED',reporter.get('reason_for_stopping'))
        self.assertLessEqual(result['steps'],result['config']['max_steps'])
