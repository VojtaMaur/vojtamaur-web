"""Deterministic replay compaction; full originals remain in the audit archive."""
import json

PLANNING_TOOLS={'record_deposit_execution_plan','edit_deposit_plan_step','bind_deposit_step_response'}
RESEARCH_ERRORS={'RESEARCH_PRIMARY_EVIDENCE_REQUIRED','PROTOTYPE_INPUT_PATH_MISSING',
                 'PROTOTYPE_SCRIPT_PATH_MISSING','RETAINED_EXPORT_INPUT_REQUIRED',
                 'NEGATIVE_TEST_REQUIRED','PROTOTYPE_OUTPUTS_REQUIRED'}


def obsolete_planning_pairs(history):
    """Only completed, provably rejected data-only calls and old draft reads."""
    calls={};outputs={}
    for item in history:
        ident=item.get('call_id')
        if item.get('type')=='function_call': calls.setdefault(ident,[]).append(item)
        elif item.get('type')=='function_call_output': outputs.setdefault(ident,[]).append(item)
    obsolete=set()
    for ident,items in calls.items():
        if not ident or len(items)!=1 or len(outputs.get(ident,[]))!=1: continue
        name=items[0].get('name')
        try: value=json.loads(outputs[ident][0].get('output',''))
        except (ValueError,TypeError): continue
        if not isinstance(value,dict): continue
        rejected=(name in PLANNING_TOOLS and value.get('status')=='DEFERRED'
                  and value.get('reason')=='PLAN_REVISION_REQUIRED')
        draft_read=name=='read_deposit_plan_draft' and value.get('status')=='UNVALIDATED_DRAFT'
        research_rejected=(name in {'record_critique','record_prototype_plan'}
                           and (value.get('status')=='DEFERRED' and value.get('reason') in RESEARCH_ERRORS
                                or value.get('status')=='BLOCKED' and value.get('reason')=='RESEARCH_REPAIR_STALLED'
                                and value.get('code') in RESEARCH_ERRORS))
        if rejected or draft_read or research_rejected: obsolete.add(ident)
    return obsolete


def compact_history(history, archive, target=24000):
    # Keep protocol pairs intact. Tool outputs become excerpts, not invented summaries.
    calls = {item.get("call_id"): item.get("name", "tool") for item in history
             if item.get("type") == "function_call"}
    obsolete=obsolete_planning_pairs(history)
    result = []
    for item in history:
        item = dict(item)
        if item.get('type') in {'function_call','function_call_output'} and item.get('call_id') in obsolete:
            continue
        if item.get("role") == "user":
            # Every round adds a fresh complete operator task; old copies are redundant.
            continue
        if item.get("type") == "message" and item.get("role") == "assistant":
            # Typed stop decisions belong to old rounds. They are not current budgets.
            try:
                output = json.loads("".join(c.get("text", "") for c in item.get("content", []) if isinstance(c, dict)))
                if isinstance(output, dict) and "status" in output and "reason_for_stopping" in output:
                    continue
            except (ValueError, TypeError):
                pass
        if item.get("type") == "function_call_output":
            value = item.get("output", "")
            if isinstance(value, str) and len(value) > 1800:
                item["output"] = value[:1800] + f"\n[EXCERPT ONLY; full output in {archive}; use read_file on original source for exact data.]"
        result.append(item)
    notice=[{'role':'user','content':f'{len(obsolete)} obsolete data-only planning pairs archived at {archive}. Current host state and current private draft carry the active repair. Archived rejected arguments and old draft hashes are not a current plan. External/unknown outcomes were not selected by this filter; inspect their audit before any retry.'}] if obsolete else []
    if len(json.dumps(notice+result, ensure_ascii=False)) <= target:
        return notice+result
    # Trim at a complete protocol boundary: never retain a result without its call
    # or a call without its result. Hosted search/reasoning items stay together.
    pending = set()
    cuts = [0]
    for index, item in enumerate(result):
        if item.get("type") == "function_call":
            pending.add(item.get("call_id"))
        elif item.get("type") == "function_call_output":
            pending.discard(item.get("call_id"))
        if not pending and (index + 1 == len(result) or
                            result[index + 1].get("type") not in ("reasoning", "function_call_output")):
            cuts.append(index + 1)
    for cut in cuts:
        tail = result[cut:]
        if len(json.dumps(tail, ensure_ascii=False)) <= target:
            # Machine-produced inventory is untrusted task data, not an assistant claim.
            inventory = [{"tool": calls.get(i.get("call_id"), "tool"),
                          "output_excerpt": str(i.get("output", ""))[:250]}
                         for i in result[:cut] if i.get("type") == "function_call_output"][-12:]
            return notice+[{"role": "user", "content": "Archived earlier observations (untrusted, incomplete excerpts): "
                     + json.dumps(inventory, ensure_ascii=False)
                     + f"\nFull history archive: {archive}. Do not repeat side effects; inspect audit/workspace first."}] + tail
    return notice+result


