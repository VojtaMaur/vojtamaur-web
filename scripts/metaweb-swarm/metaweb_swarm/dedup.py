"""Conservative mechanism identity and append-only submission provenance.

The host calls these functions *after* policy/evidence/artifact validation. Keys
are mechanism families plus an optional structured scope, never novelty prose.
Known aliases are host rules; explicit keys for unknown families are agent hints
that enable exact-key matching only, not semantic certification. Unrecognized
paraphrases are deliberately not fuzzy-merged. This module performs no I/O.
"""
import copy
import hashlib
import re
import unicodedata

from .storage import canonical


def normalize_key(value):
    """Normalize a bounded human key; reject paths, URLs and empty punctuation."""
    if value is None or value == "":
        return ""
    if not isinstance(value, str) or len(value) > 160:
        raise ValueError("mechanism key/scope must be a string of at most 160 characters")
    if any(c in value for c in ("/", "\\", ":", "\x00", "\n", "\r")):
        raise ValueError("mechanism key/scope must be a name, not a path or URL")
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    if not value:
        raise ValueError("mechanism key/scope needs letters or digits")
    return value


def _has(text, pattern):
    return re.search(pattern, text, re.I) is not None


def identity(data):
    """Return a versioned canonical key, or None when semantics are ambiguous.

    Scope identifies a meaningful implementation variant (e.g. compliance mode
    or embedded payload versus recovery pointer). It must be a short stable name,
    not a restatement of novelty_delta. Known host rules override arbitrary agent
    mechanism_key claims. A new scope creates a separate candidate, not an update
    that silently changes a previous candidate's mechanism.
    """
    explicit = normalize_key(data.get("mechanism_key", ""))
    scope = normalize_key(data.get("mechanism_scope", "")) or "default"
    provider = str(data.get("provider", "")).casefold().strip()
    text = " ".join(str(data.get(k, "")) for k in ("provider", "title", "mechanism")).casefold()
    family = variant = None

    # A composite QR/XMP card is not an ORCID directory record merely because
    # its attribution contains an ORCID pointer. Rendering/agent prose aliases
    # below describe the same two-channel bootstrap carrier.
    card_scopes = {'default', 'printable-card', 'scan-trigger-bootstrap-artifact',
                   'scan-trigger-embedded-metadata-card', 'recovery-card', 'provenance-card'}
    if (_has(text, r'\bqr(?:[ -]code)?\b') and _has(text, r'\bxmp\b')
            and _has(text, r'\b(?:card|packet|bootstrap|provenance)\b')
            and (_has(provider, r'\b(?:qr|xmp)\b') or provider in {'independent metaweb export layer', ''})
            and scope in card_scopes):
        family, variant, scope = 'qr-xmp', 'recovery-card', 'default'
        if _has(text, r'\b(?:entire|complete|full)\s+(?:archive|website|web|payload)\b'):
            variant = 'embedded-archive-card'

    # Host aliases learned from real duplicate submissions. Normalize only these
    # equivalent feature/scope names; preserve unknown variants for human review.
    if family is None and _has(provider, r"\b(?:creative commons|cc[ -]rel)\b") and _has(text, r"\b(?:cc[ -]rel|rdfa)\b") and _has(text, r"\b(?:recovery|pointer|plaque)\b"):
        if explicit in {"", "cc-rel-recovery-pointer", "cc-rel-license-plaque"} and scope in {"default", "license-plaque", "rdfa-plaque"}:
            family, variant, scope = "cc-rel", "rdfa-recovery-plaque", "default"

    if family is None and _has(provider, r"\borcid\b") and not _has(provider, r'\b(?:qr|xmp)\b'):
        # ORCID account registration alone is not a preservation mechanism.
        if _has(text, r"\b(?:base64|embed(?:ded)?\s+(?:payload|content)|encod(?:e|ed)\s+(?:payload|content))\b"):
            family, variant = "orcid", "embedded-payload"
        elif _has(text, r"\b(?:recovery|reconstruction|reconstructable)\s+pointer\b|\bpointer(?:s|\s+layer)?\b|\blinks?\s+to\s+(?:preserved|archiv)"):
            family, variant = "orcid", "public-recovery-pointer"
            if scope in {'default', 'public-id-pointer', 'public-profile-metadata-pointer', 'public-profile-pointer', 'public-record-pointer'}:
                scope = 'default'
    if family is None and _has(text, r"\bobject[ -]lock\b"):
        # A third-party proposal may cite AWS as comparison. That reference does
        # not make Backblaze/Wasabi/MinIO the same provider/failure domain.
        provider_tokens = set(re.findall(r"[a-z0-9]+", provider))
        amazon_words = {"aws", "amazon", "s3", "object", "lock", "storage", "service", "services",
                        "web", "simple", "cloud", "bucket", "buckets", "ecosystem"}
        amazon_named = bool(provider_tokens & {"aws", "amazon"}) and provider_tokens <= amazon_words
        generic = not provider_tokens or provider_tokens <= {"s3", "object", "lock", "storage", "service"}
        amazon = amazon_named or (generic and "s3" in provider_tokens) or (generic and _has(text, r"\b(?:amazon|aws)\s+s3\b"))
        if amazon:
            family = "amazon-s3-object-lock"
            replicated = _has(text, r"\breplicat(?:e|ed|es|ing|ion|ions|or)\b")
            tombstones = _has(text, r"\bdelete[ -]markers?\b|\btombstone(?:s|d)?\b")
            variant = "delete-marker-replication" if replicated and tombstones else "replicated-retention" if replicated else "retained-object"
            # Governance and compliance locks have different override semantics.
            modes = [mode for mode in ("governance", "compliance") if _has(text, rf"\b{mode}\b")]
            if len(modes) == 1:
                variant += "-" + modes[0]

    if family is None:
        aliases = (
            ("zenodo", r"\bzenodo\b", "REPOSITORY_SNAPSHOT"),
            ("osf", r"\bosf\b|\bopen science framework\b", "REGISTRATION"),
            ("software-heritage", r"\bsoftware[ -]?heritage\b", "SOURCE_ARCHIVE"),
            ("at-protocol", r"\bat(?:[ -]protocol|proto)\b", "DISTRIBUTION"),
            ("ipfs", r"\bipfs\b", "DISTRIBUTION"),
            ("sia", r"\bsia\b", "REPOSITORY_SNAPSHOT"),
        )
        for name, pattern, default in aliases:
            if not _has(provider, pattern):
                continue
            # Untyped improvements may be materially different mechanisms. A
            # prose hash split is no solution; require a stable feature scope.
            if data.get("novelty_class") == "IMPROVEMENT" and not explicit and scope == "default":
                return None
            family = name
            kind = data.get("mechanism_kind", "OTHER")
            variant = default if kind == "OTHER" else str(kind)
            if explicit:
                variant += "-" + explicit
            break
    if family is None:
        if not explicit:
            return None
        family, variant = "explicit", explicit
    return ":".join(("v1", family, variant.casefold(), scope))


