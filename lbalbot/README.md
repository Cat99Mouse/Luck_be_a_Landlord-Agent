# LBALBot

LBALBot is the Luck be a Landlord equivalent of BalatroBot.

It patches the Godot `Luck be a Landlord.pck` file by injecting a small
JSON-RPC HTTP bridge into `res://Main.tscn`. The bridge runs inside the game
process and exposes structured game state plus semantic actions such as
`spin`, `choose`, `skip`, and `reroll`.

Default API settings match BalatroBot:

- host: `127.0.0.1`
- port: `12346`
- protocol: JSON-RPC 2.0 over HTTP POST

## Patch

```powershell
uv run lbalbot patch "C:\path\to\Luck be a Landlord.pck"
```

The patcher writes a `.bak` backup by default before replacing the PCK.

## Smoke Test

After launching the patched game:

```powershell
uv run lbalbot health
uv run lbalbot call gamestate
```

Or let the launcher start the game and keep it open:

```powershell
uv run lbalbot start --game-path "..\dll\Luck be a Landlord.exe"
```

The main JSON-RPC methods are:

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
