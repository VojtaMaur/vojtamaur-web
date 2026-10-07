"""Strict operator configuration; agents cannot mutate limits or capabilities."""
import json
import math
import sys
from pathlib import Path
from .models import TIERS, PRICE_KEYS, prices_for

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
if not (PACKAGE_ROOT / "config.json").is_file():
    PACKAGE_ROOT = Path(sys.prefix) / "share" / "metaweb-swarm"


def load_config(path=None):
    defaults = json.loads((PACKAGE_ROOT / "config.json").read_text(encoding="utf-8-sig"))
    if path:
        supplied = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        unknown = set(supplied) - set(defaults)
        if unknown:
            raise ValueError(f"Unknown configuration fields: {sorted(unknown)}")
        defaults.update(supplied)
    validate_config(defaults)
    return defaults


def validate_config(config):
    if config.get("schema_version") != 1:
        raise ValueError("Unsupported configuration schema_version")
    if config.get("run_mode", "supervised") not in ("supervised", "autonomous"):
        raise ValueError("run_mode must be supervised or autonomous")
    if config.get("external_scope", "sandbox-only") not in ("sandbox-only", "external"):
        raise ValueError("external_scope must be sandbox-only or external")
    for field in ("approval_required", "include_exports", "semantic_dedupe", "sandbox_smoke_test"):
        if field in config and type(config[field]) is not bool:
            raise ValueError(f"{field} must be boolean")
    for field in ("max_external_actions", "max_external_bytes"):
        if field in config and (type(config[field]) is not int or config[field] < 0):
            raise ValueError(f"{field} must be a nonnegative integer")
    for field in ("max_export_file_bytes", "max_export_total_bytes", "max_web_search_calls_per_request", "max_web_search_context_tokens_per_call"):
        if field in config and (type(config[field]) is not int or config[field] < 1):
            raise ValueError(f"{field} must be a positive integer")
    from .actions import validate_resources
    validate_resources(config.get("external_resources", []))
    from .roles import SEED_ROLES
    overrides = config.get("role_round_limits", {})
    if not isinstance(overrides, dict) or any(not isinstance(k, str) or not k.strip() or len(k) > 160 or type(v) is not int or v < 1 for k, v in overrides.items()):
        raise ValueError("role_round_limits must map role names to positive integer round limits")
    roles = config.get("seed_roles", [])
    if not isinstance(roles, list) or any(not isinstance(r, str) or r not in {s[1] for s in SEED_ROLES} for r in roles) or len(set(roles)) != len(roles):
        raise ValueError("seed_roles must contain unique known seed role names")
    for key in ("max_concurrent_agents", "max_agents", "max_descendants", "max_depth",
                "max_agent_rounds", "max_steps", "max_turns", "max_output_tokens",
                "max_total_tokens", "max_active_seconds", "step_timeout_seconds",
                "experiment_timeout_seconds", "max_file_bytes", "max_snapshot_bytes",
                "prompt_chars", "history_chars"):
        if type(config.get(key)) is not int or config[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    if config["max_concurrent_agents"] > config["max_agents"]:
        raise ValueError("Concurrency cannot exceed max_agents")
    if config.get("experiments") not in ("disabled", "docker"):
        raise ValueError("experiments must be disabled or docker; host execution is unavailable")
    if config.get('package_installation', 'disabled') not in ('disabled', 'pypi'):
        raise ValueError('package_installation must be disabled or pypi')
    if config.get('prior_work_policy', 'continue') not in ('novelty-first', 'continue'):
        raise ValueError('prior_work_policy must be novelty-first or continue')
    for field in ('package_install_timeout_seconds', 'max_package_installs_per_agent', 'max_package_bytes'):
        if field in config and (type(config[field]) is not int or config[field] < 1):
            raise ValueError(f'{field} must be a positive integer')
    if config.get('package_install_timeout_seconds', 120) > 3600:
        raise ValueError('package_install_timeout_seconds must be at most 3600')
    if config.get("model") is not None and (not isinstance(config["model"], str) or not config["model"].strip()):
        raise ValueError("model must be a nonempty API model name or null")
    tiers = config.get("model_tiers", {})
    if not isinstance(tiers, dict) or set(tiers) - set(TIERS) or any(not isinstance(v, str) or not v.strip() for v in tiers.values()):
        raise ValueError("model_tiers must map cheap/strong/flag to nonempty API model names")
    assignments = config.get("role_model_tiers", {})
    if not isinstance(assignments, dict) or any(not isinstance(k, str) or not k.strip() or len(k) > 160 or v not in TIERS for k, v in assignments.items()):
        raise ValueError("role_model_tiers must map role names to cheap/strong/flag")
    if config.get("emergent_model_tier", "strong") not in TIERS:
        raise ValueError("emergent_model_tier must be cheap, strong or flag")
    model_prices = config.get("model_prices", {})
    if not isinstance(model_prices, dict):
        raise ValueError("model_prices must be an object")
    for model, rates in model_prices.items():
        if not isinstance(model, str) or not model.strip() or not isinstance(rates, dict) or set(rates) != set(PRICE_KEYS) or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in rates.values()):
            raise ValueError("Each model_prices entry requires three finite nonnegative operator price ceilings")
    image = config.get("docker_image", "")
    if not isinstance(image, str) or not image or image.startswith("-") or any(c.isspace() for c in image):
        raise ValueError("Invalid Docker image")
    prices = ("input_price_per_million", "output_price_per_million", "web_search_price_per_call")
    for key in (*prices, "estimated_budget_usd"):
        value = config.get(key)
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise ValueError(f"{key} must be a nonnegative finite number or null")
    if config.get("estimated_budget_usd") is not None:
        used_models = set(tiers.values()) | ({config["model"]} if config.get("model") else set())
        if not used_models or any(any(prices_for(config, m).get(k) is None for k in prices) for m in used_models):
            raise ValueError("An estimated dollar budget requires all three operator-supplied prices for every configured model")


