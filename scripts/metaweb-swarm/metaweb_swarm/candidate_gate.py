"""Run-local comparison contracts. No history lookup, inference or filesystem I/O."""
import hashlib
from .storage import canonical

FIELDS = ("id", "title", "provider", "mechanism", "mechanism_key", "mechanism_scope", "validation_plan")


def certain_match(ideas, candidate):
    from .dedup import resolve, identity
    found = resolve(ideas, candidate)
    if found is not None and (identity(candidate) or '').startswith('v1:explicit:'):
        fingerprints = set(found.get('fingerprints', [])) | {found.get('fingerprint')}
        # Unknown agent-supplied family labels are hints, not semantic proof.
        if candidate.get('fingerprint') not in fingerprints:
            return None
    return found


def projection(idea):
    # Never hide a material difference at the end of a mechanism description.
    # The caller caps the whole request and defers oversized comparisons.
    return {key: str(idea.get(key, "")) for key in FIELDS}


def digest(ideas):
    return hashlib.sha256(canonical([projection(i) for i in ideas]).encode()).hexdigest()


def comparison_request(candidate, ideas):
    return {"candidate": projection(candidate), "current_run_candidates": [projection(i) for i in ideas],
            "candidate_digest": digest([candidate]), "registry_digest": digest(ideas)}


def validate_decision(decision, candidate, ideas):
    if not isinstance(decision, dict) or decision.get("candidate_digest") != digest([candidate]) or decision.get("registry_digest") != digest(ideas):
        raise ValueError("Candidate comparison expired; retry against current run registry")
    verdict = decision.get("verdict")
    reason = decision.get("reason", "")
    if verdict not in {"SAME", "DISTINCT", "UNCERTAIN"} or not isinstance(reason, str) or not 5 <= len(reason) <= 2400:
        raise ValueError("Invalid candidate comparison decision")
    target = decision.get("existing_id", "")
    if verdict == "SAME":
        found = next((i for i in ideas if i["id"] == target), None)
        if found is None:
            raise ValueError("Comparison refers to unknown current-run IDEA")
        return found
    if target:
        raise ValueError("Only SAME may choose an existing IDEA ID")
    return None
