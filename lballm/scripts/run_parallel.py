"""Run LBALLM games in parallel with isolated saves and aggregated results.

Unlike scripts/run_experiments.py (which runs one game at a time on a single
port and a shared save file), this launches each run as its own subprocess with:

  - a unique bridge port           (avoids port collisions)
  - an isolated HOME               (avoids Godot save-file collisions)
  - its own logs/trace directory   (avoids output collisions)

Concurrency is bounded by --parallel. Each run's outcome is recovered from its
trace.jsonl (the run_end event carries the final gamestate), aggregated into
<experiment_dir>/results.jsonl plus a printed per-model summary.

Config format is the same experiment YAML used by run_experiments.py
(base_config / models / runs_per_model / overrides / logs_root /
experiment_name), with two extra optional top-level keys:

  game_path: absolute path to the game binary (required on macOS/Linux where
             the .exe auto-detect does not apply). Falls back to the copied
             app under ../dll if present.
  base_port: first port to allocate (default 12346).

Run from the lballm directory:
  uv run python scripts/run_parallel.py --config config/experiments_heuristic.yaml --parallel 3
  uv run python scripts/run_parallel.py --config config/experiments.yaml --parallel 4 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # the lballm/ directory
REPO_ROOT = PROJECT_ROOT.parent
LBALLM_BIN = PROJECT_ROOT / ".venv" / "bin" / "lballm"

# Fields that may appear in a per-run lballm config YAML.
# Godot writes user data under XDG_DATA_HOME (we force this path on every OS for
# server portability). This is where saves/settings live inside an isolated HOME.
GODOT_USERDATA_REL = Path(".local/share/Godot/app_userdata/Luck be a Landlord")

# When seeding a fresh home from a configured reference, copy everything (language,
# settings, unlocked stats) EXCEPT in-progress game saves, so each run still begins
# a brand-new game rather than resuming the reference's save.
SEED_EXCLUDE = frozenset({"LBAL.save", "LBAL-Sandbox-Data.save"})
SEED_EXCLUDE_DIRS = frozenset({"logs", "run_logs", "mods"})

CONFIG_FIELDS = frozenset(
    {
        "provider",
        "model",
        "strategy",
        "host",
        "port",
        "base_url",
        "api_key",
        "max_steps",
        "start_game",
        "start_action",
        "fallback_to_heuristic",
        "trace_enabled",
        "trace_path",
        "game_path",
        "logs_path",
        "model_config",
    }
)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = base.copy()
    for key, value in override.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _safe(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip())
    return text.strip(".-_")[:80] or "model"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"config must be a YAML mapping: {path}")
    return data


def _resolve(value: str | Path, base: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    for candidate in (base / path, PROJECT_ROOT / path, Path.cwd() / path):
        if candidate.exists():
            return candidate
    return base / path


def _default_game_path() -> str | None:
    mac = (
        REPO_ROOT
        / "dll"
        / "Luck be a Landlord.app"
        / "Contents"
        / "MacOS"
        / "Luck be a Landlord"
    )
    if mac.exists():
        return str(mac)
    linux = REPO_ROOT / "dll" / "Luck be a Landlord"
    if linux.exists() and linux.is_file():
        return str(linux)
    return None


def _config_subset(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k in CONFIG_FIELDS}


def _build_plan(
    exp: dict[str, Any],
    exp_dir: Path,
    *,
    config_base: Path,
    runs_override: int | None,
    game_path: str | None,
    base_port: int,
) -> list[dict[str, Any]]:
    base_config_value = exp.get("base_config")
    base: dict[str, Any] = {}
    if base_config_value:
        base_path = _resolve(base_config_value, config_base)
        if base_path.exists():
            base = _config_subset(_load_yaml(base_path))
    overrides = exp.get("overrides") or {}
    if not isinstance(overrides, dict):
        raise ValueError("overrides must be a mapping")
    overrides = _config_subset(_deep_merge(overrides, {}))

    models = exp.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("config must contain a non-empty models list")

    runs_per_model = int(runs_override or exp.get("runs_per_model", 3))
    if runs_per_model < 1:
        raise ValueError("runs_per_model must be >= 1")

    plan: list[dict[str, Any]] = []
    port = base_port
    for entry in models:
        if not isinstance(entry, dict):
            raise ValueError("each model entry must be a mapping")
        label = str(entry.get("name") or entry.get("model") or "model")
        safe_label = _safe(label)
        for run_index in range(1, runs_per_model + 1):
            run_dir = exp_dir / safe_label / f"run-{run_index:02d}"
            cfg = _deep_merge(_deep_merge(base, overrides), _config_subset(entry))
            cfg["port"] = port
            cfg["logs_path"] = str(run_dir / "game")
            cfg["trace_path"] = str(run_dir / "trace")
            if game_path and not cfg.get("game_path"):
                cfg["game_path"] = game_path
            plan.append(
                {
                    "label": label,
                    "safe_label": safe_label,
                    "run_index": run_index,
                    "run_dir": run_dir,
                    "port": port,
                    "config": cfg,
                }
            )
            port += 1
    return plan


def _write_run_config(spec: dict[str, Any]) -> Path:
    run_dir: Path = spec["run_dir"]
    run_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = run_dir / "config.yaml"
    with cfg_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(spec["config"], f, allow_unicode=True, sort_keys=True)
    return cfg_path


def _default_reference_home() -> Path | None:
    """Locate a configured Godot userdata dir to seed language/settings from."""
    candidates = [
        Path.home() / "Library/Application Support/Godot/app_userdata/Luck be a Landlord",
        Path.home() / ".local/share/Godot/app_userdata/Luck be a Landlord",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return None


def _isolated_home(spec: dict[str, Any], reference: Path | None) -> Path:
    """Create a fresh per-run HOME, seeding settings so the game skips first-run
    onboarding (language select) but still starts a new game (saves excluded)."""
    home = spec["run_dir"] / "home"
    userdata = home / GODOT_USERDATA_REL
    userdata.mkdir(parents=True, exist_ok=True)
    if reference and reference.is_dir():
        for item in reference.iterdir():
            if item.name in SEED_EXCLUDE or item.name in SEED_EXCLUDE_DIRS:
                continue
            if item.is_file():
                shutil.copy2(item, userdata / item.name)
    return home


def _build_command(cfg_path: Path, spec: dict[str, Any]) -> list[str]:
    cmd = [
        str(LBALLM_BIN),
        "--config",
        str(cfg_path),
        "--port",
        str(spec["port"]),
        "--logs-path",
        spec["config"]["logs_path"],
        "--trace-path",
        spec["config"]["trace_path"],
        "--verbose",
    ]
    # On a headless Linux server the Godot window needs a virtual display.
    if platform.system() == "Linux" and shutil.which("xvfb-run"):
        cmd = ["xvfb-run", "-a", "--server-args=-screen 0 1280x720x24", "--", *cmd]
    return cmd


def _parse_trace(trace_dir: str) -> dict[str, Any]:
    """Recover the final outcome from a run's trace.jsonl (run_end event)."""
    path = Path(trace_dir) / "trace.jsonl"
    if not path.exists():
        return {"run_end_reason": None, "game_outcome": "unknown"}
    run_end: dict[str, Any] | None = None
    last_step: dict[str, Any] | None = None
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") == "run_end":
                run_end = event
            elif event.get("event") == "step":
                last_step = event
    gs = (run_end or {}).get("gamestate") or (last_step or {}).get("gamestate") or {}
    reason = (run_end or {}).get("reason")
    outcome = (
        "game_over"
        if reason == "game_over" or gs.get("state") == "GAME_OVER"
        else ("unfinished" if reason else "unknown")
    )
    return {
        "run_end_reason": reason,
        "run_end_step": (run_end or {}).get("step"),
        "game_outcome": outcome,
        "state": gs.get("state"),
        "event": gs.get("event"),
        "coins": gs.get("coins"),
        "effective_coins": gs.get("effective_coins"),
        "spins": gs.get("spins"),
        "current_floor": gs.get("current_floor"),
        "rent_values": gs.get("rent_values"),
        "times_rent_paid": gs.get("times_rent_paid"),
        "times_to_pay_rent": gs.get("times_to_pay_rent"),
    }


