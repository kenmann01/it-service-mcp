"""Trace of Thought / Action / Observation steps.

Every step is printed as it happens so a terminal capture doubles as the
submission screenshot, and stored structurally so the Reflector can review
the observations.
"""

from dataclasses import dataclass, field

_LABELS = {
    "thought": "[THOUGHT]",
    "action": "[ACTION]",
    "observation": "[OBSERVATION]",
    "route": "[ROUTE]",
    "draft": "[DRAFT]",
    "reflection": "[REFLECTION]",
    "error": "[ERROR]",
}


@dataclass
class TraceStep:
    """One labeled step in a ReAct trace."""

    type: str
    content: str


@dataclass
class Trace:
    """Ordered steps of one agent run, printed as they are added when echo is on."""

    echo: bool = True
    steps: list[TraceStep] = field(default_factory=list)

    def add(self, type: str, content: str) -> TraceStep:
        """Record a step and print it when echo is on."""
        step = TraceStep(type, content)
        self.steps.append(step)
        if self.echo:
            label = _LABELS.get(type, f"[{type.upper()}]")
            prefix = "\n" if type in ("thought", "draft") else ""
            print(f"{prefix}{label} {content}", flush=True)
        return step

    def observations(self) -> str:
        """Join observation steps for the reflector prompt."""
        return "\n".join(step.content for step in self.steps if step.type == "observation")

    def to_text(self) -> str:
        """Render the whole trace as labeled lines."""
        return "\n".join(
            f"{_LABELS.get(step.type, step.type.upper())} {step.content}" for step in self.steps
        )
