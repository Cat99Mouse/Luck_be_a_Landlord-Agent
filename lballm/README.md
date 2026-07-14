# LBALLM

LBALLM is the Luck be a Landlord equivalent of BalatroLLM.

It talks to the in-game LBALBot JSON-RPC bridge and uses an OpenAI-compatible
chat-completions model with tool calling. Defaults are set for Qwen/DashScope:

- `base_url`: `https://dashscope.aliyuncs.com/compatible-mode/v1`
- `model`: `qwen-plus`

## Modes

LBALLM separates the control flow from the decision provider.

Control modes:

- `agent` is the default multi-turn controller. It uses the `default` strategy,
  exposes observation tools, supports one local observation before the final game
  action in a decision, and maintains compact run memory.
- `chatbot` is a single-turn controller. It uses the `chatbot` strategy by
  default, does not expose observation tools, and only keeps the last successful
  actions as short context.

Providers:

- `qwen` uses DashScope's OpenAI-compatible chat completions endpoint.
- `openai` uses an OpenAI-compatible endpoint configured by `base_url`.
- `heuristic` uses a deterministic local fallback policy and does not call a
  model. This is useful for smoke tests.

`control_mode` and `provider` are independent settings. For example,
`--provider heuristic` is a no-network policy, while `--control-mode chatbot`
changes the prompt/tool flow used for model decisions.

## Agent mode features

In `agent` mode the full stored symbol inventory is intentionally not included
in the default prompt. The prompt includes current resources, visible choices,
visible buttons, current items, the visible reel grid, removable symbols, and
destroyable items.

The `inspect_symbol_inventory` observation tool is exposed in every decision.
It returns the full current stored symbol inventory without changing game state.
The controller supports a two-step model decision:

1. the model may call `inspect_symbol_inventory`;
2. after the observation result is appended locally, the model must return one
   legal game action.

Action tools in `agent` mode may include an optional `memory_update` field. When
present, it replaces the compact global memory paragraph shown in future
prompts. This memory is capped at 1200 characters and is treated as a working
note; current game state and tool results remain authoritative.

The structured run memory also keeps bounded recent facts:

- current rent-cycle summary;
- recent spin net income;
- recent decisions;
- recently removed symbols and destroyed items.

## Chatbot mode features

`chatbot` mode is designed as a simpler single-turn controller. It renders the
current state once and expects exactly one legal game action tool call.

Differences from `agent` mode:

- no `inspect_symbol_inventory` tool;
- no model-maintained global memory paragraph;
- no multi-turn inspect-then-act step inside one decision;
- prompt memory only includes the last successful actions.

Use it with:

```powershell
uv run lballm --config .\config\api.example.yaml --control-mode chatbot
```

If `control_mode: chatbot` is set and the strategy is left as `default`, LBALLM
automatically switches the strategy to `chatbot`.

## Tools and legality checks

Available tools depend on the current game state:

- `spin` starts the next spin in `SLOTS`.
- `remove_symbol` is exposed only when symbols are currently removable. Its
  schema enum is restricted to the current `removable_symbols`.
- `destroy_item` is exposed only when items are currently manually destroyable.
  Its schema enum is restricted to the current `destroyable_items`.
- `choose` is exposed for visible choices and its enum is restricted to the
  current visible choices.
- `skip` is exposed only when a visible skip button exists.
- `reroll_choices` is exposed only when a visible reroll-pay button exists and
  reroll tokens are available.
- `press_button` presses a visible event button by zero-based index. The runtime
  validates that the index points to a currently visible button before sending
  the action to the game bridge.

Environment variables:

- `LBALLM_CONFIG`
- `LBALLM_CONTROL_MODE` (`agent` or `chatbot`)
- `LBALLM_PROVIDER` (`qwen`, `openai`, or `heuristic`)
- `LBALLM_API_KEY`, `DASHSCOPE_API_KEY`, or `QWEN_API_KEY`
- `LBALLM_MODEL`
- `LBALLM_BASE_URL`
- `LBALLM_STRATEGY`
- `LBALLM_HOST`
- `LBALLM_PORT`
- `LBALLM_MAX_STEPS`
- `LBALLM_START_GAME`
- `LBALLM_START_ACTION` (`new` or `continue`)
- `LBALLM_FALLBACK_TO_HEURISTIC`
- `LBALLM_TRACE_ENABLED`
- `LBALLM_LOGS_PATH`
- `LBALLM_TRACE_PATH`
- `LBALLM_GAME_PATH`

Run with Qwen/DashScope:

```powershell
uv run lballm --api-key $env:DASHSCOPE_API_KEY
```

Run a no-network smoke test with the deterministic fallback policy:

```powershell
uv run lballm --provider heuristic --max-steps 80
```

Run the default agent controller with an explicit config:

```powershell
uv run lballm --config .\config\local.yaml --verbose
```

## Experiment runner

Run repeated experiments from `config/experiments.yaml`:

```powershell
uv run python scripts\run_experiments.py --config config\experiments.yaml
```

Preview the run plan without starting games:

```powershell
uv run python scripts\run_experiments.py --config config\experiments.yaml --dry-run
```

Force every planned run to a control mode without editing the YAML:

```powershell
uv run python scripts\run_experiments.py --config config\experiments.yaml --control-mode chatbot
```

When `--control-mode chatbot` is used, entries that still have
`strategy: default` are normalized to `strategy: chatbot`.

## Logs and traces

Detailed JSONL traces are enabled by default and written under `logs/`.
The default log root is split by control mode: `logs/agent/` for agent mode and
`logs/chatbot/` for chatbot mode.
Default run directory names include the model, for example
`logs/agent/lballm-agent-2026-07-14T17-30-00-gpt-5.5/` or
`logs/chatbot/lballm-chatbot-2026-07-14T17-30-00-gpt-5.5/`.

Each run directory may contain:

- the main trace file, named after the run directory;
- `requests.jsonl`, containing model request payloads and rendered prompts;
- `responses.jsonl`, containing raw model responses;
- `global_memory.jsonl`, containing global-memory changes in `agent` mode;
- the LBALBot game bridge log, such as `12346.log`, when LBALLM starts the game.

Use `--trace-path .\logs\latest-agent.jsonl` to choose a fixed trace file.
Standalone LLM payloads are also written under the trace stem:
`logs/latest-agent/latest-agent.jsonl`, `logs/latest-agent/requests.jsonl`,
and `logs/latest-agent/responses.jsonl`.

If `logs_path` is left as `logs`, LBALLM splits logs by control mode. If
`logs_path` is set to a custom path, that path is used directly.
