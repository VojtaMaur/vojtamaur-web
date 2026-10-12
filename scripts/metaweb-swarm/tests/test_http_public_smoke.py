"""Public profile policy and actual SDK dispatch; simulated HTTPS for regression."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from metaweb_swarm.config import load_config,validate_config
from metaweb_swarm.engine import initialize,Engine,ToolAPI
from metaweb_swarm.http_smoke import service,INPUT_PATH
from metaweb_swarm.workspace import Workspace
from tests.test_backend import SDK_AVAILABLE,FINAL
from tests.test_http_smoke import FixtureBackend

class PublicSmokeTests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  project=self.root/'project';project.mkdir();(project/'site.txt').write_text('never upload me')
  self.config=load_config(Path(__file__).resolve().parent.parent/'config.http-public-smoke.json')
  self.run_dir=initialize(project,self.root/'runs',self.config)
  self.engine=Engine(self.run_dir,FixtureBackend('skip'),'demo');self.agent=self.engine.state['agents'][0]
  self.calls=[]
 def tearDown(self):
  self.engine.close();self.temp.cleanup()
 def api(self):
  ws=Workspace(self.run_dir/'snapshot',self.run_dir/'agents'/self.agent['id']/'workspace')
  ws.write_file(INPUT_PATH,(self.run_dir/INPUT_PATH).read_text(encoding='utf-8'))
  return ToolAPI(self.engine,self.agent,ws)
 def network(self,prepared,config,timeout):
  self.calls.append(prepared)
  origin='https://tmpfiles.org';f=self.engine.state['http_smoke']
  specimen=(self.run_dir/INPUT_PATH).read_bytes()
  if prepared.url==f['documentation_url']:
   body=json.dumps({'field':'opaque_payload_field','upload':origin+'/receive','retention':'temporary'}).encode()
  elif prepared.url==f['terms_url']:
   body=b'Public noncommercial interoperability testing allowed; temporary retention.'
  elif prepared.method=='POST':
   self.assertIn(b'name="opaque_payload_field"',prepared.body)
   self.assertIn(specimen,prepared.body)
   body=json.dumps({'file_url':origin+'/info'}).encode()
  elif prepared.url==origin+'/info':
   body=b'<a href="/download/sample">Download file</a>'
  elif prepared.url==origin+'/download/sample':
   body=specimen
  else:
   raise AssertionError('Unexpected request '+prepared.url)
  digest=hashlib.sha256(body).hexdigest()
  return {'status':200,'headers':{},'request_bytes':len(prepared.body),'response_bytes':len(body),
          'stored_bytes':len(body),'raw_sha256':digest,'stored_sha256':digest,
          'truncated':False,'outcome_uncertain':False},body
 async def docs(self,api):
  f=self.engine.state['http_smoke']
  for url in (f['documentation_url'],f['terms_url']):
   r=await api.http_request({'method':'GET','url':url},purpose='Read protocol and terms')
   api.read_file(r['response']['path'])
 def upload_spec(self):
  return {'method':'POST','url':'https://tmpfiles.org/receive',
          'multipart_files':[{'field':'opaque_payload_field','path':INPUT_PATH,'filename':'specimen.txt','content_type':'text/plain'}]}
 async def test_public_round_trip_and_truthful_report(self):
  with service(self.engine),patch('metaweb_swarm.http_transport.execute_request',side_effect=self.network):
   api=self.api();await self.docs(api)
   upload=await api.http_request(self.upload_spec(),purpose='Upload granted harmless specimen')
   download=await api.http_request({'method':'GET','url':'https://tmpfiles.org/download/sample'},purpose='Read public bytes back')
   receipt=api.verify_http_copy(upload['id'],download['id'],INPUT_PATH)
   self.assertTrue(receipt['host_verified'])
   self.assertFalse(receipt['preservation_deposit'])
   self.assertIn('https://',receipt['location'])
   self.assertEqual(len(self.calls),4)
   self.assertFalse(self.engine.state['ideas'])
  from metaweb_swarm.engine import refresh_reports
  refresh_reports(self.engine.store,self.engine.state)
  report=(self.run_dir/'SWARM_REPORT.md').read_text(encoding='utf-8')
  self.assertIn('veřejné HTTPS služby',report);self.assertIn('Ověřená uložení: 0',report)
  self.engine.store.verify()
 async def test_docs_scope_synthetic_payload_and_one_attempt_guard(self):
  with service(self.engine),patch('metaweb_swarm.http_transport.execute_request',side_effect=self.network):
   api=self.api()
   result=await api.http_request(self.upload_spec(),purpose='Premature upload must be blocked')
   self.assertEqual(result['reason'],'PUBLIC_SMOKE_DOCS_AND_TERMS_READ_REQUIRED')
   self.assertFalse(self.calls)
   for url in ('https://example.com/x','http://tmpfiles.org/x','https://tmpfiles.org.attacker.invalid/x'):
    result=await api.http_request({'method':'GET','url':url},purpose='Test origin confinement')
    self.assertEqual(result['reason'],'HTTP_SMOKE_FIXTURE_ONLY')
   await self.docs(api)
   api.workspace.write_file('other.txt','different site content')
   spec=self.upload_spec();spec['multipart_files'][0]['path']='other.txt'
   self.assertEqual((await api.http_request(spec,purpose='Reject real website upload'))['reason'],'PUBLIC_SMOKE_SYNTHETIC_INPUT_ONLY')
   spec=self.upload_spec();spec['multipart_fields']={'metadata':'secret text is forbidden'}
   self.assertEqual((await api.http_request(spec,purpose='Reject extra form content'))['reason'],'PUBLIC_SMOKE_NUMERIC_METADATA_ONLY')
   await api.http_request(self.upload_spec(),purpose='Single allowed upload')
   spec=self.upload_spec();spec['multipart_files'][0]['filename']='different-name.txt'
   self.assertEqual((await api.http_request(spec,purpose='No repeated upload'))['reason'],'PUBLIC_SMOKE_UPLOAD_ALREADY_ATTEMPTED')
   self.assertEqual(len([r for r in self.calls if r.method=='POST']),1)
 async def test_uncertain_upload_cannot_retry_with_new_bytes_or_path(self):
  with service(self.engine),patch('metaweb_swarm.http_transport.execute_request',side_effect=self.network):
   api=self.api();await self.docs(api)
   with patch('metaweb_swarm.http_transport.execute_request',side_effect=TimeoutError):
    upload=await api.http_request(self.upload_spec(),purpose='Simulated uncertain upload')
   self.assertEqual(upload['status'],'UNKNOWN')
   spec=self.upload_spec();spec['url']='https://tmpfiles.org/different'
   result=await api.http_request(spec,purpose='Forbidden retry with changed endpoint')
   self.assertEqual(result['reason'],'PUBLIC_SMOKE_UPLOAD_ALREADY_ATTEMPTED')
 def test_paginated_document_reads_cover_full_response(self):
  from metaweb_swarm.http_public_smoke import fully_read
  reads=[{'path':'doc.txt','ledger_length':1,'offset':0,'end':8000,'total_chars':10000},
         {'path':'doc.txt','ledger_length':1,'offset':8000,'end':10000,'total_chars':10000}]
  self.assertTrue(fully_read({'http_smoke_reads':reads},'doc.txt',1))
  reads[1]['offset']=8001
  self.assertFalse(fully_read({'http_smoke_reads':reads},'doc.txt',1))
  self.assertFalse(fully_read({'http_smoke_reads':reads},'doc.txt',0))
 def test_invalid_operator_grants(self):
  from copy import deepcopy
  for grant in (None,{'documentation_url':'http://tmpfiles.org/api','terms_url':'https://tmpfiles.org/tos','allowed_origins':['https://tmpfiles.org']},
    {'documentation_url':'https://example.com/api','terms_url':'https://tmpfiles.org/tos','allowed_origins':['https://tmpfiles.org']},
    {'documentation_url':'https://tmpfiles.org/api','terms_url':'https://tmpfiles.org/tos','allowed_origins':['https://tmpfiles.org/path']}):
   if grant is None:continue
   c=deepcopy(self.config);c['http_smoke_service']=grant
   with self.assertRaises(ValueError):validate_config(c)
  c=dict(self.config,http_smoke_test=False)
  with self.assertRaises(ValueError):validate_config(c)

 @unittest.skipUnless(SDK_AVAILABLE,'optional SDK unavailable')
 async def test_actual_sdk_learns_non_provider_specific_protocol(self):
  from metaweb_swarm.backend import OpenAIBackend
  from tests.test_backend import FakeProvider,FakeModel,tool_response,final_response
  engine=self.engine
  class ProtocolModel(FakeModel):
   def __init__(self):
    super().__init__([]);self.index=0
   async def get_response(self,*args,**kwargs):
    self.calls.append((args,kwargs));ledger=engine.state.get('http_requests',[])
    f=engine.state['http_smoke'];i=self.index;self.index+=1
    if i==0:
     name='http_request';a={'request_json':json.dumps({'method':'GET','url':f['documentation_url']}),'idea_id':'','purpose':'Discover upload protocol'}
    elif i==1:
     name='read_file';a={'path':ledger[0]['response']['path'],'offset':0,'limit':8000}
    elif i==2:
     name='http_request';a={'request_json':json.dumps({'method':'GET','url':f['terms_url']}),'idea_id':'','purpose':'Review service terms'}
    elif i==3:
     name='read_file';a={'path':ledger[1]['response']['path'],'offset':0,'limit':8000}
    elif i==4:
     workspace=engine.store.run_dir/'agents'/engine.state['agents'][0]['id']/'workspace'
     protocol=json.loads((workspace/ledger[0]['response']['path']).read_text())
     name='http_request';a={'request_json':json.dumps({'method':'POST','url':protocol['upload'],
       'multipart_files':[{'field':protocol['field'],'path':INPUT_PATH,'filename':'smoke.txt','content_type':'text/plain'}]}),
       'idea_id':'','purpose':'Upload harmless public test input'}
    elif i==5:
     name='read_file';a={'path':ledger[2]['response']['path'],'offset':0,'limit':8000}
    elif i==6:
     workspace=engine.store.run_dir/'agents'/engine.state['agents'][0]['id']/'workspace'
     uploaded=json.loads((workspace/ledger[2]['response']['path']).read_text())
     name='http_request';a={'request_json':json.dumps({'method':'GET','url':uploaded['file_url']}),'idea_id':'','purpose':'Inspect returned file URL'}
    elif i==7:
     name='read_file';a={'path':ledger[3]['response']['path'],'offset':0,'limit':8000}
    elif i==8:
     from html.parser import HTMLParser
     workspace=engine.store.run_dir/'agents'/engine.state['agents'][0]['id']/'workspace'
     class Links(HTMLParser):
      def handle_starttag(self,tag,attrs):
       if tag=='a':self.href=dict(attrs)['href']
     parser=Links();parser.feed((workspace/ledger[3]['response']['path']).read_text())
     from urllib.parse import urljoin
     name='http_request';a={'request_json':json.dumps({'method':'GET','url':urljoin(ledger[3]['action']['payload']['url'],parser.href)}),'idea_id':'','purpose':'Download uploaded raw bytes'}
    elif i==9:
     name='verify_http_copy';a={'upload_request_id':ledger[2]['id'],'download_request_id':ledger[4]['id'],'source_path':INPUT_PATH}
    else:
     return final_response('final-'+str(i))
    return tool_response(name,a,'public-'+str(i))
  provider=FakeProvider([]);provider.model=ProtocolModel()
  engine.backend=OpenAIBackend(model_provider=provider);engine.backend_name='openai';engine.state['backend']='openai'
  with patch('metaweb_swarm.http_transport.execute_request',side_effect=self.network):
   state=await engine.run()
  self.assertEqual(state['status'],'COMPLETED',state['stop_reason'])
  self.assertTrue(state['http_smoke']['passed'])
  self.assertEqual(len(self.calls),5)
  self.assertEqual(state['usage']['web_search_calls'],0)
  self.assertEqual(len(provider.model.calls),12)
  engine.store.verify()
