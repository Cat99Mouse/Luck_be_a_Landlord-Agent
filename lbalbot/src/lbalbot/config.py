"""Configuration for launching Luck be a Landlord with LBALBot."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

ENV_MAP = {
    "host": "LBALBOT_HOST",
    "port": "LBALBOT_PORT",
    "game_path": "LBALBOT_GAME_PATH",
    "logs_path": "LBALBOT_LOGS_PATH",
}

INT_FIELDS = frozenset({"port"})


def _parse_env_value(field: str, value: str) -> int | str:
    if field in INT_FIELDS:
        return int(value)
    return value


def _default_game_path() -> str | None:
    workspace_copy = Path.cwd() / "dll" / "Luck be a Landlord.exe"
    if workspace_copy.exists():
        return str(workspace_copy)
    sibling_copy = Path.cwd().parent / "dll" / "Luck be a Landlord.exe"
    if sibling_copy.exists():
        return str(sibling_copy)
    steam_default = Path(
        r"C:\Program Files (x86)\Steam\steamapps\common\Luck be a Landlord"
    ) / "Luck be a Landlord.exe"
    if steam_default.exists():
        return str(steam_default)
    return None


@dataclass
class Config:
    """Launcher configuration."""

    host: str = "127.0.0.1"
    port: int = 12346
    game_path: str | None = None
    logs_path: str = "logs"
    session_log_dir: str | None = None

    @classmethod
    def from_env(cls) -> Self:
        kwargs: dict[str, Any] = {}
        for field, env_var in ENV_MAP.items():
            if (value := os.environ.get(env_var)) is not None:
                kwargs[field] = _parse_env_value(field, value)
        cfg = cls(**kwargs)
        if cfg.game_path is None:
            cfg.game_path = _default_game_path()
        return cfg

    def to_env(self) -> dict[str, str]:
        env = {
            "LBALBOT_HOST": self.host,
            "LBALBOT_PORT": str(self.port),
        }
        if self.game_path:
            env["LBALBOT_GAME_PATH"] = self.game_path
        return env

    def validate(self) -> None:
        if self.port < 1 or self.port > 65535:
            raise ValueError("port must be between 1 and 65535")
        if not self.game_path:
            raise ValueError("game_path is required")
        if not Path(self.game_path).exists():
            raise FileNotFoundError(self.game_path)
