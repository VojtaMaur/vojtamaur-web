"""Deterministic policy gates. Prompts are guidance; capabilities are code."""
import hashlib
import math
import re
from urllib.parse import urlsplit
from .storage import canonical

IDEA_STATUSES = {"DISCOVERED", "INVESTIGATING", "VERIFIED", "PROTOTYPED", "BLOCKED", "REJECTED", "COMPLETED", "LIMIT_REACHED"}
AGENT_STATUSES = {"CONTINUE", "COMPLETED", "BLOCKED", "REJECTED", "LIMIT_REACHED"}
PAYMENTS = {"FREE", "ONE_TIME", "RECURRING", "UNKNOWN"}
ACTION_KINDS = {"PUBLISH", "ACCOUNT", "LEGAL", "ONE_TIME_PAYMENT", "MESSAGE", "PHYSICAL_ACTION", "PRODUCTION_CHANGE", "CREDENTIALS", "HUMAN_JUDGMENT"}


def text_field(data, key, maximum=8000, required=False):
    value = data.get(key, "")
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValueError(f"Invalid {key}")
    return value.strip()


def string_list(data, key, maximum=50):
    value = data.get(key, [])
    if not isinstance(value, list) or len(value) > maximum or any(not isinstance(x, str) or len(x) > 4000 for x in value):
        raise ValueError(f"Invalid {key}")
    return value


def normalize_idea(data):
    if str(data.get("provider", "")).strip().casefold() in {"metaweb research audit", "metaweb audit", "research audit"}:
        raise ValueError("A research audit is an observation, not a provider/mechanism. Use note.")
    result = {k: text_field(data, k, required=k in ("title", "mechanism", "summary")) for k in
              ("title", "mechanism", "provider", "summary", "novelty", "blocker", "next_action", "rejection_reason")}
    if re.search(r"no (?:novel|new) preservation mechanism|audit conclusion|evidence review only|^n/a|coverage baseline map|organizational gap analysis|not itself a preservation mechanism|role-gap observation|need for a .*specialist", result["title"] + " " + result["mechanism"], re.I):
        raise ValueError("General audit conclusions are observations: use note, not submit_idea. Submit a concrete preservation mechanism or improvement.")
    result["status"] = data.get("status", "DISCOVERED")
    result["payment"] = data.get("payment", "UNKNOWN")
    renewal = data.get("requires_ongoing_payments")
    if renewal is not None and type(renewal) is not bool:
        raise ValueError("requires_ongoing_payments must be boolean or null")
    result["requires_ongoing_payments"] = renewal
    if renewal:
        result["payment"] = "RECURRING"
    if result["status"] not in IDEA_STATUSES or result["payment"] not in PAYMENTS:
        raise ValueError("Unknown idea status or payment category")
    result["failure_domains"] = string_list(data, "failure_domains")
    result["artifacts"] = string_list(data, "artifacts")
    result["mechanism_kind"] = data.get("mechanism_kind", "OTHER")
    result["novelty_class"] = data.get("novelty_class", "UNASSESSED")
    if result["mechanism_kind"] not in {"REPOSITORY_SNAPSHOT", "REGISTRATION", "SOURCE_ARCHIVE", "RECOVERY_FORMAT", "DISTRIBUTION", "OTHER"} or result["novelty_class"] not in {"UNASSESSED", "POTENTIALLY_NEW", "KNOWN_CARRIER", "IMPROVEMENT", "DUPLICATE"}:
        raise ValueError("Invalid mechanism_kind or novelty_class")
    result["baseline_evidence_ids"] = string_list(data, "baseline_evidence_ids")
    result["novelty_delta"] = text_field(data, "novelty_delta")
    for field in ("baseline_behavior", "proposed_change", "validation_plan"):
        result[field] = text_field(data, field)
    result["mechanism_key"] = text_field(data, "mechanism_key", 160)
    result["mechanism_scope"] = text_field(data, "mechanism_scope", 160)
    if result["novelty_class"] == "IMPROVEMENT" and not result["novelty_delta"]:
        raise ValueError("IMPROVEMENT needs an explicit novelty_delta beyond the known layer")
    evidence = data.get("evidence", [])
    if not isinstance(evidence, list) or len(evidence) > 40:
        raise ValueError("Invalid evidence")
    result["evidence"] = []
    for source in evidence:
        url = text_field(source, "url", 2000, True)
        parsed = urlsplit(url)
        if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Evidence must use public HTTP(S) URLs without credentials")
        result["evidence"].append({"url": url, "claim": text_field(source, "claim", 8000, True),
                                   "verified": source.get("verified") is True, "verification_author": "agent claim"})
    scores = data.get("scores", {})
    if not isinstance(scores, dict) or len(scores) > 15:
        raise ValueError("Invalid scores")
    result["scores"] = {}
    for key, value in scores.items():
        if not isinstance(key, str) or len(key) > 80 or type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 10:
            raise ValueError("Scores must be finite values from 0 to 10")
        result["scores"][key] = value
    result["policy_notes"] = []
    combined = " ".join(result[k] for k in ("title", "mechanism", "provider")).lower()
    if re.search(r"\b(piql(?:film)?|arctic world archive|awa)\b", combined):
        result.update(status="REJECTED", rejection_reason="DUPLICATE_KNOWN: PiqlFilm / Arctic World Archive production already in progress per owner (2026-10-06).")
        result["policy_notes"].append("Piql/AWA is existing work, not a new discovery; improvements may be recorded separately as explicitly scoped follow-ups.")
    elif result["payment"] == "RECURRING":
        result.update(status="REJECTED", rejection_reason="RECURRING_PAYMENT: this provider depends on recurring payments.")
        result["policy_notes"].append("Reject this provider variant only. Investigate free or one-time implementations of the underlying mechanism.")
    elif result["payment"] == "UNKNOWN" and result["status"] in {"VERIFIED", "COMPLETED", "PROTOTYPED"}:
        result.update(status="BLOCKED", blocker="PRICING_UNVERIFIED")
        result["policy_notes"].append("Payment independence must be verified before recommendation.")
    if result["status"] == "COMPLETED":
        result.update(status="BLOCKED", blocker="EXTERNAL_COMPLETION_RECEIPT_MISSING")
        result["policy_notes"].append("COMPLETED requires a host-verified deposit receipt; model claims cannot certify an implementation.")
    if result["status"] == "BLOCKED" and not result["blocker"]:
        raise ValueError("BLOCKED requires a concrete blocker")
    if result["status"] == "REJECTED" and not result["rejection_reason"]:
        raise ValueError("REJECTED requires a reason")
    if result["status"] == "VERIFIED" and not result["evidence"]:
        result.update(status="INVESTIGATING")
        result["policy_notes"].append("No cited evidence; verified status downgraded.")
    if result["payment"] == "ONE_TIME":
        result["policy_notes"].append("One-time payment is admissible; execution follows operator approval policy and available payment capabilities.")
    result["fingerprint"] = hashlib.sha256(canonical([result["mechanism"].casefold(), result["provider"].casefold(), result["title"].casefold()]).encode()).hexdigest()
    return result


