"""Current-run research handoffs, independent of external deposit qualification."""
import hashlib
from pathlib import PurePosixPath
from .storage import canonical


def enabled(state):
    config = state.get('config',{})
    return bool(config.get('research_handoffs') and config.get('task_style') == 'research'
                and not config.get('sandbox_smoke_test') and not config.get('http_smoke_test'))


def revision(idea):
    # An evidence/provenance merge keeps the implementation job it contributed to.
    # This anchor is set by the host, never taken from a model proposal.
    return idea.get('implementation_revision') or evidence_revision(idea)


def evidence_revision(idea):
    # Status, critiques and local artifacts must not create an audit feedback loop.
    fields = ('id', 'title', 'mechanism', 'provider', 'summary', 'payment', 'evidence',
              'novelty_delta', 'baseline_evidence_ids', 'validation_plan', 'proposed_change')
    return hashlib.sha256(canonical({k: idea.get(k) for k in fields}).encode()).hexdigest()


def inventory(state):
    return [{k: i.get(k) for k in ('id', 'title', 'status', 'agent_id', 'mechanism_key',
                                 'provider', 'blocker', 'prototype_tested', 'next_action')}
            for i in state['ideas']]


def reviews(state, agent):
    from .research_recovery import blocked
    if state['config'].get('coding_acceptance'):return []
    return [i for i in state['ideas'] if i.get('status') not in {'REJECTED', 'COMPLETED'}
            and agent['id'] != i.get('agent_id')
            and not blocked(agent, i, 'REVIEW')
            and not any(c.get('idea_id') == i['id'] and c.get('agent_id') == agent['id']
                        and c.get('research_revision') == evidence_revision(i) for c in state.get('critiques', []))]


def local_candidates(state, agent):
    from .research_recovery import blocked
    from .prototype_focus import eligible
    from .prototype_debug import local_issue
    from .prototype_preflight import local_issue as plan_issue
    from . import prototype_queue as queue
    choices = [i for i in state['ideas'] if i.get('status') not in {'REJECTED', 'COMPLETED'}
            and eligible(state,i)
            and not local_issue(state,agent,i['id'])
            and not plan_issue(state,agent,i['id'])
            and i.get('payment') in {'FREE','ONE_TIME'} and i.get('requires_ongoing_payments') is not True
            and not blocked(agent, i, 'LOCAL')
            and not i.get('prototype_tested') and not i.get('completion_receipts')
            and not (queue.receipt_excludes(state,i) if queue.enabled(state) else any(t.get('idea_id')==i['id']
                        and t.get('host_execution_verified') and t.get('prototype_plan',{}).get('research_revision')==revision(i)
                        and t.get('prototype_review',{}).get('verdict')!='REVISE' for t in state.get('tests',[])))
            and (state['config'].get('run_mode') == 'autonomous'
                 or state.get('implementation_choices', {}).get(i['id'], {}).get('decision') == 'implement')
            and not any(b['idea_id'] == i['id'] and b['revision'] == revision(i)
                        and b['operator_notes_count'] == len(agent.get('operator_notes', []))
                        for b in agent.get('research_blockers', []))]
    return queue.select_candidates(state,agent,choices) if queue.enabled(state) else choices


def assign(engine, agent):
    state = engine.state
    if not enabled(state): return
    if agent.get('work_kind') == 'LOCAL':
        choices = local_candidates(state, agent)
        old = agent.get('research_assignment', {})
        idea = next((i for i in choices if i['id'] == old.get('target_id')), choices[0] if choices else None)
        packet = {'kind': 'LOCAL_IDEA', 'target_id': idea['id'], 'revision': revision(idea)} if idea else {'kind': 'NONE'}
        if packet != old:
            agent['research_assignment'] = packet
            engine.store.commit(state, 'research_task_assigned', packet, agent['id'])


