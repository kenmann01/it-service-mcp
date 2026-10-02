"""Ollama chat client with OpenAI-style tool calling, used by the TAO loop."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:8b"

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_think(text: str) -> str:
    """Drop qwen3 <think> blocks so reasoning tokens never leak into drafts."""
    text = _THINK_RE.sub("", text)
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    return text.strip()


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }


@dataclass
class LLMResponse:
    content: str | None
    tool_call: ToolCall | None = None

    @property
    def has_tool_call(self) -> bool:
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
        self.host = host.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout  # generous: a cold start loads the model into VRAM
        self.think = think
        self.keep_alive = keep_alive

    @classmethod
    def from_env(cls) -> "OllamaClient":
        return cls(
            host=os.environ.get("OLLAMA_HOST", DEFAULT_HOST),
            model=os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL),
        )

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
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
