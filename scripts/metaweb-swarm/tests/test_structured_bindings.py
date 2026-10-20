"""Host-encoded response references and scoped context cleanup; no paid calls."""
import copy
import json
import unittest
from metaweb_swarm.deposit_plan import PlanValidationError,resolve_url
from metaweb_swarm.memory import compact_history,obsolete_planning_pairs
from tests import test_plan_edits as fixture
from tests.test_backend import SDK_AVAILABLE


def pair(name, ident, result, args=None):
    return [{'type':'function_call','name':name,'call_id':ident,'arguments':json.dumps(args or {})},
            {'type':'function_call_output','call_id':ident,'output':json.dumps(result)}]


class BindingTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.EditTests.setUp
    tearDown=fixture.EditTests.tearDown
    for_agent=fixture.EditTests.for_agent
    candidate=fixture.EditTests.candidate
    bad_binding=fixture.EditTests.bad_binding
    reject=fixture.EditTests.reject

    def bind(self,step_id,field,source,pointer,target='',prefix='',suffix=''):
        draft=self.planner.read_deposit_plan_draft(self.idea['id'])
        return self.planner.bind_deposit_step_response(self.idea['id'],draft['draft_sha256'],step_id,
            field,source,pointer,target,prefix,suffix)

    async def test_whole_url_is_host_encoded_and_missing_key_does_not_grant_execution(self):
        await self.candidate();self.reject(self.bad_binding())
        self.assertEqual(self.planner.deposit_binding_source_ids(),['reserve','send','finish'])
        result=self.bind('send','url','reserve','/upload/signedUrl')
        q=next(q for q in self.engine.state['deposit_qualifications'] if q['id']==result['qualification_id'])
        self.assertEqual(q['plan']['execution_steps'],self.steps)
        self.assertIn('ACCOUNT_SETUP_REQUIRED',q['reasons'])
        self.assertFalse(self.engine.state['approvals']);self.assertFalse(self.engine.state['external_actions'])
        self.assertEqual(self.server.calls,['/docs','/terms'])

    async def test_field_target_and_escaped_path_preserve_literal_json(self):
        await self.candidate();steps=copy.deepcopy(self.steps)
        steps[2].update(body_json='{"literal":42,"nested":{"a/b":"placeholder"}}',max_body_bytes=1024)
        self.reject(dict_bad(steps,3,'url','{{missing:/url}}'))
        with self.assertRaises(PlanValidationError) as caught:
            self.bind('finish','body_json','reserve','/object_key','/nested/a~1b')
        self.assertEqual(caught.exception.problem['issue']['code'],'BINDING_SOURCE_REQUIRED')
        view=self.planner.read_deposit_plan_draft(self.idea['id'],'finish')
        body=json.loads(view['step']['body_json'])
        self.assertEqual(body,{'literal':42,'nested':{'a/b':{'$response':'reserve','pointer':'/object_key'}}})
        self.assertFalse(self.engine.state['external_actions'])

    async def test_literal_url_parts_use_existing_executor_escaping(self):
        await self.candidate();self.reject(dict_bad(self.steps,2,'url','{{missing:/url}}'))
        result=self.bind('finish','url','reserve','/id',prefix=self.origin+'/complete/',suffix='/final')
        q=next(q for q in self.engine.state['deposit_qualifications'] if q['id']==result['qualification_id'])
        url=q['plan']['execution_steps'][2]['url']
        self.assertEqual(resolve_url(url,{'reserve':{'id':'a/b?c'}}),self.origin+'/complete/a%2Fb%3Fc/final')
        self.assertFalse(self.engine.state['external_actions'])

    async def test_unknown_forward_and_malformed_sources_are_rejected_without_inference(self):
        await self.candidate();self.reject(self.bad_binding())
        for source,pointer,code in [('missing','/url','BINDING_SOURCE_REQUIRED'),
                ('verify','/url','BINDING_SOURCE_REQUIRED'),('reserve','/bad~x','BINDING_POINTER_INVALID'),
                ('{{reserve:/url}}','/url','BINDING_NAME_INVALID')]:
            with self.assertRaises(PlanValidationError) as caught:self.bind('send','url',source,pointer)
            self.assertEqual(caught.exception.problem['issue']['code'],code)
        self.assertEqual(self.idea['qualification_id'],self.q['id'])
        self.assertFalse(self.engine.state['approvals'])

    async def test_bad_json_parent_no_guess_and_stale_hash_or_active_flow_no_edit(self):
        await self.candidate();steps=self.bad_binding();steps[2]['body_json']='not JSON'
        self.reject(steps)
        original=self.planner.read_deposit_plan_draft(self.idea['id'])
        with self.assertRaises(PlanValidationError) as caught:
            self.bind('finish','body_json','reserve','/id','/object_key')
        self.assertEqual(caught.exception.problem['issue']['code'],'BINDING_TARGET_INVALID')
        with self.assertRaisesRegex(ValueError,'STALE_DRAFT'):
            self.planner.bind_deposit_step_response(self.idea['id'],'outdated','send','url','reserve','/url')
        self.engine.state['deposit_executions']=[{'idea_id':self.idea['id']}]
        with self.assertRaises(ValueError):self.bind('send','url','reserve','/url')
        self.assertFalse(self.engine.state['external_actions'])

    async def test_origins_and_header_policy_are_still_enforced(self):
        await self.candidate()
        for args,code in [(('send','url','reserve','/id','', 'https://github.com/files/',''),'PLAN_DATA_INVALID'),
                     (('finish','headers_json','reserve','/token','/Authorization','',''),'HEADERS_INVALID')]:
            self.reject(dict_bad(self.steps,3,'url','{{missing:/url}}'))
            with self.assertRaises(PlanValidationError) as caught:self.bind(*args)
            self.assertEqual(caught.exception.problem['issue']['code'],code)
        self.assertEqual(self.idea['qualification_id'],self.q['id'])
        self.assertFalse(self.engine.state['approvals']);self.assertFalse(self.engine.state['external_actions'])

    @unittest.skipUnless(SDK_AVAILABLE,'SDK not installed')
    async def test_sdk_source_enum_and_structured_repair_have_no_paid_or_external_calls(self):
        import agents
        from metaweb_swarm.backend import OpenAIBackend,_make_sdk_tools
        from tests.test_backend import FakeProvider,tool_response,final_response,FINAL
        await self.candidate();self.reject(self.bad_binding())
        tools,_=_make_sdk_tools(agents,self.planner)
        tool=next(t for t in tools if t.name=='bind_deposit_step_response')
        self.assertEqual(tool.params_json_schema['properties']['source_step_id']['enum'],['reserve','send','finish'])
        self.assertIs(tool.params_json_schema['additionalProperties'],False)
        draft=self.planner.read_deposit_plan_draft(self.idea['id'])
        self.local['history']=pair('record_deposit_execution_plan','bad',
            {'status':'DEFERRED','reason':'PLAN_REVISION_REQUIRED'}, {'steps':'OBSOLETE_BAD_TEMPLATE'})
        original=copy.deepcopy(self.local['history'])
        args=dict(idea_id=self.idea['id'],draft_sha256=draft['draft_sha256'],step_id='send',field='url',
            source_step_id='reserve',response_pointer='/upload/signedUrl',target_pointer='',url_prefix='',url_suffix='')
        provider=FakeProvider([tool_response('bind_deposit_step_response',args),final_response(output=FINAL)])
        self.engine.backend=OpenAIBackend(provider)
        await self.engine.step(self.local)
        self.assertEqual(self.local['status'],'COMPLETED')
        archived=json.loads((self.run/'raw/AGENT-003-history-before-round-1.json').read_text(encoding='utf-8'))
        self.assertEqual(archived,original)
        self.assertNotIn('OBSOLETE_BAD_TEMPLATE',json.dumps(self.local['history']))
        self.assertFalse(self.engine.state['approvals']);self.assertFalse(self.engine.state['external_actions'])
        self.engine.store.verify()


