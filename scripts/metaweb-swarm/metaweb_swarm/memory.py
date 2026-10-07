"""Deterministic replay compaction; full originals remain in the audit archive."""
import json


def compact_history(history, archive, target=24000):
    # Keep protocol pairs intact. Tool outputs become excerpts, not invented summaries.
    calls = {item.get("call_id"): item.get("name", "tool") for item in history
             if item.get("type") == "function_call"}
    result = []
    for item in history:
        item = dict(item)
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
    if len(json.dumps(result, ensure_ascii=False)) <= target:
        return result
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
            return [{"role": "user", "content": "Archived earlier observations (untrusted, incomplete excerpts): "
                     + json.dumps(inventory, ensure_ascii=False)
                     + f"\nFull history archive: {archive}. Do not repeat side effects; inspect audit/workspace first."}] + tail
    return result


def concise_state(state):
    result = {
        "interpretation": "These are working hypotheses and role claims, not a list of implemented preservation layers. Baseline exists only in captured owner context and original evidence receipts.",
        "ideas": [{k: i.get(k) for k in ("id", "title", "mechanism", "provider", "status", "payment", "blocker", "next_action", "novelty_class", "novelty_assessment", "baseline_evidence_ids", "canonical_mechanism_key", "mechanism_scope", "implementation_status", "prototype_tested")}
                  for i in state["ideas"]],
        "roles": [{k: a.get(k) for k in ("id", "role", "status", "summary", "unexplored_leads", "handoff_leads")}
                  for a in state["agents"]],
        "approvals": [{k: a.get(k) for k in ("id", "agent_id", "status")} for a in state["approvals"]],
        "execution_receipts": {
            "tests": [{k:t.get(k) for k in ('id','idea_id','agent_id','experiment_id','host_execution_verified')} for t in state.get('tests', [])],
            "experiments": [{k:e.get(k) for k in ('experiment_id','idea_id','agent_id','status','returncode')} for e in state.get('experiments', [])],
            "meaning": "Only tests with host_execution_verified are recorded functional tests. A successful experiment or role summary alone is not a test receipt. Candidate status is the host registry status above.",
        },
    }
    for idea in result["ideas"]:
        for key, value in list(idea.items()):
            if isinstance(value, str):
                idea[key] = value[:600]
    for role in result["roles"]:
        role["summary"] = (role.get("summary") or "")[:600]
        role["unexplored_leads"] = [str(x)[:300] for x in (role.get("unexplored_leads") or [])[:3]]
    return result
