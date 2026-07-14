"""OpenAI-compatible chat completions client."""

from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from .config import Config, get_model_config


class LLMClient:
    """Small wrapper around OpenAI-compatible chat completions."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=120.0,
            max_retries=5,
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ChatCompletion:
        model_config = get_model_config(self.config.model_config)
        return await self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            tools=tools,
            **model_config,
        )

