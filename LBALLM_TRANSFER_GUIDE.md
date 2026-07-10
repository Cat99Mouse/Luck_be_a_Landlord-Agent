# LBALLM 克隆后运行指南

本文面向克隆本仓库的使用者，说明如何准备 Luck be a Landlord 游戏文件、安装依赖、patch 游戏 PCK，并运行自动游玩 agent。

## 克隆后的目录结构

克隆仓库后，目录结构应保持为：

```text
Luck_be_a_Landlord_Agent/
  dll/
    Luck be a Landlord.exe
    Luck be a Landlord.pck
    steam_api64.dll
    steam_appid.txt        # 可选；离开 Steam 目录启动时可能需要
  lbalbot/
  lballm/
```

`lballm` 通过相对路径依赖 `../lbalbot`，所以不要改变 `lbalbot/` 和 `lballm/` 的同级关系。
`dll/` 包含本地游戏文件，不上传到仓库；克隆仓库后需要手动准备。

## 前提条件

使用本仓库前需要满足：

- Windows 系统，推荐 Windows 10/11。
- 已安装 `uv`，用于创建 `.venv` 和安装 Python 依赖。
- Python 3.13 或更高版本。项目的 `pyproject.toml` 写的是 `requires-python = ">=3.13"`。
- 已配置 API key，例如 `DASHSCOPE_API_KEY`、`LBALLM_API_KEY`，或 `lballm/config/local.yaml`。
- 已安装或拥有合法的 Luck be a Landlord 本地游戏文件。克隆仓库后需要把游戏文件复制到 `dll/`，再用 `lbalbot` patch `Luck be a Landlord.pck`。


## 安装本地环境

### 1. 安装 uv

先在 PowerShell 中检查是否已有 `uv`：

```powershell
uv --version
```

如果没有安装，可以使用 `winget` 安装：

```powershell
winget install --id astral-sh.uv -e
```

安装后重新打开 PowerShell，再确认：

```powershell
uv --version
```

### 2. 准备 Python 3.13

如果系统已经安装 Python 3.13，可以直接进入下一步。

如果没有，可以让 `uv` 安装：

```powershell
uv python install 3.13
```

确认 Python 可用：

```powershell
uv python list
```

### 3. 准备项目文件

克隆后的仓库至少需要这些目录：

```text
Luck_be_a_Landlord_Agent/
  dll/
  lbalbot/
  lballm/
```

其中：

- `dll/` 不在仓库里，需要手动创建并放入游戏文件。
- `lballm/` 是 LLM agent。
- `lbalbot/` 是游戏 bridge、patch 和本地控制接口。
- `lballm` 会通过相对路径引用 `../lbalbot`，所以两个目录必须保持同级。

### 4. 准备 `dll/` 游戏文件

克隆仓库后，根目录默认没有 `dll/`。先从自己的 Luck be a Landlord 安装目录复制运行所需文件。Steam 默认目录通常是：

```text
C:\Program Files (x86)\Steam\steamapps\common\Luck be a Landlord
```

在仓库根目录执行：

```powershell
cd 路径\Luck_be_a_Landlord_Agent
New-Item -ItemType Directory -Force .\dll

$game = "C:\Program Files (x86)\Steam\steamapps\common\Luck be a Landlord"
Copy-Item "$game\Luck be a Landlord.exe" .\dll\
Copy-Item "$game\Luck be a Landlord.pck" .\dll\
Copy-Item "$game\steam_api64.dll" .\dll\ -ErrorAction SilentlyContinue
```

如果从 `dll/` 直接启动游戏时遇到 Steam API 相关错误，可以在 `dll/` 下创建 `steam_appid.txt`：

```powershell
Set-Content -Encoding ASCII .\dll\steam_appid.txt "1404850"
```

复制完成后，`dll/` 至少应包含：

```text
dll/
  Luck be a Landlord.exe
  Luck be a Landlord.pck
  steam_api64.dll          # 如果原游戏目录里有，建议一起复制
```

然后用 `lbalbot` patch PCK，注入本项目的 JSON-RPC bridge：

```powershell
cd 路径\Luck_be_a_Landlord_Agent\lbalbot
uv sync
uv run lbalbot patch "..\dll\Luck be a Landlord.pck"
```

