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
