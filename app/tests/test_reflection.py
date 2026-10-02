"""Checks of the Reflector's CONFIRMED / CORRECTED handling, with a fake LLM."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent.llm_client import LLMResponse
from agent.reflection import reflect
from agent.trace import Trace


class FakeLLM:
    """Scripted chat(): returns prepared LLMResponse objects in order."""

    def __init__(self, script: list[LLMResponse]) -> None:
        self.script = iter(script)
        self.messages: list[list[dict]] = []

    def chat(self, messages, tools=None) -> LLMResponse:
        self.messages.append(messages)
        return next(self.script)


def _trace_with_observation() -> Trace:
    trace = Trace(echo=False)
    trace.add("observation", '{"decision": "approve", "rule": "headphones_replacement"}')
    return trace


class ReflectTests(unittest.TestCase):
    def test_confirmed_keeps_the_draft(self) -> None:
        llm = FakeLLM([LLMResponse(content="CONFIRMED")])
        trace = _trace_with_observation()
        result = reflect("Your replacement headphones are approved.", trace, llm)
        self.assertTrue(result.confirmed)
        self.assertEqual(result.final_draft, "Your replacement headphones are approved.")

    def test_prompt_includes_draft_and_observations(self) -> None:
        llm = FakeLLM([LLMResponse(content="CONFIRMED")])
        trace = _trace_with_observation()
        reflect("Draft text.", trace, llm)
        prompt = llm.messages[0][-1]["content"]
        self.assertIn("Draft text.", prompt)
        self.assertIn("headphones_replacement", prompt)

    def test_corrected_replaces_the_draft(self) -> None:
        llm = FakeLLM([LLMResponse(content="CORRECTED: The corrected draft.")])
        result = reflect("The draft.", _trace_with_observation(), llm)
        self.assertFalse(result.confirmed)
        self.assertEqual(result.final_draft, "The corrected draft.")
        self.assertEqual(result.original, "The draft.")

    def test_empty_correction_keeps_the_original(self) -> None:
        llm = FakeLLM([LLMResponse(content="CORRECTED:")])
        result = reflect("The draft.", _trace_with_observation(), llm)
        self.assertEqual(result.final_draft, "The draft.")

    def test_unparseable_reply_fails_open(self) -> None:
        llm = FakeLLM([LLMResponse(content="The draft looks fine to me.")])
        result = reflect("The draft.", _trace_with_observation(), llm)
        self.assertTrue(result.confirmed)
        self.assertEqual(result.final_draft, "The draft.")


if __name__ == "__main__":
    unittest.main()
