"""Replay a recorded trace into a live Luck be a Landlord instance.

The script starts the game through LBALBot, replays recorded action_request
events, then pauses before a target action so the live UI can be inspected.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from lbalbot import LBALClient, LBALError
from lbalbot.config import Config
from lbalbot.manager import LBALInstance


DEFAULT_TRACE_DIR = Path(
    "logs/experiments/lballm-multi-model/gpt-5.5/run-01/trace"
)
SKIP_METHODS = {"health", "gamestate"}


def main() -> None:
    args = parse_args()
    asyncio.run(run(args))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch the game and replay trace actions to a target step."
    )
    parser.add_argument(
        "trace",
        nargs="?",
        default=str(DEFAULT_TRACE_DIR),
        help="Trace directory or trace.jsonl path. Defaults to gpt-5.5 run-01.",
    )
    parser.add_argument(
        "--target-step",
        type=int,
        default=24,
        help="Stop before this recorded step's target action. Default: 24.",
    )
    parser.add_argument(
        "--target-method",
        default="destroy_item",
        help="Recorded action_request method to stop before. Default: destroy_item.",
    )
    parser.add_argument(
        "--target-item",
        default="treasure_map",
        help="For destroy_item, stop when params.item matches this value.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=12346)
    parser.add_argument(
        "--game-path",
        help="Path to Luck be a Landlord.exe. Defaults to lbalbot config lookup.",
    )
    parser.add_argument(
        "--logs-path",
        default="logs/live-replay",
        help="Game stdout log directory for the launched instance.",
    )
    parser.add_argument(
        "--attach",
        action="store_true",
        help="Attach to an already-running LBALBot instance instead of launching.",
    )
    parser.add_argument(
        "--no-confirm",
        action="store_true",
        help="Execute the target action immediately instead of waiting for Enter.",
    )
    parser.add_argument(
        "--leave-at-target",
        action="store_true",
        help=(
            "Stop before the target action, leave the launched game running, "
            "and exit without executing the target."
        ),
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    trace_path = resolve_trace_path(args.trace)
    events = load_jsonl(trace_path)
    actions = [
        event
        for event in events
        if event.get("event") == "action_request"
        and event.get("method") not in SKIP_METHODS
    ]

    instance: LBALInstance | None = None
    keep_running = False
    try:
        if not args.attach:
            cfg = Config(
                host=args.host,
                port=args.port,
                game_path=args.game_path,
                logs_path=args.logs_path,
            )
            if cfg.game_path is None:
                cfg = Config.from_env()
                cfg.host = args.host
                cfg.port = args.port
                cfg.logs_path = args.logs_path
            instance = LBALInstance(cfg)
            print("Starting Luck be a Landlord...")
            await instance.start()
            print(f"Game started on {args.host}:{args.port}")
            print(f"Game log: {instance.log_path}")
        else:
            print(f"Attaching to existing LBALBot at {args.host}:{args.port}")

        async with LBALClient(host=args.host, port=args.port) as client:
            await client.call("health")
            target = find_target_action(actions, args)
            if target is None:
                raise SystemExit("Target action not found in trace.")
            print(
                "Replaying actions before "
                f"step={target.get('step')} method={target.get('method')} "
                f"params={target.get('params') or {}}"
            )
            await replay_until_target(client, actions, target)
            before = await wait_stable(client)
            print()
            print("Reached target action. Inspect the live game window now.")
            print_state("before", before)
            print_target_details(before, args.target_item)

            if args.leave_at_target:
                keep_running = True
                print("Leaving game running at target state.")
                return

            if not args.no_confirm:
                answer = input(
                    "Press Enter to execute target via bridge; "
                    "type 'manual' to leave game running; "
                    "type 'stop' to stop: "
                ).strip().lower()
                if answer in {"manual", "m", "keep"}:
                    keep_running = True
                    print("Leaving game running for manual inspection.")
                    return
                if answer in {"stop", "q", "quit", "exit"}:
                    return

            print("Executing target action...")
            result = await client.call(
                str(target.get("method")),
                target.get("params") or {},
            )
            after = await wait_stable(client, initial=result)
            print_state("after", after)
            print_target_details(after, args.target_item)
            answer = input(
                "Press Enter to stop the launched game; "
                "type 'keep' to leave it running: "
            ).strip().lower()
            if answer in {"keep", "manual", "m"}:
                keep_running = True
                print("Leaving game running.")
    finally:
        if instance is not None and not keep_running:
            await instance.stop()


def resolve_trace_path(path_text: str) -> Path:
    path = Path(path_text)
    if path.is_dir():
        path = path / "trace.jsonl"
    if not path.exists():
        raise SystemExit(f"trace not found: {path}")
    return path


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def find_target_action(
    actions: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, Any] | None:
    for action in actions:
        if action.get("step") != args.target_step:
            continue
        if action.get("method") != args.target_method:
            continue
        params = action.get("params") or {}
        if args.target_method == "destroy_item" and params.get("item") != args.target_item:
            continue
        return action
    return None


async def replay_until_target(
    client: LBALClient,
    actions: list[dict[str, Any]],
    target: dict[str, Any],
) -> None:
    for action in actions:
        if action is target:
            return
        method = str(action.get("method"))
        params = action.get("params") or {}
        step = action.get("step")
        print(f"step={step} method={method} params={params}")
        before = await wait_stable(client)
        warn_if_action_not_visible(before, method, params)
        try:
            result = await client.call(method, params)
        except LBALError as error:
            print("Replay action failed.")
            print_state("current", before)
            print(f"error: {error}")
            raise
        await wait_stable(client, initial=result)


async def wait_stable(
    client: LBALClient,
    *,
    initial: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    state = initial if is_gamestate(initial) else await client.call("gamestate")
    loop = asyncio.get_running_loop()
    start = loop.time()
    while loop.time() - start < timeout:
        if state.get("state") != "SPINNING" and state.get("stable", True):
            return state
        await asyncio.sleep(0.25)
        state = await client.call("gamestate")
    return state


def is_gamestate(value: Any) -> bool:
    return isinstance(value, dict) and "state" in value


def warn_if_action_not_visible(
    gamestate: dict[str, Any],
    method: str,
    params: dict[str, Any],
) -> None:
    if method == "choose":
        choice = str(params.get("choice"))
        visible = {str(choice.get("type")) for choice in gamestate.get("choices") or []}
        if choice not in visible:
            print(f"WARNING: choice {choice!r} is not visible. visible={sorted(visible)}")
    elif method == "destroy_item":
        item = str(params.get("item"))
        visible = {
            str(entry.get("type"))
            for entry in gamestate.get("destroyable_items") or []
        }
        if item not in visible:
            print(
                f"WARNING: destroy item {item!r} is not listed. "
                f"destroyable={sorted(visible)}"
            )
    elif method == "remove_symbol":
        symbol = str(params.get("symbol"))
        visible = {
            str(entry.get("type"))
            for entry in gamestate.get("removable_symbols") or []
        }
        if symbol not in visible:
            print(
                f"WARNING: remove symbol {symbol!r} is not listed. "
                f"removable={sorted(visible)}"
            )


def print_state(label: str, gamestate: dict[str, Any]) -> None:
    print(
        f"{label}: state={gamestate.get('state')} "
        f"stable={gamestate.get('stable')} "
        f"coins={gamestate.get('effective_coins')} "
        f"rent={gamestate.get('rent_values')} "
        f"spins={gamestate.get('spins')} "
        f"paid={gamestate.get('times_rent_paid')} "
        f"symbols_total={sum_symbols(gamestate)}"
    )


def print_target_details(gamestate: dict[str, Any], item: str) -> None:
    current_items = [
        compact_item(entry)
        for entry in gamestate.get("items") or []
        if str(entry.get("type")) == item
    ]
    destroyable = [
        compact_item(entry)
        for entry in gamestate.get("destroyable_items") or []
        if str(entry.get("type")) == item
    ]
    print(f"current {item}: {json.dumps(current_items, ensure_ascii=False)}")
    print(f"destroyable {item}: {json.dumps(destroyable, ensure_ascii=False)}")


def compact_item(entry: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "type",
        "name",
        "count",
        "item_count",
        "destroy_counters",
        "destroyable",
        "destroyed",
        "disabled",
        "description",
    ]
    return {key: entry.get(key) for key in keys if key in entry}


def sum_symbols(gamestate: dict[str, Any]) -> int:
    return sum(
        (symbol.get("count") or 0)
        for symbol in gamestate.get("symbol_inventory") or []
    )


if __name__ == "__main__":
    main()
