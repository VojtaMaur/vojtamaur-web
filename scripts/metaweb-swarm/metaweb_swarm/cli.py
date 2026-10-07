"""Operator-only command line. Agent tools never receive this CLI."""
import argparse
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

from .config import load_config, validate_config, round_allowance
from .engine import Engine, initialize, decide, unblock, refresh_reports, select_implementation, finish_research
from .storage import Store, atomic_write, now, run_lock
from .models import TIERS
from .roles import seed_agents


def parser():
    cli = argparse.ArgumentParser(description="Metaweb swarm: isolated copies, independent autonomy/capabilities/approval, durable audit")
    commands = cli.add_subparsers(dest="command", required=True)
    for name in ("init", "start"):
        init = commands.add_parser(name, help="Snapshot production read-only" if name == "init" else "Check prerequisites, initialize a NEW run and start the selected backend")
        init.add_argument("--project", required=True, type=Path)
        init.add_argument("--runs-root", required=True, type=Path)
        init.add_argument("--config", type=Path)
        init.add_argument("--model", help="Override ALL tiers for this new run without editing the profile")
        init.add_argument("--experiments", choices=("disabled", "docker"))
        init.add_argument("--mode", choices=("supervised", "autonomous"))
        init.add_argument("--external-scope", choices=("sandbox-only", "external"))
        init.add_argument("--approval", choices=("required", "disabled"))
        init.add_argument("--fetch-live", action=argparse.BooleanOptionalAction, default=False)
        init.add_argument("--previous-report", type=Path, action="append", default=[])
        if name == "start":
            init.add_argument("--backend", choices=("demo", "openai"), required=True)
    for name in ("run", "resume"):
        command = commands.add_parser(name)
        command.add_argument("run_dir", type=Path)
        command.add_argument("--backend", choices=("demo", "openai"), required=True)
        if name == "resume":
            command.add_argument("--extend-steps", type=int, default=0)
            command.add_argument("--extend-tokens", type=int, default=0)
            command.add_argument("--extend-seconds", type=int, default=0)
            command.add_argument("--extend-rounds", type=int, default=0)
    for name in ("pause", "status", "approvals", "report", "verify"):
        command = commands.add_parser(name)
        command.add_argument("run_dir", type=Path)
    command = commands.add_parser("decide")
    command.add_argument("run_dir", type=Path)
    command.add_argument("approval_id")
    command.add_argument("--decision", choices=("approve", "reject"), required=True)
    command.add_argument("--note", required=True)
    command = commands.add_parser("unblock")
    command.add_argument("run_dir", type=Path)
    command.add_argument("agent_id")
    command.add_argument("--note", required=True)
    command = commands.add_parser("select", help="Choose realization independently of scientific candidate status")
    command.add_argument("run_dir", type=Path)
    command.add_argument("idea_id")
    command.add_argument("--decision", choices=("implement", "defer"), required=True)
    command.add_argument("--note", required=True)
    command = commands.add_parser("finish-research", help="Save supervised research without requiring realization")
    command.add_argument("run_dir", type=Path)
    command.add_argument("--note", required=True)
    command = commands.add_parser("reconcile-budget", help="Account a verified uncertain request; never an agent tool")
    command.add_argument("run_dir", type=Path)
    command.add_argument("reservation_id")
    for field in ("input_tokens", "output_tokens", "web_search_calls"):
        command.add_argument("--" + field.replace("_", "-"), type=int, required=True)
    command.add_argument("--note", required=True)
    command = commands.add_parser("doctor")
    command.add_argument("--backend", choices=("demo", "openai"), default="demo")
    command.add_argument("--docker-check", action="store_true", help="Read-only Linux daemon and local image readiness check")
    command.add_argument("--config", type=Path)
    command.add_argument("--format", choices=("json", "text"), default="json")
    return cli


def check_run(path):
    path = path.resolve()
    if not (path / "state.sqlite3").is_file():
        raise ValueError("This is not an initialized run directory")
    return path


