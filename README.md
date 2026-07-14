# Luck be a Landlord Agent

<details open>
<summary>中文</summary>

## 项目简介

这是一个用于自动游玩《Luck be a Landlord》的 agent 项目。项目分为两层：

- `lbalbot/`: 游戏内控制层。负责 patch `Luck be a Landlord.pck`，向游戏注入 JSON-RPC bridge，并提供 `health`、`gamestate`、`spin`、`choose`、`skip`、`reroll` 等本地接口。
- `lballm/`: 外部 agent 层。负责读取游戏状态、构造 prompt、调用 OpenAI-compatible 模型或本地 heuristic 策略，并通过 `lbalbot` 执行动作。

默认本地控制接口是：

```text
http://127.0.0.1:12346
```

## 目录结构

```text
Luck_be_a_Landlord_Agent/
  lbalbot/                  # 游戏 bridge、PCK patch、JSON-RPC client/launcher
  lballm/                   # LLM agent、策略模板、运行配置
  dll/                      # 本地游戏文件，不提交到仓库
  LBALLM_TRANSFER_GUIDE.md  # 克隆后准备和运行指南
```

`dll/` 不包含在仓库中。克隆后需要从你自己的合法游戏安装目录复制游戏文件。

## 克隆后快速开始

安装依赖工具：

```powershell
uv --version
```

如果没有安装 `uv`：

```powershell
winget install --id astral-sh.uv -e
```

准备游戏文件：

```powershell
cd 路径\Luck_be_a_Landlord_Agent
New-Item -ItemType Directory -Force .\dll

$game = "C:\Program Files (x86)\Steam\steamapps\common\Luck be a Landlord"
Copy-Item "$game\Luck be a Landlord.exe" .\dll\
Copy-Item "$game\Luck be a Landlord.pck" .\dll\
Copy-Item "$game\steam_api64.dll" .\dll\ -ErrorAction SilentlyContinue
Set-Content -Encoding ASCII .\dll\steam_appid.txt "1404850"
```

安装 Python 依赖并 patch 游戏 PCK：

```powershell
cd 路径\Luck_be_a_Landlord_Agent\lbalbot
uv sync
uv run lbalbot patch "..\dll\Luck be a Landlord.pck"
```

同步 agent 环境：

```powershell
cd 路径\Luck_be_a_Landlord_Agent\lballm
uv sync
```

先用不调用模型的 heuristic 模式验证本地链路：

```powershell
uv run lballm --provider heuristic --max-steps 20
```

使用模型运行：

```powershell
Copy-Item .\config\api.example.yaml .\config\local.yaml
# 编辑 config\local.yaml，填写 provider、model、base_url 和 api_key
uv run lballm --config .\config\local.yaml --verbose
```

## 模式与新增功能

`lballm` 当前支持两种控制流程模式：

- `agent`：默认模式。支持工具调用、多轮“观察后行动”、完整储物间观察工具 `inspect_symbol_inventory`、全局记忆段落和详细 JSONL trace。
- `chatbot`：单轮决策模式。默认使用 `chatbot` 策略，不暴露观察工具，只把最近成功动作作为短上下文。

`provider` 与控制模式是两类配置：`qwen` / `openai` / `heuristic` 决定决策来源，`agent` / `chatbot` 决定 prompt 和工具流程。无模型本地验证可继续使用：

```powershell
uv run lballm --provider heuristic --max-steps 20
```

默认日志会按模式保存到 `lballm/logs/agent/` 或 `lballm/logs/chatbot/`。每局运行目录包含主 trace、`requests.jsonl`、`responses.jsonl`，agent 模式还会记录 `global_memory.jsonl`。详见 [LBALLM 说明](./lballm/README.md)。

## 并行实验

`lballm/scripts/run_parallel.py` 可以并行跑多局游戏，每局都是一个完全隔离的子进程，跑完后按模型汇总结果：

