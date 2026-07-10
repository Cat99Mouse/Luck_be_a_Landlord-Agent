"""Replay destroy_item calls from an existing lballm trace.

This is a read-only log inspector. It does not connect to the game or execute
tools; it reconstructs the before/after states around destroy_item calls that
already happened in a trace.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_TRACE = Path(
    "logs/experiments/lballm-multi-model/gpt-5.5/run-01/trace"
)


def main() -> None:
    args = parse_args()
    trace_dir, trace_path, request_path = resolve_paths(args.path)
    events = load_jsonl(trace_path)
    requests = load_requests(request_path)
    report = build_report(events, requests, item=args.item)

    print_header(trace_dir, trace_path, request_path, args.item, report)
    print_call_table(report, mode=args.table)

    selected = selected_calls(report, args)
    if selected:
        print()
        print("Detailed calls:")
        for call in selected:
            print_call_detail(call, include_prompt=args.prompt)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect destroy_item(item) calls from a completed lballm trace."
        )
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=str(DEFAULT_TRACE),
        help=(
            "Trace directory containing trace.jsonl/requests.jsonl, or a "
            "trace.jsonl path. Defaults to gpt-5.5 run-01."
        ),
    )
    parser.add_argument(
        "--item",
        default="treasure_map",
        help="destroy_item target to inspect. Default: treasure_map.",
    )
    parser.add_argument(
        "--steps",
        help="Comma-separated step numbers to print in detail.",
    )
    parser.add_argument(
        "--all-details",
        action="store_true",
        help="Print detailed before/after state for every matching call.",
    )
    parser.add_argument(
        "--table",
        choices=["compact", "all", "none"],
        default="compact",
        help=(
            "How many one-line table rows to print. compact prints the first "
            "5, changed calls, and last 5. Default: compact."
        ),
    )
    parser.add_argument(
        "--prompt",
        action="store_true",
        help="Include prompt snippets around Destroyable items and Current items.",
    )
    return parser.parse_args()


def resolve_paths(path_text: str) -> tuple[Path, Path, Path]:
    path = Path(path_text)
    if path.is_dir():
        trace_dir = path
        trace_path = path / "trace.jsonl"
    else:
        trace_path = path
        trace_dir = path.parent
    request_path = trace_dir / "requests.jsonl"
    if not trace_path.exists():
        raise SystemExit(f"trace file not found: {trace_path}")
    if not request_path.exists():
        raise SystemExit(f"requests file not found: {request_path}")
    return trace_dir, trace_path, request_path


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_requests(path: Path) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for entry in load_jsonl(path):
        step = entry.get("step")
        if isinstance(step, int):
            out[step] = entry
    return out


def build_report(
    events: list[dict[str, Any]],
    requests: dict[int, dict[str, Any]],
    *,
    item: str,
) -> list[dict[str, Any]]:
    step_states = {
        event.get("step"): event.get("gamestate", {})
        for event in events
        if event.get("event") == "step"
    }
    report: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        if event.get("event") != "tool_call":
            continue
        if event.get("name") != "destroy_item":
            continue
        args = event.get("arguments") or {}
        if str(args.get("item")) != item:
            continue
        step = event.get("step")
        before = step_states.get(step, {})
        result = find_action_result(events, start=index, step=step)
        after = result.get("result", {}) if result else {}
        request = requests.get(step, {})
        report.append(
            {
                "step": step,
                "reasoning": str(args.get("reasoning", "")),
                "before": before,
                "after": after,
                "request": request,
                "action_result": result,
                "diff": diff_state(before, after, item),
            }
        )
    return report


def find_action_result(
    events: list[dict[str, Any]],
    *,
    start: int,
    step: int | None,
) -> dict[str, Any] | None:
    for event in events[start + 1 : start + 12]:
        if event.get("event") != "action_result":
            continue
        if event.get("step") != step:
            continue
        if event.get("method") == "destroy_item":
            return event
    return None


def diff_state(
    before: dict[str, Any],
    after: dict[str, Any],
    item: str,
) -> dict[str, Any]:
    before_item = target_items(before, item)
    after_item = target_items(after, item)
    before_destroyable = target_destroyable_items(before, item)
    after_destroyable = target_destroyable_items(after, item)
    changed_keys = [
        key
        for key in [
            "state",
            "effective_coins",
            "coins",
            "queued_coins",
            "spins",
            "rent_values",
            "times_rent_paid",
        ]
        if before.get(key) != after.get(key)
    ]
    symbols_changed = symbol_signature(before) != symbol_signature(after)
    items_changed = item_signature(before) != item_signature(after)
    noop = not changed_keys and not symbols_changed and not items_changed
    return {
        "changed_keys": changed_keys,
        "symbols_changed": symbols_changed,
        "items_changed": items_changed,
        "noop": noop,
        "target_before": before_item,
        "target_after": after_item,
        "destroyable_before": before_destroyable,
        "destroyable_after": after_destroyable,
    }


def symbol_signature(gamestate: dict[str, Any]) -> list[tuple[Any, ...]]:
    return [
        (
            symbol.get("type"),
            symbol.get("count"),
            symbol.get("value"),
            symbol.get("value_text"),
            symbol.get("times_displayed"),
        )
        for symbol in gamestate.get("symbol_inventory") or []
    ]


def item_signature(gamestate: dict[str, Any]) -> list[tuple[Any, ...]]:
    return [
        (
            item.get("type"),
            item.get("item_count"),
            item.get("destroyed"),
            item.get("destroyable"),
            item.get("disabled"),
            item.get("destroy_counters"),
        )
        for item in gamestate.get("items") or []
    ]


def target_items(gamestate: dict[str, Any], item: str) -> list[dict[str, Any]]:
    return [
        compact_item(entry)
        for entry in gamestate.get("items") or []
        if str(entry.get("type")) == item
    ]


def target_destroyable_items(
    gamestate: dict[str, Any],
    item: str,
) -> list[dict[str, Any]]:
    return [
        compact_item(entry)
        for entry in gamestate.get("destroyable_items") or []
        if str(entry.get("type")) == item
    ]


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
        "rarity",
        "description",
    ]
    return {key: entry.get(key) for key in keys if key in entry}


def print_header(
    trace_dir: Path,
    trace_path: Path,
    request_path: Path,
    item: str,
    report: list[dict[str, Any]],
) -> None:
    noops = sum(1 for call in report if call["diff"]["noop"])
    changed = len(report) - noops
    print(f"Trace dir: {trace_dir}")
    print(f"Trace file: {trace_path}")
    print(f"Requests: {request_path}")
    print(f"Target item: {item}")
    print(f"Matching destroy_item calls: {len(report)}")
    print(f"No-op calls: {noops}")
    print(f"Changed calls: {changed}")


def print_call_table(report: list[dict[str, Any]], *, mode: str) -> None:
    if mode == "none":
        return
    rows = report if mode == "all" else compact_table_rows(report)
    print()
    print("Matching calls:" if mode == "all" else "Matching calls (compact):")
    print(
        "step | noop | coins before->after | rent before->after | "
        "target before -> after | destroyable before -> after"
    )
    for call in rows:
        before = call["before"]
        after = call["after"]
        diff = call["diff"]
        print(
            f"{call['step']:>4} | "
            f"{str(diff['noop']):<5} | "
            f"{before.get('effective_coins')}->{after.get('effective_coins')} | "
            f"{before.get('rent_values')}->{after.get('rent_values')} | "
            f"{short_items(diff['target_before'])} -> "
            f"{short_items(diff['target_after'])} | "
            f"{short_items(diff['destroyable_before'])} -> "
            f"{short_items(diff['destroyable_after'])}"
        )
    if mode == "compact" and len(rows) < len(report):
        print(f"... {len(report) - len(rows)} rows omitted; use --table all")


def compact_table_rows(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for call in report[:5]:
        append_once(rows, call)
    for call in report:
        if not call["diff"]["noop"]:
            append_once(rows, call)
    for call in report[-5:]:
        append_once(rows, call)
    return sorted(rows, key=lambda call: call.get("step") or -1)


def selected_calls(
    report: list[dict[str, Any]],
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    if args.all_details:
        return report
    if args.steps:
        wanted = {
            int(part.strip())
            for part in args.steps.split(",")
            if part.strip()
        }
        return [call for call in report if call["step"] in wanted]
    selected: list[dict[str, Any]] = []
    for call in report[:3]:
        append_once(selected, call)
    for call in report:
        if not call["diff"]["noop"]:
            append_once(selected, call)
    for call in report[-3:]:
        append_once(selected, call)
    return selected


def append_once(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    if item not in items:
        items.append(item)


def print_call_detail(call: dict[str, Any], *, include_prompt: bool) -> None:
    before = call["before"]
    after = call["after"]
    diff = call["diff"]
    request = call["request"]
    print()
    print("=" * 80)
    print(f"step={call['step']} noop={diff['noop']}")
    print("reasoning:", truncate(call["reasoning"], 500))
    print_state("before", before)
    print("target item before:", json_dumps(diff["target_before"]))
    print("destroyable before:", json_dumps(diff["destroyable_before"]))
    print_state("after", after)
    print("target item after:", json_dumps(diff["target_after"]))
    print("destroyable after:", json_dumps(diff["destroyable_after"]))
    print(
        "changed:",
        {
            "keys": diff["changed_keys"],
            "symbols_changed": diff["symbols_changed"],
            "items_changed": diff["items_changed"],
        },
    )
    print("tool schema:", json_dumps(destroy_tool_schema(request)))
    if include_prompt:
        print_prompt_sections(request)


def print_state(label: str, gamestate: dict[str, Any]) -> None:
    print(
        f"{label}: "
        f"state={gamestate.get('state')} "
        f"stable={gamestate.get('stable')} "
        f"coins={gamestate.get('effective_coins')} "
        f"rent={gamestate.get('rent_values')} "
        f"spins={gamestate.get('spins')} "
        f"paid={gamestate.get('times_rent_paid')} "
        f"symbols_total={sum_symbol_counts(gamestate)} "
        f"items={len(gamestate.get('items') or [])}"
    )


def sum_symbol_counts(gamestate: dict[str, Any]) -> int:
    return sum((symbol.get("count") or 0) for symbol in gamestate.get("symbol_inventory") or [])


def destroy_tool_schema(request: dict[str, Any]) -> dict[str, Any] | None:
    for tool in request.get("tools") or []:
        function = tool.get("function") or {}
        if function.get("name") == "destroy_item":
            return function.get("parameters")
    return None


def print_prompt_sections(request: dict[str, Any]) -> None:
    messages = request.get("messages") or []
    if len(messages) < 2:
        return
    content = messages[1].get("content", "")
    for start, end in [
        ("Destroyable items:", "Available choices:"),
        ("Current items:", "Current symbol inventory:"),
    ]:
        start_index = content.find(start)
        end_index = content.find(end, start_index + 1)
        if start_index < 0:
            continue
        section = content[start_index:end_index if end_index >= 0 else None].strip()
        print()
        print(f"prompt section: {start}")
        print(section)


def short_items(items: list[dict[str, Any]]) -> str:
    if not items:
        return "[]"
    parts = []
    for item in items:
        parts.append(
            "{type=%s,count=%s,item_count=%s,destroy_counters=%s,"
            "destroyable=%s,destroyed=%s,disabled=%s}"
            % (
                item.get("type"),
                item.get("count"),
                item.get("item_count"),
                item.get("destroy_counters"),
                item.get("destroyable"),
                item.get("destroyed"),
                item.get("disabled"),
            )
        )
    return "[" + ", ".join(parts) + "]"


def truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


if __name__ == "__main__":
    main()
