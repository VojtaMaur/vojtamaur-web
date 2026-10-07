"""Research assignments and observable coverage; source discovery is not verification."""
from urllib.parse import urlsplit

QUESTIONS = {
    "Loophole Archivist": "Find surprising LAWFUL uses of systems whose advertised purpose is NOT archiving, hosting, repository storage or backup. Zenodo and ordinary repositories do not satisfy your assignment. Explore at least three unrelated families: independently replicated protocol metadata, append-only public records with legitimate user payload fields, and machine-readable information on widely distributed physical/media artifacts. Examples such as DNS are questions, not endorsed solutions. First generate unusual hypotheses, then search actual primary documentation for supported payload sizes, retention, replication topology, eligibility, deletion and terms. Preserve a speculative idea honestly without demanding VERIFIED before recording it. Return one concrete clever mechanism plus its decoder/bootstrap design, not another catalogue of archival services. A small discoverable payload can be a recovery pointer or meaningful excerpt; explain the limit rather than pretending it holds the entire web. No spam, unauthorized changes, exploitation or evasion of platform restrictions. No external publishing/accounts/payments without human approval.",
    "Anomaly Engineer": "Design one strange but understandable artifact that a stranger would notice, decode and voluntarily replicate. Optimize surprise and discoverability separately from durability. Investigate ordinary products, public creative/scientific media formats or legitimate published datasets that can carry a self-describing Metaweb fragment. Search actual specifications and distribution rules; avoid ordinary archives and repository services. Compare two sharply different concepts, keep at least one bold hypothesis even if verification is incomplete, and create a local specimen with write_file. Explain who finds it, why they copy it, the payload capacity, and how its decoder survives. Never publish externally or abuse a service.",
    "Format Mutant": "Investigate independently specified self-describing encodings or error-correcting representations beyond the existing SSTV/Rosetta/export stack. Consult external specifications and propose a concrete decoding/recovery improvement, with a local specimen if feasible.",
    "Failure-Domain Hunter": "Build a concrete dependency table for known layers, then investigate two external alternatives that remove a specific shared host/operator/funding/protocol risk. Compare actual failure domains; merely increasing mirror count is insufficient.",
    "Infrastructure Scout": "Search external institutional/public preservation services and protocol specifications. Produce two concrete candidates with primary evidence of eligibility, capacity, retention, payment model, and lawful intended use. Do not audit the owner's site again.",
    "Future Archaeologist": "Consult external format specifications or preservation standards for independent decoding. Design a discoverable bootstrap/decoder instruction specimen and test its logical reconstruction steps against missing modern dependencies.",
}


def requires_external(agent):
    return agent.get("work_kind", "DISCOVERY" if agent["role"] in QUESTIONS or agent.get("parent_id") else "LOCAL") == "DISCOVERY"


def research_brief(agent):
    if agent["role"] in QUESTIONS:
        return ("DISCOVERY ASSIGNMENT: " + QUESTIONS[agent["role"]]
                + " Start with external web search, not list_files. The owner context is already supplied as a baseline. "
                "Use check_baseline with provider/format aliases before submitting a candidate. It prioritizes ARCHIVE.txt and searches captured state, documentation and original posts. Never restrict discovery to site:vojtamaur.cz. "
                "A mention alone does not prove implementation: read the excerpt and distinguish actual use from a proposal or unrelated example. "
                "Consult at least two sources on external domains before claiming completed discovery. "
                "Record promising unverified mechanisms as INVESTIGATING or BLOCKED; verification is not required to preserve a hypothesis. "
                "Use note for audit observations and negative results, submit_idea only for a concrete mechanism. "
                "Own your assigned search space: do not spend your discovery rounds refining another role's first candidate. Hand overlap to the current IDEA and investigate a different family yourself. Review and Prototyper roles own downstream work. "
                "Do not adopt another agent's negative result as proof that your distinct search space is exhausted.")
    if agent["role"] == "Meta-Archivist / Orchestrator":
        return "Map the baseline briefly and identify gaps. Do not conclude the swarm has no new possibilities from a local audit. Discovery roles own external searches; you own coverage and concrete delegations."
    if agent["role"] == "Role Architect":
        return "If a specific coverage gap needs a new specialist, actually call spawn_agent with its bounded question and unique expertise; do not merely list imaginary future roles in a summary."
    if agent["role"] in ("Hostile Reviewer", "Evidence Auditor"):
        return "Review actual candidate IDs and external claims. If there are no candidates, record that once and stop your assigned review; do not manufacture a negative audit candidate or loop on the owner's website."
    if agent["role"] == "Prototyper":
        return "Select one feasible current-run candidate immediately. Copy a prepared export, install the actual needed packages, create an encoder/decoder and assertion script, submit their paths to the SAME IDEA, run_experiment with that ID, then record_test. Carry out these actions now; repeatedly describing a future test is not progress. A candidate need not be externally VERIFIED to test a local hypothesis. Use evidence=[] for a local draft, never file:// URLs. Return COMPLETED when this assigned local test is done, placing external deployment/research in handoff_leads. If no candidate exists, note that once and stop."
    if agent["role"] != "Synthesizer / Reporter":
        return "Carry out your specific emergent specialist question and mission. DISCOVERY work requires external primary-source research even for newly spawned roles; LOCAL work stays in the copy. Use check_baseline to support known/duplicate claims. Do not repeat a general baseline audit."
    return "Synthesize actual observations and candidates. Report coverage gaps honestly; an incomplete search is not evidence that novel mechanisms do not exist."


def external_sources(event):
    action = event.get("action", {}) or {}
    sources = action.get("sources", []) or []
    if action.get("url"):
        sources = sources + [{"url": action["url"]}]
    result = []
    for source in sources:
        url = source.get("url", "") if isinstance(source, dict) else ""
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme in ("http", "https") and host and host != "vojtamaur.cz" and not host.endswith(".vojtamaur.cz"):
            result.append(url)
    return result
