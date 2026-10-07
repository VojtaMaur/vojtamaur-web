"""Operator-owned role tiers; emergent agents cannot promote themselves."""
TIERS = ("cheap", "strong", "flag")
PRICE_KEYS = ("input_price_per_million", "output_price_per_million", "web_search_price_per_call")
ROLE_TIERS = {
    "Meta-Archivist / Orchestrator": "flag",
    "Synthesizer / Reporter": "flag",
    "Hostile Reviewer": "flag",
    "Loophole Archivist": "flag", "Anomaly Engineer": "strong",
    "Format Mutant": "strong", "Failure-Domain Hunter": "strong",
    "Future Archaeologist": "strong", "Evidence Auditor": "strong",
    "Prototyper": "strong", "Role Architect": "cheap",
    "Infrastructure Scout": "cheap",
}


def tier_for(config, agent):
    return config.get("role_model_tiers", {}).get(agent["role"],
        config.get("emergent_model_tier", "strong") if agent.get("parent_id") else
        ROLE_TIERS.get(agent["role"], config.get("emergent_model_tier", "strong")))


def assign_model(config, agent):
    agent.setdefault("model_tier", tier_for(config, agent))
    agent.setdefault("model", config.get("model_tiers", {}).get(agent["model_tier"], config.get("model")))
    return agent


def prices_for(config, model):
    explicit = config.get("model_prices", {}).get(model)
    if explicit is not None:
        return explicit
    # Legacy prices cover only the explicitly named legacy/global model.
    # An expensive new tier cannot inherit the cheap model's dollar prices.
    if model == config.get("model"):
        return {k: config.get(k) for k in PRICE_KEYS}
    return {k: None for k in PRICE_KEYS}


def search_allowance(config, agent):
    # These roles synthesize supplied observations; they do not discover sources.
    if agent.get("work_kind") in {"COORDINATION", "SYNTHESIS", "LOCAL"}:
        return 0
    return config.get("max_web_search_calls_per_request", 1)