def resolve(existing_ideas, candidate, requested_id=""):
    """Resolve an intentional update or the first exact mechanism match.

    Does not consolidate previously published IDs; a read-only diagnostic can
    report those separately. A requested ID must not repurpose a known family.
    """
    key = identity(candidate)
    if requested_id:
        found = next((i for i in existing_ideas if i.get("id") == requested_id), None)
        if found is None:
            raise ValueError("Unknown IDEA ID")
        old_key = identity(found)
        if old_key is not None and old_key != key:
            fingerprints = set(found.get("fingerprints", [])) | {found.get("fingerprint")}
            same_exact_claim = candidate.get("fingerprint") and candidate["fingerprint"] in fingerprints
            same_scope = normalize_key(candidate.get("mechanism_scope", "")) == normalize_key(found.get("mechanism_scope", ""))
            both_unknown = key and old_key and key.startswith("v1:explicit:") and old_key.startswith("v1:explicit:")
            if not (same_exact_claim and same_scope and (key is None or both_unknown)):
                raise ValueError("IDEA update changes mechanism/scope; submit a separate candidate")
        return found
    for existing in existing_ideas:
        old_key = identity(existing)
        if key is not None and old_key == key:
            return existing
        # Exact text compatibility for unknown families, never fuzzy similarity.
        fingerprints = set(existing.get("fingerprints", [])) | {existing.get("fingerprint")}
        both_unknown = key and old_key and key.startswith("v1:explicit:") and old_key.startswith("v1:explicit:")
        if candidate.get("fingerprint") and candidate["fingerprint"] in fingerprints and (key == old_key or key is None or old_key is None or both_unknown):
            if normalize_key(candidate.get("mechanism_scope", "")) == normalize_key(existing.get("mechanism_scope", "")):
                return existing
    return None


