"""Durable policy and audit around provider-independent HTTP requests."""
import asyncio
import hashlib
import json
import os
import uuid

from .storage import canonical, now
from .policy import action_hash


class HttpTools:
    def read_audit_artifact(self, request_id, offset=0, limit=8000):
        from .audit_artifacts import read
        return read(self, request_id, offset, limit)

    async def read_document(self, url, purpose, offset=0, limit=12000):
        from .documents import read_document
        from .review_tasks import read_gate, read_result
        gate=read_gate(self,url)
        if gate: return gate
        result=await read_document(self, url, purpose, offset, limit)
        return read_result(self,url,result)

    def list_http_credentials(self):
        # Names and host grants only. Never enumerate environment or host stores.
        return {'credentials': [dict({k: c.get(k) for k in ('id', 'hosts', 'header', 'scheme')},
                                     available=bool(os.getenv(c['env'])))
                                for c in self.engine.state['config'].get('http_credentials', [])],
                'ambient_credentials_available': False}

    async def http_request(self, request, idea_id='', purpose=''):
        from .http_transport import normalize_request, execute_request, READ_METHODS, HttpTransportError, redact
        config, state = self.engine.state['config'], self.engine.state
        if not isinstance(purpose, str) or not 5 <= len(purpose) <= 2000:
            raise ValueError('Describe the purpose of this HTTP request (5..2000 characters)')
        if config.get('http_access', 'read-only') == 'disabled':
            return {'status':'BLOCKED', 'reason':'HTTP_DISABLED'}
        if config.get('http_smoke_test'):
            from .http_smoke import permitted_url
            if not permitted_url(state, request.get('url', '')):
                return {'status':'BLOCKED', 'reason':'HTTP_SMOKE_FIXTURE_ONLY'}
        if config.get('http_smoke_service'):
            from .http_public_smoke import metadata_gate
            if request.get('method', 'GET').upper() not in READ_METHODS:
                reason = metadata_gate(request)
                if reason:
                    return {'status':'BLOCKED', 'reason':reason}
        descriptor, prepared = normalize_request(request, config, self.workspace)
        from .deposit_execution import request_permit, lease_totals
        permit = request_permit(self, descriptor)
        if getattr(self, '_deposit_context', None) and permit is None:
            return {'status':'BLOCKED','reason':'INVALID_SEQUENCE_EXECUTION_PERMIT'}
        if permit:
            # Approval binds templates, exact origins and wire SHA, never exposes
            # a returned signed URL/path/header or a resolved capability in JSON.
            if permit.get('private_target'):
                from urllib.parse import urlsplit
                parts=urlsplit(prepared.url)
                descriptor['url']=parts.scheme+'://'+parts.netloc+'/[PRIVATE_FLOW_TARGET]'
            descriptor['headers']={k:'[PRIVATE_FLOW_HEADER]' for k in descriptor.get('headers',{})}
            descriptor.pop('body_preview',None)
        if config.get('http_smoke_service'):
            from .http_public_smoke import request_gate
            reason = request_gate(self, descriptor, prepared)
            if reason:
                return {'status':'BLOCKED', 'reason':reason}
        mutation = descriptor['method'] not in READ_METHODS
        privileged = mutation or bool(descriptor.get('credential_id'))
        if idea_id:
            self.idea(idea_id)
        if mutation and config.get('require_deposit_qualification') and not permit:
            from .deposit_qualification import execution_gate
            reason = execution_gate(self, self.idea(idea_id) if idea_id else None, descriptor)
            if reason:
                return {'status': 'DEFERRED', 'reason': reason}
        if mutation and config.get('require_independent_http_review'):
            idea = self.idea(idea_id) if idea_id else None
            critique = (idea or {}).get('critique', {})
            reviewer = next((a for a in state['agents'] if a['id'] == critique.get('agent_id')), None)
            if not (idea and critique.get('verdict') == 'PASS' and reviewer
                    and reviewer['role'] == 'Evidence Auditor' and reviewer['id'] != idea.get('agent_id')):
                return {'status': 'DEFERRED', 'reason': 'INDEPENDENT_AUDIT_REQUIRED'}
        if mutation:
            if config.get('http_access', 'read-only') != 'enabled':
                return {'status':'BLOCKED', 'reason':'HTTP_READ_ONLY'}
            gate = self.implementation_allowed(idea_id)
            if gate:
                return {'status':'DEFERRED', 'reason':gate}
        if privileged and config.get('external_scope', 'sandbox-only') != 'external':
            return {'status':'BLOCKED', 'reason':'EXTERNAL_SCOPE_DISABLED'}
        if privileged and self.agent.get('work_kind') == 'SYNTHESIS':
            return {'status':'BLOCKED', 'reason':'SYNTHESIS_ROLE_READ_ONLY'}
        action = {'idea_id':idea_id, 'kind':'PUBLISH' if mutation else 'CREDENTIALS',
                  'description':purpose, 'target':descriptor['url'],
                  'payload':dict(descriptor, bytes=descriptor.get('bytes', len(prepared.body)))}
        digest = action_hash(action)
        effect_digest = descriptor.get('wire_sha256') or hashlib.sha256(canonical({k:v for k,v in descriptor.items() if k != 'response_path'}).encode()).hexdigest()
        with self.engine.mutex:
            ledger = state.setdefault('http_requests', [])
            # Mutations are exactly-once attempts. A crash/error must be reconciled,
            # not implicitly retried by a model or a resumed process.
            previous = next((r for r in ledger if mutation and r.get('effect_digest', r['hash']) == effect_digest), None)
            if previous:
                if previous['status'] in {'COMPLETED', 'VERIFIED'}:
                    return dict(previous, replayed=True)
                return {'status':'BLOCKED', 'reason':'PREVIOUS_HTTP_ATTEMPT_REQUIRES_RECONCILIATION', 'request_id':previous['id']}
            approval = None
            if privileged and config.get('approval_required', True) and not permit:
                approval = next((a for a in state['approvals'] if a['hash'] == digest), None)
                if approval is None:
                    approval = {'id':f"APPROVAL-{len(state['approvals'])+1:04d}", 'agent_id':self.agent['id'],
                                'status':'PENDING', 'action':action, 'hash':digest, 'created_at':now(),
                                'decision':None, 'note':'', 'executed':False, 'executor':'http_request'}
                    state['approvals'].append(approval)
                    self.event('approval_requested', approval)
                if approval['status'] != 'APPROVED':
                    return {'status':'DEFERRED' if approval['status'] == 'PENDING' else 'REJECTED',
                            'approval_id':approval['id'], 'reason':'HUMAN_APPROVAL_REQUIRED' if approval['status'] == 'PENDING' else 'ACTION_DECLINED'}
            held = lease_totals(state, permit['flow_id'] if permit else '')
            if len(ledger) + held['requests'] >= config.get('max_http_requests', 100):
                return {'status':'LIMIT_REACHED', 'reason':'MAX_HTTP_REQUESTS'}
            reserved_bytes = len(prepared.body) + config.get('max_http_response_bytes', 16777216) + 1
            if sum(r['budget_bytes'] for r in ledger) + reserved_bytes + held['total'] > config.get('max_http_total_bytes', 134217728):
                return {'status':'LIMIT_REACHED', 'reason':'MAX_HTTP_TOTAL_BYTES'}
            external = state.setdefault('external_actions', [])
            if privileged:
                if len(external) + held['actions'] >= config.get('max_external_actions', 5):
                    return {'status':'LIMIT_REACHED', 'reason':'MAX_EXTERNAL_ACTIONS'}
                if sum(r['action']['payload'].get('bytes', 0) for r in external) + len(prepared.body) + held['body'] > config.get('max_external_bytes', 536870912):
                    return {'status':'LIMIT_REACHED', 'reason':'MAX_EXTERNAL_BYTES'}
            remaining = config['max_active_seconds'] - self.engine.current_active_seconds()
            budget_stop = self.check_model_budget()
            if budget_stop:
                return {'status':'LIMIT_REACHED', 'reason':budget_stop}
            if remaining <= 0 or (self.engine.store.run_dir/'PAUSE.flag').exists():
                return {'status':'LIMIT_REACHED' if remaining <= 0 else 'DEFERRED', 'reason':'MAX_ACTIVE_SECONDS' if remaining <= 0 else 'PAUSE_REQUESTED'}
            record = {'id':'HTTP-'+uuid.uuid4().hex[:16], 'agent_id':self.agent['id'], 'idea_id':idea_id,
                      'status':'RESERVED', 'hash':digest, 'effect_digest':effect_digest, 'action':action, 'created_at':now(),
                      'budget_bytes':reserved_bytes, 'approval_id':approval['id'] if approval else None,
                      'approval_policy':'required' if approval else 'disabled' if privileged else 'read-only',
                      'privileged':privileged}
            ledger.append(record)
            if permit:
                record.update(flow_id=permit['flow_id'],flow_step=permit['flow_step'],approval_id=permit.get('approval_id'),
                              approval_policy='sequence-approved' if config.get('approval_required',True) else 'disabled')
            if privileged:
                external.append(record)
            self.event('http_request_reserved', record)
        if permit and permit.get('private_bindings'):
            from .flow_vault import save
            capture_private = lambda value: save(self.engine.store.run_dir, record['id'], value)
            worker = asyncio.create_task(asyncio.to_thread(execute_request, prepared, config, min(config.get('http_timeout_seconds', 30), remaining), capture_private))
        else:
            worker = asyncio.create_task(asyncio.to_thread(execute_request, prepared, config, min(config.get('http_timeout_seconds', 30), remaining)))
        cancelled = False
        try:
            try:
                metadata, body = await asyncio.shield(worker)
            except asyncio.CancelledError:
                cancelled = True
                while not worker.done():
                    try:
                        await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                metadata, body = worker.result()
            if permit and permit.get('private_target'):
                from urllib.parse import parse_qsl, urlsplit
                from .http_transport import _sanitize_body
                parts=urlsplit(prepared.url)
                private_values=tuple(v for v in (prepared.url, parts.path.rsplit('/',1)[-1], *[v for k,v in parse_qsl(parts.query)], *prepared.headers.values()) if v)
                content_type=next((v for k,v in metadata.get('headers',{}).items() if k.lower()=='content-type'),'')
                body=_sanitize_body(body,content_type,private_values)
                metadata.update(stored_bytes=len(body),stored_sha256=hashlib.sha256(body).hexdigest(),sanitized=metadata.get('sanitized') or hashlib.sha256(body).hexdigest()!=metadata.get('raw_sha256'))
                metadata['url']=descriptor['url']
                metadata['headers']=redact({k:'[PRIVATE_FLOW_URL]' if isinstance(v,str) and v.startswith(('https://','http://')) else v for k,v in metadata.get('headers',{}).items()},private_values)
                if metadata.get('error'): metadata['error']='Private sequence request failed; remote diagnostic withheld'
            path = descriptor.get('response_path') or 'http/'+record['id']+'.bin'
            # Enforce workspace confinement even when the remote server proposes
            # filenames/Content-Disposition. It never chooses a host path.
            self.workspace.write_file(path, body)
            with self.engine.mutex:
                record.update(status='UNKNOWN' if metadata.get('outcome_uncertain') else 'FAILED' if metadata.get('error') or metadata.get('status') is None else 'COMPLETED',
                              response=dict(metadata, path=path), finished_at=now())
                if metadata.get('private_response'):
                    record['private_response'] = metadata['private_response']
                record['budget_bytes'] = metadata.get('request_bytes', len(prepared.body)) + metadata.get('response_bytes', 0)
                if approval:
                    approval['executed'] = True
                try:
                    from .audit_artifacts import capture
                    capture(self, record, body)
                except Exception as error:
                    # A shared-copy failure never changes a known network outcome
                    # or invites replaying a mutation; preserve its original receipt.
                    record['audit_artifact_error'] = type(error).__name__
                self.event('http_request_finished', record)
                if isinstance(metadata.get('status'), int) and 200 <= metadata['status'] < 300:
                    self.agent.setdefault('external_sources', []).append({'url':descriptor['url'], 'source':'http_request', 'time':now()})
        except Exception as error:
            with self.engine.mutex:
                before_send = isinstance(error, HttpTransportError) and not error.outcome_uncertain
                diagnosis = {'type':type(error).__name__, 'stage':getattr(error, 'stage', ''),
                             'message':redact(str(error))[:2000] if isinstance(error, HttpTransportError) else 'HTTP attempt failed; detailed arbitrary exception suppressed'}
                record.update(status='FAILED' if before_send else 'UNKNOWN', error=diagnosis,
                              request_not_sent=before_send,
                              reason=diagnosis['type']+': '+diagnosis['message'], finished_at=now())
                if before_send:
                    record['budget_bytes'] = 0
                self.event('http_request_failed' if before_send else 'http_request_uncertain', record)
        if cancelled:
            raise asyncio.CancelledError()
        return record

    def verify_http_copy(self, upload_request_id, download_request_id, source_path):
        with self.engine.mutex:
            return self._verify_http_copy(upload_request_id, download_request_id, source_path)

    def _verify_http_copy(self, upload_request_id, download_request_id, source_path):
        """Confirm exact public file read-back, not retention or availability guarantees."""
        state = self.engine.state
        upload = next((r for r in state.get('http_requests', []) if r['id'] == upload_request_id and r['agent_id'] == self.agent['id']), None)
        download = next((r for r in state.get('http_requests', []) if r['id'] == download_request_id and r['agent_id'] == self.agent['id']), None)
        if not upload or not download or upload['status'] not in {'COMPLETED','VERIFIED'} or download['status'] != 'COMPLETED':
            raise ValueError('Need this agent\'s two completed HTTP requests')
        if upload['action']['payload']['method'] not in {'POST','PUT','PATCH'} or download['action']['payload']['method'] != 'GET':
            raise ValueError('Read-back must be a separate GET after a mutation')
        ledger = state['http_requests']
        if ledger.index(download) <= ledger.index(upload) or download['created_at'] < upload['finished_at']:
            raise ValueError('Read-back GET must be started after the upload finished')
        if not all(isinstance(r['response'].get('status'), int) and 200 <= r['response']['status'] < 300 and not r['response'].get('truncated') for r in (upload, download)):
            raise ValueError('Both HTTP responses must be successful and complete')
        expected = self.workspace.file_info(source_path)
        if not any(f.get('path') == source_path and f.get('sha256') == expected['sha256'] for f in upload['action']['payload'].get('files', [])):
            raise ValueError('Source bytes were not part of that upload')
        observed = self.workspace.file_info(download['response']['path'])
        if observed['sha256'] != expected['sha256'] or download['response'].get('raw_sha256') != expected['sha256']:
            raise ValueError('Downloaded bytes do not match the uploaded source')
        if state['config'].get('http_smoke_test'):
            from .http_smoke import record_receipt
            return record_receipt(self, upload, download, expected)
        idea = self.idea(upload['idea_id'])
        receipt = {'action_id':upload['id'], 'download_request_id':download['id'], 'location':download['action']['payload']['url'],
                   'sha256':expected['sha256'], 'bytes':expected['bytes'], 'host_verified':True,
                   'verification':'independent HTTP GET SHA256 read-back', 'time':now(),
                   'meaning':'Exact byte read-back only; no assertion of permanence or anonymous availability'}
        idea.setdefault('completion_receipts', []).append(receipt)
        eligible = idea.get('payment') in {'FREE','ONE_TIME'} and idea.get('requires_ongoing_payments') is not True
        idea['implementation_status'] = 'DEPOSIT_VERIFIED' if eligible else 'BYTE_COPY_VERIFIED_PAYMENT_UNRESOLVED'
        if eligible and idea['status'] != 'REJECTED':
            idea.update(status='COMPLETED', blocker='')
        upload.update(status='VERIFIED', receipt=receipt)
        for action in state.get('external_actions', []):
            if action['id'] == upload['id']:
                action.update(upload)
        self.event('http_copy_verified', receipt)
        return receipt
