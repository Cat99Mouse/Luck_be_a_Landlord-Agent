"""Structured run trace logging."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


class RunTrace:
    """Append-only JSONL trace for agent runs."""

    def __init__(
        self,
        logs_path: str,
        trace_path: str | None = None,
        enabled: bool = True,
        model_label: str | None = None,
    ) -> None:
        self.enabled = enabled
        self.path: Path | None = None
        self.artifact_dir: Path | None = None
        self._artifact_counts: dict[str, int] = {"request": 0, "response": 0}
        if not enabled:
            return

        if trace_path:
            requested = Path(trace_path)
            if requested.suffix:
                self.artifact_dir = requested.with_suffix("")
                self.path = self.artifact_dir / requested.name
            else:
                self.artifact_dir = requested
                self.path = self.artifact_dir / f"{requested.name}.jsonl"
        else:
            timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
            run_name = f"lballm-agent-{timestamp}"
            safe_model = self._safe_path_part(model_label)
            if safe_model:
                run_name = f"{run_name}-{safe_model}"
            self.artifact_dir = Path(logs_path) / run_name
            self.path = self.artifact_dir / f"{run_name}.jsonl"
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        for kind in ("request", "response"):
            self._artifact_counts[kind] = self._count_jsonl_records(
                self._llm_artifact_path(kind)
            )

    def write(self, event: str, **fields: Any) -> None:
        """Write one JSONL event."""
        if not self.enabled or self.path is None:
            return
        payload = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "event": event,
            **fields,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    def write_llm_artifact(
        self,
        kind: str,
        *,
        step: int | None,
        payload: dict[str, Any],
    ) -> str | None:
        """Append an LLM request/response payload to requests/responses JSONL."""
        if not self.enabled or self.artifact_dir is None:
            return None
        if kind not in {"request", "response"}:
            raise ValueError("kind must be 'request' or 'response'")

        path = self._llm_artifact_path(kind)
        self._artifact_counts[kind] = self._artifact_counts.get(kind, 0) + 1
        index = self._artifact_counts[kind]
        data = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "kind": kind,
            "index": index,
            "step": step,
            **payload,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")
        return f"{path}#L{index}"

    def _llm_artifact_path(self, kind: str) -> Path:
        if self.artifact_dir is None:
            raise RuntimeError("trace artifact directory is not initialized")
        filename = "requests.jsonl" if kind == "request" else "responses.jsonl"
        return self.artifact_dir / filename

    @staticmethod
    def _count_jsonl_records(path: Path) -> int:
        if not path.exists():
            return 0
        with path.open("r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())

    @staticmethod
    def _safe_path_part(value: str | None) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        text = re.sub(r"[^A-Za-z0-9._-]+", "-", text)
        text = text.strip(".-_")
        return text[:80]


def jsonable(value: Any) -> Any:
    """Best-effort conversion for Pydantic/OpenAI response objects."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return value