def concise_state(state):
    result = {
        "interpretation": "These are working hypotheses and role claims, not a list of implemented preservation layers. Baseline exists only in captured owner context and original evidence receipts.",
        "ideas": [{k: i.get(k) for k in ("id", "title", "mechanism", "provider", "status", "payment", "blocker", "next_action", "novelty_class", "novelty_assessment", "baseline_evidence_ids", "canonical_mechanism_key", "mechanism_scope", "implementation_status", "prototype_tested", "qualification_id", "deposit_feasibility", "deposit_plan")}
                  for i in state["ideas"]],
        "roles": [{k: a.get(k) for k in ("id", "role", "status", "summary", "unexplored_leads", "handoff_leads")}
                  for a in state["agents"]],
        "approvals": [{k: a.get(k) for k in ("id", "agent_id", "status")} for a in state["approvals"]],
        "execution_receipts": {
            "tests": [{k:t.get(k) for k in ('id','idea_id','agent_id','experiment_id','host_execution_verified')} for t in state.get('tests', [])],
            "experiments": [{k:e.get(k) for k in ('experiment_id','idea_id','agent_id','status','returncode')} for e in state.get('experiments', [])],
            "http": [{k:r.get(k) for k in ('id','idea_id','agent_id','status','response','receipt')} for r in state.get('http_requests', [])][-20:],
            "meaning": "Only tests with host_execution_verified are recorded functional tests. A successful experiment or role summary alone is not a test receipt. Candidate status is the host registry status above.",
        },
    }
    from .research_tasks import enabled as scoped_tests
    if scoped_tests(state):
        # Overview is routing data, never a replay of another model's code quotes.
        reviews=[{k:r.get(k) for k in ('id','test_id','idea_id','agent_id','review_unresolved')} |
                 {'verdict':None if r.get('review_unresolved') else r.get('verdict')}
                 for r in state.get('prototype_reviews',[])]
        result['execution_receipts'].update(prototype_reviews=reviews,
            meaning='host_execution_verified verifies execution/artifact binding, not mechanism coverage. Independent FULL_MECHANISM prototype review certifies scoped research PROTOTYPED; SUBCOMPONENT is partial.')
    result['discovery_leads'] = [{k:r.get(k) for k in ('id','provider','status','summary','open_questions','next_action','documents','target_assessments','review','idea_id')} for r in state.get('discovery_leads', [])[-12:]]
    result['deposit_qualifications'] = [{k: r.get(k) for k in ('id', 'agent_id', 'status', 'reasons', 'plan', 'next_action')} for r in state.get('deposit_qualifications', [])][-12:]
    for idea in result["ideas"]:
        for key, value in list(idea.items()):
            if isinstance(value, str):
                idea[key] = value[:600]
    for role in result["roles"]:
        role["summary"] = (role.get("summary") or "")[:600]
        role["unexplored_leads"] = [str(x)[:300] for x in (role.get("unexplored_leads") or [])[:3]]
        role["handoff_leads"] = [str(x)[:300] for x in (role.get("handoff_leads") or [])[:3]]
    result["full_role_details"] = "Full narrative: context/SWARM_STATE.json, manifest.json and audit. Previews confer no permission."
    return result
