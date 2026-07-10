# Luck be a Landlord Automation Stack

This repository contains a Luck be a Landlord equivalent of the
BalatroBot/BalatroLLM split.

## Components

- `lbalbot/`: in-game control layer. It patches `Luck be a Landlord.pck` and
  injects a Godot GDScript JSON-RPC HTTP bridge into `res://Main.tscn`.
- `lballm/`: external agent layer. It starts or connects to the patched game,
  reads structured game state, renders prompts, calls a Qwen/OpenAI-compatible
  chat-completions model with tools, and sends JSON-RPC actions back to
  `lbalbot`.
- `dll/`: local-only game files. This directory is not committed to the
  repository. After cloning, copy your own game files into `dll/`; after patching,
  the patched PCK is `dll/Luck be a Landlord.pck` and the original backup is
  `dll/Luck be a Landlord.pck.bak`.

The API defaults match BalatroBot:

- host: `127.0.0.1`
- port: `12346`
- protocol: JSON-RPC 2.0 over HTTP POST

## Patch

```powershell
cd 路径\Luck_be_a_Landlord_Agent\lbalbot
.\.venv\Scripts\lbalbot.exe patch "..\dll\Luck be a Landlord.pck"
```

The repository does not include `dll/` or a patched PCK. After cloning, copy
your local Luck be a Landlord game files into `dll/`, then run the patch command
above to inject the LBALBot bridge.

## Run The Bridge

```powershell
cd 路径\Luck_be_a_Landlord_Agent\lbalbot
.\.venv\Scripts\lbalbot.exe start --game-path "..\dll\Luck be a Landlord.exe"
```

Useful API calls:

```powershell
.\.venv\Scripts\lbalbot.exe health
.\.venv\Scripts\lbalbot.exe call gamestate
```

## Run The Agent

No-network smoke test with the deterministic policy:

```powershell
cd 路径\Luck_be_a_Landlord_Agent\lballm
.\.venv\Scripts\lballm.exe --provider heuristic --max-steps 80
```

Qwen/DashScope run:

```powershell
cd 路径\Luck_be_a_Landlord_Agent\lballm
$env:DASHSCOPE_API_KEY = "..."
.\.venv\Scripts\lballm.exe --provider qwen --api-key $env:DASHSCOPE_API_KEY
```

Defaults:

- model: `qwen-plus`
- base URL: `https://dashscope.aliyuncs.com/compatible-mode/v1`
- start action: `new`
- heuristic fallback: enabled

## JSON-RPC Methods

- `health`
- `gamestate`
- `new_game`
- `continue_game`
- `spin`
- `remove_symbol` with `{"symbol": "symbol_type"}`
- `destroy_item` with `{"item": "item_type"}`
- `choose` with `{"choice": "symbol_or_item_type"}`
- `skip`
- `reroll`
- `button` with `{"index": 0}`

## Implementation Notes

Official Workshop mods are data-restricted, so the control bridge is injected
into the PCK instead of being packaged as a normal Workshop mod. The injected
bridge runs inside the Godot process and calls game objects directly. For
example, the `spin` endpoint calls `$"Reels".spin()`, matching the real spin
button target in `Buttons Menu.tscn`.

The external agent intentionally uses the same high-level architecture as the
Balatro stack: structured state in, one tool call out, JSON-RPC action
execution, then another state read.

Current gamestate also includes human-readable metadata for decision points:

- `choices[]`: `name`, `description`, `rarity`, `value`, `values`, and `groups`
  when available from the game data.
- `items[]`: current item metadata, including tooltip text where available.
- `symbol_inventory[]`: unique current symbols with counts and tooltip text,
  so the model can reason about the existing build without repeating every reel
  slot's description.
- `removable_symbols[]` and `destroyable_items[]`: pre-spin actions available
  before pressing the spin button.
