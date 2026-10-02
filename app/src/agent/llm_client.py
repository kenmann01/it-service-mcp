"""Ollama chat client with OpenAI-style tool calling, used by the TAO loop."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

# Host Ollama, reachable from inside Docker. Do not pull models in the container.
DEFAULT_HOST = "http://host.docker.internal:11434"
DEFAULT_MODEL = "qwen3:8b"

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _dotenv_value(name: str) -> str | None:
    """Read one key from the repo `.env`. Process env still wins in `from_env`."""
    env_path = _REPO_ROOT / ".env"
    if not env_path.is_file():
        return None
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return None


def strip_think(text: str) -> str:
    """Drop qwen3 <think> blocks so reasoning tokens never leak into drafts."""
    text = _THINK_RE.sub("", text)
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    return text.strip()


@dataclass
class ToolCall:
    """One tool call the model asked the agent to make."""

    id: str
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return this call in OpenAI/Ollama tool_calls shape."""
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }


@dataclass
class LLMResponse:
    """Parsed chat reply: assistant text and at most one tool call."""

    content: str | None
    tool_call: ToolCall | None = None

    @property
    def has_tool_call(self) -> bool:
        """True when the model asked for a tool."""
        return self.tool_call is not None


class OllamaClient:
    """Synchronous /api/chat client; parses tool_calls when the model emits them."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.3,
        timeout: float = 240.0,
        think: bool = False,
        keep_alive: str = "30m",
    ) -> None:
        """Bind the host, model, and chat options for one client."""
        self.host = host.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout  # generous: a cold start loads the model into VRAM
        self.think = think
        self.keep_alive = keep_alive

    @classmethod
    def from_env(cls) -> "OllamaClient":
        """Build a client from the process environment, then `.env`, then defaults."""
        return cls(
            host=os.environ.get("OLLAMA_HOST") or _dotenv_value("OLLAMA_HOST") or DEFAULT_HOST,
            model=os.environ.get("OLLAMA_MODEL") or _dotenv_value("OLLAMA_MODEL") or DEFAULT_MODEL,
        )

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        """POST one non-streaming /api/chat turn and parse the reply."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": self.think,
            "keep_alive": self.keep_alive,
            "options": {"temperature": self.temperature},
        }
        if tools:
            payload["tools"] = tools

        response = httpx.post(f"{self.host}/api/chat", json=payload, timeout=self.timeout)
        response.raise_for_status()
        message = response.json().get("message", {})
        content = strip_think(message.get("content") or "")

        calls = message.get("tool_calls") or []
        if calls:
            call = calls[0]
            function = call.get("function", {})
            return LLMResponse(
                content=content,
                tool_call=ToolCall(
                    id=call.get("id") or "call_1",
                    name=function.get("name", ""),
                    arguments=function.get("arguments") or {},
                ),
            )
        return LLMResponse(content=content)
