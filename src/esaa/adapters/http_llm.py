from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from ..errors import ESAAError
from .base import AgentAdapter


class HttpLlmAdapter(AgentAdapter):
    def __init__(
        self,
        url: str,
        agent_id: str = "agent-http",
        token: str | None = None,
        timeout: float = 30.0,
        max_response_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        self.url = url
        self.agent_id = agent_id
        self.token = token
        self.timeout = timeout
        self.max_response_bytes = int(max_response_bytes)

    @classmethod
    def from_env(cls) -> HttpLlmAdapter:
        url = os.environ.get("ESAA_LLM_URL")
        if not url:
            raise ValueError("ESAA_LLM_URL is required for HttpLlmAdapter")
        return cls(
            url=url,
            agent_id=os.environ.get("ESAA_LLM_AGENT_ID", "agent-http"),
            token=os.environ.get("ESAA_LLM_TOKEN"),
            timeout=float(os.environ.get("ESAA_LLM_TIMEOUT", "30")),
            max_response_bytes=int(os.environ.get("ESAA_LLM_MAX_RESPONSE_BYTES", str(4 * 1024 * 1024))),
        )

    def health(self) -> dict[str, str]:
        return {"status": "ok", "url": self.url}

    def execute(self, dispatch_context: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(dispatch_context, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(self.max_response_bytes + 1)
                if len(raw) > self.max_response_bytes:
                    raise ESAAError(
                        "RESOURCE_LIMIT_EXCEEDED",
                        f"adapter response exceeds max_adapter_response_bytes={self.max_response_bytes}",
                    )
                payload = json.loads(raw.decode("utf-8"))
        except urllib.error.URLError as exc:
            raise ValueError(f"HTTP LLM adapter request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError("HTTP LLM adapter response was not valid JSON") from exc

        if "agent_result" in payload:
            payload = payload["agent_result"]
        if not isinstance(payload, dict) or "activity_event" not in payload:
            raise ValueError("HTTP LLM adapter response must be an agent_result envelope")
        return payload
