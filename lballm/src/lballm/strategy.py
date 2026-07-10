"""Strategy templates and tool schemas."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .config import STRATEGIES_DIR


class Strategy:
    """Loads prompt templates and tools for a strategy directory."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.path = STRATEGIES_DIR / name
        self.env = Environment(
            loader=FileSystemLoader(self.path),
            undefined=StrictUndefined,
            autoescape=False,
        )
        self.tools = json.loads((self.path / "TOOLS.json").read_text(encoding="utf-8"))

    def render_system(self) -> str:
        return self.env.get_template("SYSTEM.md.jinja").render()

    def render_state(
        self,
        gamestate: dict[str, Any],
        last_error: str | None,
        memory: dict[str, Any] | None = None,
    ) -> str:
        return self.env.get_template("GAMESTATE.md.jinja").render(
            G=gamestate,
            M=memory or {},
            last_error=last_error,
        )

    def get_tools(self, gamestate: dict[str, Any] | str) -> list[dict[str, Any]]:
        if isinstance(gamestate, str):
            state = gamestate
            current: dict[str, Any] = {}
        else:
            current = gamestate
            state = str(current.get("state", ""))

        if state == "SLOTS":
            return self._slots_tools(current)
        if state in {"ADD_TILE", "ADD_ITEM", "RENT_DUE"}:
            return self._choice_tools(current)
        return self._choice_tools(current)

    def _slots_tools(self, gamestate: dict[str, Any]) -> list[dict[str, Any]]:
        tool_by_name = {
            tool["function"]["name"]: tool
            for tool in self.tools.get("SLOTS", [])
        }
        tools: list[dict[str, Any]] = []

        if "spin" in tool_by_name:
            tools.append(deepcopy(tool_by_name["spin"]))

        removable_symbols = self._unique_types(gamestate.get("removable_symbols"))
        if removable_symbols and "remove_symbol" in tool_by_name:
            remove_tool = deepcopy(tool_by_name["remove_symbol"])
            symbol_schema = remove_tool["function"]["parameters"]["properties"][
                "symbol"
            ]
            symbol_schema["enum"] = removable_symbols
            symbol_schema["description"] = (
                "Exact type string from current removable_symbols."
            )
            tools.append(remove_tool)

        destroyable_items = self._unique_types(gamestate.get("destroyable_items"))
        if destroyable_items and "destroy_item" in tool_by_name:
            destroy_tool = deepcopy(tool_by_name["destroy_item"])
            item_schema = destroy_tool["function"]["parameters"]["properties"]["item"]
            item_schema["enum"] = destroyable_items
            item_schema["description"] = (
                "Exact type string from current destroyable_items."
            )
            tools.append(destroy_tool)

        return tools

    def _choice_tools(self, gamestate: dict[str, Any]) -> list[dict[str, Any]]:
        tool_by_name = {
            tool["function"]["name"]: tool
            for tool in self.tools.get("CHOICE", [])
        }
        tools: list[dict[str, Any]] = []

        choices = [
            str(choice.get("type"))
            for choice in gamestate.get("choices") or []
            if choice.get("type")
        ]
        if choices and "choose" in tool_by_name:
            choose_tool = deepcopy(tool_by_name["choose"])
            choice_schema = choose_tool["function"]["parameters"]["properties"][
                "choice"
            ]
            choice_schema["enum"] = choices
            choice_schema["description"] = (
                "Exact type string from the current choices. "
                "Use skip() to decline choices."
            )
            tools.append(choose_tool)

        buttons = gamestate.get("buttons") or []
        button_args = {
            str(arg)
            for button in buttons
            for arg in (button.get("args") or [])
        }
        if "skip" in button_args and "skip" in tool_by_name:
            tools.append(deepcopy(tool_by_name["skip"]))

        if (
            "reroll_pay" in button_args
            and self._int_value(gamestate.get("reroll_tokens")) > 0
            and "reroll_choices" in tool_by_name
        ):
            tools.append(deepcopy(tool_by_name["reroll_choices"]))

        if self._has_general_button(buttons) and "press_button" in tool_by_name:
            tools.append(deepcopy(tool_by_name["press_button"]))

        return tools

    @staticmethod
    def _unique_types(values: Any) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for value in values or []:
            if not isinstance(value, dict) or not value.get("type"):
                continue
            t = str(value["type"])
            if t in seen:
                continue
            seen.add(t)
            out.append(t)
        return out

    @staticmethod
    def _has_general_button(buttons: list[dict[str, Any]]) -> bool:
        specialized_args = {"skip", "reroll_pay"}
        for button in buttons:
            args = [str(arg) for arg in (button.get("args") or [])]
            if not args or args[0] not in specialized_args:
                return True
        return False

    @staticmethod
    def _int_value(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