patch 会在同目录生成 `Luck be a Landlord.pck.bak` 作为原始备份。之后运行 agent 时使用的就是 `dll/Luck be a Landlord.pck` 这个已 patch 版本。

## 首次准备

在仓库所在目录打开 PowerShell：

如果已经按上一步 patch 过 PCK，通常只需要在 `lballm` 目录同步一次：

```powershell
cd 路径\Luck_be_a_Landlord_Agent\lballm
uv sync
```

这会自动创建新的 `lballm\.venv`，并把 `../lbalbot` 作为本地依赖安装进去。

如果你还需要单独运行 `lbalbot` 命令，例如重新 patch PCK，也可以给 `lbalbot` 单独同步环境。准备 `dll/` 时如果已经执行过 `uv sync`，这里可以跳过：

```powershell
cd 路径\Luck_be_a_Landlord_Agent\lbalbot
uv sync
```

同步完成后可以检查：

```powershell
cd 路径\Luck_be_a_Landlord_Agent\lballm
uv run python --version
uv run python -c "import lballm, lbalbot; print('ok')"
```

如果不确定 `dll/Luck be a Landlord.pck` 是否已经 patch，重新 patch 一次：

```powershell
cd 路径\Luck_be_a_Landlord_Agent\lbalbot
uv run lbalbot patch "..\dll\Luck be a Landlord.pck"
```

## API 配置

可以使用环境变量：

```powershell
$env:LBALLM_API_KEY = "你的 API Key"
```

或使用配置文件，例如：

```powershell
cd 路径\Luck_be_a_Landlord_Agent\lballm
Copy-Item .\config\api.example.yaml .\config\local.yaml
```

然后编辑 `config/local.yaml`，填入 provider、model、base_url 和 api_key。

## 运行

推荐从 `lballm` 目录运行：

```powershell
cd 路径\Luck_be_a_Landlord_Agent\lballm
uv run lballm --config .\config\local.yaml
```

也可以直接通过命令行传参数：

```powershell
uv run lballm --provider openai --model gpt-5.4-mini --api-key $env:LBALLM_API_KEY
```

如果只想验证本地链路，不调用模型：

```powershell
uv run lballm --provider heuristic --max-steps 20
```

## 游戏路径解析

默认启动器会自动寻找：

```text
运行时工作目录\dll\Luck be a Landlord.exe
上级目录\dll\Luck be a Landlord.exe
Steam 默认安装目录
```

因此从 `Luck_be_a_Landlord_Agent\lballm` 运行时，通常会自动找到：

```text
Luck_be_a_Landlord_Agent\dll\Luck be a Landlord.exe
```

如果目录不同，可以显式指定：

```powershell
uv run lballm --config .\config\local.yaml --game-path "..\dll\Luck be a Landlord.exe"
```

## 日志

默认日志写在：

```text
lballm/logs/
```

默认 run 目录会包含模型名，例如：

```text
logs/lballm-agent-2026-07-09T17-44-26-gpt-5.4-mini/
```

目录中会有：

```text
lballm-agent-....jsonl
requests.jsonl
responses.jsonl
```

## 常见问题

### 找不到游戏路径

确认目录结构是否是：

```text
Luck_be_a_Landlord_Agent/dll/Luck be a Landlord.exe
Luck_be_a_Landlord_Agent/lballm/
```

或使用 `--game-path` 显式指定。

### Health check failed

通常表示游戏没有启动成功，或 PCK 没有 patch。检查：

- `dll/Luck be a Landlord.pck` 是否已 patch。
- 游戏是否被安全软件拦截。
- 端口 `12346` 是否被占用。

### 模型 API 报错

检查：

- API key 是否配置。
- `provider`、`model`、`base_url` 是否匹配。
- 当前网络环境是否能访问对应 API。

### 运行的是旧 bridge

如果换了 `lbalbot/src/lbalbot/bridge.gd`，需要重新 patch：

```powershell
cd 路径\Luck_be_a_Landlord_Agent\lbalbot
uv run lbalbot patch "..\dll\Luck be a Landlord.pck"
```

已经启动的游戏进程不会热加载新的 PCK，需要重启游戏。