def dict_bad(steps,index,key,value):
    result=copy.deepcopy(steps);result[index][key]=value;return result


class PlanningMemoryTests(unittest.TestCase):
    def test_only_rejected_data_and_old_draft_pairs_are_removed(self):
        rejected={'status':'DEFERRED','reason':'PLAN_REVISION_REQUIRED'}
        history=pair('record_deposit_execution_plan','reject',rejected,{'url':'OBSOLETE_BAD_TEMPLATE'})
        history+=pair('read_deposit_plan_draft','read',{'status':'UNVALIDATED_DRAFT','draft_sha256':'OLD_HASH'})
        history+=pair('http_request','external',rejected,{'method':'POST'})
        history+=pair('execute_deposit_plan','unknown',{'status':'UNKNOWN','reason':'inspect remote outcome'})
        history+=pair('record_deposit_execution_plan','accepted',{'status':'ACCOUNT_SETUP_REQUIRED','qualification_id':'QUAL-current'})
        history+=pair('read_document','docs',{'status':'COMPLETED','text':'DOCUMENTED_JSON_POINTER'})
        history+=[{'type':'function_call','name':'edit_deposit_plan_step','call_id':'orphan','arguments':'{}'}]
        before=copy.deepcopy(history)
        compact=compact_history(history,'context/original.json',24000)
        names=[i.get('call_id') for i in compact if i.get('type')=='function_call']
        self.assertEqual(names,['external','unknown','accepted','docs','orphan'])
        self.assertNotIn('OBSOLETE_BAD_TEMPLATE',json.dumps(compact));self.assertNotIn('OLD_HASH',json.dumps(compact))
        self.assertIn('DOCUMENTED_JSON_POINTER',json.dumps(compact));self.assertIn('original.json',json.dumps(compact))
        self.assertEqual(history,before)

    def test_ambiguous_or_malformed_outputs_are_never_assumed_rejected(self):
        h=pair('edit_deposit_plan_step','dup',{'status':'DEFERRED','reason':'PLAN_REVISION_REQUIRED'})
        h+=[copy.deepcopy(h[-1])]
        h+=pair('edit_deposit_plan_step','malformed',{'status':'DEFERRED','reason':'PLAN_REVISION_REQUIRED'})
        h[-1]['output']='broken JSON'
        h+=pair('edit_deposit_plan_step','interrupted',{'status':'INTERRUPTED'})
        self.assertFalse(obsolete_planning_pairs(h))
        self.assertTrue(all(i in compact_history(h,'original.json') for i in h))
