"""Real PDF parser + audited reads; fixtures are local, no paid API."""
import io
import json
import hashlib
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
import pypdf
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from metaweb_swarm.pdf_documents import extract, PdfDocumentError
from metaweb_swarm.review_contract import source_quote
from metaweb_swarm.discovery_leads import awaiting_review
from metaweb_swarm.deposit_handoff import recover
from metaweb_swarm.engine import Engine
from metaweb_swarm.demo import DemoBackend
from tests import test_focused_tasking as fixture


def pdf_bytes(texts, encrypted=False):
    writer = pypdf.PdfWriter()
    font = writer._add_object(DictionaryObject({NameObject('/Type'):NameObject('/Font'),
                    NameObject('/Subtype'):NameObject('/Type1'), NameObject('/BaseFont'):NameObject('/Helvetica')}))
    for text in texts:
        page = writer.add_blank_page(width=400, height=300)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'):font})})
        if text:
            stream = DecodedStreamObject()
            escaped = text.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
            stream.set_data(('BT /F1 12 Tf 10 200 Td (' + escaped + ') Tj ET').encode('ascii'))
            page[NameObject('/Contents')] = writer._add_object(stream)
    if encrypted:
        writer.encrypt('fixture-password')
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


PDF = pdf_bytes(['API guide. POST sends exact bytes.', 'Monthly subscription required. Public download documented.'])