def prepare_task_context(engine, agent, workspace):
    """Archive old task conversations; current assignment is the new model context."""
    if not enabled(engine.state): return
    task=(agent.get('review_assignment') if agent.get('work_kind')=='REVIEW' else
          {'kind':'DISCOVERY_PIVOT','target_id':agent['discovery_pivot']['provider'],
           'revision':canonical(agent.get('known_discovery_directions',[]))} if agent.get('discovery_pivot') else
          {'kind':'DISCOVERY'} if agent.get('work_kind')=='DISCOVERY' else agent.get('research_assignment'))
    if agent.get('work_kind')=='SYNTHESIS':
        from .deposit_handoff import report_revision
        task={'kind':'CURRENT_RUN_REPORT','target_id':engine.state['run_id'],'revision':report_revision(engine.state)}
        # The same current packet is delivered directly in Engine.prompt.
        agent['research_report_revision']=task['revision']
    if not task: return
    if agent.get('work_kind')=='LOCAL':
        from .prototype_debug import last
        from .prototype_revision import latest
        revised=latest(engine.state,agent,task.get('target_id'))
        if revised:
            task={'kind':'LOCAL_REVISION','target_id':revised['id'],'revision':revised['prototype_review']['id']}
        failed=last(engine.state,agent,agent.get('research_assignment',{}).get('target_id'))
        if failed and failed.get('failure_review'):
            task={'kind':'LOCAL_REPAIR','target_id':failed['experiment_id'],'revision':failed['failure_review']['id']}
    key=canonical({k:task.get(k) for k in ('kind','target_id','revision')})
    if agent.get('work_kind') in {'LOCAL','REVIEW'} and engine.state['config'].get('coding_backend')=='sdk_shell':
        key=canonical({'task':key,'prototype_workflow':'review-environment-0.8.3'})
    elif agent.get('work_kind')=='LOCAL' and engine.state['config'].get('require_prototype_focus'):
        key=canonical({'task':key,'prototype_workflow':'0.6.18'})
    if agent.get('active_task_key')==key: return
    if agent.get('work_kind')=='REVIEW' and task.get('kind')=='PROTOTYPE_TEST':
        # A read in discarded model history is not a read available to the new
        # context. Force the actual immutable source/output reads again.
        ident=task['target_id']
        fields=('prototype_artifact_reads','prototype_artifact_checks','prototype_fact_reads','prototype_review_repairs')
        invalidated=[name for name in fields if ident in agent.get(name,{})]
        for name in fields:agent.get(name,{}).pop(ident,None)
        if invalidated:
            engine.store.commit(engine.state,'prototype_review_context_reads_invalidated',
                {'test_id':ident,'fields':invalidated,'reason':'Source observations must be present in the current model context'},agent['id'])
    if agent.get('history'):
        from .storage import atomic_write
        archive=f"context/task-history-before-round-{agent['rounds']}.json"
        original=canonical(agent['history'])
        atomic_write(engine.store.run_dir/'raw'/f"{agent['id']}-task-history-before-round-{agent['rounds']}.json",original)
        workspace.write_file(archive,original)
        agent['history']=[]
        engine.store.commit(engine.state,'task_context_reset',{'archive':archive,
            'archive_sha256':hashlib.sha256(original.encode()).hexdigest(),
            'previous_task':agent.get('active_task_key'),'current_task':key,
            'meaning':'Model context reset only; receipts, files, budgets, approval and unknown external outcomes retained.'},agent['id'])
    agent['active_task_key']=key
    if getattr(engine,'console_enabled',False) and task.get('kind')!='NONE':
        print(f"  {agent['id']} | Task: {task['kind']}"+(f" {task['target_id']}" if task.get('target_id') else ''),flush=True)


