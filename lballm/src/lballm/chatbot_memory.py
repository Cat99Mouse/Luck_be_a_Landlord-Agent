"""Minimal successful-action memory for chatbot control mode."""

from __future__ import annotations

from collections import deque
from typing import Any


class ChatbotMemory:
    """Tracks only the last successful game actions for prompt context."""

    def __init__(self, *, max_successful_actions: int = 10) -> None:
        self.successful_actions: deque[dict[str, Any]] = deque(
            maxlen=max_successful_actions
        )

    def observe_state(
        self,
        gamestate: dict[str, Any],
        *,
        step: int | None = None,
    ) -> None:
        return None

    def begin_spin(self, gamestate: dict[str, Any], *, step: int | None) -> None:
        return None

    def record_decision(
        self,
        *,
        step: int | None,
        action: str,
        arguments: dict[str, Any] | None,
        result: dict[str, Any],
        source: str,
    ) -> None:
        """Record a successfully executed action."""
        if not self._is_gamestate(result):
            return
        args = arguments or {}
        self.successful_actions.append(
            {
                "step": step,
                "source": source,
                "action": action,
                "target": self._decision_target(action, args),
                "result_state": result.get("state"),
                "effective_coins": self._effective_coins(result),
                "rent_values": self._copy_rent_values(result),
                "spins_taken": result.get("spins"),
                "times_rent_paid": result.get("times_rent_paid"),
                "reasoning": self._truncate(args.get("reasoning", ""), 220),
            }
        )

    def update_global(self, value: Any) -> None:
        return None

    def snapshot(self) -> dict[str, Any]:
        return {
            "recent_successful_actions": list(self.successful_actions),
        }

    @staticmethod
    def _decision_target(action: str, args: dict[str, Any]) -> str:
        if action == "choose":
            return str(args.get("choice", ""))
        if action == "remove_symbol":
            return str(args.get("symbol", ""))
        if action == "destroy_item":
            return str(args.get("item", ""))
        if action == "press_button":
            button = args.get("button")
            if isinstance(button, dict):
                return "index=" + str(args.get("index", 0)) + " args=" + str(
                    button.get("args", [])
                )
            return "index=" + str(args.get("index", 0))
        return ""

    @staticmethod
    def _is_gamestate(value: Any) -> bool:
        return isinstance(value, dict) and isinstance(value.get("state"), str)

    @staticmethod
    def _copy_rent_values(gamestate: dict[str, Any]) -> list[Any]:
        values = gamestate.get("rent_values")
        return list(values) if isinstance(values, list) else []

    @staticmethod
    def _effective_coins(gamestate: dict[str, Any]) -> float | int | None:
        value = gamestate.get("effective_coins")
        if value is not None:
            return value
        coins = gamestate.get("coins")
        queued = gamestate.get("queued_coins", 0)
        if coins is None:
            return None
        return coins + queued

    @staticmethod
    def _truncate(value: Any, limit: int) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."