```bash
cd lballm
uv run python scripts/run_parallel.py --config config/experiments.yaml --runs 10 --parallel 4
```

- `--runs N`：覆盖 YAML 里的 `runs_per_model`。
- `--parallel N`：同时最多跑几局。
- `--base-port`：首个 bridge 端口（默认 `12346`）。
- `--dry-run`：只打印计划，不真正启动游戏。

并行逻辑：计划展开成 `模型 × 局数` 个 spec，每个 spec 分到唯一端口（`base_port + i`）、独立运行目录和独立 `HOME`/`XDG_*`（从参考 home 拷贝、排除存档），因此并发的多局不共享端口/存档/日志。`asyncio.Semaphore` 作为闸门，所有任务一次性创建、但同时只有 `parallel` 个真正运行，某局结束即释放名额、队列里下一局补上：

```python
sem = asyncio.Semaphore(parallel)
tasks = [
    asyncio.create_task(_run_one(spec, sem, i, len(plan), reference_home))
    for i, spec in enumerate(plan, 1)
]
records = await asyncio.gather(*tasks)
```

每个 `_run_one` 先抢名额，再以隔离环境启动子进程；某局崩溃（returncode != 0）只影响自己那条记录，不拖累其他局。结果写入 `<output_dir>/results.jsonl`，并在结束时打印每模型汇总（`runs` / `ok` / `game_over` / `avg_coins` / `avg_rent_paid` / `max_floor`）。

## 重要说明

- 不要提交 `dll/`，其中包含本地游戏文件。
- 不要提交 `.venv/`、`logs/`、`lballm/config/local.yaml`。
- 如果修改了 `lbalbot/src/lbalbot/bridge.gd`，需要重新执行 `uv run lbalbot patch "..\dll\Luck be a Landlord.pck"`。
- 已启动的游戏进程不会热加载新的 PCK，重新 patch 后需要重启游戏。

## 更多文档

- [克隆后运行指南](./LBALLM_TRANSFER_GUIDE.md)
- [LBALBot 说明](./lbalbot/README.md)
- [LBALLM 说明](./lballm/README.md)
- [API 配置说明](./lballm/API_CONFIG.md)

</details>

<details>
<summary>English</summary>

## Overview

This project is an automation agent for Luck be a Landlord. It has two main layers:

- `lbalbot/`: the in-game control layer. It patches `Luck be a Landlord.pck`, injects a JSON-RPC bridge into the game, and exposes local methods such as `health`, `gamestate`, `spin`, `choose`, `skip`, and `reroll`.
- `lballm/`: the external agent layer. It reads structured game state, renders prompts, calls an OpenAI-compatible model or a local heuristic policy, and sends actions back through `lbalbot`.

The default local control endpoint is:

```text
http://127.0.0.1:12346
```

## Repository Layout

```text
Luck_be_a_Landlord_Agent/
  lbalbot/                  # Game bridge, PCK patcher, JSON-RPC client/launcher
  lballm/                   # LLM agent, strategy templates, runtime config
  dll/                      # Local game files, not committed to the repository
  LBALLM_TRANSFER_GUIDE.md  # Clone-and-run guide
```

The `dll/` directory is intentionally not included in the repository. After cloning, copy the game files from your own legal local installation.

## Quick Start After Cloning

Check that `uv` is installed:

```powershell
uv --version
```

If `uv` is not installed:

```powershell
winget install --id astral-sh.uv -e
```

Prepare local game files:

```powershell
cd path\to\Luck_be_a_Landlord_Agent
New-Item -ItemType Directory -Force .\dll

$game = "C:\Program Files (x86)\Steam\steamapps\common\Luck be a Landlord"
Copy-Item "$game\Luck be a Landlord.exe" .\dll\
Copy-Item "$game\Luck be a Landlord.pck" .\dll\
Copy-Item "$game\steam_api64.dll" .\dll\ -ErrorAction SilentlyContinue
Set-Content -Encoding ASCII .\dll\steam_appid.txt "1404850"
```