def admission(api, data):
    """An explicit named ARCHIVE layer cannot become a new carrier by wording alone."""
    if not enabled(api.engine.state) or not isinstance(data,dict) or data.get('id') or not isinstance(data.get('provider',''),str): return None
    from .carrier_screening import registry_matches
    from urllib.parse import urlsplit
    urls=[e.get('url','') for e in data.get('evidence',[]) if isinstance(e,dict)]
    matches=registry_matches(api.engine.baseline,data.get('provider',''),'')
    for url in urls:
        if isinstance(url,str):
            try: host=urlsplit(url).hostname or ''
            except ValueError: continue
            matches += registry_matches(api.engine.baseline,data.get('provider',''),host)
    if not matches: return None
    improvement=all(isinstance(data.get(k),str) and data[k].strip() for k in
                    ('novelty_delta','baseline_behavior','proposed_change','validation_plan'))
    baseline=api.engine.baseline.search([data.get('provider','')[:100]])
    valid_ids={m['id'] for m in baseline.get('matches',[])}
    if improvement and set(data.get('baseline_evidence_ids',[])) & valid_ids: return None
    result={'status':'DEFERRED','reason':'EXISTING_ARCHIVE_LAYER','provider':data.get('provider'),
            'registered_entries':matches,'baseline':baseline,
            'next_action':'Switch to a different carrier or document a material improvement with actual BASE IDs, current behavior, precise change and a validation plan. This is not a new layer and is not scientifically REJECTED.'}
    api.event('known_candidate_deferred',result)
    return result


def packet(state, agent):
    from .prototype_focus import eligible
    kind = agent.get('work_kind')
    if kind == 'REVIEW':
        from .review_tasks import current
        task = current(state, agent) or {'kind': 'NONE', 'stage': 'DONE'}
        if task.get('kind') in {'PROTOTYPE_TEST','PROTOTYPE_FAILURE','PROTOTYPE_PLAN'}:
            from .review_tasks import pending
            return dict(task,remaining_ids=[p['target_id'] for p in pending(state,agent)])
        idea = next((i for i in state['ideas'] if i['id'] == task.get('target_id')), None)
        return dict(task, candidate=idea, remaining_ids=[i['id'] for i in reviews(state, agent)])
    if kind == 'LOCAL':
        task = agent.get('research_assignment', {'kind': 'NONE'})
        idea = next((i for i in state['ideas'] if i['id'] == task.get('target_id')), None)
        receipts = [t['id'] for t in state.get('tests', []) if t.get('idea_id') == task.get('target_id')
                    and t.get('agent_id') == agent['id'] and t.get('host_execution_verified')]
        from .research_recovery import current, blocked, materialized_inputs
        from .prototype_debug import last
        from .prototype_revision import latest,packet as revision_packet
        revised=latest(state,agent,task.get('target_id'))
        inputs = materialized_inputs(agent)
        from .prototype_inputs import view as input_view
        # Current claims are task input; repeated historical submissions remain in SWARM_STATE/audit.
        candidate={k:v for k,v in idea.items() if k not in {'revisions','submissions'}} if idea else None
        return dict(task, candidate=candidate, recorded_tests=receipts,
                    test_revision=revision_packet(revised) if revised else None,
                    failed_prototype=last(state,agent,task.get('target_id')),
                    prototype_focus=idea.get('prototype_focus') if idea else None,
                    focus_deferrals=[{'idea_id':i['id'],'prototype_focus':i.get('prototype_focus')} for i in state['ideas']
                        if state['config'].get('require_prototype_focus') and not eligible(state,i)],
                    payment_deferrals=[{'idea_id':i['id'],'payment':i.get('payment'),
                        'next_action':'Discovery/audit must verify pricing from primary docs before provider prototyping. UNKNOWN is retained, not rejected.'}
                        for i in state['ideas'] if i.get('payment')=='UNKNOWN'],
                    materialized_inputs=inputs, payload_inputs=input_view(state,agent,idea),
                    repair=(blocked(agent, idea, 'LOCAL') or current(agent, idea, 'LOCAL')) if idea else None,
                    prototype_plan=agent.get('prototype_plans',{}).get(task.get('target_id')),
                    last_execution=next(({k:e.get(k) for k in ('experiment_id','status','returncode','output','prototype_readiness')}
                        for e in reversed(state.get('experiments',[])) if e.get('agent_id')==agent['id'] and e.get('idea_id')==task.get('target_id')),None),
                    sandbox_capabilities=agent.get('sandbox_capabilities',{}),
                    environment_hint='Bundled image supplies Python, not Node. get_sandbox_capabilities observes the actual image without network. Prefer Python for prototypes; pip does not install a JS runtime.',
                    external_outcomes=[{k:r.get(k) for k in ('id','idea_id','status')} for r in state.get('http_requests',[]) if r.get('agent_id')==agent['id']],
                    remaining_ids=[i['id'] for i in local_candidates(state, agent)],
                    next_action='Implement THIS current IDEA. Materialize a retained export FIRST and use the returned workspace path in BOTH script and input_path. Inspect its contents/format, write an actual Python test script that WRITES planned outputs and tests corrupt/invalid input, THEN record_prototype_plan. To repair a prototype plan, correct paths/script and call record_prototype_plan again; deposit-plan edits are unrelated. '
                        'For the host-owned LOCAL workflow, execute_prototype(argv) runs the checked code and captures its receipt together; no IDEA/test/experiment IDs or manual registration. The host selects repair links. After a code change resubmit record_prototype_plan with repair_notes and repair_check, never any repair IDs. Wait for independent plan review without polling. Receipt records execution only; independent review determines coverage. '
                        'Follow prototype_focus.goal. Implementation/debug playbook is context/PROTOTYPING_GUIDE.md; reference recipes are optional and only relevant to matching algorithms. Test the carrier/format operation, not input fields. A disk path is not a public recovery pointer; a copied original is not a decoder output. Extract from the generated specimen and feed THAT result into downstream outputs. '
                        'No new IDEA and no prior-run placeholder. Concrete impossibility: record_research_blocker; promising ideas remain retained.')
    if kind == 'SYNTHESIS':
        from .report_packet import build
        return build(state)
    return {'kind': 'COORDINATION' if kind == 'COORDINATION' else 'DISCOVERY', 'ideas': inventory(state),
            'known_directions_this_role':agent.get('known_discovery_directions',[]),
            'current_pivot':agent.get('discovery_pivot'),
            'roles': [{k: a.get(k) for k in ('id', 'role', 'mission', 'status')} for a in state['agents']],
            'next_action': 'Coordinate concrete coverage and queue specialists if needed; an empty early inventory is normal.'
                if kind == 'COORDINATION' else agent['discovery_pivot']['next_action'] if agent.get('discovery_pivot') else
                'Compare current IDs. Search a materially different family after a known-layer deferral; no more capacity research for that unchanged layer. submit_idea id="" creates a draft; use its returned ID for updates. Empty evidence is permitted for an honest hypothesis; never invent IDEA/LEAD IDs.'}


