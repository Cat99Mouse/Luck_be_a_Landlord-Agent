"""Fact-only run memory for prompt context."""

from __future__ import annotations

from collections import deque
from typing import Any


POST_RENT_STATES = {"SLOTS", "ADD_TILE", "ADD_ITEM"}


class RunMemory:
    """Tracks compact factual context derived from game state and actions."""

    def __init__(
        self,
        *,
        max_recent_decisions: int = 8,
        max_recent_spins: int = 8,
        max_permanent_changes: int = 16,
    ) -> None:
        self.recent_decisions: deque[dict[str, Any]] = deque(
            maxlen=max_recent_decisions
        )
        self.recent_spin_income: deque[dict[str, Any]] = deque(maxlen=max_recent_spins)
        self.removed_symbols: deque[dict[str, Any]] = deque(
            maxlen=max_permanent_changes
        )
        self.destroyed_items: deque[dict[str, Any]] = deque(
            maxlen=max_permanent_changes
        )
        self._last_state: dict[str, Any] | None = None
        self._cycle: dict[str, Any] | None = None
        self._cycle_spin_gains: list[float | int] = []
        self._pending_rent_key: tuple[int | None, int | None] | None = None
        self._pending_spin: dict[str, Any] | None = None

    def observe_state(self, gamestate: dict[str, Any], *, step: int | None = None) -> None:
        """Update memory from a gamestate returned by the bridge."""
        if not self._is_gamestate(gamestate):
            return
        self._last_state = gamestate
        self._observe_rent_cycle(gamestate)
        self._finish_spin_if_ready(gamestate, step=step)

    def begin_spin(self, gamestate: dict[str, Any], *, step: int | None) -> None:
        """Remember the effective coin count immediately before a spin."""
        if not self._is_gamestate(gamestate):
            return
        before = self._effective_coins(gamestate)
        if before is None:
            return
        self._pending_spin = {
            "step": step,
            "before_effective_coins": before,
            "spins_before": gamestate.get("spins"),
            "rent_values_before": self._copy_rent_values(gamestate),
        }

    def record_decision(
        self,
        *,
        step: int | None,
        action: str,
        arguments: dict[str, Any] | None,
        result: dict[str, Any],
        source: str,
    ) -> None:
        """Record a compact action/result fact for future prompts."""
        args = arguments or {}
        entry = {
            "step": step,
            "source": source,
            "action": action,
            "target": self._decision_target(action, args),
            "reasoning": self._truncate(args.get("reasoning", ""), 220),
        }
        if self._is_gamestate(result):
            entry.update(
                {
                    "result_state": result.get("state"),
                    "coins": self._effective_coins(result),
                    "rent_values": self._copy_rent_values(result),
                    "spins_taken": result.get("spins"),
                    "times_rent_paid": result.get("times_rent_paid"),
                }
            )
        self.recent_decisions.append(entry)
        self._record_permanent_change(step=step, action=action, args=args, result=result)

    def snapshot(self) -> dict[str, Any]:
        """Return JSON-serializable memory for prompt rendering and traces."""
        return {
            "current_rent_cycle": self._rent_cycle_snapshot(),
            "recent_spin_income": list(self.recent_spin_income),
            "recent_decisions": list(self.recent_decisions),
            "permanent_changes": {
                "previously_removed_symbols": list(self.removed_symbols),
                "destroyed_items": list(self.destroyed_items),
            },
        }

    def _observe_rent_cycle(self, gamestate: dict[str, Any]) -> None:
        rent_values = gamestate.get("rent_values") or []
        if len(rent_values) < 2:
            return
        target = self._to_int(rent_values[0])
        remaining = self._to_int(rent_values[1])
        paid = self._to_int(gamestate.get("times_rent_paid"))
        if target is None or remaining is None:
            return

        key = (paid, target)
        state = str(gamestate.get("state", ""))
        can_start_cycle = state in POST_RENT_STATES and remaining > 0

        if self._cycle is None:
            if can_start_cycle:
                self._start_cycle(gamestate, key=key, target=target, remaining=remaining)
            return

        current_key = self._cycle.get("rent_key")
        if key != current_key:
            self._pending_rent_key = key
            if can_start_cycle:
                self._start_cycle(gamestate, key=key, target=target, remaining=remaining)

    def _start_cycle(
        self,
        gamestate: dict[str, Any],
        *,
        key: tuple[int | None, int | None],
        target: int,
        remaining: int,
    ) -> None:
        self._cycle = {
            "rent_key": key,
            "rent_target": target,
            "spins_total": remaining,
            "spins_remaining_at_start": remaining,
            "cycle_start_effective_coins": self._effective_coins(gamestate),
            "start_spins_taken": gamestate.get("spins"),
            "times_rent_paid_at_start": gamestate.get("times_rent_paid"),
        }
        self._cycle_spin_gains = []
        self._pending_rent_key = None

    def _rent_cycle_snapshot(self) -> dict[str, Any] | None:
        if self._cycle is None or self._last_state is None:
            return None
        rent_values = self._last_state.get("rent_values") or []
        if len(rent_values) < 2:
            return None
        current_target = self._to_int(rent_values[0])
        current_remaining = self._to_int(rent_values[1])
        current_effective = self._effective_coins(self._last_state)
        start_effective = self._cycle.get("cycle_start_effective_coins")
        spins_total = self._to_int(self._cycle.get("spins_total"))
        if (
            current_target is None
            or current_remaining is None
            or current_effective is None
            or start_effective is None
            or spins_total is None
        ):
            return None

        spins_used = max(0, spins_total - current_remaining)
        net_gain = current_effective - start_effective
        spin_net_gain = sum(self._cycle_spin_gains)
        rent_gap = current_target - current_effective

        return {
            "rent_target": current_target,
            "spins_total": spins_total,
            "spins_used": spins_used,
            "spins_remaining": current_remaining,
            "cycle_start_effective_coins": self._round_number(start_effective),
            "current_effective_coins": self._round_number(current_effective),
            "rent_gap": self._round_number(rent_gap),
            "net_gain": self._round_number(net_gain),
            "spin_net_gain": self._round_number(spin_net_gain),
            "spins_recorded": len(self._cycle_spin_gains),
            "times_rent_paid_at_start": self._cycle.get("times_rent_paid_at_start"),
        }

    def _finish_spin_if_ready(
        self,
        gamestate: dict[str, Any],
        *,
        step: int | None,
    ) -> None:
        if self._pending_spin is None:
            return
        if gamestate.get("state") == "SPINNING" or not gamestate.get("stable", True):
            return
        after = self._effective_coins(gamestate)
        before = self._pending_spin.get("before_effective_coins")
        if after is None or before is None:
            return
        net_gain = after - before
        entry = {
            "step": self._pending_spin.get("step", step),
            "before_effective_coins": self._round_number(before),
            "after_effective_coins": self._round_number(after),
            "net_gain": self._round_number(net_gain),
            "result_state": gamestate.get("state"),
            "spins_taken": gamestate.get("spins"),
            "rent_values": self._copy_rent_values(gamestate),
        }
        self.recent_spin_income.append(entry)
        if self._spin_belongs_to_current_cycle(gamestate):
            self._cycle_spin_gains.append(net_gain)
        self._pending_spin = None

    def _spin_belongs_to_current_cycle(self, gamestate: dict[str, Any]) -> bool:
        if self._cycle is None:
            return False
        rent_values = gamestate.get("rent_values") or []
        if len(rent_values) < 1:
            return False
        paid = self._to_int(gamestate.get("times_rent_paid"))
        target = self._to_int(rent_values[0])
        return (paid, target) == self._cycle.get("rent_key")

    def _record_permanent_change(
        self,
        *,
        step: int | None,
        action: str,
        args: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        if not self._is_gamestate(result):
            return
        if action == "remove_symbol":
            symbol = args.get("symbol")
            if symbol:
                self.removed_symbols.append(
                    {
                        "step": step,
                        "symbol": str(symbol),
                        "removal_tokens_after": result.get("removal_tokens"),
                    }
                )
        elif action == "destroy_item":
            item = args.get("item")
            if item:
                self.destroyed_items.append(
                    {
                        "step": step,
                        "item": str(item),
                    }
                )

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
    def _to_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _round_number(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if value.is_integer():
                return int(value)
            return round(value, 2)
        return value

    @staticmethod
    def _truncate(value: Any, limit: int) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."
