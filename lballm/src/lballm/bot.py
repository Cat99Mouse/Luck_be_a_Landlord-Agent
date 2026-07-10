"""Main gameplay loop for Luck be a Landlord."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from lbalbot import LBALClient, LBALError

from .config import Config
from .llm import LLMClient
from .memory import RunMemory
from .strategy import Strategy
from .trace import RunTrace, jsonable

logger = logging.getLogger(__name__)


class BotError(Exception):
    """Fatal agent error."""


class Bot:
    """LLM agent that plays through LBALBot."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.strategy = Strategy(config.strategy)
        self.client = LBALClient(host=config.host, port=config.port)
        self.llm = None if config.provider == "heuristic" else LLMClient(config)
        self.trace = RunTrace(
            logs_path=config.logs_path,
            trace_path=config.trace_path,
            enabled=config.trace_enabled,
            model_label=(
                "heuristic" if config.provider == "heuristic" else config.model
            ),
        )
        self.last_error: str | None = None
        self.memory = RunMemory()

    async def play(self) -> dict[str, Any]:
        """Run a game loop and return the final gamestate."""
        async with self.client:
            self.trace.write(
                "run_start",
                provider=self.config.provider,
                model=self.config.model,
                base_url=self.config.base_url,
                max_steps=self.config.max_steps,
                start_action=self.config.start_action,
            )
            try:
                await self._call_game("health", source="startup")
                gamestate = await self._call_game("gamestate", source="startup")
                step = 0
                while (
                    self.config.max_steps is None
                    or step < self.config.max_steps
                ):
                    state = gamestate.get("state", "")
                    logger.info("step=%s state=%s", step, state)
                    self.trace.write(
                        "step",
                        step=step,
                        state=state,
                        stable=gamestate.get("stable"),
                        gamestate=gamestate,
                    )
                    if state == "TITLE":
                        method = (
                            "new_game"
                            if self.config.start_action == "new"
                            else "continue_game"
                        )
                        gamestate = await self._call_game(
                            method,
                            step=step,
                            source="auto",
                        )
                    elif state == "SPINNING" or not gamestate.get("stable", True):
                        gamestate = await self._wait_for_stable(step=step)
                    elif state == "GAME_OVER":
                        self.trace.write(
                            "run_end",
                            reason="game_over",
                            step=step,
                            gamestate=gamestate,
                        )
                        return gamestate
                    elif state == "SLOTS":
                        if self._has_pre_spin_actions(gamestate):
                            if self.config.provider == "heuristic":
                                gamestate = await self._heuristic_choice(
                                    gamestate,
                                    step=step,
                                )
                            else:
                                gamestate = await self._llm_choice(gamestate, step=step)
                        else:
                            self.memory.begin_spin(gamestate, step=step)
                            gamestate = await self._call_game(
                                "spin",
                                step=step,
                                source="auto",
                            )
                    elif (
                        not gamestate.get("choices")
                        and len(gamestate.get("buttons") or []) == 1
                    ):
                        gamestate = await self._call_game(
                            "button",
                            {"index": 0},
                            step=step,
                            source="auto_single_button",
                        )
                    elif gamestate.get("choices") or gamestate.get("buttons"):
                        if self.config.provider == "heuristic":
                            gamestate = await self._heuristic_choice(
                                gamestate,
                                step=step,
                            )
                        else:
                            gamestate = await self._llm_choice(gamestate, step=step)
                    else:
                        await asyncio.sleep(0.25)
                        gamestate = await self._call_game(
                            "gamestate",
                            step=step,
                            source="idle_poll",
                        )
                    step += 1
                self.trace.write(
                    "run_end",
                    reason="max_steps",
                    step=step,
                    gamestate=gamestate,
                )
                return gamestate
            except Exception as e:
                self.trace.write(
                    "run_error",
                    error_type=type(e).__name__,
                    error=str(e),
                )
                raise

    async def _call_game(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        step: int | None = None,
        source: str,
    ) -> dict[str, Any]:
        call_params = params or {}
        self.trace.write(
            "action_request",
            step=step,
            source=source,
            method=method,
            params=call_params,
        )
        try:
            result = await self.client.call(method, call_params)
        except Exception as e:
            self.trace.write(
                "action_error",
                step=step,
                source=source,
                method=method,
                params=call_params,
                error_type=type(e).__name__,
                error=str(e),
            )
            raise
        self.trace.write(
            "action_result",
            step=step,
            source=source,
            method=method,
            params=call_params,
            result=result,
        )
        self.memory.observe_state(result, step=step)
        return result

    async def _wait_for_stable(
        self,
        timeout: float = 20.0,
        *,
        step: int | None = None,
    ) -> dict[str, Any]:
        start = asyncio.get_running_loop().time()
        gamestate = await self._call_game(
            "gamestate",
            step=step,
            source="wait_stable",
        )
        while asyncio.get_running_loop().time() - start < timeout:
            state = gamestate.get("state")
            if state != "SPINNING" and gamestate.get("stable", True):
                self.trace.write(
                    "wait_stable_done",
                    step=step,
                    elapsed=asyncio.get_running_loop().time() - start,
                    state=state,
                )
                return gamestate
            await asyncio.sleep(0.25)
            gamestate = await self._call_game(
                "gamestate",
                step=step,
                source="wait_stable",
            )
        self.trace.write(
            "wait_stable_timeout",
            step=step,
            elapsed=asyncio.get_running_loop().time() - start,
            gamestate=gamestate,
        )
        return gamestate

    async def _llm_choice(
        self,
        gamestate: dict[str, Any],
        *,
        step: int | None = None,
    ) -> dict[str, Any]:
        if self.llm is None:
            return await self._heuristic_choice(gamestate, step=step)
        memory = self.memory.snapshot()
        messages = [
            {"role": "system", "content": self.strategy.render_system()},
            {
                "role": "user",
                "content": self.strategy.render_state(
                    gamestate,
                    self.last_error,
                    memory,
                ),
            },
        ]
        tools = self.strategy.get_tools(gamestate)
        request_artifact = self.trace.write_llm_artifact(
            "request",
            step=step,
            payload={
                "state": gamestate.get("state"),
                "messages": messages,
                "tools": tools,
                "last_error": self.last_error,
                "memory": memory,
            },
        )
        self.trace.write(
            "llm_request",
            step=step,
            state=gamestate.get("state"),
            messages=messages,
            tools=tools,
            last_error=self.last_error,
            artifact=request_artifact,
        )
        response = await self.llm.chat(
            messages=messages,
            tools=tools,
        )
        response_payload = jsonable(response)
        response_artifact = self.trace.write_llm_artifact(
            "response",
            step=step,
            payload={"response": response_payload},
        )
        self.trace.write(
            "llm_response",
            step=step,
            response=response_payload,
            artifact=response_artifact,
        )
        tool_calls = response.choices[0].message.tool_calls or []
        if not tool_calls:
            self.last_error = "Model returned no tool call"
            return await self._fallback_choice(gamestate, step=step)
        call = tool_calls[0]
        fn_name = call.function.name
        try:
            args = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            self.last_error = "Model returned invalid JSON arguments"
            self.trace.write(
                "tool_parse_error",
                step=step,
                tool_call=jsonable(call),
                error=self.last_error,
            )
            return await self._fallback_choice(gamestate, step=step)

        self.trace.write(
            "tool_call",
            step=step,
            name=fn_name,
            arguments=args,
            raw_tool_call=jsonable(call),
        )

        try:
            if fn_name == "choose":
                if "choice" not in args:
                    raise BotError("choose requires choice")
                valid_choices = {
                    str(choice.get("type"))
                    for choice in gamestate.get("choices") or []
                    if choice.get("type")
                }
                if str(args["choice"]) not in valid_choices:
                    raise BotError(
                        "choose choice is not visible: " + str(args["choice"])
                    )
                gamestate = await self._call_game(
                    "choose",
                    {"choice": args["choice"]},
                    step=step,
                    source="llm_tool",
                )
            elif fn_name == "skip":
                if not self._has_button_arg(gamestate, "skip"):
                    raise BotError("skip requires a visible skip button")
                gamestate = await self._call_game(
                    "skip",
                    step=step,
                    source="llm_tool",
                )
            elif fn_name in {"reroll_choices", "reroll"}:
                if not self._has_button_arg(gamestate, "reroll_pay"):
                    raise BotError("reroll_choices requires a visible reroll button")
                if self._int_value(gamestate.get("reroll_tokens")) <= 0:
                    raise BotError("reroll_choices requires reroll tokens")
                gamestate = await self._call_game(
                    "reroll",
                    step=step,
                    source="llm_tool",
                )
            elif fn_name == "spin":
                self.memory.begin_spin(gamestate, step=step)
                gamestate = await self._call_game(
                    "spin",
                    step=step,
                    source="llm_tool",
                )
            elif fn_name == "remove_symbol":
                if "symbol" not in args:
                    raise BotError("remove_symbol requires symbol")
                if not self._has_target_type(
                    gamestate.get("removable_symbols"),
                    args["symbol"],
                ):
                    raise BotError(
                        "remove_symbol target is not removable: "
                        + str(args["symbol"])
                    )
                gamestate = await self._call_game(
                    "remove_symbol",
                    {"symbol": args["symbol"]},
                    step=step,
                    source="llm_tool",
                )
            elif fn_name == "destroy_item":
                if "item" not in args:
                    raise BotError("destroy_item requires item")
                if not self._has_target_type(
                    gamestate.get("destroyable_items"),
                    args["item"],
                ):
                    raise BotError(
                        "destroy_item target is not destroyable: "
                        + str(args["item"])
                    )
                gamestate = await self._call_game(
                    "destroy_item",
                    {"item": args["item"]},
                    step=step,
                    source="llm_tool",
                )
            elif fn_name == "press_button":
                button_index = int(args.get("index", 0))
                button = self._button_info(gamestate, button_index)
                args = {**args, "index": button_index}
                if button is not None:
                    args["button"] = button
                gamestate = await self._call_game(
                    "button",
                    {"index": button_index},
                    step=step,
                    source="llm_tool",
                )
            else:
                raise BotError(f"Unknown tool: {fn_name}")
            self.last_error = None
            self.memory.record_decision(
                step=step,
                action=fn_name,
                arguments=args,
                result=gamestate,
                source="llm_tool",
            )
            return gamestate
        except (BotError, LBALError) as e:
            self.last_error = str(e)
            self.trace.write(
                "tool_error",
                step=step,
                name=fn_name,
                arguments=args,
                error_type=type(e).__name__,
                error=str(e),
            )
            return await self._fallback_choice(gamestate, step=step)

    async def _fallback_choice(
        self,
        gamestate: dict[str, Any],
        *,
        step: int | None = None,
    ) -> dict[str, Any]:
        if not self.config.fallback_to_heuristic:
            return await self._call_game(
                "gamestate",
                step=step,
                source="fallback_disabled",
            )
        logger.warning("falling back to heuristic choice: %s", self.last_error)
        self.trace.write(
            "fallback_to_heuristic",
            step=step,
            reason=self.last_error,
            gamestate=gamestate,
        )
        return await self._heuristic_choice(gamestate, step=step)

    async def _heuristic_choice(
        self,
        gamestate: dict[str, Any],
        *,
        step: int | None = None,
    ) -> dict[str, Any]:
        """Small deterministic policy used for smoke tests and model fallbacks."""
        state = gamestate.get("state", "")
        if not gamestate.get("stable", True):
            self.trace.write("heuristic_decision", step=step, method="wait_stable")
            return await self._wait_for_stable(step=step)
        if state == "SLOTS":
            self.trace.write("heuristic_decision", step=step, method="spin")
            self.memory.begin_spin(gamestate, step=step)
            result = await self._call_game("spin", step=step, source="heuristic")
            self.memory.record_decision(
                step=step,
                action="spin",
                arguments={"reasoning": "heuristic"},
                result=result,
                source="heuristic",
            )
            return result

        choices = gamestate.get("choices") or []
        if choices:
            choice = max(choices, key=self._choice_score)
            self.trace.write(
                "heuristic_decision",
                step=step,
                method="choose",
                choice=choice,
            )
            result = await self._call_game(
                "choose",
                {"choice": choice["type"]},
                step=step,
                source="heuristic",
            )
            self.memory.record_decision(
                step=step,
                action="choose",
                arguments={"choice": choice["type"], "reasoning": "heuristic"},
                result=result,
                source="heuristic",
            )
            return result

        buttons = gamestate.get("buttons") or []
        if buttons:
            index = self._button_index(buttons)
            self.trace.write(
                "heuristic_decision",
                step=step,
                method="button",
                index=index,
                button=buttons[index],
            )
            result = await self._call_game(
                "button",
                {"index": index},
                step=step,
                source="heuristic",
            )
            self.memory.record_decision(
                step=step,
                action="press_button",
                arguments={
                    "index": index,
                    "button": buttons[index],
                    "reasoning": "heuristic",
                },
                result=result,
                source="heuristic",
            )
            return result

        self.trace.write("heuristic_decision", step=step, method="gamestate")
        return await self._call_game("gamestate", step=step, source="heuristic")

    @staticmethod
    def _has_pre_spin_actions(gamestate: dict[str, Any]) -> bool:
        return bool(
            gamestate.get("removable_symbols") or gamestate.get("destroyable_items")
        )

    @staticmethod
    def _choice_score(choice: dict[str, Any]) -> float:
        rarity_score = {
            "common": 0.0,
            "uncommon": 1.0,
            "rare": 2.0,
            "very_rare": 3.0,
        }.get(str(choice.get("rarity", "")), 0.0)
        value_match = re.search(r"-?\d+(\.\d+)?", str(choice.get("value", "0")))
        value = float(value_match.group(0)) if value_match else 0.0
        return value * 10.0 + rarity_score

    @staticmethod
    def _button_index(buttons: list[dict[str, Any]]) -> int:
        for index, button in enumerate(buttons):
            args = [str(arg) for arg in button.get("args", [])]
            if "pay_reply" in args:
                return index
        return 0

    @staticmethod
    def _button_info(
        gamestate: dict[str, Any],
        index: int,
    ) -> dict[str, Any] | None:
        buttons = gamestate.get("buttons") or []
        if index < 0 or index >= len(buttons):
            return None
        return buttons[index]

    @staticmethod
    def _has_button_arg(gamestate: dict[str, Any], expected: str) -> bool:
        for button in gamestate.get("buttons") or []:
            if expected in {str(arg) for arg in (button.get("args") or [])}:
                return True
        return False

    @staticmethod
    def _has_target_type(values: Any, expected: Any) -> bool:
        target = str(expected)
        for value in values or []:
            if isinstance(value, dict) and str(value.get("type")) == target:
                return True
        return False

    @staticmethod
    def _int_value(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
