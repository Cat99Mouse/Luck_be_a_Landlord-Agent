"""Async JSON-RPC client for the LBALBot in-game bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import httpx


class LBALError(Exception):
    """Raised when the in-game bridge returns a JSON-RPC error."""

    def __init__(
        self,
        code: int,
        message: str,
        data: dict[Literal["name"], str] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.data = data or {"name": "UNKNOWN"}
        super().__init__(f"[{self.data['name']}] {message}")


@dataclass
class LBALClient:
    """Async JSON-RPC 2.0 client for LBALBot."""

    host: str = "127.0.0.1"
    port: int = 12346
    timeout: float = 30.0

    _client: httpx.AsyncClient | None = field(default=None, init=False, repr=False)
    _request_id: int = field(default=0, init=False, repr=False)

    async def __aenter__(self) -> "LBALClient":
        self._client = httpx.AsyncClient(
            base_url=f"http://{self.host}:{self.port}",
            timeout=self.timeout,
            trust_env=False,
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if self._client is None:
            raise RuntimeError("Client not connected. Use async with LBALClient().")

        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": self._request_id,
        }
        response = await self._client.post("/", json=payload)
        data = response.json()
        if "error" in data:
            err = data["error"]
            raise LBALError(err["code"], err["message"], err.get("data"))
        return data["result"]