def doctor(backend, docker_check=False, config_path=None, output_format="json"):
    from importlib.metadata import PackageNotFoundError, version
    from .workspace import DockerExecutor
    checks = {"python": sys.version.split()[0], "offline_core": "available", "docker": DockerExecutor.executable() is not None,
              "openai_api_key_present": bool(os.getenv("OPENAI_API_KEY")), "api_called": False}
    config = load_config(config_path)
    checks["models"] = [{k: a.get(k) for k in ("role", "model_tier", "model")} for a in seed_agents(config)]
    checks["execution_policy"] = {k: config[k] for k in ("run_mode", "external_scope", "approval_required", "experiments")}
    checks['package_installation'] = {'mode': config.get('package_installation', 'disabled'),
        'timeout_seconds': config.get('package_install_timeout_seconds', 120),
        'max_installs_per_agent': config.get('max_package_installs_per_agent', 8),
        'fetch_project_access': False, 'experiment_network': 'none'}
    checks["budget"] = {"usd_limit_configured": config.get("estimated_budget_usd") is not None,
                        "max_total_tokens": config["max_total_tokens"], "max_active_seconds": config["max_active_seconds"],
                        "request_search_token_reserve": config["max_web_search_calls_per_request"] * config["max_web_search_context_tokens_per_call"],
                        "pricing_basis": "operator supplied ceilings; no provider billing access"}
    try:
        checks["openai_agents_version"] = version("openai-agents")
    except PackageNotFoundError:
        checks["openai_agents_version"] = None
    if backend == "openai":
        try:
            from .backend import check_sdk
            checks["sdk_interface"] = check_sdk()
        except (ImportError, ValueError) as error:
            checks["sdk_interface"] = str(error)
    if docker_check:
        from .workspace import DockerExecutor
        checks["docker_readiness"] = DockerExecutor(config["docker_image"]).check_ready()
    if output_format == "json":
        print(json.dumps(checks, ensure_ascii=False, indent=2))
    else:
        print(f"Python {checks['python']} | SDK {checks['openai_agents_version']} | API key present: {checks['openai_api_key_present']} | paid API calls: 0")
        print(f"pip: {config.get('package_installation', 'disabled')} | experiments stay networkless")
        for tier in TIERS:
            rows = [a for a in checks["models"] if a["model_tier"] == tier]
            print(f"{tier}: " + ", ".join(sorted({a['model'] or 'UNSET' for a in rows})) + f" ({len(rows)} seed roles)")
        if docker_check:
            print(f"Docker image: {config['docker_image']} | ready: {checks['docker_readiness']['ready']}")
    interface = checks.get("sdk_interface", {})
    if backend == "openai" and (not checks["openai_api_key_present"] or not checks["openai_agents_version"] or not isinstance(interface, dict) or not interface.get("compatible")):
        return 2
    if docker_check and not checks["docker_readiness"]["ready"]:
        return 2
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "doctor":
            return doctor(args.backend, args.docker_check, args.config, args.format)
        if args.command in ("init", "start"):
            config = load_config(args.config)
            if args.model is not None:
                if args.model != config.get("model"):
                    for key in ("input_price_per_million", "output_price_per_million", "web_search_price_per_call"):
                        config[key] = None
                config["model"] = args.model
                config["model_tiers"] = {tier: args.model for tier in TIERS}
            if args.experiments is not None:
                config["experiments"] = args.experiments
            if args.mode is not None:
                config["run_mode"] = args.mode
            if args.external_scope is not None:
                config["external_scope"] = args.external_scope
            if args.approval is not None:
                config["approval_required"] = args.approval == "required"
            validate_config(config)
            if args.command == "start":
                if args.backend == "openai":
                    from .backend import check_sdk
                    if not os.environ.get("OPENAI_API_KEY"):
                        raise ValueError("OPENAI_API_KEY is not set; no run or paid API calls started")
                    if not check_sdk().get("compatible") or any(not a.get("model") for a in seed_agents(config)):
                        raise ValueError("Compatible SDK and explicit models for every seed role are required")
                if config["experiments"] == "docker":
                    from .workspace import DockerExecutor
                    ready = DockerExecutor(config["docker_image"]).check_ready()
                    if not ready.get("ready"):
                        raise ValueError("Docker daemon / configured image is unavailable: " + str(ready))
                print("Prerequisites checked. Capturing project/context/exports for a new isolated run...", flush=True)
            path = initialize(args.project, args.runs_root, config, args.fetch_live, args.previous_report)
            print(path)
            if args.command == "start":
                return main(["run", str(path), "--backend", args.backend])
            return 0
        run_dir = check_run(args.run_dir)
        if args.command == "pause":
            atomic_write(run_dir / "PAUSE.flag", now() + "\n")
            print("Pause requested; current bounded batch finishes before pausing.")
            return 0
        if args.command in ("status", "approvals", "verify"):
            store = Store(run_dir)
            try:
                state = store.load()
                if args.command == "status":
                    data = {k: state.get(k) for k in ("run_id", "status", "stop_reason", "backend", "steps", "active_seconds", "usage", "usage_estimated_usd")}
                    data["agents"] = [{k: a.get(k) for k in ("id", "role", "status", "rounds", "reason_for_stopping")} for a in state["agents"]]
                    data["execution_policy"] = {k: state["config"].get(k) for k in ("run_mode", "external_scope", "approval_required", "experiments")}
                    data["budget_reservations"] = state.get("budget_reservations", {})
                    data["external_actions"] = state.get("external_actions", [])
                    data['package_installations'] = state.get('package_installations', [])
                    print(json.dumps(data, ensure_ascii=False, indent=2))
                elif args.command == "approvals":
                    print(json.dumps(state["approvals"], ensure_ascii=False, indent=2))
                else:
                    print(json.dumps(store.verify(), ensure_ascii=False, indent=2))
            finally:
                store.close()
            return 0
        with run_lock(run_dir):
            if args.command in ("run", "resume"):
                if args.backend == "demo":
                    from .demo import DemoBackend
                    backend = DemoBackend()
                else:
                    from .backend import OpenAIBackend, check_sdk
                    if not os.environ.get("OPENAI_API_KEY"):
                        raise ValueError("OPENAI_API_KEY is not set; no agent copies or API calls started")
                    if not check_sdk().get("compatible"):
                        raise ValueError("OpenAI Agents SDK interface is incompatible")
                    backend = OpenAIBackend()
                engine = Engine(run_dir, backend, args.backend)
                try:
                    if args.backend == "openai" and any(not a.get("model") for a in engine.state["agents"]):
                        raise ValueError("Set an available OpenAI API model explicitly in the init config")
                    if args.command == "resume":
                        changes = {key: getattr(args, key) for key in ("extend_steps", "extend_tokens", "extend_seconds", "extend_rounds")}
                        if any(value < 0 for value in changes.values()):
                            raise ValueError("Budget extensions must be nonnegative")
                        engine.state["config"]["max_steps"] += args.extend_steps
                        engine.state["config"]["max_total_tokens"] += args.extend_tokens
                        engine.state["config"]["max_active_seconds"] += args.extend_seconds
                        engine.state["config"]["max_agent_rounds"] += args.extend_rounds
                        for role in engine.state["config"].get("role_round_limits", {}):
                            engine.state["config"]["role_round_limits"][role] += args.extend_rounds
                        if any(changes.values()):
                            for agent in engine.state["agents"]:
                                if agent["status"] == "LIMIT_REACHED" and agent["rounds"] < round_allowance(engine.state["config"], agent):
                                    agent["status"] = "PENDING"
                            engine.store.commit(engine.state, "operator_budget_extension", changes)
                        flag = run_dir / "PAUSE.flag"
                        if flag.exists():
                            flag.unlink()
                    state = asyncio.run(engine.run())
                    print(f"{state['status']}: {state['stop_reason']}\nReport: {run_dir / 'SWARM_REPORT.md'}")
                    return 0 if state["status"] in ("COMPLETED", "PAUSED", "BLOCKED") else 3
                finally:
                    engine.close()
            store = Store(run_dir)
            try:
                state = store.load()
                store.verify()
                if args.command == "decide":
                    decide(store, state, args.approval_id, args.decision, args.note)
                    print("Human decision recorded. No external action was executed.")
                elif args.command == "unblock":
                    unblock(store, state, args.agent_id, args.note)
                    print("Human resolution recorded; resume explicitly.")
                elif args.command == "report":
                    refresh_reports(store, state)
                    print(run_dir / "SWARM_REPORT.md")
                elif args.command == "select":
                    select_implementation(store, state, args.idea_id, args.decision, args.note)
                    print("Selection saved. Candidate research status retained; resume explicitly.")
                elif args.command == "finish-research":
                    finish_research(store, state, args.note)
                    print(run_dir / "SWARM_REPORT.md")
                elif args.command == "reconcile-budget":
                    from .budget import reconcile
                    actual = {"input_tokens": args.input_tokens, "output_tokens": args.output_tokens, "total_tokens": args.input_tokens + args.output_tokens, "web_search_calls": args.web_search_calls}
                    hold = state.get("budget_reservations", {}).get(args.reservation_id)
                    if not hold:
                        raise ValueError("Unknown reservation; inspect status")
                    previous = hold.get("accounted_usage", hold.get("observed_usage", {}))
                    record = reconcile(state, args.reservation_id, actual, args.note)
                    agent = next(a for a in state["agents"] if a["id"] == hold["agent_id"])
                    if not state["usage"].get("by_model"):
                        state["usage"]["by_model"] = {state["config"].get("model") or "UNSET": {k: v for k, v in state["usage"].items() if k != "by_model"}}
                    model = hold.get("model") or state["config"].get("model") or "UNSET"
                    model_counts = state["usage"]["by_model"].setdefault(model, {})
                    for key in actual:
                        additional = max(0, actual[key] - previous.get(key, 0))
                        state["usage"][key] += additional
                        agent["usage"][key] += additional
                        model_counts[key] = model_counts.get(key, 0) + additional
                    state["usage"]["unknown_steps"] = max(0, state["usage"]["unknown_steps"] - 1)
                    agent["usage"]["unknown_steps"] = max(0, agent["usage"]["unknown_steps"] - 1)
                    model_counts["unknown_steps"] = max(0, model_counts.get("unknown_steps", 0) - 1)
                    store.commit(state, "operator_budget_reconciled", record)
                    refresh_reports(store, state)
                    print("Verified usage reconciled; unblock the agent and resume explicitly.")
            finally:
                store.close()
        return 0
    except KeyboardInterrupt:
        print("Paused after interrupt; resume from the saved run.", file=sys.stderr)
        return 130
    except (ValueError, OSError, ImportError) as error:
        print(f"BLOCKED: {error}", file=sys.stderr)
        return 2
