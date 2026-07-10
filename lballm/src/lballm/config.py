"""Configuration for LBALLM."""

from __future__ import annotations

import os
from argparse import Namespace
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised only without deps
    yaml = None

STRATEGIES_DIR = Path(__file__).parent / "strategies"

DEFAULT_MODEL_CONFIG: dict[str, Any] = {
    "parallel_tool_calls": False,
    "tool_choice": "auto",
    "extra_headers": {
        "X-Title": "LBALLM",
    },
    "extra_body": {},
}

ENV_MAP: dict[str, str] = {
    "provider": "LBALLM_PROVIDER",
    "model": "LBALLM_MODEL",
    "strategy": "LBALLM_STRATEGY",
    "host": "LBALLM_HOST",
    "port": "LBALLM_PORT",
    "base_url": "LBALLM_BASE_URL",
    "api_key": "LBALLM_API_KEY",
    "max_steps": "LBALLM_MAX_STEPS",
    "start_game": "LBALLM_START_GAME",
    "start_action": "LBALLM_START_ACTION",
    "fallback_to_heuristic": "LBALLM_FALLBACK_TO_HEURISTIC",
    "trace_enabled": "LBALLM_TRACE_ENABLED",
    "trace_path": "LBALLM_TRACE_PATH",
    "game_path": "LBALLM_GAME_PATH",
    "logs_path": "LBALLM_LOGS_PATH",
}

INT_FIELDS = frozenset({"port", "max_steps"})
BOOL_FIELDS = frozenset({"start_game", "fallback_to_heuristic", "trace_enabled"})
STRING_FIELDS = frozenset(
    {
        "provider",
        "model",
        "strategy",
        "host",
        "base_url",
        "api_key",
        "start_action",
        "trace_path",
        "game_path",
        "logs_path",
    }
)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def get_model_config(user_config: dict[str, Any] | None = None) -> dict[str, Any]:
    if not user_config:
        return DEFAULT_MODEL_CONFIG.copy()
    return _deep_merge(DEFAULT_MODEL_CONFIG, user_config)


def _parse_env_value(field: str, value: str) -> bool | int | str | None:
    if field in BOOL_FIELDS:
        return value in {"1", "true", "TRUE", "yes", "YES"}
    if field == "max_steps" and value.strip().lower() in {
        "",
        "none",
        "null",
        "unlimited",
    }:
        return None
    if field in INT_FIELDS:
        return int(value)
    return value


def _load_from_env() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field_name, env_var in ENV_MAP.items():
        if (val := os.environ.get(env_var)) is not None:
            result[field_name] = _parse_env_value(field_name, val)
    if "api_key" not in result:
        result["api_key"] = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get(
            "QWEN_API_KEY"
        )
    return {k: v for k, v in result.items() if v is not None}


def _load_from_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load YAML config files")
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    result: dict[str, Any] = {}
    for field_name in INT_FIELDS | STRING_FIELDS | BOOL_FIELDS:
        if field_name in data:
            result[field_name] = data[field_name]
    if isinstance(data.get("model_config"), dict):
        result["model_config"] = data["model_config"]
    return result


def _load_from_args(args: Namespace) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field_name in INT_FIELDS | STRING_FIELDS | BOOL_FIELDS:
        if (val := getattr(args, field_name, None)) is not None:
            result[field_name] = val
    return result


@dataclass
class Config:
    """Agent configuration."""

    provider: str = "qwen"
    model: str = "qwen-plus"
    strategy: str = "default"
    host: str = "127.0.0.1"
    port: int = 12346
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key: str | None = None
    max_steps: int | None = None
    start_game: bool = True
    start_action: str = "new"
    fallback_to_heuristic: bool = True
    trace_enabled: bool = True
    trace_path: str | None = None
    game_path: str | None = None
    logs_path: str = "logs"
    model_config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(
        cls,
        yaml_path: Path | None = None,
        args: Namespace | None = None,
    ) -> Self:
        data: dict[str, Any] = {}
        data.update(_load_from_env())
        if yaml_path:
            yaml_data = _load_from_yaml(yaml_path)
            if "model_config" in data and "model_config" in yaml_data:
                yaml_data["model_config"] = _deep_merge(
                    data["model_config"], yaml_data["model_config"]
                )
            data.update(yaml_data)
        if args:
            data.update(_load_from_args(args))
        return cls(**data)

    def validate(self) -> None:
        if self.provider not in {"qwen", "openai", "heuristic"}:
            raise ValueError("provider must be one of: qwen, openai, heuristic")
        if self.start_action not in {"new", "continue"}:
            raise ValueError("start_action must be 'new' or 'continue'")
        if self.provider != "heuristic" and not self.api_key:
            raise ValueError("api_key is required")
        if self.port < 1 or self.port > 65535:
            raise ValueError("port must be between 1 and 65535")
        if self.max_steps is not None and self.max_steps < 1:
            raise ValueError("max_steps must be >= 1")
        if not (STRATEGIES_DIR / self.strategy).exists():
            raise ValueError(f"strategy not found: {self.strategy}")