Install dependencies and patch the game PCK:

```powershell
cd path\to\Luck_be_a_Landlord_Agent\lbalbot
uv sync
uv run lbalbot patch "..\dll\Luck be a Landlord.pck"
```

Sync the agent environment:

```powershell
cd path\to\Luck_be_a_Landlord_Agent\lballm
uv sync
```

Run a no-model local smoke test with the heuristic policy:

```powershell
uv run lballm --provider heuristic --max-steps 20
```

Run with a model:

```powershell
Copy-Item .\config\api.example.yaml .\config\local.yaml
# Edit config\local.yaml with provider, model, base_url, and api_key.
uv run lballm --config .\config\local.yaml --verbose
```

## Modes and New Features

`lballm` currently supports two control-flow modes:

- `agent`: the default mode. It supports tool calling, inspect-then-act
  decisions, the `inspect_symbol_inventory` observation tool, a compact global
  memory paragraph, and detailed JSONL traces.
- `chatbot`: a single-turn decision mode. It uses the `chatbot` strategy by
  default, does not expose observation tools, and only keeps recent successful
  actions as short context.

`provider` and control mode are separate settings. `qwen` / `openai` /
`heuristic` choose the decision source, while `agent` / `chatbot` choose the
prompt and tool flow. A no-model local smoke test still works with:

```powershell
uv run lballm --provider heuristic --max-steps 20
```

Default logs are split into `lballm/logs/agent/` or `lballm/logs/chatbot/`.
Each run directory contains the main trace, `requests.jsonl`, and
`responses.jsonl`; agent mode also records `global_memory.jsonl`. See
[LBALLM README](./lballm/README.md) for details.

## Parallel Experiments

`lballm/scripts/run_parallel.py` runs many games concurrently, each in a fully
isolated subprocess, and aggregates the results per model:

```bash
cd lballm
uv run python scripts/run_parallel.py --config config/experiments.yaml --runs 10 --parallel 4
```

- `--runs N` overrides `runs_per_model` from the YAML.
- `--parallel N` caps how many games run at the same time.
- `--base-port` sets the first bridge port (default `12346`).
- `--dry-run` prints the plan without launching any game.

The plan expands to `models × runs` specs. Each spec gets a unique bridge port
(`base_port + i`), its own run directory, and an isolated `HOME`/`XDG_*` seeded
from a reference home (saves excluded), so concurrent games never share ports,
saves, or logs. An `asyncio.Semaphore` gates concurrency: all tasks are created
up front, but only `parallel` run at once; as one finishes it releases the permit
and the next queued run starts:

```python
sem = asyncio.Semaphore(parallel)
tasks = [
    asyncio.create_task(_run_one(spec, sem, i, len(plan), reference_home))
    for i, spec in enumerate(plan, 1)
]
records = await asyncio.gather(*tasks)
```

Each `_run_one` acquires a permit, then launches the isolated subprocess. A
crashing run (returncode != 0) only affects its own record. Results are written
to `<output_dir>/results.jsonl`, and a per-model summary (`runs`, `ok`,
`game_over`, `avg_coins`, `avg_rent_paid`, `max_floor`) is printed at the end.

## Important Notes

- Do not commit `dll/`; it contains local game files.
- Do not commit `.venv/`, `logs/`, or `lballm/config/local.yaml`.
- If you change `lbalbot/src/lbalbot/bridge.gd`, run `uv run lbalbot patch "..\dll\Luck be a Landlord.pck"` again.
- A running game process will not hot-reload the patched PCK. Restart the game after patching.

## More Documentation

- [Clone-and-run guide](./LBALLM_TRANSFER_GUIDE.md)
- [LBALBot README](./lbalbot/README.md)
- [LBALLM README](./lballm/README.md)
- [API configuration guide](./lballm/API_CONFIG.md)

</details>
