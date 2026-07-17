"""Model-provider abstraction.

Every agent (triage / investigator / compliance) talks to a `ModelProvider`,
never to the Anthropic SDK directly. That keeps two things clean:

1. Swapping models per tier (Haiku for triage, Sonnet for investigation) is
   just a `model=` string, not a code branch.
2. A `ReplayProvider` can stand in for the real one with zero code changes
   in the agents, which is what lets the whole pipeline run deterministically
   with no API key and no cost.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.llm import transcripts


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ModelResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"


class ModelProvider(ABC):
    @abstractmethod
    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
        replay_family: str | None = None,
        replay_scenario: str = "low",
        replay_vars: dict[str, Any] | None = None,
    ) -> ModelResponse: ...

    @property
    @abstractmethod
    def is_live(self) -> bool: ...


class AnthropicProvider(ModelProvider):
    """Real Claude calls via the Anthropic SDK."""

    def __init__(self, api_key: str):
        import anthropic  # imported lazily so replay-only deployments don't need the key at import time

        self._client = anthropic.Anthropic(api_key=api_key)

    @property
    def is_live(self) -> bool:
        return True

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
        replay_family: str | None = None,
        replay_scenario: str = "low",
        replay_vars: dict[str, Any] | None = None,
    ) -> ModelResponse:
        kwargs: dict[str, Any] = {}
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice

        response = self._client.messages.create(
            model=model,
            max_tokens=1536,
            system=system,
            messages=messages,
            **kwargs,
        )

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))

        return ModelResponse(text="".join(text_parts), tool_calls=tool_calls, stop_reason=response.stop_reason)


class ReplayProvider(ModelProvider):
    """Deterministic, offline stand-in for AnthropicProvider.

    Not a mock in the "unit test double" sense - this is a genuine runtime
    mode of the deployed service, used whenever no API key is configured
    (e.g. the public Vercel showcase before you add one). It walks a fixed
    script of canned tool calls per agent/scenario, keyed by how many
    assistant turns have already happened in the conversation, so the same
    multi-turn tool-use loop shape works whether or not a real model is
    behind it.
    """

    @property
    def is_live(self) -> bool:
        return False

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
        replay_family: str | None = None,
        replay_scenario: str = "low",
        replay_vars: dict[str, Any] | None = None,
    ) -> ModelResponse:
        replay_vars = replay_vars or {}
        turn = sum(1 for m in messages if m.get("role") == "assistant")

        if replay_family == "triage":
            step = transcripts.triage_step(replay_scenario)
        elif replay_family == "investigation":
            steps = transcripts.investigation_steps(replay_scenario, **replay_vars)
            step = steps[min(turn, len(steps) - 1)]
        elif replay_family == "compliance":
            step = transcripts.compliance_step(replay_scenario, **replay_vars)
        else:
            step = {"text": "[replay mode: no script configured for this agent]"}

        return self._step_to_response(step)

    @staticmethod
    def _step_to_response(step: dict[str, Any]) -> ModelResponse:
        if "tool" in step:
            return ModelResponse(
                text="",
                tool_calls=[ToolCall(id=f"replay_{uuid.uuid4().hex[:8]}", name=step["tool"], input=step["input"])],
                stop_reason="tool_use",
            )
        return ModelResponse(text=step.get("text", ""), tool_calls=[], stop_reason="end_turn")


def get_provider(settings) -> ModelProvider:
    if settings.use_live_models:
        return AnthropicProvider(settings.anthropic_api_key)
    return ReplayProvider()