class PdfServer(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        self.server.calls.append(self.path)
        body = {'/bad':b'%PDF-invalid', '/encrypted':pdf_bytes(['Private'], True), '/image':pdf_bytes([''])}.get(self.path, getattr(self.server,'pdf',PDF))
        kind = 'application/octet-stream' if self.path == '/generic' else 'application/pdf'
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.end_headers()
        self.wfile.write(body)


class PdfTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixture.FocusedTests.setUp
    tearDown = fixture.FocusedTests.tearDown
    for_agent = fixture.FocusedTests.for_agent

    async def setup_pdf(self):
        self.server.RequestHandlerClass = PdfServer
        self.engine.state['config']['carrier_screening'] = True
        screen = self.api.screen_carrier('Independent fixture', self.origin + '/pdf')
        return screen

    async def test_real_binary_pdf_read_receipts_pages_cache_and_lead_handoff(self):
        screen = await self.setup_pdf()
        doc = await self.api.read_document(self.origin + '/pdf', 'Read exact API document')
        self.assertEqual(doc['status'], 'COMPLETED')
        self.assertEqual(doc['pages'], [1, 2])
        self.assertEqual(doc['pdf']['page_count'], 2)
        self.assertEqual(doc['sha256'], hashlib.sha256(PDF).hexdigest())
        self.assertIn('Monthly subscription required.', doc['text'])
        receipt = self.agent['http_document_reads'][doc['request_id']]
        self.assertEqual(receipt['pages'], [1,2])
        self.assertEqual(receipt['pdf']['source_sha256'], doc['sha256'])
        lead = self.engine.state['discovery_leads'][0]
        self.assertEqual(lead['id'], screen['lead_id'])
        self.assertEqual(lead['documents'][0]['pages'], [1,2])
        self.assertTrue(awaiting_review(self.engine.state))
        auditor = self.engine.state['agents'][1]
        auditor.update(status='BLOCKED',reason_for_stopping='NO_ADMITTED_DISCOVERY_CANDIDATE')
        recover(self.engine)
        self.assertEqual(auditor['status'], 'PENDING')
        with patch('metaweb_swarm.pdf_documents.extract', side_effect=AssertionError('Repeated parsing')):
            page = await self.api.read_document(self.origin + '/pdf', 'Read second PDF page', offset=doc['text'].index('[PDF page 2]'))
        self.assertTrue(page['cached']);self.assertEqual(page['pages'],[2])
        self.assertEqual(self.server.calls, ['/pdf'])
        self.assertFalse(self.engine.state['external_actions'])
        self.engine.store.verify()

    async def test_shared_pdf_is_readable_but_not_an_independent_audit(self):
        await self.setup_pdf()
        doc = await self.api.read_document(self.origin + '/pdf', 'Read original API guide')
        review = self.for_agent(self.engine.state['agents'][1])
        shared = review.read_audit_artifact(doc['request_id'])
        self.assertEqual(shared['status'],'COMPLETED');self.assertEqual(shared['pages'],[1,2])
        self.assertFalse(review.agent.get('http_document_reads'))
        own = await review.read_document(self.origin + '/pdf', 'Independently inspect actual PDF')
        self.assertNotEqual(doc['request_id'], own['request_id'])
        quoted = source_quote(review, 'Monthly subscription required.', [self.origin + '/pdf'])
        self.assertEqual(quoted['pages'], [2])
        r = review.record_lead_review(doc['lead_id'], 'NOT_SUITABLE', 'Recurring subscription would violate the operator policy.',
                 'Find a carrier without recurring payment.', 'Monthly subscription required.', [self.origin+'/pdf'])
        self.assertEqual(r['disposition'], 'NOT_SUITABLE')

    async def test_corrupt_derived_text_rebuilt_from_original_not_trusted(self):
        await self.setup_pdf()
        doc = await self.api.read_document(self.origin + '/pdf', 'Read original PDF')
        path = self.run/doc['pdf']['path']
        path.write_text(json.dumps({'pages':['FAKE negative evidence']}),encoding='utf-8')
        rebuilt = await self.api.read_document(self.origin + '/pdf', 'Read unchanged source with modified cache')
        self.assertTrue(rebuilt['cached'])
        self.assertNotIn('FAKE', rebuilt['text'])
        self.assertEqual(len(self.server.calls),1)
        self.engine.close();self.engine=Engine(self.run, DemoBackend(), 'demo')
        api=self.for_agent(self.engine.state['agents'][0])
        with patch('metaweb_swarm.pdf_documents.extract', side_effect=AssertionError('Cache not restored')):
            read = await api.read_document(self.origin+'/pdf','Read restored cached PDF')
        self.assertEqual(read['pages'],[1,2])

    async def test_encrypted_empty_malformed_and_marker_only_are_not_read_receipts(self):
        await self.setup_pdf()
        for url, reason in [('/encrypted','PDF_ENCRYPTED'),('/image','PDF_NO_TEXT_OCR_REQUIRED'),('/bad','PDF_PARSE_FAILED')]:
            r=await self.api.read_document(self.origin+url,'Read unsupported PDF case')
            self.assertEqual(r['status'],'BLOCKED');self.assertEqual(r['reason'],reason)
            self.assertNotIn(r['request_id'],self.agent.get('http_document_reads',{}))
        r=await self.api.read_document(self.origin+'/pdf','Read page marker only',limit=2)
        self.assertEqual(r['reason'],'PDF_NO_TEXT_IN_RANGE')
        self.assertNotIn(r['request_id'],self.agent.get('http_document_reads',{}))
        self.assertFalse(self.engine.state['discovery_leads'][0]['documents'])

    async def test_pdf_magic_recognized_but_screening_not_bypassed(self):
        await self.setup_pdf()
        r=await self.api.read_document('https://different.example.org/api.pdf','Read unrelated PDF')
        self.assertEqual(r['status'],'DEFERRED');self.assertFalse(self.server.calls)
        r=await self.api.read_document(self.origin+'/generic','Read octet-stream PDF with real header')
        self.assertEqual(r['status'],'COMPLETED');self.assertIn('API guide',r['text'])

    def test_parser_resource_limits_and_timeout(self):
        with self.assertRaisesRegex(PdfDocumentError,'PDF_BYTE_LIMIT'):extract(b'x'*8_000_001)
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('fixed worker',20)):
            with self.assertRaisesRegex(PdfDocumentError,'PDF_EXTRACTION_TIMEOUT'):extract(PDF)
        with self.assertRaisesRegex(PdfDocumentError,'PDF_PAGE_LIMIT'):extract(pdf_bytes(['']*501))

    def test_worker_does_not_inherit_credentials_or_agent_paths(self):
        with patch.dict('os.environ',{'OPENAI_API_KEY':'fixture-secret','META_SWARM_CRED_FIXTURE':'fixture-key','PYTHONPATH':'bad-path'}):
            with patch('subprocess.run',return_value=subprocess.CompletedProcess([],0,json.dumps({'pages':['hello'],'parser':'fixture','parser_version':'1'}).encode())) as run:
                extract(PDF)
        kwargs=run.call_args.kwargs
        self.assertNotIn('OPENAI_API_KEY',kwargs['env']);self.assertNotIn('META_SWARM_CRED_FIXTURE',kwargs['env'])
        self.assertNotIn('PYTHONPATH',kwargs['env']);self.assertFalse(kwargs['shell'])
        self.assertEqual(run.call_args.args[0][1],'-I')

    async def test_missing_dependency_returns_concrete_blocker_without_false_receipt(self):
        await self.setup_pdf()
        with patch('subprocess.run',return_value=subprocess.CompletedProcess([],0,b'{"error":"PDF_DEPENDENCY_MISSING"}')):
            r=await self.api.read_document(self.origin+'/pdf','Read PDF while dependency missing')
        self.assertEqual(r['reason'],'PDF_DEPENDENCY_MISSING')
        self.assertFalse(self.agent.get('http_document_reads'))
        r=await self.api.read_document(self.origin+'/pdf','Retry same cached PDF after dependency available')
        self.assertEqual(r['status'],'COMPLETED');self.assertTrue(r['cached'])
        self.assertEqual(self.server.calls,['/pdf'])

    async def test_derived_pdf_text_redacts_assigned_secret_but_original_hash_is_preserved(self):
        await self.setup_pdf()
        secret='fixture-secret-value-that-must-not-leak'
        body=pdf_bytes(['Example secret: '+secret])
        self.server.pdf=body
        with patch.dict('os.environ',{'OPENAI_API_KEY':secret}):
            r=await self.api.read_document(self.origin+'/pdf','Read PDF with echoed assigned secret')
        self.assertNotIn(secret,r['text']);self.assertIn('[REDACTED]',r['text'])
        self.assertEqual(r['sha256'],hashlib.sha256(body).hexdigest())
        self.assertNotIn(secret,(self.run/r['pdf']['path']).read_text(encoding='utf-8'))