async def _run_one(
    spec: dict[str, Any],
    sem: asyncio.Semaphore,
    ordinal: int,
    total: int,
    reference_home: Path | None,
) -> dict[str, Any]:
    async with sem:
        cfg_path = _write_run_config(spec)
        home = _isolated_home(spec, reference_home)
        cmd = _build_command(cfg_path, spec)

        env = os.environ.copy()
        env["HOME"] = str(home)
        env["XDG_DATA_HOME"] = str(home / ".local" / "share")
        env["XDG_CONFIG_HOME"] = str(home / ".config")
        env["XDG_CACHE_HOME"] = str(home / ".cache")

        console = spec["run_dir"] / "console.log"
        started = datetime.now()
        print(
            f"[{ordinal}/{total}] start {spec['label']} run {spec['run_index']} "
            f"port={spec['port']} home={home}"
        )
        with console.open("w", encoding="utf-8") as log:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(PROJECT_ROOT),
                env=env,
                stdout=log,
                stderr=asyncio.subprocess.STDOUT,
            )
            rc = await proc.wait()

        summary = _parse_trace(spec["config"]["trace_path"])
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "model_label": spec["label"],
            "run_index": spec["run_index"],
            "port": spec["port"],
            "home": str(home),
            "duration_s": round((datetime.now() - started).total_seconds(), 1),
            "returncode": rc,
            "runner_status": "complete" if rc == 0 else "error",
            "console_log": str(console),
            "trace_path": spec["config"]["trace_path"],
            **summary,
        }
        print(
            f"[{ordinal}/{total}] done  {spec['label']} run {spec['run_index']} "
            f"rc={rc} outcome={record['game_outcome']} "
            f"coins={record.get('coins')} floor={record.get('current_floor')} "
            f"rent_paid={record.get('times_rent_paid')} ({record['duration_s']}s)"
        )
        return record


