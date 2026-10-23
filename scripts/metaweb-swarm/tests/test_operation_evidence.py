"""Regressions for the actual RSS run: claim stability, range evidence, coverage."""
import copy, hashlib, json, unittest
from unittest.mock import patch
from metaweb_swarm.demo import DemoBackend
from metaweb_swarm.research_tasks import revision,evidence_revision,local_candidates
from metaweb_swarm.prototype_review import enforce_scope
from metaweb_swarm.source_refs import resolve,page
from metaweb_swarm.format_operation import contract,validate,read_pointer
from metaweb_swarm.review_probe import assertion_syntax
from tests import test_local_contract as fixture


class FormatTests(unittest.TestCase):
    idea={'title':'Podcast RSS episode metadata','mechanism':'RSS recovery pointer'}
    payload={'export':'web.epub','path':'inputs/hash/web.epub','sha256':'a'*64}
    def feed(self):
        import xml.etree.ElementTree as ET
        root=ET.Element('rss',version='2.0');channel=ET.SubElement(root,'channel')
        for key,value in {'title':'Metaweb','link':'https://vojtamaur.cz/','description':'Local RSS pointer prototype'}.items():ET.SubElement(channel,key).text=value
        item=ET.SubElement(channel,'item')
        for key,value in contract(self.idea,self.payload)['expected'].items():ET.SubElement(item,key).text=value
        return ET.tostring(root)
    def test_json_with_feed_names_is_not_rss(self):
        result=validate(self.idea,self.payload,['episode.json'],lambda p:b'{"feed":"rss"}')
        self.assertFalse(result['passed']);self.assertEqual(result['reason'],'NATIVE_RSS_OPERATION_REQUIRED')
    def test_real_feed_is_parsed_against_input_bound_values(self):
        result=validate(self.idea,self.payload,['feed.rss'],lambda p:self.feed())
        self.assertTrue(result['passed']);self.assertIn('still require review',result['meaning'])
    def test_well_formed_missing_guid_is_rejected(self):
        import xml.etree.ElementTree as ET
        root=ET.fromstring(self.feed());item=root.find('channel/item');item.remove(item.find('guid'))
        with self.assertRaisesRegex(ValueError,'guid'):read_pointer(ET.tostring(root))
    def test_dummy_url_wrong_digest_dtd_and_non_xml_fail(self):
        body=self.feed()
        for altered in (body.replace(b'https://vojtamaur.cz/',b'https://example.invalid/'),
                        body.replace(b'a'*64,b'0'*64),b'<!DOCTYPE rss>'+body,b'JSON'):
            self.assertFalse(validate(self.idea,self.payload,['feed.xml'],lambda p:altered)['passed'])
    def test_other_formats_are_not_forced_into_rss(self):
        self.assertIsNone(contract({'title':'CBOR manifest'},self.payload))
    def test_source_inspection_is_not_behavioral_even_after_running_driver(self):
        code="import runpy\nrunpy.run_path('prototype/test.py')\nsrc=open('prototype/test.py').read()\nassert 'negative_case' in src"
        self.assertFalse(assertion_syntax(code))
        self.assertFalse(assertion_syntax("from pathlib import Path\nsrc=Path('test.py').read_text()\ncopy=src\nassert len(copy)>1"))
    def test_actual_consumer_assertion_can_follow_source_inspection(self):
        code="src=open('test.py').read()\nassert 'parse' in src\nactual=parse('feed.rss')\nassert actual==expected"
        self.assertTrue(assertion_syntax(code))
    def test_partial_lines_are_not_numbered_as_read(self):
        self.assertEqual(page('first\nsecond\n',2,10),[])
        self.assertEqual(page('first\nsecond\n',6,13)[0]['line'],2)


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.LocalContractReviewTests.setUp
    tearDown=fixture.LocalContractReviewTests.tearDown
    for_agent=fixture.LocalContractReviewTests.for_agent
    prepare=fixture.LocalContractReviewTests.prepare
    plan=fixture.LocalContractReviewTests.plan
    artifacts=fixture.LocalContractReviewTests.artifacts
    executed=fixture.LocalContractReviewTests.executed
    evidence=fixture.LocalContractReviewTests.evidence
    captured=fixture.LocalContractReviewTests.captured

    def ref(self,lo,hi=None):return {'path':'prototype/test.py','start_line':lo,'end_line':hi or lo}
    async def test_disjoint_ranges_resolve_without_reconstructed_contiguous_quote(self):
        test=await self.captured()
        ranges=resolve(self.review,test,[self.ref(4),self.ref(10)])
        self.assertEqual(len(ranges),2);self.assertIn('base64.b64encode',ranges[0]['quote'])
        result=self.review.review_prototype_test(test['id'],'REVISE','Actual captured negative case only compares hashes; use a rejecting consumer instead',
            negative_refs=[self.ref(10),self.ref(4)],positive_refs=[],defect_code=None,
            required_local_change='Feed the deliberately damaged specimen into the decoder and assert rejection',observed_recovery=None,review_basis=None)
        self.assertEqual(result['verdict'],'REVISE');self.assertEqual(len(result['negative_source_ranges']),2)
        self.assertEqual(result['defect_evidence']['sha256'],ranges[0]['sha256'])
    async def test_unread_unrelated_out_of_range_and_modified_source_are_rejected(self):
        test=await self.captured()
        for ref in (self.ref(10000),dict(self.ref(1),path='prototype/specimen.bin'),self.ref(0)):
            with self.assertRaises(ValueError):resolve(self.review,test,[ref])
        self.auditor['prototype_artifact_reads'][test['id']]={}
        with self.assertRaisesRegex(ValueError,'Read'):resolve(self.review,test,[self.ref(4)])
        self.evidence(test)
        blob=next(a for a in test['audit_artifacts'] if a['source_path']=='prototype/test.py')
        (self.run/blob['path']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'hash'):resolve(self.review,test,[self.ref(4)])
    async def test_latest_revise_and_pending_capture_clear_old_component_approval(self):
        test=await self.captured();self.review.review_prototype_test(test['id'],'SUBCOMPONENT','Working local representation only; remote custody is untested',**self.evidence(test),observed_recovery=None,review_basis=None)
        self.assertTrue(self.idea['prototype_component_tested'])
        newer=copy.deepcopy(test);newer.update(id='NEW-TEST');newer.pop('prototype_review',None)
        self.engine.state['tests'].append(newer);enforce_scope(self.engine.state)
        self.assertFalse(self.idea['prototype_component_tested']);self.assertFalse(self.idea['prototype_tested'])
        newer['prototype_review']={'verdict':'REVISE'};enforce_scope(self.engine.state)
        self.assertFalse(self.idea['prototype_component_tested'])
        self.assertEqual(test['prototype_review']['verdict'],'SUBCOMPONENT')
    async def test_same_merge_adds_evidence_without_reopening_coding(self):
        test=await self.captured();self.engine.state['config']['coding_backend']='sdk_shell'
        self.review.review_prototype_test(test['id'],'SUBCOMPONENT','Working local representation only; remote custody is untested',**self.evidence(test),observed_recovery=None,review_basis=None)
        before=revision(self.idea);old_title=self.idea['title'];evidence_before=evidence_revision(self.idea)
        proposal=DemoBackend.idea(self.idea['title'],'format-one','FREE','DISCOVERED')
        proposal['summary']='Alternative wording of the same mechanism with another source'
        proposal['evidence']=[{'url':'https://example.org/new','claim':'Another source','verified':False}]
        merged=self.api.submit_idea(proposal)
        self.assertEqual(merged['id'],self.idea['id']);self.assertEqual(len(self.engine.state['ideas']),1)
        self.assertEqual(revision(merged),before);self.assertNotEqual(evidence_revision(merged),evidence_before)
        self.assertEqual(merged['title'],old_title);self.assertGreater(len(merged['submissions']),1)
        self.assertTrue(merged['prototype_component_tested']);self.assertNotIn(merged,local_candidates(self.engine.state,self.proto))
    async def test_explicit_changed_operation_invalidates_approval(self):
        test=await self.captured();self.review.review_prototype_test(test['id'],'SUBCOMPONENT','Working local representation only; remote custody is untested',**self.evidence(test),observed_recovery=None,review_basis=None)
        proposal=DemoBackend.idea('Same family revised operation','format-one','FREE','DISCOVERED');proposal['id']=self.idea['id']
        proposal['validation_plan']='Use a materially new native parser and reject malformed serialized messages'
        previous=revision(self.idea);merged=self.api.submit_idea(proposal)
        self.assertNotEqual(revision(merged),previous);self.assertFalse(merged['prototype_component_tested'])

    async def test_same_merge_does_not_weaken_a_recurring_payment_rejection(self):
        await self.captured()
        proposal=DemoBackend.idea(self.idea['title'],'format-one','RECURRING','DISCOVERED')
        merged=self.api.submit_idea(proposal)
        self.assertEqual(merged['id'],self.idea['id']);self.assertEqual(merged['status'],'REJECTED')
        self.assertEqual(merged['payment'],'RECURRING');self.assertFalse(merged['prototype_tested'])

    async def test_live_sdk_review_uses_line_ranges_not_copied_code(self):
        from tests.test_backend import SDK_AVAILABLE,FakeProvider,tool_response,final_response
        if not SDK_AVAILABLE:self.skipTest('SDK optional')
        from metaweb_swarm.backend import OpenAIBackend
        test=await self.captured()
        args={'test_id':test['id'],'verdict':'SUBCOMPONENT','reason':'Captured local round trip and altered input are limited to a local representation',
              'positive_refs':[self.ref(7)],'negative_refs':[self.ref(10)],'required_local_change':''}
        provider=FakeProvider([tool_response('review_prototype_test',args),final_response()])
        await OpenAIBackend(provider).step(self.auditor,self.engine.prompt(self.auditor),[],self.review,self.engine.state['config'])
        self.assertEqual(test['prototype_review']['verdict'],'SUBCOMPONENT')
        call=provider.model.calls[0];tools=call[1].get('tools',call[0][3] if len(call[0])>3 else [])
        props=next(t for t in tools if t.name=='review_prototype_test').params_json_schema['properties']
        self.assertIn('positive_refs',props);self.assertNotIn('positive_code',props)


