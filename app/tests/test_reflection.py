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
        """Store the replies this fake will return, in order."""
        self.script = iter(script)
        self.messages: list[list[dict]] = []

    def chat(self, messages, tools=None) -> LLMResponse:
        """Record the messages and return the next scripted reply."""
        self.messages.append(messages)
        return next(self.script)


def _trace_with_observation() -> Trace:
    """Build a silent trace that already has one policy observation."""
    trace = Trace(echo=False)
    trace.add("observation", '{"decision": "approve", "rule": "headphones_replacement"}')
    return trace


class ReflectTests(unittest.TestCase):
    """CONFIRMED keeps the draft; CORRECTED replaces it; anything else fails open."""

    def test_confirmed_keeps_the_draft(self) -> None:
        """A CONFIRMED reply leaves the original draft in place."""
        llm = FakeLLM([LLMResponse(content="CONFIRMED")])
        trace = _trace_with_observation()
        result = reflect("Your replacement headphones are approved.", trace, llm)
        self.assertTrue(result.confirmed)
        self.assertEqual(result.final_draft, "Your replacement headphones are approved.")

    def test_prompt_includes_draft_and_observations(self) -> None:
        """The review prompt contains the draft and the observation text."""
        llm = FakeLLM([LLMResponse(content="CONFIRMED")])
        trace = _trace_with_observation()
        reflect("Draft text.", trace, llm)
        prompt = llm.messages[0][-1]["content"]
        self.assertIn("Draft text.", prompt)
        self.assertIn("headphones_replacement", prompt)

    def test_corrected_replaces_the_draft(self) -> None:
        """A CORRECTED reply becomes the final draft and keeps the original."""
        llm = FakeLLM([LLMResponse(content="CORRECTED: The corrected draft.")])
        result = reflect("The draft.", _trace_with_observation(), llm)
        self.assertFalse(result.confirmed)
        self.assertEqual(result.final_draft, "The corrected draft.")
        self.assertEqual(result.original, "The draft.")

    def test_empty_correction_keeps_the_original(self) -> None:
        """A CORRECTED reply with no text keeps the original draft."""
        llm = FakeLLM([LLMResponse(content="CORRECTED:")])
        result = reflect("The draft.", _trace_with_observation(), llm)
        self.assertEqual(result.final_draft, "The draft.")

    def test_placeholder_echo_keeps_the_original(self) -> None:
        """A CORRECTED reply that echoes the prompt placeholder keeps the draft."""
        llm = FakeLLM([LLMResponse(content="CORRECTED: <the revised draft>")])
        result = reflect("Denied under employee_phone_second.", _trace_with_observation(), llm)
        self.assertEqual(result.final_draft, "Denied under employee_phone_second.")
        self.assertNotIn("<", result.final_draft)

    def test_unparseable_reply_fails_open(self) -> None:
        """A reply that is neither CONFIRMED nor CORRECTED keeps the draft."""
        llm = FakeLLM([LLMResponse(content="The draft looks fine to me.")])
        result = reflect("The draft.", _trace_with_observation(), llm)
        self.assertTrue(result.confirmed)
        self.assertEqual(result.final_draft, "The draft.")

    def test_prompt_includes_the_request(self) -> None:
        """The review prompt contains the sentence the requester wrote."""
        llm = FakeLLM([LLMResponse(content="CONFIRMED")])
        reflect("Draft text.", _trace_with_observation(), llm, request="My headphones broke.")
        prompt = llm.messages[0][-1]["content"]
        self.assertIn("My headphones broke.", prompt)

    def test_repeated_correction_cannot_keep_an_unstated_count(self) -> None:
        """A CORRECTED reply that still says 200 is filed without that count."""
        invented = "Grace, your request for 200 new headphones is approved."
        llm = FakeLLM(
            [
                LLMResponse(content=f"CORRECTED: {invented}"),
                LLMResponse(content=f"CORRECTED: {invented}"),
            ]
        )
        result = reflect(
            invented,
            _trace_with_observation(),
            llm,
            request="Hi, I'm Grace Hopper (E001). My headphones broke, so I need a replacement.",
        )
        self.assertNotIn("200", result.final_draft)
        self.assertIn("headphones", result.final_draft)
        self.assertFalse(result.confirmed)

    def test_retry_placeholder_echo_falls_back_to_the_strip(self) -> None:
        """A retry that echoes the placeholder cannot become the final letter."""
        invented = "Denied under employee_phone_second; you asked for 2 phones."
        llm = FakeLLM(
            [
                LLMResponse(content=f"CORRECTED: {invented}"),
                LLMResponse(content="CORRECTED: <the revised draft>"),
            ]
        )
        result = reflect(
            invented,
            _trace_with_observation(),
            llm,
            request="Hi, I'm Radia Perlman (E005). I want a second phone.",
        )
        self.assertNotIn("<", result.final_draft)
        self.assertNotIn("2", result.final_draft)
        self.assertFalse(result.confirmed)

    def test_a_count_written_in_the_request_is_kept(self) -> None:
        """A number the requester actually wrote survives the review."""
        llm = FakeLLM([LLMResponse(content="CONFIRMED")])
        draft = "Your request for 2 headphones is approved."
        result = reflect(draft, _trace_with_observation(), llm, request="I need 2 headphones.")
        self.assertEqual(result.final_draft, draft)
        self.assertEqual(len(llm.messages), 1)


if __name__ == "__main__":
    unittest.main()
