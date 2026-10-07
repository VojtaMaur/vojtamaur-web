"""Seed roles are starting coverage, not a closed roster."""
from .models import assign_model
SEED_ROLES = [
    (0, "Meta-Archivist / Orchestrator", "Map existing preservation layers and coordinate missing coverage. Request precise new specialists where the seed roster is inadequate; do not rediscover current systems."),
    (1, "Loophole Archivist", "Investigate legitimate unexpected preservation mechanisms in systems not primarily intended as archives. Find a way to tuck this web, in some reconstructable form, into the cracks of the internet. Verify terms, capacity, discoverability and recurring payment independence."),
    (1, "Anomaly Engineer", "Explore unusual, lawful artifacts likely to be discovered, understood, copied and reinterpreted by people. Measure anomaly value separately from storage durability."),
    (1, "Format Mutant", "Research diverse representations and decoding strategies: image, audio, physical structures and compact self-describing encodings. Avoid existing exports unless a material improvement is demonstrated."),
    (1, "Failure-Domain Hunter", "Find hidden correlated dependencies across mirrors, accounts, networks, institutions, formats and payment systems. Seek independent failure domains rather than copy counts."),
    (1, "Infrastructure Scout", "Search current services, protocols and institutions. Cite primary evidence for actual capacity, deletion policies, eligibility, costs and legal use."),
    (1, "Future Archaeologist", "Assess whether a finder in 10, 100 or 1000 years can identify, decode, verify and reconstruct the content without the present software ecosystem."),
    (2, "Hostile Reviewer", "Review stable IDEA IDs; challenge false novelty, hidden fees, ToS violations, misleading permanence and correlated failure domains. Preserve promising blocked mechanisms and suggest provider alternatives."),
    (2, "Evidence Auditor", "Audit claims and cited primary sources, distinguish model claims from observed tool evidence, and correct existing IDEA IDs. Do not infer permanence or prices without current evidence."),
    (2, "Role Architect", "Review roles, discoveries, rejections and blockers; identify organizational blind spots and propose specific emergent specialists with a concrete question and unique expertise."),
    (2, "Prototyper", "Implement selected mechanisms using prepared public build exports and private prototypes. Execute and record functional tests in networkless Docker. In autonomous mode deposit through granted connectors, verify receipts and continue. Follow independent external scope and approval policy; never modify production."),
    (3, "Synthesizer / Reporter", "Produce a grounded cross-agent conclusion, prioritize high-value blocked candidates and unresolved questions, and assess emergent roles. The deterministic report retains all raw evidence and outcomes."),
]


def seed_agents(config):
    selected = config.get("seed_roles", [])
    roster = [s for s in SEED_ROLES if not selected or s[1] in selected]
    if config["max_agents"] < len(roster):
        raise ValueError("max_agents must allow the selected seed roles")
    return [assign_model(config, new_agent(f"AGENT-{n:03d}", role, mission, phase)) for n, (phase, role, mission) in enumerate(roster, 1)]


def new_agent(agent_id, role, mission, phase=1, parent_id=None, depth=0, reason="Seed role"):
    return {"id": agent_id, "role": role, "mission": mission, "phase": phase,
            "parent_id": parent_id, "depth": depth, "creation_reason": reason,
            "work_kind": "DISCOVERY" if phase == 1 else "REVIEW" if role in ("Evidence Auditor", "Hostile Reviewer") else "LOCAL" if role == "Prototyper" else "COORDINATION" if role in ("Role Architect", "Meta-Archivist / Orchestrator") else "SYNTHESIS",
            "status": "PENDING", "rounds": 0, "summary": "", "reason_for_stopping": "",
            "unexplored_leads": [], "blind_spots": [], "history": [], "usage": {}, "patch": {}}
