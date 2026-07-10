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

- `provider`: `qwen`、`openai` 或 `heuristic`。默认用 `qwen`。
- `model`: Qwen 模型名，默认 `qwen-plus`。
- `base_url`: DashScope OpenAI-compatible endpoint。
- `api_key`: 模型 API key。也可以不写，改用 `DASHSCOPE_API_KEY` 环境变量。
- `host` / `port`: 本地游戏桥接 API，默认 `127.0.0.1:12346`。
- `start_game`: `true` 时由 agent 自动启动游戏。
- `start_action`: `new` 开新局，`continue` 继续存档。
- `fallback_to_heuristic`: 模型没返回合法 tool call 时，用本地规则策略兜底一步。
- `trace_enabled`: 是否写详细 JSONL 日志，默认 `true`。
- `trace_path`: 可选，指定详细日志文件路径；不填则自动写到 `logs/lballm-agent-时间.jsonl`。

## 详细日志

每次运行会写一个 JSONL trace 文件，默认位置类似：

```text
路径\Luck_be_a_Landlord_Agent\lballm\logs\lballm-agent-2026-07-09T12-00-00-gpt-5.4-mini\lballm-agent-2026-07-09T12-00-00-gpt-5.4-mini.jsonl
```

启动时控制台也会输出：

```text
Agent trace: logs\lballm-agent-....\lballm-agent-....jsonl
LLM artifacts: logs\lballm-agent-....
```

日志包含：

- 每一步 `gamestate`
- 发送给模型的完整 `system` / `user` prompt
- 传给模型的 tools schema
- 模型原始 response
- 解析出的 tool call 和参数
- 实际执行的 JSON-RPC 动作
- 动作返回结果或错误

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

## 无 API Key 测试

先确认本地控制链能跑：

```powershell
cd 路径\Luck_be_a_Landlord_Agent\lballm
.\.venv\Scripts\lballm.exe --provider heuristic --max-steps 80
```

这个模式不调用模型，只验证游戏启动、JSON-RPC、状态读取和动作执行。
