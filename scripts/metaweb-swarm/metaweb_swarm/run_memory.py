"""Small, derived cross-run notes. Prior agent claims never become baseline facts.

Historical ledgers are read without opening Store (which would mutate them). The
index and Markdown are disposable views; each run's SQLite ledger is authoritative.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from .context import redact_text
from .workspace import _atomic_write, _confined, _plain_absolute, _read_bytes

STOPPED = {"COMPLETED", "BLOCKED", "LIMIT_REACHED", "REJECTED", "FAILED"}
NOTICE = ("UNTRUSTED PRIOR RESEARCH, NOT IMPLEMENTED METAWEB BASELINE. These notes are "
          "derived from stopped runs. Candidate names and conclusions are agent claims; "
          "do not rediscover or reverify unchanged mechanisms. Continue only a concrete "
          "unfinished test, changed capability or material improvement. Failed, rejected, untested and "
          "tested artifacts are distinct. Original run ledgers remain authoritative.")


def _short(value, limit=140):
    if not isinstance(value, str):
        return ""
    value = " ".join(redact_text(value).split())
    return value[:limit] + ("…" if len(value) > limit else "")


def _load_state(run_dir: Path, max_state_bytes: int):
    """Read a closed SQLite database, or a bounded checkpoint projection.

    immutable=1 guarantees SQLite creates neither journals nor shared-memory
    files. It cannot see a live WAL, so a WAL-bearing run uses its checkpoint
    projection and records that weaker source explicitly.
    """
    database = _confined(run_dir, "state.sqlite3")
    wal = _confined(run_dir, "state.sqlite3-wal")
    errors = []
    if database.is_file() and not (wal.exists() and wal.stat().st_size):
        connection = None
        try:
            connection = sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)
            connection.execute("PRAGMA query_only=ON")
            row = connection.execute("SELECT length(CAST(body AS BLOB)) FROM state WHERE id=1").fetchone()
            if row and row[0] <= max_state_bytes:
                body = connection.execute("SELECT body FROM state WHERE id=1").fetchone()[0]
                state = json.loads(body)
                if isinstance(state, dict) and state.get("schema_version") == 1:
                    return state, "sqlite_read_only", hashlib.sha256(body.encode("utf-8")).hexdigest()
            errors.append("Missing, oversized or unsupported SQLite state")
        except (OSError, sqlite3.Error, ValueError):
            errors.append("SQLite state could not be read")
        finally:
            if connection:
                connection.close()
    checkpoint = _confined(run_dir, "checkpoint.json")
    if checkpoint.is_file():
        body = _read_bytes(run_dir, Path("checkpoint.json"), max_state_bytes)
        state = json.loads(body.decode("utf-8-sig"))
        if not isinstance(state, dict) or state.get("schema_version") != 1:
            raise ValueError("Unsupported checkpoint state")
        return state, "checkpoint_projection_not_authoritative", hashlib.sha256(body).hexdigest()
    raise ValueError("No readable state snapshot" + (": " + "; ".join(errors) if errors else ""))


def summarize_run(state: dict, run_id: str, source: str, source_sha256: str):
    """One short sentence based on recorded states, with no inferred deployment."""
    ideas = [item for item in state.get("ideas", []) if isinstance(item, dict)]
    agents = [item for item in state.get("agents", []) if isinstance(item, dict)]
    statuses = Counter(str(item.get("status", "UNKNOWN")) for item in ideas)
    checked = sum(bool(item.get("artifact_checks")) for item in ideas)
    tested = sum(item.get("prototype_tested") is True and bool(item.get("artifact_checks")) for item in ideas)
    # COMPLETED alone is a model claim, not a deposition receipt.
    deposits = sum(isinstance(item, dict) and (
                   item.get("status") == "VERIFIED" and isinstance(item.get("receipt"), dict)
                   and item["receipt"].get("host_verified") is True
                   or item.get("status") == "COMPLETED" and isinstance(item.get("result"), dict)
                   and item["result"].get("verified") is True)
                   for item in state.get("external_actions", []))
    failed_agents = sum(item.get("status") in {"FAILED", "BLOCKED"} for item in agents)
    subjects = []
    for item in ideas:
        title = _short(item.get("title", ""), 64)
        if title:
            title += " [" + _short(str(item.get("status", "UNKNOWN")), 20) + "]"
        if title and title not in subjects:
            subjects.append(title)
        if len(subjects) == 3:
            break
    summary = (f"{_short(run_id, 100)}: stopped {state['status']}; {len(ideas)} candidates, "
               f"{statuses['REJECTED']} rejected, {statuses['BLOCKED']} blocked, "
               f"{failed_agents} blocked/failed agents; local artifacts {checked} checked, "
               f"{tested} tested, {checked - tested} untested; {deposits} verified external receipts")
    if subjects:
        summary += "; investigated " + ", ".join(subjects)
    summary += "."
    return {"run_id": run_id, "status": state["status"], "updated_at": _short(state.get("updated_at", ""), 40),
            "source": source, "source_sha256": source_sha256, "summary": summary,
            "counts": {"candidates": len(ideas), "rejected": statuses["REJECTED"], "blocked": statuses["BLOCKED"],
                       "checked_artifacts": checked, "tested_artifacts": tested,
                       "untested_artifacts": checked - tested, "verified_external_receipts": deposits},
            "trust": "prior_run_claims_not_implemented_baseline",
            "candidates": [_candidate(item, run_id) for item in ideas[:64]]}


def _candidate(item, run_id):
    from .dedup import identity
    try:
        key = identity(item)
    except ValueError:
        key = None
    fields = {k: _short(item.get(k, ''), 450 if k == 'mechanism' else 160)
              for k in ('id', 'title', 'provider', 'mechanism', 'mechanism_key', 'mechanism_scope', 'status', 'blocker', 'next_action')}
    return {**fields, 'ref': run_id + '/' + fields['id'], 'run_id': run_id,
            'canonical_key': key, 'artifact_count': len(item['artifact_checks']) if isinstance(item.get('artifact_checks'), list) else 0,
            'tested_claim': item.get('prototype_tested') is True,
            'evidence_urls': [_short(e['url'], 400) for e in (item.get('evidence') or []) if isinstance(e, dict) and isinstance(e.get('url'), str)][:4]}


def prior_candidates(memory):
    """Bounded mechanism inventory: all candidates, not just first three titles."""
    return [c for entry in memory.get('entries', []) if isinstance(entry, dict)
            for c in entry.get('candidates', []) if isinstance(c, dict)][:200]


def matching_prior(candidates, idea):
    from .dedup import identity
    key = identity(idea)
    title = _short(idea.get('title', ''), 160).casefold()
    return [c for c in candidates if (key and c.get('canonical_key') == key)
            or (not key and title and c.get('title', '').casefold() == title
                and c.get('provider', '').casefold() == str(idea.get('provider', '')).casefold())][:8]


def search_prior(candidates, terms):
    if not isinstance(terms, list) or not 1 <= len(terms) <= 8 or any(not isinstance(t, str) or not 1 <= len(t.strip()) <= 160 for t in terms):
        raise ValueError('Choose 1..8 prior mechanism/provider terms')
    matches = [c for c in candidates if any(t.casefold().strip() in ' '.join(str(c.get(k, '')) for k in
                ('provider', 'title', 'mechanism', 'mechanism_key', 'canonical_key')).casefold() for t in terms)]
    return {'matches': matches[:8], 'total_matches': len(matches),
            'meaning': 'Previously explored research, NOT implemented baseline or rejection. Discovery must move elsewhere; continuation needs an explicit unfinished task.'}


def prior_brief(candidates, limit=1800):
    counts = Counter(c.get('canonical_key') or c.get('title') for c in candidates)
    lines = ['PRIOR WORK: do not propose these again as discoveries. Read check_prior_work for specific unfinished work.']
    seen = set()
    for item in sorted(candidates, key=lambda c: counts[c.get('canonical_key') or c.get('title')], reverse=True):
        key = item.get('canonical_key') or item.get('title')
        if key in seen:
            continue
        line = f"{item['title']} | explored {counts[key]} submissions/runs | {item['ref']} | {item['status']}"
        if sum(len(s) + 1 for s in lines) + len(line) > limit:
            break
        lines.append(line); seen.add(key)
    return '\n'.join(lines)


def build_run_memory(runs_root, current_run_id=None, *, max_runs=20, max_chars=8000,
                     max_state_bytes=32 * 1024 * 1024, max_scan_runs=500, include_demo=False):
    """Read bounded stopped sibling runs; never alter old runs or follow links."""
    if any(type(value) is not int or value < 1 for value in (max_runs, max_chars, max_state_bytes, max_scan_runs)):
        raise ValueError("Run memory limits must be positive integers")
    if max_chars < len(NOTICE) + 80:
        raise ValueError("Run memory character limit is too small for its trust notice")
    runs_root = _plain_absolute(runs_root)
    result = {"schema_version": 1, "notice": NOTICE, "entries": [], "skipped": [], "truncated": False}
    if not runs_root.exists():
        return result
    # Only direct children are potential runs; do not walk workspaces or archives.
    paths = []
    with os.scandir(runs_root) as entries:
        for entry in entries:
            if len(paths) >= max_scan_runs:
                result["truncated"] = True
                break
            paths.append(Path(entry.path))
    paths.sort(key=lambda path: path.name, reverse=True)
    consumed = len(NOTICE)
    candidate_count = 0
    for directory in paths[:max_scan_runs]:
        if directory.name == current_run_id:
            continue
        try:
            directory = _confined(runs_root, directory.name)
            if not directory.is_dir():
                continue
            if not (directory / "state.sqlite3").exists() and not (directory / "checkpoint.json").exists():
                continue
            state, source, digest = _load_state(directory, max_state_bytes)
            if state.get("backend") == "demo" and not include_demo:
                continue
            if state.get("status") not in STOPPED or state.get("active_batch_started_at"):
                continue
            entry = summarize_run(state, directory.name, source, digest)
        except (OSError, ValueError, sqlite3.Error) as error:
            result["skipped"].append({"run_id": _short(directory.name, 100), "reason": _short(type(error).__name__, 80)})
            continue
        if len(result["entries"]) == max_runs or consumed + len(entry["summary"]) + 3 > max_chars:
            result["truncated"] = True
            break
        result["entries"].append(entry)
        entry['candidates'] = entry.get('candidates', [])[:max(0, 200 - candidate_count)]
        candidate_count += len(entry['candidates'])
        consumed += len(entry["summary"]) + 3
    result["skipped"] = result["skipped"][:20]
    return result


def memory_markdown(memory):
    lines = ["# Prior run notes", "", memory["notice"], ""]
    lines += ["- " + entry["summary"] for entry in memory["entries"]]
    if not memory["entries"]:
        lines.append("No readable stopped prior runs were included.")
    if memory.get("truncated"):
        lines += ["", "Older notes were omitted by the memory size limit."]
    return "\n".join(lines) + "\n"


def write_run_memory(run_dir, memory=None, *, write_index=True, current_state=None, **limits):
    """Atomically write derived views; the current run must already exist."""
    run_dir = _plain_absolute(run_dir)
    if not run_dir.is_dir():
        raise ValueError("Current run must be an existing directory")
    memory = memory if memory is not None else build_run_memory(run_dir.parent, run_dir.name, **limits)
    encoded = (json.dumps(memory, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _atomic_write(_confined(run_dir, "context/PRIOR_RUNS.md"), memory_markdown(memory).encode("utf-8"))
    _atomic_write(_confined(run_dir, "context/prior-runs.json"), encoded)
    if write_index:
        index = memory
        if isinstance(current_state, dict) and current_state.get("status") in STOPPED and not current_state.get("active_batch_started_at"):
            # The caller has just committed this state. Do not read its open WAL.
            index = dict(memory)
            current_body = json.dumps(current_state, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            current = summarize_run(current_state, run_dir.name, "caller_committed_state",
                                    hashlib.sha256(current_body.encode("utf-8")).hexdigest())
            index["entries"] = [current] + [entry for entry in memory["entries"] if entry["run_id"] != run_dir.name]
            index["entries"] = index["entries"][:limits.get("max_runs", 20)]
        # Last complete regeneration wins; this view has no authority and loses no ledger data.
        index_encoded = (json.dumps(index, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        _atomic_write(_confined(run_dir.parent, "RUN_MEMORY.json"), index_encoded)
    return memory
