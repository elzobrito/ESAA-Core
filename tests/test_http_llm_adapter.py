from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from esaa.adapters.http_llm import HttpLlmAdapter
from esaa.service import ESAAService
from esaa.store import parse_event_store


class _Handler(BaseHTTPRequestHandler):
    contexts: list[dict[str, Any]] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler name
        length = int(self.headers.get("Content-Length", "0"))
        context = json.loads(self.rfile.read(length).decode("utf-8"))
        self.__class__.contexts.append(context)
        task = context["task"]

        if task["status"] == "todo":
            response = {
                "activity_event": {
                    "action": "claim",
                    "task_id": task["task_id"],
                    "prior_status": "todo",
                }
            }
        else:
            response = {
                "activity_event": {
                    "action": "complete",
                    "task_id": task["task_id"],
                    "prior_status": "in_progress",
                    "verification": {"checks": ["http-adapter-ok"]},
                },
                "file_updates": [
                    {"path": "docs/spec/T-1000.md", "content": "# HTTP adapter\n"}
                ],
            }

        body = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def test_http_llm_adapter_runs_claim_and_complete_against_fake_server(contract_bundle: Path) -> None:
    _Handler.contexts = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        url = f"http://127.0.0.1:{server.server_port}/agent"
        service = ESAAService(contract_bundle, adapter=HttpLlmAdapter(url=url, agent_id="agent-http"))
        service.init(force=True, with_demo_tasks=True)

        result = service.run(steps=2)

        assert result["steps_executed"] == 2
        assert (contract_bundle / "docs/spec/T-1000.md").read_text(encoding="utf-8") == "# HTTP adapter\n"
        events = parse_event_store(contract_bundle)
        assert [event["action"] for event in events if event["actor"] == "agent-http"] == ["claim", "complete"]
        assert [context["expected_action"] for context in _Handler.contexts] == ["claim", "complete"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

