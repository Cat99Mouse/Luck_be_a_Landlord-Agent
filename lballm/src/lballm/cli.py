"""CLI for LBALLM."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

from lbalbot import Config as LBALBotConfig
from lbalbot import LBALInstance

from .bot import Bot
from .config import Config

LBALLM_CONFIG_ENV = "LBALLM_CONFIG"


def _resolve_config_path(value: str | None) -> Path | None:
    if value:
        return Path(value)
    if env := os.environ.get(LBALLM_CONFIG_ENV):
        return Path(env)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Play Luck be a Landlord with an LLM")
    parser.add_argument("--config", help="Path to YAML config")
    parser.add_argument("--provider", choices=["qwen", "openai", "heuristic"])
    parser.add_argument("--model")
    parser.add_argument("--strategy")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--base-url")
    parser.add_argument("--api-key")
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--start-action", choices=["new", "continue"])
    parser.add_argument("--game-path")
    parser.add_argument("--logs-path")
    parser.add_argument("--trace-path")
    parser.add_argument("--no-start-game", action="store_true")
    parser.add_argument("--no-heuristic-fallback", action="store_true")
    parser.add_argument("--no-trace", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if args.no_start_game:
        args.start_game = False
    if args.no_heuristic_fallback:
        args.fallback_to_heuristic = False
    if args.no_trace:
        args.trace_enabled = False

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = Config.load(_resolve_config_path(args.config), args)
    config.validate()
    result = asyncio.run(_run(config))
    print(result)


async def _run(config: Config) -> dict:
    if not config.start_game:
        bot = Bot(config)
        if bot.trace.path:
            logging.getLogger(__name__).info("Agent trace: %s", bot.trace.path)
        if bot.trace.artifact_dir:
            logging.getLogger(__name__).info(
                "LLM artifacts: %s",
                bot.trace.artifact_dir,
            )
        return await bot.play()

    bot_cfg = LBALBotConfig.from_env()
    bot_cfg.host = config.host
    bot_cfg.port = config.port
    bot_cfg.logs_path = config.logs_path
    if config.game_path is not None:
        bot_cfg.game_path = config.game_path
    async with LBALInstance(bot_cfg):
        bot = Bot(config)
        if bot.trace.path:
            logging.getLogger(__name__).info("Agent trace: %s", bot.trace.path)
        if bot.trace.artifact_dir:
            logging.getLogger(__name__).info(
                "LLM artifacts: %s",
                bot.trace.artifact_dir,
            )
        return await bot.play()
