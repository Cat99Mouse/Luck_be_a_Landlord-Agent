# LBALLM

LBALLM is the Luck be a Landlord equivalent of BalatroLLM.

It talks to the in-game LBALBot JSON-RPC bridge and uses an OpenAI-compatible
chat-completions model with tool calling. Defaults are set for Qwen/DashScope:

- `base_url`: `https://dashscope.aliyuncs.com/compatible-mode/v1`
- `model`: `qwen-plus`

Environment variables:

- `LBALLM_PROVIDER` (`qwen`, `openai`, or `heuristic`)
- `LBALLM_API_KEY` or `DASHSCOPE_API_KEY`
- `LBALLM_MODEL`
- `LBALLM_BASE_URL`
- `LBALLM_HOST`
- `LBALLM_PORT`
- `LBALLM_START_ACTION` (`new` or `continue`)

Run with Qwen/DashScope:

```powershell
uv run lballm --api-key $env:DASHSCOPE_API_KEY
```

Run a no-network smoke test with the deterministic fallback policy:

```powershell
uv run lballm --provider heuristic --max-steps 80
```

Detailed JSONL traces are enabled by default and written under `logs/`.
Default run directory names include the model, for example
`logs/lballm-agent-2026-07-09T17-30-00-gpt-5.4-mini/`.
They include prompts, model responses, tool calls, game actions, and results.
Use `--trace-path .\logs\latest-agent.jsonl` to choose a fixed trace file.
Standalone LLM payloads are also written under the trace stem:
`logs/latest-agent/latest-agent.jsonl`, `logs/latest-agent/requests.jsonl`,
and `logs/latest-agent/responses.jsonl`.

When removal tokens or manually destroyable items are available in `SLOTS`, the
agent asks the model for a pre-spin action: `remove_symbol`, `destroy_item`, or
`spin`.
