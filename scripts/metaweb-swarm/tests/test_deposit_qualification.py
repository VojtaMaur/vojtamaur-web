import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from tests.test_http_tools import Service
from tests.test_backend import SDK_AVAILABLE
from metaweb_swarm.config import load_config
from metaweb_swarm.engine import Engine, ToolAPI, initialize, decide, refresh_reports
from metaweb_swarm.demo import DemoBackend
from metaweb_swarm.workspace import Workspace

class QualificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        project = self.root/'project'; (project/'exports').mkdir(parents=True)
        (project/'exports/build.epub').write_bytes(b'real public export fixture')
        (project/'public').mkdir(); (project/'public/ARCHIVE.txt').write_text('Known carrier https://known.example.org/archive\n')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Service); self.server.calls=[]; self.server.data=b''
        self.thread=threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.origin=f'http://127.0.0.1:{self.server.server_port}'
        self.config=load_config(Path(__file__).resolve().parents[1]/'config.deposit-trial.json')
        self.config.update(export_filenames=['build.epub'], http_test_origins=[self.origin], semantic_dedupe=False)
        self.config['carrier_screening']=False
        self.config['require_explicit_upload_flow']=False
        self.run=initialize(project, self.root/'runs', self.config); self.engine=Engine(self.run, DemoBackend(), 'demo')
        self.discovery, self.auditor, self.prototyper = self.engine.state['agents'][:3]
        self.api=self.for_agent(self.discovery)
    def for_agent(self, agent):
        return ToolAPI(self.engine,agent,Workspace(self.run/'snapshot',self.run/'agents'/agent['id']/'workspace'))
    def tearDown(self):
        self.engine.close(); self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()
    def plan(self, **changes):
        data={'upload_url':self.origin+'/file','method':'POST','authentication':'ANONYMOUS','credential_id':'',
              'export_path':'build.epub','required_external_actions':1,'documentation_urls':[self.origin+'/docs',self.origin+'/terms'],
              'provider':'Fixture public carrier','novelty_class':'POTENTIALLY_NEW','baseline_evidence_ids':[],
              'baseline_behavior':'','proposed_change':'','validation_plan':''}
        data.update(changes); return data
    def idea(self, receipt=None):
        data=DemoBackend.idea('Public export carrier','Deposit exact public EPUB bytes','FREE','DISCOVERED')
        data['provider']='Fixture public carrier'; data['qualification_id']=receipt['id'] if receipt else ''
        return data
    async def observe(self, api):
        for path in ['/docs','/terms']:
            r=await api.http_request({'url':self.origin+path},purpose='Read primary API and terms')
            api.read_file(r['response']['path'])
    def test_forbidden_target_precedes_account_setup_and_never_creates_idea(self):
        for host in ['gitlab.com','api.github.com','codeberg.org','vojtamaur.cz','gitlab.com.']:
            plan=self.plan(upload_url='https://'+host+'/api/files',authentication='ACCOUNT_REQUIRED')
            r=self.api.check_deposit_target(plan)
            self.assertEqual(r['status'],'POLICY_FORBIDDEN'); self.assertFalse(r['admissible'])
            self.assertEqual(self.api.submit_idea(self.idea(r))['reason'],'DEPOSIT_QUALIFICATION_REQUIRED')
        self.assertFalse(self.engine.state['ideas']); self.assertFalse(self.engine.state['approvals']); self.assertFalse(self.server.calls)
    async def test_missing_grant_is_blocked_lead_not_rejected_mechanism(self):
        await self.observe(self.api)
        r=self.api.check_deposit_target(self.plan(authentication='ACCOUNT_REQUIRED'))
        self.assertEqual(r['status'],'ACCOUNT_SETUP_REQUIRED')
        idea=self.api.submit_idea(self.idea(r)); self.assertEqual(idea['status'],'BLOCKED')
        review=self.for_agent(self.auditor)
        self.assertEqual(review.record_critique(idea['id'],'PASS','Cannot pass without grant')['reason'],'DEPOSIT_QUALIFICATION_NOT_READY')
    async def test_exact_reviewed_export_approval_resume_and_readback(self):
        await self.observe(self.api)
        r=self.api.check_deposit_target(self.plan()); self.assertEqual(r['status'],'READY_FOR_AUDIT')
        self.assertEqual(self.api.check_deposit_target(self.plan())['id'], r['id'])
        idea=self.api.submit_idea(self.idea(r)); self.assertIn('id',idea)
        review=self.for_agent(self.auditor)
        self.auditor['external_sources']=self.plan()['documentation_urls']
        self.assertEqual(review.record_critique(idea['id'],'PASS','Search links alone are insufficient')['reason'],'AUDIT_DOCUMENTS_NOT_READ')
        await self.observe(review)
        critique=review.record_critique(idea['id'],'PASS','Independent documents support exact free public export deposit')
        self.assertEqual(critique['qualification_id'],r['id'])
        execute=self.for_agent(self.prototyper); execute.materialize_export('build.epub','payload/export.epub')
        request={'url':self.origin+'/file','method':'POST','upload_path':'payload/export.epub'}
        execute.write_file('payload/toy.txt','wrong payload')
        bad=await execute.http_request(dict(request,upload_path='payload/toy.txt'),idea['id'],'Upload reviewed public export')
        self.assertEqual(bad['reason'],'UPLOAD_IS_NOT_QUALIFIED_EXPORT')
        bad=await execute.http_request(dict(request,url=self.origin+'/other'),idea['id'],'Upload reviewed public export')
        self.assertEqual(bad['reason'],'UPLOAD_DIFFERS_FROM_QUALIFIED_PLAN')
        pending=await execute.http_request(request,idea['id'],'Upload reviewed public export')
        self.assertEqual(pending['reason'],'HUMAN_APPROVAL_REQUIRED')
        decide(self.engine.store,self.engine.state,pending['approval_id'],'approve','Approve exact fixture deposit')
        self.engine.close(); self.engine=Engine(self.run,DemoBackend(),'demo')
        execute=self.for_agent(self.engine.state['agents'][2])
        sent=await execute.http_request(request,idea['id'],'Upload reviewed public export')
        get=await execute.http_request({'url':self.origin+'/file'},idea['id'],'Download stored exact export')
        receipt=execute.verify_http_copy(sent['id'],get['id'],'payload/export.epub')
        self.assertTrue(receipt['host_verified'])
        refresh_reports(self.engine.store,self.engine.state)
        manifest=json.loads((self.run/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['deposit_qualifications'][0]['id'],r['id'])
        self.assertIn('READY_FOR_AUDIT',(self.run/'SWARM_REPORT.md').read_text(encoding='utf-8'))
    async def test_auditor_cannot_manufacture_candidate_and_source_claims_not_enough(self):
        self.assertEqual(self.api.submit_idea(self.idea())['reason'],'DEPOSIT_QUALIFICATION_REQUIRED')
        r=self.api.check_deposit_target(self.plan()); self.assertEqual(r['status'],'PRIMARY_SOURCES_REQUIRED')
        self.assertEqual(self.for_agent(self.auditor).submit_idea(self.idea(r))['reason'],'DISCOVERY_OWNS_NEW_CANDIDATES')
    async def test_resource_failure_and_archive_mention_are_separate(self):
        await self.observe(self.api)
        r=self.api.check_deposit_target(self.plan(required_external_actions=2)); self.assertEqual(r['status'],'RESOURCE_LIMIT')
        plan=self.plan(upload_url='https://known.example.org/files',provider='Known carrier')
        r=self.api.check_deposit_target(plan); self.assertEqual(r['status'],'BASELINE_COMPARISON_REQUIRED')
        self.assertNotIn('ALREADY_KNOWN_BASELINE',r['reasons'])
        hits=r['baseline']['matches']; self.assertTrue(hits)
        plan.update(novelty_class='KNOWN_CARRIER',baseline_evidence_ids=[hits[0]['id']])
        self.assertEqual(self.api.check_deposit_target(plan)['status'],'ALREADY_KNOWN_BASELINE')
    async def test_dedicated_grant_is_host_scoped_and_no_secret_recorded(self):
        await self.observe(self.api)
        self.engine.state['config']['http_credentials']=[{'id':'dedicated','env':'META_SWARM_CRED_FIXTURE',
            'hosts':['example.org'],'header':'Authorization','scheme':'Bearer'}]
        p=self.plan(upload_url='https://example.org/upload',authentication='DEDICATED_CREDENTIAL',credential_id='dedicated')
        with patch.dict(os.environ,{'META_SWARM_CRED_FIXTURE':'fixture-secret'}):
            r=self.api.check_deposit_target(p); self.assertEqual(r['status'],'READY_FOR_AUDIT')
            self.assertNotIn('fixture-secret',json.dumps(r))
            r=self.api.check_deposit_target(dict(p,upload_url='https://other.example.org/upload'))
            self.assertEqual(r['status'],'ACCOUNT_SETUP_REQUIRED')
    async def test_no_qualified_candidate_skips_downstream_model_work(self):
        calls=[]
        class Finish:
            async def step(inner,agent,prompt,history,api,config):
                calls.append(agent['role'])
                return {'output':{'status':'COMPLETED','reason_for_stopping':'Assigned work finished','summary':'No usable plan',
                    'unexplored_leads':[],'handoff_leads':[],'blind_spots':[]},'history':history,
                    'usage':{},'raw':{'usage_complete':True}}
        self.engine.backend=Finish(); await self.engine.run()
        self.assertEqual(calls,['Loophole Archivist','Synthesizer / Reporter'])
        self.assertEqual(self.engine.state['status'],'BLOCKED')

    @unittest.skipUnless(SDK_AVAILABLE, 'SDK required')
    async def test_actual_sdk_dispatches_qualification_tool_without_paid_api(self):
        from tests.test_backend import FakeProvider, tool_response, final_response
        from metaweb_swarm.backend import OpenAIBackend
        await self.observe(self.api)
        provider=FakeProvider([tool_response('check_deposit_target', self.plan()), final_response()])
        result=await OpenAIBackend(provider).step(self.discovery,self.engine.prompt(self.discovery),[],self.api,self.config)
        self.assertEqual(result['output']['status'],'COMPLETED')
        self.assertEqual(self.engine.state['deposit_qualifications'][-1]['status'],'READY_FOR_AUDIT')
        self.assertFalse(self.engine.state['ideas'])
        self.assertFalse(any(m=='POST' for m,*_ in self.server.calls))

    async def test_plan_change_invalidates_old_audit(self):
        await self.observe(self.api)
        q=self.api.check_deposit_target(self.plan()); idea=self.api.submit_idea(self.idea(q))
        review=self.for_agent(self.auditor); await self.observe(review)
        review.record_critique(idea['id'],'PASS','Independent review of initial plan')
        changed=self.api.check_deposit_target(self.plan(upload_url=self.origin+'/changed'))
        data=self.idea(changed); data['id']=idea['id']; self.api.submit_idea(data)
        executor=self.for_agent(self.prototyper); executor.materialize_export('build.epub','payload/export.epub')
        result=await executor.http_request({'url':self.origin+'/changed','method':'POST','upload_path':'payload/export.epub'},idea['id'],'Upload changed target')
        self.assertEqual(result['reason'],'QUALIFIED_PLAN_NEEDS_INDEPENDENT_AUDIT')
        self.assertFalse(self.engine.state['approvals'])
