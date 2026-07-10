"""Run repeated LBALLM experiments across multiple configured models."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from lballm.cli import _run
from lballm.config import Config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FIELDS = frozenset(Config.__dataclass_fields__)


def _safe_path_part(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "model"
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text)
    return text.strip(".-_")[:80] or "model"


def _timestamp_path_part(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H-%M-%S")


def _unique_experiment_dir(logs_root: Path, dirname: str) -> Path:
    candidate = logs_root / dirname
    if not candidate.exists():
        return candidate
    for index in range(2, 1000):
        candidate = logs_root / f"{dirname}-{index:02d}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not allocate experiment directory under {logs_root}")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = base.copy()
    for key, value in override.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"experiment config must be a YAML mapping: {path}")
    return data


def _resolve_path(value: str | Path, *, base: Path | None = None) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    candidates = []
    if base is not None:
        candidates.append(base / path)
    candidates.append(PROJECT_ROOT / path)
    candidates.append(Path.cwd() / path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _config_overrides(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    fields: dict[str, Any] = {}
    model_config: dict[str, Any] = {}
    for key, value in data.items():
        if key == "model_config":
            if not isinstance(value, dict):
                raise ValueError("model_config must be a mapping")
            model_config = value
        elif key in CONFIG_FIELDS:
            fields[key] = value
    return fields, model_config


def _build_run_config(
    base: Config,
    *,
    common: dict[str, Any],
    model_entry: dict[str, Any],
    logs_path: Path,
    trace_path: Path,
) -> Config:
    common_fields, common_model_config = _config_overrides(common)
    model_fields, model_model_config = _config_overrides(model_entry)
    model_config = _deep_merge(base.model_config, common_model_config)
    model_config = _deep_merge(model_config, model_model_config)
    fields = {
        **common_fields,
        **model_fields,
        "logs_path": str(logs_path),
        "trace_path": str(trace_path),
        "model_config": model_config,
    }
    return replace(base, **fields)


def _public_config(config: Config) -> dict[str, Any]:
    return {
        "provider": config.provider,
        "model": config.model,
        "strategy": config.strategy,
        "base_url": config.base_url,
        "max_steps": config.max_steps,
        "start_game": config.start_game,
        "start_action": config.start_action,
        "logs_path": config.logs_path,
        "trace_path": config.trace_path,
        "model_config": config.model_config,
    }


def _result_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": result.get("state"),
        "event": result.get("event"),
        "coins": result.get("coins"),
        "effective_coins": result.get("effective_coins"),
        "spins": result.get("spins"),
        "rent_values": result.get("rent_values"),
        "times_rent_paid": result.get("times_rent_paid"),
        "reroll_tokens": result.get("reroll_tokens"),
        "removal_tokens": result.get("removal_tokens"),
    }


def _run_end_summary(trace_path: str | None) -> dict[str, Any]:
    if trace_path is None:
        return {}
    path = Path(trace_path) / "trace.jsonl"
    if not path.exists():
        return {}
    run_end: dict[str, Any] | None = None
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("event") == "run_end":
                run_end = event
    if run_end is None:
        return {}
    return {
        "reason": run_end.get("reason"),
        "step": run_end.get("step"),
    }


def _game_outcome(
    result: dict[str, Any],
    *,
    run_end_reason: str | None,
) -> str:
    if run_end_reason == "game_over" or result.get("state") == "GAME_OVER":
        return "game_over"
    if run_end_reason is None:
        return "unknown"
    return "unfinished"


async def _run_all(args: argparse.Namespace) -> int:
    experiment_config = _resolve_path(args.config)
    data = _load_yaml(experiment_config)
    base_config_value = data.get("base_config", "local.yaml")
    base_config_path = _resolve_path(
        base_config_value,
        base=experiment_config.parent,
    )
    base = Config.load(base_config_path)
    base.validate()

    runs_per_model = int(args.runs or data.get("runs_per_model", 3))
    if runs_per_model < 1:
        raise ValueError("runs_per_model must be >= 1")

    models = data.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("experiment config must contain a non-empty models list")
    for entry in models:
        if not isinstance(entry, dict):
            raise ValueError("each model entry must be a mapping")

    common = data.get("overrides") or {}
    if not isinstance(common, dict):
        raise ValueError("overrides must be a mapping")

    experiment_name = str(
        args.name
        or data.get("experiment_name")
        or "experiment-" + datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    )
    logs_root = _resolve_path(data.get("logs_root", "logs/experiments"))
    experiment_run = _timestamp_path_part(datetime.now())
    experiment_dir = _unique_experiment_dir(logs_root, experiment_run)
    results_path = experiment_dir / "results.jsonl"

    plan: list[tuple[str, int, Config]] = []
    for model_entry in models:
        label = str(model_entry.get("name") or model_entry.get("model") or "model")
        safe_label = _safe_path_part(label)
        for run_index in range(1, runs_per_model + 1):
            run_dir = experiment_dir / safe_label / f"run-{run_index:02d}"
            cfg = _build_run_config(
                base,
                common=common,
                model_entry=model_entry,
                logs_path=run_dir / "game",
                trace_path=run_dir / "trace",
            )
            cfg.validate()
            plan.append((label, run_index, cfg))

    print(f"Experiment: {experiment_name}")
    print(f"Output directory: {experiment_dir}")
    print(f"Base config: {base_config_path}")
    print(f"Runs: {len(plan)} ({len(models)} models x {runs_per_model})")
    for label, run_index, cfg in plan:
        print(
            f"- {label} run {run_index}: provider={cfg.provider} "
            f"model={cfg.model} trace={cfg.trace_path}"
        )

    if args.dry_run:
        return 0

    experiment_dir.mkdir(parents=True, exist_ok=True)
    with results_path.open("a", encoding="utf-8") as results_file:
        for ordinal, (label, run_index, cfg) in enumerate(plan, 1):
            print(
                f"\n[{ordinal}/{len(plan)}] Running {label} "
                f"run {run_index} ({cfg.model})"
            )
            record: dict[str, Any] = {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "experiment": experiment_name,
                "model_label": label,
                "run_index": run_index,
                "experiment_run": experiment_dir.name,
                "experiment_dir": str(experiment_dir),
                "config": _public_config(cfg),
                "runner_status": "started",
            }
            results_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            results_file.flush()

            try:
                result = await _run(cfg)
            except Exception as exc:
                logging.exception("Experiment failed: %s run %s", label, run_index)
                record = {
                    **record,
                    "ts": datetime.now().isoformat(timespec="seconds"),
                    "runner_status": "error",
                    "run_end_reason": _run_end_summary(cfg.trace_path).get("reason"),
                    "game_outcome": "unknown",
                    "game_status": None,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                results_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                results_file.flush()
                if args.fail_fast:
                    return 1
                continue

            run_end = _run_end_summary(cfg.trace_path)
            run_end_reason = run_end.get("reason")
            record = {
                **record,
                "ts": datetime.now().isoformat(timespec="seconds"),
                "runner_status": "complete",
                "run_end_reason": run_end_reason,
                "run_end_step": run_end.get("step"),
                "game_outcome": _game_outcome(
                    result,
                    run_end_reason=run_end_reason,
                ),
                "game_status": result.get("state"),
                "game_event": result.get("event"),
                "result": _result_summary(result),
            }
            results_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            results_file.flush()
            print(
                f"Completed {label} run {run_index}: "
                f"runner_status={record['runner_status']} "
                f"game_outcome={record['game_outcome']} "
                f"run_end_reason={record['run_end_reason']} "
                f"result={record['result']}"
            )

    print(f"\nResults: {results_path}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run repeated LBALLM experiments for configured models.",
    )
    parser.add_argument(
        "--config",
        default="config/experiments.yaml",
        help="Experiment YAML path.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        help="Override runs_per_model from the experiment YAML.",
    )
    parser.add_argument(
        "--name",
        help="Override experiment_name from the experiment YAML.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned runs without starting games.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first failed run.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    raise SystemExit(asyncio.run(_run_all(args)))


if __name__ == "__main__":
    main()
