"""Ollama client checks with httpx faked. No live model."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent.llm_client import OllamaClient, strip_think


class _Response:
    """httpx-shaped reply that returns a prepared JSON body."""

    def __init__(self, payload: dict) -> None:
        """Store the JSON body chat() will read."""
        self._payload = payload

    def raise_for_status(self) -> None:
        """Pretend the POST succeeded."""
        return None

    def json(self) -> dict:
        """Return the prepared body."""
        return self._payload


class StripThinkTests(unittest.TestCase):
    """qwen3 think blocks never leak into a draft."""

    def test_closed_block_is_removed(self) -> None:
        """A finished think block is dropped and the surrounding text remains."""
        self.assertEqual(strip_think("hello <think>secret</think> world"), "hello  world")

    def test_unclosed_block_keeps_text_after_the_end_tag(self) -> None:
        """Text after a stray end tag is kept."""
        self.assertEqual(strip_think("hidden</think> visible"), "visible")

    def test_plain_text_is_unchanged(self) -> None:
        """Text with no think tags is returned stripped."""
        self.assertEqual(strip_think("  visible  "), "visible")


class FromEnvTests(unittest.TestCase):
    """Host and model come from the process, then .env, then the defaults."""

    def test_process_env_wins_over_dotenv(self) -> None:
        """OLLAMA_HOST and OLLAMA_MODEL override a conflicting .env file."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text(
                'OLLAMA_HOST="http://dotenv:11434"\nOLLAMA_MODEL="from-file"\n',
                encoding="utf-8",
            )
            with (
                patch("agent.llm_client._REPO_ROOT", root),
                patch.dict(
                    os.environ,
                    {"OLLAMA_HOST": "http://env:11434", "OLLAMA_MODEL": "from-env"},
                ),
            ):
                client = OllamaClient.from_env()
        self.assertEqual(client.host, "http://env:11434")
        self.assertEqual(client.model, "from-env")

    def test_dotenv_supplies_quoted_values_and_skips_comments(self) -> None:
        """A .env value is used when the process has neither variable."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text(
                "# comment\n"
                "ignored\n"
                'OLLAMA_HOST="http://dotenv:11434"\n'
                "OLLAMA_MODEL='custom-model'\n",
                encoding="utf-8",
            )
            env = {key: value for key, value in os.environ.items() if key not in ("OLLAMA_HOST", "OLLAMA_MODEL")}
            with patch("agent.llm_client._REPO_ROOT", root), patch.dict(os.environ, env, clear=True):
                client = OllamaClient.from_env()
        self.assertEqual(client.host, "http://dotenv:11434")
        self.assertEqual(client.model, "custom-model")

    def test_defaults_when_env_and_dotenv_are_absent(self) -> None:
        """The host default points at Ollama outside Docker, and the model is qwen3:8b."""
        with tempfile.TemporaryDirectory() as tmp:
            env = {key: value for key, value in os.environ.items() if key not in ("OLLAMA_HOST", "OLLAMA_MODEL")}
            with (
                patch("agent.llm_client._REPO_ROOT", Path(tmp)),
                patch.dict(os.environ, env, clear=True),
            ):
                client = OllamaClient.from_env()
        self.assertEqual(client.host, "http://host.docker.internal:11434")
        self.assertEqual(client.model, "qwen3:8b")

    def test_defaults_when_dotenv_has_no_matching_keys(self) -> None:
        """A .env that does not name the host or model still uses the defaults."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("# comment\nOTHER=value\n", encoding="utf-8")
            env = {key: value for key, value in os.environ.items() if key not in ("OLLAMA_HOST", "OLLAMA_MODEL")}
            with patch("agent.llm_client._REPO_ROOT", root), patch.dict(os.environ, env, clear=True):
                client = OllamaClient.from_env()
        self.assertEqual(client.host, "http://host.docker.internal:11434")
        self.assertEqual(client.model, "qwen3:8b")

    def test_init_strips_a_trailing_slash(self) -> None:
        """The host stored on the client has no trailing slash."""
        client = OllamaClient(host="http://host.docker.internal:11434/")
        self.assertEqual(client.host, "http://host.docker.internal:11434")


class ChatTests(unittest.TestCase):
    """chat() parses /api/chat without opening a socket."""

    def _post(self, payload: dict, tools: list[dict] | None = None) -> tuple[object, dict]:
        """POST through a fake and return the parsed reply plus the JSON body sent."""
        captured: dict = {}

        def fake_post(url: str, json: dict, timeout: float) -> _Response:
            """Record the request and return the prepared payload."""
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            return _Response(payload)

        client = OllamaClient(host="http://host.docker.internal:11434/", model="qwen3:8b", timeout=12)
        with patch("agent.llm_client.httpx.post", fake_post):
            response = client.chat([{"role": "user", "content": "hi"}], tools=tools)
        return response, captured

    def test_reply_without_a_tool_call_returns_content(self) -> None:
        """A message with no tool_calls is content only, posted to /api/chat."""
        response, captured = self._post({"message": {"content": "hello <think>x</think> there"}})
        self.assertEqual(response.content, "hello  there")
        self.assertIsNone(response.tool_call)
        self.assertEqual(captured["url"], "http://host.docker.internal:11434/api/chat")
        self.assertNotIn("tools", captured["json"])

    def test_tool_call_maps_id_name_and_arguments(self) -> None:
        """A tool call keeps the id, name, and arguments from the message."""
        response, captured = self._post(
            {
                "message": {
                    "content": "looking up",
                    "tool_calls": [
                        {
                            "id": "abc",
                            "function": {
                                "name": "get_employee_info",
                                "arguments": {"employee_id": "E001"},
                            },
                        }
                    ],
                }
            },
            tools=[{"type": "function", "function": {"name": "get_employee_info"}}],
        )
        self.assertEqual(response.content, "looking up")
        self.assertIsNotNone(response.tool_call)
        assert response.tool_call is not None
        self.assertEqual(response.tool_call.id, "abc")
        self.assertEqual(response.tool_call.name, "get_employee_info")
        self.assertEqual(response.tool_call.arguments, {"employee_id": "E001"})
        self.assertEqual(
            captured["json"]["tools"],
            [{"type": "function", "function": {"name": "get_employee_info"}}],
        )

    def test_missing_id_and_arguments_use_defaults(self) -> None:
        """A tool call with no id or arguments becomes call_1 and an empty dict."""
        response, _captured = self._post(
            {"message": {"content": "", "tool_calls": [{"function": {"name": "ping"}}]}}
        )
        assert response.tool_call is not None
        self.assertEqual(response.tool_call.id, "call_1")
        self.assertEqual(response.tool_call.name, "ping")
        self.assertEqual(response.tool_call.arguments, {})
        self.assertEqual(response.tool_call.to_dict()["function"]["name"], "ping")
