import json,unittest,threading,urllib.request,urllib.error
from tests.test_gui import GUITests
from metaweb_swarm.gui import make_server

class MemoryTests(unittest.TestCase):
    setUp=GUITests.setUp
    tearDown=GUITests.tearDown
    def fixture(self):
        return {'schema_version':1,'notice':'Historical claims','entries':[{'run_id':self.run_id,'status':'COMPLETED','summary':'Test memory','candidates':[{'id':'IDEA-0001','title':'DNS','status':'INVESTIGATING'}]}],'truncated':True,'skipped':[]}
    def test_shared_index_read_is_exact_and_does_not_mutate_any_file(self):
        path=self.runs_root/'RUN_MEMORY.json';body=json.dumps(self.fixture(),ensure_ascii=False,indent=2);path.write_text(body,encoding='utf-8')
        before=(path.read_bytes(),path.stat().st_mtime_ns,(self.path/'state.sqlite3').read_bytes())
        result=self.service.memory()
        self.assertEqual(result['text'],body);self.assertEqual(result['scope'],'shared');self.assertTrue(result['truncated'])
        self.assertEqual(result['entries'][0]['candidates'][0]['title'],'DNS')
        self.assertEqual(before,(path.read_bytes(),path.stat().st_mtime_ns,(self.path/'state.sqlite3').read_bytes()))
    def test_captured_memory_is_separate_and_missing_is_never_generated(self):
        missing=self.service.memory();self.assertFalse(missing['exists']);self.assertFalse((self.runs_root/'RUN_MEMORY.json').exists())
        context=self.path/'context';context.mkdir()
        (context/'prior-runs.json').write_text(json.dumps(self.fixture()),encoding='utf-8')
        result=self.service.memory(self.run_id)
        self.assertEqual(result['scope'],'captured');self.assertIn('prior-runs.json',result['path'])
        self.assertFalse(self.service.memory()['exists'])
        with self.assertRaises(ValueError):self.service.memory('../escape')
    def test_size_and_shape_limits(self):
        path=self.runs_root/'RUN_MEMORY.json'
        for value in ({'schema_version':2,'entries':[]},{'schema_version':1,'entries':['bad']},{'schema_version':1,'entries':[{'candidates':['bad']}]}):
            path.write_text(json.dumps(value),encoding='utf-8')
            with self.assertRaises(ValueError):self.service.memory()
        path.write_bytes(b' '* (4*1024*1024+1))
        with self.assertRaisesRegex(ValueError,'4 MiB'):self.service.memory()
    def test_endpoint_uses_gui_auth_and_redacts_secrets(self):
        key='fixture-private-api-key';self.service.settings({'api_key':key})
        path=self.runs_root/'RUN_MEMORY.json';data=self.fixture();data['notice']=key;path.write_text(json.dumps(data),encoding='utf-8')
        server=make_server(self.service);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        url='http://127.0.0.1:'+str(server.server_port)+'/api/memory'
        try:
            with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(url,timeout=3)
            with urllib.request.urlopen(urllib.request.Request(url,headers={'X-Swarm-Token':self.service.token}),timeout=3) as response:
                value=response.read().decode('utf-8');self.assertNotIn(key,value);self.assertIn('[REDACTED]',value)
        finally:server.shutdown();server.server_close();worker.join(3)