def normalize_output(data, *, synthesis=False):
    if not isinstance(data, dict) or data.get("status") not in AGENT_STATUSES:
        raise ValueError("Agent must return a structured stopping decision")
    result = {"status": data["status"], "reason_for_stopping": text_field(data, "reason_for_stopping", required=True),
              "summary": text_field(data, "summary"), "unexplored_leads": string_list(data, "unexplored_leads"),
              "blind_spots": string_list(data, "blind_spots")}
    result["handoff_leads"] = string_list(data, "handoff_leads")
    if synthesis and result['status'] == 'COMPLETED':
        # A finished report can describe unfinished research without reopening
        # its read-only reporting assignment. Preserve that text for handoff.
        result['handoff_leads'] = list(dict.fromkeys(result['handoff_leads'] + result['unexplored_leads']))
        result['unexplored_leads'] = []
    if result["status"] == "COMPLETED" and result["unexplored_leads"]:
        result.update(status="CONTINUE", reason_for_stopping="Unexplored leads remain; scheduler requires another bounded round.")
    return result


def normalize_action(data):
    kind = data.get("kind")
    if kind not in ACTION_KINDS:
        raise ValueError(f"Unknown action kind; choose one of {sorted(ACTION_KINDS)}")
    payload = data.get("payload", {})
    if not isinstance(payload, dict) or len(canonical(payload)) > 16000:
        raise ValueError("Invalid action payload")
    return {"idea_id": text_field(data, "idea_id", 80), "kind": kind,
            "description": text_field(data, "description", required=True), "target": text_field(data, "target", 2000, True),
            "payload": payload}


def action_hash(action):
    return hashlib.sha256(canonical(action).encode()).hexdigest()


def spawn_verdict(request, parent, agents, config):
    fields = {key: text_field(request, key, required=True) for key in
              ("role", "mission", "reason", "unique_expertise", "question", "expected_output")}
    if len(agents) >= config["max_agents"]:
        return fields, "MAX_AGENTS"
    if parent["depth"] >= config["max_depth"]:
        return fields, "MAX_DEPTH"
    if sum(a["parent_id"] == parent["id"] for a in agents) >= config["max_descendants"]:
        return fields, "MAX_DESCENDANTS"
    role_words = set(re.findall(r"\w+", fields["role"].casefold()))
    for agent in agents:
        existing = set(re.findall(r"\w+", agent["role"].casefold()))
        union = existing | role_words
        if union and len(existing & role_words) / len(union) > 0.7:
            return fields, f"OVERLAP_ROLE:{agent['id']}"
        if fields["mission"].casefold() == agent["mission"].casefold():
            return fields, f"OVERLAP_MISSION:{agent['id']}"
    return fields, None
