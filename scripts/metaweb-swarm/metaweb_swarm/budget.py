"""Durable pre-request reservations; callers hold/persist the engine mutex.

Bounds are local conservative limits, not a promise about the provider invoice.
USD enforcement assumes correct operator price ceilings including search/input
charges; text token bounds assume the selected model's text tokenization. Unknown
remote outcomes retain reservations across pause/resume and require reconciliation.
This module neither calls providers nor increments state['usage']; response hooks
must settle and account known usage atomically under the same host lock.
"""
import copy
import json
import re
from decimal import Decimal, InvalidOperation

from .storage import now
from .models import prices_for

PRICE_KEYS = ("input_price_per_million", "output_price_per_million", "web_search_price_per_call")
USAGE_KEYS = ("input_tokens", "output_tokens", "total_tokens", "web_search_calls")


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _money(value, name):
    if type(value) not in (str, int, float, Decimal) or isinstance(value, bool):
        raise ValueError(f"{name} must be a nonnegative finite amount")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError(f"Invalid {name}") from error
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"{name} must be a nonnegative finite amount")
    return amount


def _cost(usage, config):
    if any(config.get(k) is None for k in PRICE_KEYS):
        return None
    prices = [_money(config[k], k) for k in PRICE_KEYS]
    return (Decimal(usage.get("input_tokens", 0)) * prices[0] / 1_000_000
            + Decimal(usage.get("output_tokens", 0)) * prices[1] / 1_000_000
            + Decimal(usage.get("web_search_calls", 0)) * prices[2])