def _aggregate(records: list[dict[str, Any]]) -> None:
    by_model: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        by_model.setdefault(r["model_label"], []).append(r)

    def _avg(values: list[Any]) -> float | None:
        nums = [v for v in values if isinstance(v, (int, float))]
        return round(sum(nums) / len(nums), 1) if nums else None

    print("\n" + "=" * 78)
    print("SUMMARY (per model)")
    print("=" * 78)
    header = (
        f"{'model':<22}{'runs':>5}{'ok':>4}{'game_over':>10}"
        f"{'avg_coins':>11}{'avg_rent_paid':>14}{'max_floor':>10}"
    )
    print(header)
    print("-" * len(header))
    for label, rows in by_model.items():
        runs = len(rows)
        ok = sum(1 for r in rows if r["returncode"] == 0)
        game_over = sum(1 for r in rows if r["game_outcome"] == "game_over")
        avg_coins = _avg([r.get("coins") for r in rows])
        avg_rent = _avg([r.get("times_rent_paid") for r in rows])
        floors = [r.get("current_floor") for r in rows if isinstance(r.get("current_floor"), (int, float))]
        max_floor = max(floors) if floors else None
        print(
            f"{label[:22]:<22}{runs:>5}{ok:>4}{game_over:>10}"
            f"{str(avg_coins):>11}{str(avg_rent):>14}{str(max_floor):>10}"
        )


async def _main(args: argparse.Namespace) -> int:
    exp_path = _resolve(args.config, PROJECT_ROOT)
    config_base = exp_path.parent
    exp = _load_yaml(exp_path)

    game_path = args.game_path or exp.get("game_path") or _default_game_path()
    base_port = int(args.base_port or exp.get("base_port", 12346))

    logs_root = _resolve(exp.get("logs_root", "logs/experiments"), PROJECT_ROOT)
    exp_name = str(args.name or exp.get("experiment_name") or "parallel")
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    exp_dir = logs_root / f"{stamp}-{_safe(exp_name)}"

    plan = _build_plan(
        exp,
        exp_dir,
        config_base=config_base,
        runs_override=args.runs,
        game_path=game_path,
        base_port=base_port,
    )

    parallel = max(1, int(args.parallel))
    print(f"Experiment: {exp_name}")
    print(f"Output dir: {exp_dir}")
    print(f"Game path : {game_path}")
    print(f"Runs      : {len(plan)}  |  parallelism: {parallel}  |  base_port: {base_port}")
    if platform.system() == "Linux" and not shutil.which("xvfb-run"):
        print("WARNING: on Linux without xvfb-run; a headless server needs it.")
    for spec in plan:
        print(
            f"- {spec['label']} run {spec['run_index']}: port={spec['port']} "
            f"provider={spec['config'].get('provider')} "
            f"model={spec['config'].get('model')}"
        )

    if args.dry_run:
        return 0

    if not LBALLM_BIN.exists():
        print(f"ERROR: {LBALLM_BIN} not found. Run `uv sync` in {PROJECT_ROOT}.", file=sys.stderr)
        return 2

    exp_dir.mkdir(parents=True, exist_ok=True)
    reference_home = _default_reference_home()
    sem = asyncio.Semaphore(parallel)
    tasks = [
        asyncio.create_task(_run_one(spec, sem, i, len(plan), reference_home))
        for i, spec in enumerate(plan, 1)
    ]
    records = await asyncio.gather(*tasks)

    results_path = exp_dir / "results.jsonl"
    with results_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    _aggregate(list(records))
    print(f"\nResults: {results_path}")
    failures = [r for r in records if r["returncode"] != 0]
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="config/experiments.yaml", help="Experiment YAML path.")
    parser.add_argument("--parallel", type=int, default=3, help="Max concurrent games.")
    parser.add_argument("--runs", type=int, help="Override runs_per_model.")
    parser.add_argument("--name", help="Override experiment_name.")
    parser.add_argument("--game-path", help="Path to the game binary (overrides config/auto-detect).")
    parser.add_argument("--base-port", type=int, help="First bridge port to allocate.")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without running.")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
