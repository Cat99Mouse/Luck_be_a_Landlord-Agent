"""Process manager for a Luck be a Landlord instance."""

from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import httpx

from .config import Config

HEALTH_TIMEOUT = 30.0


class LBALInstance:
    """Start/stop one Luck be a Landlord process and wait for LBALBot health."""

    def __init__(self, config: Config | None = None, **overrides) -> None:
        base = config or Config.from_env()
        self._config = replace(base, **overrides) if overrides else base
        self._process: subprocess.Popen | None = None
        self._log_path: Path | None = None

    @property
    def port(self) -> int:
        return self._config.port

    @property
    def log_path(self) -> Path | None:
        return self._log_path

    async def start(self) -> None:
        if self._process is not None:
            raise RuntimeError("Instance already started")
        self._config.validate()
        if self._config.session_log_dir:
            session_dir = Path(self._config.session_log_dir)
        else:
            timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
            session_dir = Path(self._config.logs_path) / timestamp
        session_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = session_dir / f"{self._config.port}.log"

        env = os.environ.copy()
        env.update(self._config.to_env())
        game_path = Path(self._config.game_path or "")
        with self._log_path.open("w") as log:
            self._process = subprocess.Popen(
                [str(game_path)],
                cwd=str(game_path.parent),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        try:
            await self._wait_for_health()
        except Exception:
            await self.stop()
            raise

    async def _wait_for_health(self, timeout: float = HEALTH_TIMEOUT) -> None:
        url = f"http://{self._config.host}:{self._config.port}"
        payload = {"jsonrpc": "2.0", "method": "health", "params": {}, "id": 1}
        start = asyncio.get_running_loop().time()
        last_error = ""
        while asyncio.get_running_loop().time() - start < timeout:
            try:
                async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
                    response = await client.post(url, json=payload)
                    data = response.json()
                    if data.get("result", {}).get("status") == "ok":
                        return
                    last_error = repr(data)
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
            await asyncio.sleep(0.5)
        raise RuntimeError(
            f"Health check failed on {self._config.host}:{self._config.port}. "
            f"Last error: {last_error}. Log: {self._log_path}"
        )

    async def stop(self) -> None:
        if self._process is None:
            return
        proc = self._process
        self._process = None
        proc.terminate()
        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(loop.run_in_executor(None, proc.wait), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await loop.run_in_executor(None, proc.wait)

    async def __aenter__(self) -> "LBALInstance":
        await self.start()
        return self

    async def __aexit__(self, *_args) -> None:
        await self.stop()