def gate(api, idea_id):
    if not enabled(api.engine.state) or api.agent.get('work_kind') != 'LOCAL': return None
    task = api.agent.get('research_assignment', {})
    if task.get('kind') != 'LOCAL_IDEA' or task.get('target_id') != idea_id:
        return {'status': 'DEFERRED', 'reason': 'ASSIGNED_CURRENT_IDEA_REQUIRED',
                'research_task': packet(api.engine.state, api.agent)}
    from .research_recovery import blocked
    return blocked(api.agent, api.idea(idea_id), 'LOCAL')


def register(api, idea_id, paths):
    with api.engine.mutex:
        issue = gate(api, idea_id)
        if issue: return issue
        idea = api.idea(idea_id)
        if not isinstance(paths, list) or not 1 <= len(paths) <= 128 or any(not isinstance(p, str) for p in paths):
            raise ValueError('Provide 1..128 existing workspace artifact paths')
        checks = []
        for path in paths:
            info = api.workspace.file_info(path)  # Validates ancestors/links/credentials before mutation.
            relative = str(PurePosixPath(path.replace('\\', '/')))
            checks.append({'path': f"agents/{api.agent['id']}/workspace/{relative}", **info})
        previous = {c['path']: c for c in idea.get('artifact_checks', [])}
        previous.update({c['path']: c for c in checks})
        idea['artifact_checks'] = list(previous.values())
        api.event('research_artifacts_registered', {'idea_id': idea_id, 'agent_id': api.agent['id'], 'artifacts': checks})
        return {'idea_id': idea_id, 'artifacts': checks, 'next_action': 'Execute linked to this IDEA, then record_test; registration alone is not a test.'}