class NativeWorkerTests(unittest.IsolatedAsyncioTestCase):
    from tests import test_coding_worker as coding_fixture
    setUp=coding_fixture.CodingWorkerTests.setUp
    tearDown=coding_fixture.CodingWorkerTests.tearDown
    for_agent=coding_fixture.CodingWorkerTests.for_agent
    prepare=coding_fixture.CodingWorkerTests.prepare
    setup_worker=coding_fixture.CodingWorkerTests.setup_worker

    async def test_native_check_returns_feedback_before_receipt_then_accepts_real_feed(self):
        from metaweb_swarm.research_tasks import assign
        from metaweb_swarm.coding_worker import task,finalize
        self.setup_worker();self.idea.update(title='RSS recovery pointer',mechanism='Serialize and parse RSS 2.0')
        self.idea['prototype_focus']['research_revision']=revision(self.idea)
        assign(self.engine,self.proto);current=task(self.local)
        self.assertEqual(current['format_contract']['kind'],'RSS_2_POINTER')
        self.local.workspace.write_file('prototype/test.py','print("Mocked capture; no semantic claim")\n')
        result=dict(self.result,output_paths=['prototype/feed.rss'])
        def bad(*args):
            self.local.workspace.write_file('prototype/feed.rss','{"feed":"RSS in name only"}')
            return {'status':'COMPLETED','returncode':0,'output':'mock capture','cleanup_ok':True}
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            docker.return_value.run.side_effect=bad
            failed=await finalize(self.local,result,current)
        self.assertEqual(failed['status'],'CONTINUE');self.assertEqual(self.proto['coding_last_result']['reason'],'NATIVE_RSS_OPERATION_REQUIRED')
        self.assertEqual(self.engine.state['tests'],[])
        self.local.workspace.write_file('prototype/test.py','print("Repaired driver fixture; mocked execution")\n')
        def good(*args):
            import xml.etree.ElementTree as ET
            root=ET.Element('rss',version='2.0');channel=ET.SubElement(root,'channel')
            for key,value in {'title':'Metaweb','description':'Local test','link':'https://vojtamaur.cz/'}.items():ET.SubElement(channel,key).text=value
            item=ET.SubElement(channel,'item')
            for key,value in current['format_contract']['expected'].items():ET.SubElement(item,key).text=value
            self.local.workspace.write_file('prototype/feed.rss',ET.tostring(root))
            return {'status':'COMPLETED','returncode':0,'output':'mock capture','cleanup_ok':True}
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            docker.return_value.run.side_effect=good
            passed=await finalize(self.local,result,current)
        self.assertEqual(passed['status'],'COMPLETED');self.assertEqual(len(self.engine.state['tests']),1)
        self.assertTrue(self.engine.state['tests'][0]['native_format_check']['passed'])
        self.assertFalse(self.idea['prototype_tested']);self.assertFalse(self.idea['prototype_component_tested'])
