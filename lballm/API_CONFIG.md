# LBALLM API 配置

这里配置的是外部 agent 层 `lballm` 调用模型 API 的参数。游戏内 API
仍然是本地 `127.0.0.1:12346`，不需要外网。

## 推荐方式：环境变量放 Key

PowerShell:

```powershell
cd 路径\Luck_be_a_Landlord_Agent\lballm
$env:DASHSCOPE_API_KEY = "你的DashScope API Key"
.\.venv\Scripts\lballm.exe --config .\config\api.example.yaml
```

这种方式不会把真实 key 写进文件。

也可以用 `LBALLM_CONFIG` 指定配置文件路径。配置优先级是：环境变量 < YAML 文件 < 命令行参数。

## 文件方式：写入 YAML

复制模板：

```powershell
cd 路径\Luck_be_a_Landlord_Agent\lballm
Copy-Item .\config\api.example.yaml .\config\local.yaml
```

然后打开 `config/local.yaml`，填写：

```yaml
provider: qwen
model: qwen-plus
base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
api_key: "你的DashScope API Key"
```

运行：

```powershell
.\.venv\Scripts\lballm.exe --config .\config\local.yaml
```

## 关键字段

- `control_mode`: 控制流程模式，`agent` 或 `chatbot`。默认 `agent`。
  - `agent`: 默认模式，支持观察工具、同一步内先观察再行动、全局记忆。
  - `chatbot`: 单轮决策模式，不暴露观察工具，只保留最近成功动作。
- `provider`: `qwen`、`openai` 或 `heuristic`。默认用 `qwen`。
  - `heuristic` 不调用模型，适合验证本地游戏控制链路。
- `model`: Qwen 模型名，默认 `qwen-plus`。
- `base_url`: DashScope OpenAI-compatible endpoint。
- `api_key`: 模型 API key。也可以不写，改用 `DASHSCOPE_API_KEY`、`QWEN_API_KEY` 或 `LBALLM_API_KEY` 环境变量。
- `strategy`: prompt 和 tools 模板目录。`control_mode: chatbot` 且未显式修改时，会自动使用 `chatbot` 策略。
- `host` / `port`: 本地游戏桥接 API，默认 `127.0.0.1:12346`。
- `start_game`: `true` 时由 agent 自动启动游戏。
- `start_action`: `new` 开新局，`continue` 继续存档。
- `game_path`: 可选，指定本地游戏 exe 路径。
- `fallback_to_heuristic`: 模型没返回合法 tool call 时，用本地规则策略兜底一步。
- `logs_path`: 日志根目录。默认 `logs`，运行时会按模式拆到 `logs/agent` 或 `logs/chatbot`。
- `trace_enabled`: 是否写详细 JSONL 日志，默认 `true`。
- `trace_path`: 可选，指定详细日志文件或目录；不填则自动写到当前模式的 run 目录。
- `model_config`: 透传给模型调用的附加配置，例如 `tool_choice`、`parallel_tool_calls`、`extra_headers` 和 `extra_body`。

## 模式选择

默认 agent 模式：

```yaml
control_mode: agent
strategy: default
```

agent 模式下，完整储物间符号不会默认写进 prompt。模型如果需要查看完整符号库存，需要调用 `inspect_symbol_inventory` 观察工具。观察结果只影响当前决策，不改变游戏状态。游戏动作工具可以带 `memory_update`，用于替换未来 prompt 中的一段全局记忆。

chatbot 模式：

```yaml
control_mode: chatbot
```

chatbot 模式每步只让模型做一次决策，不暴露 `inspect_symbol_inventory`，也不维护全局记忆段落。它只在 prompt 中保留最近成功动作作为短上下文。

无模型 smoke test：

```powershell
.\.venv\Scripts\lballm.exe --provider heuristic --max-steps 80
```

这个模式不需要 API key，用于确认游戏启动、JSON-RPC、状态读取和动作执行。

## 详细日志

每次运行会写一个 JSONL trace 文件，默认位置类似：

```text
路径\Luck_be_a_Landlord_Agent\lballm\logs\agent\lballm-agent-2026-07-14T12-00-00-gpt-5.5\lballm-agent-2026-07-14T12-00-00-gpt-5.5.jsonl
```

启动时控制台也会输出：

```text
Agent trace: logs\agent\lballm-agent-....\lballm-agent-....jsonl
LLM artifacts: logs\agent\lballm-agent-....
Game log: logs\agent\lballm-agent-....\12346.log
```

日志包含：

- 每一步 `gamestate`
- 发送给模型的完整 `system` / `user` prompt
- 传给模型的 tools schema
- 模型原始 response
- 解析出的 tool call 和参数
- 实际执行的 JSON-RPC 动作
- 动作返回结果或错误
- agent 模式下的全局记忆变化：`global_memory.jsonl`

如果 `control_mode: chatbot`，默认目录会变为：

```text
logs\chatbot\lballm-chatbot-时间-模型\
```

如果显式设置了非默认 `logs_path`，LBALLM 会直接使用该路径，不再自动追加 `agent` 或 `chatbot` 子目录。

指定固定日志文件：

```powershell
.\.venv\Scripts\lballm.exe --config .\config\local.yaml --trace-path .\logs\latest-agent.jsonl
```

同时会生成独立的 LLM 请求/响应文件夹：

```text
logs\latest-agent\latest-agent.jsonl
logs\latest-agent\requests.jsonl
logs\latest-agent\responses.jsonl
```

查看某一轮 prompt：

```powershell
Get-Content .\logs\latest-agent\requests.jsonl
```

查看对应模型回复：

```powershell
Get-Content .\logs\latest-agent\responses.jsonl
```