def conservative_input_tokens(system_prompt, input_items, tool_schemas, output_schema=None, overhead_tokens=4096):
    """UTF-8 byte bound for text plus message/schema framing headroom.

    Pass the actual post-SDK tool schemas and structured output schema, not tool
    names. No 4-chars-per-token heuristic. Binary/media inputs are refused because
    their provider token rules differ. Provider-internal retrieved search content
    is not present here: the caller must add its separately configured allowance
    before reserve(). Cache discounts are intentionally ignored.
    """
    _integer(overhead_tokens, "overhead_tokens")
    if not isinstance(system_prompt, str) or not isinstance(input_items, list) or not isinstance(tool_schemas, list):
        raise ValueError("Expected system prompt text, input item list and tool schema list")

    def inspect_media(value):
        if isinstance(value, dict):
            if value.get("type") in {"input_image", "image_url", "input_audio", "audio", "input_file", "file", "video"}:
                raise ValueError("Multimodal input needs an explicit model-specific token bound")
            for child in value.values():
                inspect_media(child)
        elif isinstance(value, list):
            for child in value:
                inspect_media(child)

    inspect_media(input_items)
    payload = json.dumps({"instructions": system_prompt, "input": input_items, "tools": tool_schemas,
                          "output_schema": output_schema}, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return len(payload.encode("utf-8")) + overhead_tokens + 32 * len(input_items) + 64 * len(tool_schemas)


def held_totals(state):
    reservations = state.get("budget_reservations", {})
    tokens = sum(_integer(r.get("total_upper_tokens"), "reservation tokens") for r in reservations.values())
    prices_known = all(r.get("usd_upper") is not None for r in reservations.values())
    usd = sum((_money(r["usd_upper"], "reservation USD") for r in reservations.values()), Decimal(0)) if prices_known else None
    return {"tokens": tokens, "usd": str(usd) if usd is not None else None,
            "reservations": len(reservations), "unknown": sum(r.get("status") == "UNKNOWN" for r in reservations.values())}


def reserve(state, agent_id, input_upper_tokens, output_upper_tokens, max_search_calls, model=None):
    """Return a reservation dict or a blocking reason string; no unsafe mutation.

    One in-flight provider request per agent. Request sequence numbers are durable
    and never reset at round boundaries, avoiding accidental overwrite on resume.
    The caller persists this object BEFORE it starts the remote request.
    """
    if not isinstance(agent_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", agent_id):
        raise ValueError("Invalid agent ID")
    _integer(input_upper_tokens, "input_upper_tokens")
    _integer(output_upper_tokens, "output_upper_tokens")
    _integer(max_search_calls, "max_search_calls")
    config, usage = state["config"], state.setdefault("usage", {})
    for key in USAGE_KEYS:
        _integer(usage.get(key, 0), key)
    current = state.get("budget_reservations", {})
    if any(r.get("status") == "UNKNOWN" for r in current.values()):
        return "HUMAN_BUDGET_RECONCILIATION_REQUIRED: unresolved provider request reservation"
    if usage.get("unknown_steps", 0):
        return "HUMAN_BUDGET_RECONCILIATION_REQUIRED: legacy unknown request usage"
    if any(r.get("agent_id") == agent_id for r in current.values()):
        return "ACTIVE_REQUEST_ALREADY_RESERVED"
    held = held_totals(state)
    total = input_upper_tokens + output_upper_tokens
    limit = _integer(config["max_total_tokens"], "max_total_tokens", 1)
    if usage.get("total_tokens", 0) + held["tokens"] + total > limit:
        return "MAX_TOTAL_TOKENS: insufficient capacity for complete request reservation"
    request_usage = {"input_tokens": input_upper_tokens, "output_tokens": output_upper_tokens,
                     "total_tokens": total, "web_search_calls": max_search_calls}
    model = model if model is not None else config.get("model")
    prices = prices_for(config, model)
    usd = _cost(request_usage, prices)
    budget = config.get("estimated_budget_usd")
    if budget is not None:
        if usd is None or held["usd"] is None:
            return "USD_PRICE_CEILINGS_REQUIRED"
        by_model = usage.get("by_model")
        if by_model and any(sum(u.get(k, 0) for u in by_model.values()) != usage.get(k, 0) for k in ("input_tokens", "output_tokens", "web_search_calls")):
            return "HUMAN_BUDGET_RECONCILIATION_REQUIRED: per-model usage does not match aggregate"
        costs = [_cost(u, prices_for(config, m)) for m, u in by_model.items()] if by_model else [
            _cost(usage, prices_for(config, config.get("model"))) if any(usage.get(k, 0) for k in ("input_tokens", "output_tokens", "web_search_calls")) else Decimal(0)]
        if any(c is None for c in costs):
            return "USD_PRICE_CEILINGS_REQUIRED"
        spent = sum(costs, Decimal(0))
        if spent + _money(held["usd"], "held USD") + usd > _money(budget, "estimated_budget_usd"):
            return "ESTIMATED_DOLLAR_BUDGET: insufficient capacity for complete request reservation"
    seq = state.get("budget_request_sequences", {}).get(agent_id, 0) + 1
    record = {"id": f"{agent_id}:{seq}", "agent_id": agent_id, "request_seq": seq,
              "status": "RESERVED", "created_at": now(), "input_upper_tokens": input_upper_tokens,
              "output_upper_tokens": output_upper_tokens, "total_upper_tokens": total,
              "max_search_calls": max_search_calls, "usd_upper": str(usd) if usd is not None else None,
              "price_ceilings": prices, "model": model}
    state.setdefault("budget_request_sequences", {})[agent_id] = seq
    state.setdefault("budget_reservations", {})[record["id"]] = record
    return copy.deepcopy(record)


def _find(state, agent_or_reservation):
    reservations = state.get("budget_reservations", {})
    if agent_or_reservation in reservations:
        return reservations[agent_or_reservation]
    found = [r for r in reservations.values() if r.get("agent_id") == agent_or_reservation]
    if len(found) != 1:
        raise ValueError("No unique active budget reservation")
    return found[0]


def mark_unknown(state, agent_or_reservation, reason):
    record = _find(state, agent_or_reservation)
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise ValueError("Unknown outcome needs a bounded reason")
    record.update(status="UNKNOWN", unknown_reason=reason, unknown_at=now())
    return copy.deepcopy(record)


def recover_unsettled(state):
    """At process startup, mark orphan in-flight requests unknown; never release."""
    records = []
    for record in state.get("budget_reservations", {}).values():
        if record.get("status") == "RESERVED":
            records.append(mark_unknown(state, record["id"], "Process ended before durable request settlement"))
    return records


def _known_usage(actual_usage):
    if not isinstance(actual_usage, dict) or actual_usage.get("usage_complete", True) is not True:
        raise ValueError("Provider usage is incomplete")
    values = {key: _integer(actual_usage.get(key), key) for key in USAGE_KEYS}
    if values["total_tokens"] != values["input_tokens"] + values["output_tokens"]:
        raise ValueError("Provider token usage is inconsistent")
    return values


def settle(state, agent_or_reservation, actual_usage):
    """Known response removes its reservation; unknown/breached responses retain it.

    Return the durable settlement record or reconciliation reason. Does NOT add
    usage counters: settle and the existing response accounting must be one atomic
    host transaction. A reservation recovered UNKNOWN cannot be auto-released.
    """
    record = _find(state, agent_or_reservation)
    if record.get("status") == "UNKNOWN":
        return "HUMAN_BUDGET_RECONCILIATION_REQUIRED"
    try:
        usage = _known_usage(actual_usage)
    except ValueError as error:
        mark_unknown(state, record["id"], str(error))
        return "HUMAN_BUDGET_RECONCILIATION_REQUIRED"
    bounds = {"input_tokens": record["input_upper_tokens"], "output_tokens": record["output_upper_tokens"],
              "total_tokens": record["total_upper_tokens"], "web_search_calls": record["max_search_calls"]}
    if any(usage[k] > bounds[k] for k in USAGE_KEYS):
        record["observed_usage"] = usage
        mark_unknown(state, record["id"], "Observed usage exceeded configured reservation bound")
        state.setdefault("budget_breaches", []).append({"id": record["id"], "usage": usage, "bounds": bounds, "time": now()})
        return "RESERVATION_BOUND_EXCEEDED: reconcile limits/pricing before another request"
    closed = dict(copy.deepcopy(record), status="SETTLED", settled_at=now(), actual_usage=usage)
    closed["actual_usd_at_reserved_prices"] = str(_cost(usage, record["price_ceilings"])) if record["usd_upper"] is not None else None
    state.setdefault("budget_settlements", {})[record["id"]] = closed
    del state["budget_reservations"][record["id"]]
    return copy.deepcopy(closed)


def reconcile(state, reservation_id, actual_usage, note):
    """Operator-only explicit reconciliation; caller updates usage/audit atomically.

    The CLI/operator must supply verified actual usage (including zero if certain
    no billable request happened). Preserve the original hold and note forever.
    Never expose this function as an LLM tool. The caller adjusts unknown_steps
    and only unaccounted usage; this function avoids silently double charging.
    """
    record = _find(state, reservation_id)
    if not isinstance(note, str) or not note.strip() or len(note) > 4000:
        raise ValueError("Operator reconciliation requires a note")
    usage = _known_usage(actual_usage)
    closed = dict(copy.deepcopy(record), status="RECONCILED", reconciled_at=now(), operator_note=note, actual_usage=usage)
    state.setdefault("budget_settlements", {})[record["id"]] = closed
    del state["budget_reservations"][record["id"]]
    return copy.deepcopy(closed)
