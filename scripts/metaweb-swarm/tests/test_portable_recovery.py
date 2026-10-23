"""Portable output-only review and a real file-bearing JPEG, no paid API."""
import base64,copy,hashlib,importlib.util,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from metaweb_swarm.review_probe import run
from tests import test_local_contract as fixture

ROOT=Path(__file__).resolve().parents[1]
def load_example(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'examples'/f'{name}.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
writer=load_example('jpeg_archive');reader=load_example('jpeg_extract_independent')


class JpegArchiveTests(unittest.TestCase):
    def setUp(self):self.cover=base64.b64decode((ROOT/'tests/fixtures/jpeg_cover.base64').read_text())
    def test_real_payload_round_trip_and_independent_decoder(self):
        payload=bytes(range(256))*1000+ b'actual tail'
        encoded,manifest=writer.pack(self.cover,payload,'web.epub')
        actual,decoded=reader.extract(encoded)
        self.assertEqual(actual,payload);self.assertEqual(decoded,manifest);self.assertGreater(decoded['chunks'],1)
        source_scan=list(writer.header_segments(self.cover))[-1][2]
        encoded_scan=list(writer.header_segments(encoded))[-1][2]
        self.assertEqual(self.cover[source_scan:],encoded[encoded_scan:])
    def test_even_odd_and_multi_chunk_boundaries(self):
        for size in (1,2,59999,60000,60001,120001):
            payload=b'A'*size;encoded,_=writer.pack(self.cover,payload,'x.txt')
            self.assertEqual(reader.extract(encoded)[0],payload)
    def test_payload_corruption_missing_duplicate_and_truncated_segments_fail(self):
        encoded,_=writer.pack(self.cover,b'payload from a real file '*4000,'web.epub')
        headers=list(writer.header_segments(encoded));archive=[v for v in headers if v[0]==0xED and b'MWJ1' in v[1]]
        _,_,start,end=archive[-1]
        damaged=bytearray(encoded);damaged[end-4]^=1
        variants=[bytes(damaged),encoded[:start]+encoded[end:],encoded[:end]+encoded[start:end]+encoded[end:],encoded[:-1]]
        for body in variants:
            with self.assertRaises(ValueError):reader.extract(body)
    def test_marker_only_old_stub_is_not_an_image_carrier(self):
        stub=b'\xff\xd8'+writer.resource(0,1,b'{}')+b'\xff\xd9'
        with self.assertRaises(ValueError):writer.pack(stub,b'real source','x')
        with self.assertRaises(ValueError):reader.extract(stub)
    def test_decoder_cli_needs_only_carrier_and_publishes_no_failed_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);carrier=root/'image.jpg';output=root/'restored.epub'
            original=b'real retained byte stream'*4000
            carrier.write_bytes(writer.pack(self.cover,original,'archive.epub')[0])
            code=(ROOT/'examples/jpeg_extract_independent.py').read_bytes()
            (root/'decoder.py').write_bytes(code)
            result=subprocess.run([sys.executable,'-I',str(root/'decoder.py'),str(carrier),str(output)],capture_output=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(output.read_bytes(),original)
            carrier.write_bytes(carrier.read_bytes()[:-1]);output.unlink()
            result=subprocess.run([sys.executable,'-I',str(root/'decoder.py'),str(carrier),str(output)],capture_output=True,timeout=15)
            self.assertNotEqual(result.returncode,0);self.assertFalse(output.exists())
    def test_encoder_does_not_require_or_reencode_pixels(self):
        encoded,_=writer.pack(self.cover,b'retained content','source.txt')
        with self.assertRaises(ValueError):writer.pack(encoded,b'retained content','source.txt')
        with self.assertRaises(ValueError):writer.pack(self.cover,b'','empty')


class ReviewIsolationTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.LocalContractReviewTests.setUp
    tearDown=fixture.LocalContractReviewTests.tearDown
    for_agent=fixture.LocalContractReviewTests.for_agent
    prepare=fixture.LocalContractReviewTests.prepare
    plan=fixture.LocalContractReviewTests.plan
    artifacts=fixture.LocalContractReviewTests.artifacts
    executed=fixture.LocalContractReviewTests.executed
    evidence=fixture.LocalContractReviewTests.evidence
    captured=fixture.LocalContractReviewTests.captured
    async def test_selected_specimen_is_only_staged_evidence(self):
        test=await self.captured();self.engine.state['config']['independent_review_probes']=True
        def execute(root,argv):
            files={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
            self.assertIn('prototype/specimen.bin',files)
            self.assertNotIn('prototype/test.py',files);self.assertNotIn('prototype/recovered.bin',files)
            self.assertNotIn(test['prototype_plan']['input']['path'],files)
            self.assertFalse(any(p.startswith('.packages/') for p in files))
            return {'status':'COMPLETED','returncode':0,'cleanup_ok':True,'output':'mock review transport only'}
        with patch('metaweb_swarm.review_probe.DockerExecutor') as docker:
            docker.return_value.run.side_effect=execute
            result=await run(self.review,test['id'],"actual=2; assert actual==2",['prototype/specimen.bin'])
        self.assertEqual(result['mode'],'SPECIMENS_ONLY');self.assertTrue(result['implementation_unchanged'])
        self.assertEqual(result['staged_paths'],['prototype/specimen.bin'])
    async def test_source_input_and_unselected_paths_cannot_be_smuggled_in(self):
        test=await self.captured()
        for path in ('prototype/test.py',test['prototype_plan']['input']['path'],'../secret','arbitrary.json'):
            with patch('metaweb_swarm.review_probe.DockerExecutor') as docker:
                result=await run(self.review,test['id'],'assert len(b"payload") > 0',[path])
                self.assertEqual(result['reason'],'CAPTURED_SPECIMEN_PATH_REQUIRED');docker.assert_not_called()
    async def test_mutating_selected_evidence_invalidates_probe(self):
        test=await self.captured()
        def execute(root,argv):
            (root/'prototype/specimen.bin').write_bytes(b'changed')
            return {'status':'COMPLETED','returncode':0,'cleanup_ok':True,'output':'changed evidence'}
        with patch('metaweb_swarm.review_probe.DockerExecutor') as docker:
            docker.return_value.run.side_effect=execute
            result=await run(self.review,test['id'],'assert len(b"payload") > 0',['prototype/specimen.bin'])
        self.assertFalse(result['implementation_unchanged']);self.assertEqual(result['status'],'BLOCKED')
    async def test_valid_negative_language_is_not_rejected_by_prose(self):
        self.prepare();self.local.materialize_export('build.epub','exports/input.epub')
        self.local.workspace.write_file('prototype/test.py','assert rejection_for_corrupted_input()\n')
        result=self.local.record_prototype_plan(self.idea['id'],'Test actual saved recovery and corrupted input','exports/input.epub',
            'prototype/test.py',['out/result.bin'],'Decode actual saved bytes and assert their source identity',
            'If the EPUB digest changes or output files are missing, the driver exits nonzero; a corrupted copy does not validate as the original.',
            'SUBCOMPONENT','External publication and retention remain untested')
        self.assertIn('id',result);self.assertFalse(self.idea['prototype_tested'])

    async def test_new_full_recovery_contract_requires_a_clean_consumer_probe(self):
        from metaweb_swarm.local_contract import bind,attach
        from metaweb_swarm.review_tasks import assign
        from metaweb_swarm.review_dispatch import action
        test=await self.executed('FULL_MECHANISM');plan=test['prototype_plan']
        contract=bind(self.local,{'idea_id':self.idea['id'],'scope_ceiling':'FULL_MECHANISM'},
            {'local_operation':plan['property_tested'],'positive_assertion':plan['positive_assertion'],
             'negative_assertion':plan['negative_assertion'],'limitations':'Local full-byte representation only; public deposit untested'})
        attach(self.local,plan,contract);assign(self.engine,self.auditor)
        self.evidence(test);self.review.get_prototype_review_facts(test['id'])
        self.engine.state['config'].update(coding_backend='sdk_shell',independent_review_probes=True)
        probe={'test_id':test['id'],'agent_id':self.auditor['id'],'mode':'AUTHOR_ENVIRONMENT',
            'status':'COMPLETED','returncode':0,'cleanup_ok':True,'assertion_syntax':True,'implementation_unchanged':True}
        self.engine.state['prototype_review_probes']=[probe]
        result=self.review.review_prototype_test(test['id'],'FULL_MECHANISM','Fixture transport proves the planned local inverse only; not remote custody',
            **self.evidence(test),observed_recovery=None,review_basis=None)
        self.assertEqual(result['reason'],'PORTABLE_RECOVERY_PROBE_REQUIRED');self.assertNotIn('prototype_review',test)
        self.assertIn('run_review_probe',action(self.review)['allowed_tools'])
        self.engine.state['prototype_review_probes'].append(dict(probe,mode='SPECIMENS_ONLY'))
        result=self.review.review_prototype_test(test['id'],'FULL_MECHANISM','Fixture transport proves the planned local inverse only; not remote custody',
            **self.evidence(test),observed_recovery=None,review_basis=None)
        self.assertEqual(result['verdict'],'FULL_MECHANISM')

    async def test_live_sdk_selects_output_only_environment(self):
        from tests.test_backend import SDK_AVAILABLE,FakeProvider,tool_response,final_response
        if not SDK_AVAILABLE:self.skipTest('SDK optional')
        from metaweb_swarm.backend import OpenAIBackend
        test=await self.captured();self.engine.state['config']['independent_review_probes']=True
        provider=FakeProvider([
            tool_response('run_review_probe',{'test_id':test['id'],'code':'actual=2; assert actual==2',
                'specimen_paths':['prototype/specimen.bin']},ident='portable-probe'),
            tool_response('review_prototype_test',{'test_id':test['id'],'verdict':'HELPER_ONLY',
                'reason':'Generic captured fixture is a helper; the mock probe carries no scientific certification',
                'positive_refs':[{'path':'prototype/test.py','start_line':4,'end_line':4}],
                'negative_refs':[],'required_local_change':''},ident='portable-verdict'),final_response()])
        def execute(root,argv):
            self.assertFalse((root/'prototype/test.py').exists())
            self.assertTrue((root/'prototype/specimen.bin').is_file())
            return {'status':'COMPLETED','returncode':0,'cleanup_ok':True,'output':'mock transport'}
        with patch('metaweb_swarm.review_probe.DockerExecutor') as docker:
            docker.return_value.run.side_effect=execute
            await OpenAIBackend(provider).step(self.auditor,self.engine.prompt(self.auditor),[],self.review,self.engine.state['config'])
        self.assertEqual(self.engine.state['prototype_review_probes'][-1]['mode'],'SPECIMENS_ONLY')
        self.assertEqual(test['prototype_review']['verdict'],'HELPER_ONLY')