def estimated_cost(usage, config):
    if usage.get("by_model"):
        if any(sum(counts.get(k, 0) for counts in usage["by_model"].values()) != usage.get(k, 0) for k in ("input_tokens", "output_tokens", "web_search_calls")):
            return None
        values = [estimated_cost({k: v for k, v in counts.items() if k != "by_model"}, prices_for(config, model)) for model, counts in usage["by_model"].items()]
        return None if usage.get("unknown_steps", 0) or any(v is None for v in values) else sum(values)
    if config.get("model_prices") and not usage.get("unknown_steps", 0) and not any(usage.get(k, 0) for k in ("input_tokens", "output_tokens", "web_search_calls")):
        return 0.0
    keys = ("input_price_per_million", "output_price_per_million", "web_search_price_per_call")
    if any(config.get(k) is None for k in keys) or usage.get("unknown_steps", 0):
        return None
    return (usage.get("input_tokens", 0) * config[keys[0]] / 1_000_000
            + usage.get("output_tokens", 0) * config[keys[1]] / 1_000_000
            + usage.get("web_search_calls", 0) * config[keys[2]])


def round_allowance(config, agent):
    base = config.get("role_round_limits", {}).get(agent["role"], config["max_agent_rounds"])
    return max(base, agent.get("round_limit", 0))


def schedule_batch(pending, steps_left, concurrency):
    """Phase order, fair quanta, and one protected round for each later role.

    Reserves steps only. Tokens/time/cost remain absolute global hard limits.
    """
    phase = min(a["phase"] for a in pending)
    later = [a for a in pending if a["phase"] > phase]
    reserve = len(later)
    pool = [a for a in pending if a["phase"] == phase]
    if later and steps_left <= reserve:
        # A first pass through downstream roles takes precedence over repeats.
        # Serve each once before spending a repeat on the same downstream role.
        pool = later
        slots = 1
    else:
        slots = min(concurrency, steps_left - reserve if later else steps_left)
    return sorted(pool, key=lambda a: (a["rounds"], a["phase"], a["id"]))[:max(1, slots)]
