"""Serve the Internal IT Desk and stream one agent run over SSE.

From the repo root:
    uv run python app/scripts/web.py
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent.llm_client import OllamaClient
from agent.react import run_agent
from agent.trace import Trace, TraceStep

REPO_ROOT = Path(__file__).resolve().parents[2]
PAGE_PATH = REPO_ROOT / "app" / "web" / "index.html"
POOL_PATH = REPO_ROOT / "demo" / "request_pool.json"

HOST = "127.0.0.1"
PORT = 8765

_lock = threading.Lock()
_active: "Run | None" = None


class Run:
    """One desk case: steps buffered so a late or refreshed stream can catch up."""

    def __init__(self) -> None:
        """Start an empty event buffer that listeners can wait on."""
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.done = False
        self.cond = threading.Condition()

    def push(self, name: str, data: dict[str, Any]) -> None:
        """Append one SSE event and wake listeners."""
        with self.cond:
            self.events.append((name, data))
            self.cond.notify_all()

    def finish(self) -> None:
        """Mark the run complete so listeners exit after the last event."""
        with self.cond:
            self.done = True
            self.cond.notify_all()


def _samples() -> list[dict[str, Any]]:
    """Return the demo pool in the shape the desk chips expect."""
    pool = json.loads(POOL_PATH.read_text(encoding="utf-8"))
    cases = []
    for case in pool["cases"]:
        cases.append(
            {
                "id": case["id"],
                "bucket": case["bucket"],
                "request": case["request"],
                "expected_decision": case.get("expected_decision"),
                "expected_rule": case.get("expected_rule"),
            }
        )
    return cases


def _execute(request: str, run: Run) -> None:
    """Run the agent and push each trace step, then the result or the error."""

    def on_step(step: TraceStep) -> None:
        """Push one trace step onto the run as an SSE event."""
        run.push("step", {"type": step.type, "content": step.content})

    trace = Trace(echo=False, on_step=on_step)
    try:
        result = run_agent(request, trace=trace)
        run.push(
            "result",
            {
                "final_response": result.final_response,
                "decision": result.decision,
                "rule": result.rule,
                "review_id": result.review_id,
            },
        )
    except Exception as exc:
        run.push("error", {"message": str(exc)})
    finally:
        run.finish()


class DeskHandler(BaseHTTPRequestHandler):
    """Static page plus health, samples, a single run, and its event stream."""

    def log_message(self, format: str, *args: Any) -> None:
        """Write one access line to stderr as the client address and the message."""
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))

    def do_GET(self) -> None:
        """Serve the page, health, samples, or the event stream."""
        path = urlparse(self.path).path
        if path == "/":
            self._bytes(PAGE_PATH.read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/health":
            client = OllamaClient.from_env()
            self._json({"host": client.host, "model": client.model})
        elif path == "/api/samples":
            self._json({"cases": _samples()})
        elif path == "/api/events":
            self._events()
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        """Start one agent run for a non-empty request when none is already active."""
        global _active
        path = urlparse(self.path).path
        if path != "/api/run":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json({"error": "invalid json"}, status=400)
            return
        request = str(body.get("request") or "").strip()
        if not request:
            self._json({"error": "request is required"}, status=400)
            return
        with _lock:
            if _active is not None and not _active.done:
                self._json({"error": "a run is already in progress"}, status=409)
                return
            run = Run()
            _active = run
        threading.Thread(target=_execute, args=(request, run), daemon=True).start()
        self._json({"status": "started"}, status=202)

    def _events(self) -> None:
        """Stream the active run. Replays buffered steps, then waits until it finishes."""
        with _lock:
            run = _active
        if run is None:
            self._json({"error": "no active run"}, status=404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        index = 0
        try:
            while True:
                with run.cond:
                    if index >= len(run.events) and run.done:
                        break
                    if index >= len(run.events):
                        run.cond.wait(timeout=12)
                        pending = index >= len(run.events)
                    else:
                        pending = False
                    batch = run.events[index:]
                    index = len(run.events)
                if pending:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                for name, data in batch:
                    payload = f"event: {name}\ndata: {json.dumps(data)}\n\n"
                    self.wfile.write(payload.encode("utf-8"))
                if batch:
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        """Write a JSON response with the given status."""
        self._bytes(json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8", status)

    def _bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        """Write a response body with its content type and length."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    """Serve the desk on localhost:8765 until interrupted."""
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer((HOST, PORT), DeskHandler)
    print(f"Internal IT Desk at http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