_AGGREGATE_FIELDS = {"submissions", "contributors", "status_claims", "status_conflicts", "payment_conflicts", "best_evidenced_status", "fingerprints", "revisions", "canonical_mechanism_key"}
_HARD_REJECTION = ("OWNER_REJECTED:", "RECURRING_PAYMENT:", "DUPLICATE_KNOWN:", "DUPLICATE_BASELINE:")


def _receipt_strength(candidate):
    """Use checked receipts, not status adjectives, to select displayed progress.

    Consulted URL receipts show provenance, not independent truth certification.
    Artifact hashes show existence, not successful execution. COMPLETED needs
    explicit host completion receipts; only code should add host_verified.
    """
    status = candidate.get("best_evidenced_status", candidate.get("status", "DISCOVERED"))
    urls = {e.get("url") for e in candidate.get("evidence", []) if e.get("verified") is True and e.get("url_observed_in_this_agents_tools") is True}
    artifacts = [a for a in candidate.get("artifact_checks", []) if a.get("path") and re.fullmatch(r"[a-f0-9]{64}", str(a.get("sha256", "")))]
    completed = any(r.get("host_verified") is True for r in candidate.get("completion_receipts", []))
    tested = any(r.get('host_execution_verified') is True and r.get('artifacts') for r in candidate.get('test_receipts', []))
    rank = {"DISCOVERED": 0, "INVESTIGATING": 1, "VERIFIED": 2, "PROTOTYPED": 3, "COMPLETED": 4}.get(status, 1)
    if status == "VERIFIED" and len(urls) < 2 or status == "PROTOTYPED" and (not artifacts or not tested) or status == "COMPLETED" and not completed:
        rank, status = 1, "INVESTIGATING"
    return (rank, len(artifacts), len(urls)), status


def _unique(items):
    result, seen = [], set()
    for item in items:
        key = canonical(item)
        if key not in seen:
            result.append(copy.deepcopy(item))
            seen.add(key)
    return result