def block(api, idea_id, reason):
    issue = gate(api, idea_id)
    if issue: return issue
    if not isinstance(reason, str) or not 10 <= len(reason.strip()) <= 4000:
        raise ValueError('Concrete technical blocker required, 10..4000 characters')
    idea = api.idea(idea_id)
    from .research_recovery import current, defer
    repair = current(api.agent, idea, 'LOCAL')
    if repair and repair.get('code')=='PROTOTYPE_OUTPUTS_REQUIRED':
        return defer(api, idea_id, 'LOCAL', repair['code'], repair['details'],
                     'The last successful script did not WRITE the planned specimen. Fix the script with write_file, update record_prototype_plan and rerun. Recording a bookkeeping blocker does not create a test. After repeated unresolved validation, this task is retained and other candidates can proceed.')
    record = {'idea_id': idea_id, 'revision': revision(idea), 'reason': reason,
              'operator_notes_count': len(api.agent.get('operator_notes', []))}
    api.agent.setdefault('research_blockers', []).append(record)
    api.event('research_implementation_blocked', record)
    return dict(record, status='BLOCKED', meaning='Local assignment blocked; candidate retained, not scientifically rejected')


def complete(state, agent, output):
    if not enabled(state): return output
    if agent.get('work_kind') == 'SYNTHESIS':
        from .deposit_handoff import report_revision
        receipt = agent.get('research_report_receipt',{})
        if receipt.get('revision') == report_revision(state):
            output['handoff_leads'] = list(dict.fromkeys(output['handoff_leads']+output['unexplored_leads']))
            output.update(status='COMPLETED',reason_for_stopping='Current report recorded; unresolved research retained for handoff',
                          summary=receipt['conclusion'],unexplored_leads=[])
        elif agent.get('research_report_revision') != report_revision(state):
            output.update(status='CONTINUE', reason_for_stopping='CURRENT_REPORT_PACKET_REQUIRED',
                          unexplored_leads=['Call get_research_task and synthesize current-run candidates and actual host receipts.'])
        else:
            output.update(status='CONTINUE',reason_for_stopping='RESEARCH_REPORT_RECEIPT_REQUIRED',
                          unexplored_leads=['Call record_research_report for all current IDs; lack of a prototype/deposit is a report finding, not unfinished reporter research.'])
        return output
    if agent.get('work_kind') != 'LOCAL': return output
    from . import prototype_queue as queue
    if queue.enabled(state) and queue.awaiting(state,agent):
        agent['prototype_queue_hold']='AWAITING_INDEPENDENT_PROTOTYPE_REVIEW'
        output.update(status='BLOCKED',reason_for_stopping=agent['prototype_queue_hold'],
                      unexplored_leads=['Recorded execution awaits independent review; do not start another candidate.'])
        return output
    task = packet(state, agent)
    done = (bool(task.get('recorded_tests')) and not task.get('test_revision')) or task['kind'] == 'NONE'
    from .research_recovery import blocked as repair_blocked, current, active_blocks
    idea = task.get('candidate')
    blocked = (any(b['idea_id'] == task.get('target_id') for b in agent.get('research_blockers', []))
               or bool(idea and repair_blocked(agent, idea, 'LOCAL')))
    repair = current(agent, idea, 'LOCAL') if idea else None
    if not done and not blocked and not repair and output['status'] == 'BLOCKED':
        # Keep the narrative as a technical stop; never upgrade it to a test or rejection.
        return output
    remaining = local_candidates(state, agent)
    if not done and not blocked or remaining:
        output.update(status='CONTINUE', reason_for_stopping='CURRENT_IDEA_TEST_RECEIPT_REQUIRED',
                      unexplored_leads=['Finish the assigned linked prototype/test or record a concrete blocker; then take the next current IDEA.'])
    else:
        output['handoff_leads'] = list(dict.fromkeys(output['handoff_leads'] + output['unexplored_leads']))
        output.update(status='BLOCKED' if agent.get('research_blockers') or active_blocks(state, agent, 'LOCAL') else 'COMPLETED', unexplored_leads=[],
                      reason_for_stopping='Current local assignments tested or concretely blocked; external deployment handed off')
    return output


