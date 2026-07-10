"""Command line tools for LBALBot."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import typer

from .client import LBALClient
from .config import Config
from .manager import LBALInstance
from .patcher import patch_pck

app = typer.Typer(help="Luck be a Landlord automation bridge tools")


@app.command()
def patch(
    pck: Path = typer.Argument(..., help="Path to Luck be a Landlord.pck"),
    output: Path | None = typer.Option(None, help="Write patched PCK to this path"),
    no_backup: bool = typer.Option(False, help="Do not create .bak for in-place patch"),
) -> None:
    """Inject the JSON-RPC bridge into the game PCK."""
    target = patch_pck(pck, output_path=output, backup=not no_backup)
    typer.echo(f"Patched: {target}")


@app.command()
def health(
    host: str = "127.0.0.1",
    port: int = 12346,
) -> None:
    """Call the health endpoint."""
    asyncio.run(_call_and_print("health", {}, host, port))


@app.command()
def start(
    game_path: Path | None = typer.Option(None, help="Path to Luck be a Landlord.exe"),
    host: str = "127.0.0.1",
    port: int = 12346,
    logs_path: Path = Path("logs"),
) -> None:
    """Start the game and keep it running until interrupted."""

    async def _run() -> None:
        cfg = Config(
            host=host,
            port=port,
            game_path=str(game_path) if game_path else None,
            logs_path=str(logs_path),
        )
        if cfg.game_path is None:
            cfg = Config.from_env()
            cfg.host = host
            cfg.port = port
            cfg.logs_path = str(logs_path)
        async with LBALInstance(cfg) as instance:
            typer.echo(f"Started Luck be a Landlord on {host}:{port}")
            typer.echo(f"Log: {instance.log_path}")
            while True:
                await asyncio.sleep(3600)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        typer.echo("Stopped")


@app.command("call")
def call_method(
    method: str,
    host: str = "127.0.0.1",
    port: int = 12346,
) -> None:
    """Call a JSON-RPC method with empty params."""
    asyncio.run(_call_and_print(method, {}, host, port))


async def _call_and_print(
    method: str,
    params: dict[str, Any],
    host: str,
    port: int,
) -> None:
    async with LBALClient(host=host, port=port) as client:
        result = await client.call(method, params)
        typer.echo(result)