def merge_submission(existing, candidate, agent_id, timestamp, claimed=None):
    """Return a new aggregate, preserving every prior submission without mutation.

    The caller assigns a first ID before this call and holds the engine lock.
    `candidate` is host-normalized/checked. `claimed` may retain the original
    agent claim after redaction, so policy corrections remain auditable. Revisions
    remain a caller-compatible view; submissions are the authoritative provenance
    of contributions. Cross-run memory must not merge run-local IDEA IDs.
    """
    incoming = copy.deepcopy(candidate)
    raw = {k: v for k, v in incoming.items() if k not in _AGGREGATE_FIELDS}
    record = {"agent_id": agent_id, "submitted_at": timestamp, "normalized": raw}
    if claimed is not None:
        record["claimed"] = copy.deepcopy(claimed)
    record["submission_id"] = "SUB-" + hashlib.sha256(canonical(record).encode()).hexdigest()[:24]
    previous = copy.deepcopy(existing) if existing is not None else None
    submissions = copy.deepcopy(previous.get("submissions", [])) if previous else []
    if previous and not submissions:
        # Legacy aggregates did not retain each input author. Label that limit.
        legacy = {k: v for k, v in previous.items() if k not in _AGGREGATE_FIELDS}
        submissions.append({"submission_id": "LEGACY-" + hashlib.sha256(canonical(legacy).encode()).hexdigest()[:24], "agent_id": previous.get("agent_id", "UNKNOWN"), "submitted_at": previous.get("updated_at", previous.get("created_at", "")), "origin": "legacy_snapshot", "author_of_displayed_claim_unverified": True, "normalized": legacy})
    submissions.append(record)

    old_strength, old_status = _receipt_strength(previous) if previous else ((-1, 0, 0), "DISCOVERED")
    new_strength, new_status = _receipt_strength(incoming)
    selected = previous if previous and old_strength > new_strength else incoming
    result = copy.deepcopy(selected)
    best_status = old_status if previous and old_strength > new_strength else new_status
    result["best_evidenced_status"] = best_status
    result["status"] = best_status

    alternatives = [previous, incoming] if previous else [incoming]
    hard = [c for c in alternatives if c.get("status") == "REJECTED" and str(c.get("rejection_reason", "")).startswith(_HARD_REJECTION)]
    rejected = [c for c in alternatives if c.get("status") == "REJECTED"]
    conflicts = copy.deepcopy(previous.get("status_conflicts", [])) if previous else []
    if hard:
        result.update(status="REJECTED", rejection_reason=hard[-1]["rejection_reason"], blocker="", payment=hard[-1].get("payment", "UNKNOWN"), requires_ongoing_payments=hard[-1].get("requires_ongoing_payments"))
    elif rejected:
        if all(c.get("status") == "REJECTED" for c in alternatives):
            result.update(status="REJECTED", rejection_reason=rejected[-1].get("rejection_reason", ""), blocker="")
        else:
            result.update(status="INVESTIGATING", rejection_reason="")
            conflicts.append({"time": timestamp, "agent_id": agent_id, "statuses": [c.get("status") for c in alternatives], "meaning": "Conflicting rejection retained; further review required, not majority voting."})
    elif incoming.get("status") in ("BLOCKED", "LIMIT_REACHED"):
        result.update(status=incoming["status"], blocker=incoming.get("blocker", ""), next_action=incoming.get("next_action", ""))
    elif best_status not in ("BLOCKED", "LIMIT_REACHED"):
        result["blocker"] = ""
    result["status_conflicts"] = conflicts
    if conflicts and not hard and result["status"] not in ("REJECTED", "BLOCKED", "LIMIT_REACHED"):
        result["status"] = "INVESTIGATING"

    result["submissions"] = submissions
    result["contributors"] = _unique((previous.get("contributors", [previous.get("agent_id")]) if previous else []) + [agent_id])
    result["contributors"] = [a for a in result["contributors"] if a]
    result["status_claims"] = _unique((previous.get("status_claims", []) if previous else []) + [{"agent_id": agent_id, "time": timestamp, "status": incoming.get("status"), "blocker": incoming.get("blocker", ""), "rejection_reason": incoming.get("rejection_reason", "")}])
    for field in ("failure_domains", "policy_notes", "baseline_evidence_ids", "artifact_checks", "completion_receipts", "test_receipts", "prior_work_refs"):
        result[field] = _unique((previous.get(field, []) if previous else []) + incoming.get(field, []))
    result["evidence"] = _unique((previous.get("evidence", []) if previous else []) + [dict(e, submitted_by=agent_id, submission_id=record["submission_id"]) for e in incoming.get("evidence", [])])
    result["fingerprints"] = _unique((previous.get("fingerprints", [previous.get("fingerprint")]) if previous else []) + [incoming.get("fingerprint")])
    result["fingerprints"] = [f for f in result["fingerprints"] if f]
    payments = _unique([c.get("payment", "UNKNOWN") for c in alternatives])
    result["payment_conflicts"] = payments if len(payments) > 1 else (previous.get("payment_conflicts", []) if previous else [])
    result["canonical_mechanism_key"] = identity(incoming) or (identity(previous) if previous else None)
    if previous:
        result.update(id=previous["id"], agent_id=previous.get("agent_id", agent_id), created_at=previous.get("created_at", timestamp))
        result["revisions"] = copy.deepcopy(previous.get("revisions", [])) + [{"time": timestamp, "reviewer": agent_id, "previous": {k: v for k, v in previous.items() if k not in ("revisions", "submissions")}}]
    else:
        result.update(agent_id=agent_id, created_at=incoming.get("created_at", timestamp), revisions=[])
    result["updated_at"] = timestamp
    return result