def recover(engine):
    """New actual work reopens finished handoffs only within existing allowances."""
    state = engine.state
    if not enabled(state): return
    from .config import round_allowance
    from .deposit_handoff import report_revision
    for agent in state['agents']:
        retry_local=(agent.get('work_kind')=='LOCAL' and agent['status']=='BLOCKED'
                     and agent.get('reason_for_stopping','').startswith(('Current local assignments','FAILED_CODE_','PROTOTYPE_PLAN_REVIEW_PENDING')))
        retry_review=(agent.get('work_kind')=='REVIEW' and agent['status']=='BLOCKED'
                      and agent.get('reason_for_stopping','').startswith('REVIEW_REPAIR_STALLED'))
        if agent['status'] != 'COMPLETED' and not retry_local and not retry_review: continue
        kind = agent.get('work_kind')
        from .prototype_review import pending as pending_tests
        waiting = (bool(reviews(state, agent) or pending_tests(state,agent)) if kind == 'REVIEW' else
                   bool(local_candidates(state, agent)) if kind == 'LOCAL' else
                   agent.get('research_report_revision') != report_revision(state) if kind == 'SYNTHESIS' else False)
        if not waiting: continue
        status = 'PENDING' if agent['rounds'] < round_allowance(state['config'], agent) else 'LIMIT_REACHED'
        agent.update(status=status, reason_for_stopping='New current-run handoff; existing round allowance applies')
        engine.store.commit(state, 'research_handoff_reopened', {'agent_id': agent['id'], 'status': status}, agent['id'])


def tool_names(agent):
    common = {'get_research_task', 'list_current_ideas', 'note', 'read_file', 'read_audit_artifact'}
    kind = agent.get('work_kind')
    if kind == 'SYNTHESIS': return common | {'record_research_report','read_report_detail'}
    if kind == 'COORDINATION': return common | {'spawn_agent', 'check_baseline', 'list_files'}
    if kind=='REVIEW' and agent.get('review_assignment',{}).get('kind')=='PROTOTYPE_PLAN':
        return common | {'get_review_task','read_prototype_plan','review_prototype_plan'}
    if kind=='REVIEW' and agent.get('review_assignment',{}).get('kind')=='PROTOTYPE_TEST':
        return common | {'get_review_task','read_test_artifact','review_prototype_test','get_prototype_review_facts','run_review_probe','install_packages'}
    if kind=='REVIEW' and agent.get('review_assignment',{}).get('kind')=='PROTOTYPE_FAILURE':
        return common | {'get_review_task','read_failed_experiment','record_failure_diagnosis'}
    if kind == 'REVIEW': return common | {'get_review_task', 'read_document', 'check_baseline', 'record_critique', 'read_test_artifact', 'review_prototype_test'}
    local = {'list_files', 'search_file', 'write_file', 'write_binary', 'list_exports', 'materialize_export',
             'install_packages', 'run_experiment', 'record_test', 'register_idea_artifacts', 'record_prototype_plan', 'get_sandbox_capabilities','read_failed_experiment','read_revised_test','prepare_prototype_input','execute_prototype'}
    if kind == 'LOCAL':
        local_tools = common | local | {'submit_idea', 'record_research_blocker', 'read_document'}
        names = local_tools | {'http_request', 'list_http_credentials',
            'verify_http_copy', 'check_deposit_target', 'deposit_file', 'request_approval',
            'record_deposit_execution_plan', 'read_deposit_plan_draft', 'edit_deposit_plan_step',
            'bind_deposit_step_response', 'execute_deposit_plan', 'record_deposit_flow'}
        task = agent.get('research_assignment', {})
        if task.get('kind')=='LOCAL_IDEA' and agent.get('deposit_plan_draft', {}).get('idea_id') != task.get('target_id'):
            names -= {'read_deposit_plan_draft', 'edit_deposit_plan_step', 'bind_deposit_step_response'}
        return names
    return common | local | {'submit_idea', 'check_baseline', 'check_prior_work', 'read_document', 'http_request', 'spawn_agent',
                            'screen_carrier', 'list_http_credentials', 'check_deposit_target'}
