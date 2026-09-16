"""A Strands model that replays fixed responses, to run real Agents offline.

Shared by the integration tests that drive a real `Agent` against MongoDB: the
model is the only part of the turn that must not leave the machine.
"""

from __future__ import annotations

from typing import Any

from strands.models.model import Model

USAGE = {"inputTokens": 1200, "outputTokens": 80, "totalTokens": 1280}
METRICS = {"latencyMs": 900}


def text_stream(text: str):
    """Stream events of an assistant turn that answers with plain text."""
    yield {"messageStart": {"role": "assistant"}}
    yield {"contentBlockDelta": {"delta": {"text": text}}}
    yield {"contentBlockStop": {}}
    yield {"messageStop": {"stopReason": "end_turn"}}
    yield {"metadata": {"usage": USAGE, "metrics": METRICS}}


def tool_stream(name: str, tool_use_id: str, payload: str):
    """Stream events of an assistant turn that calls a tool."""
    yield {"messageStart": {"role": "assistant"}}
    yield {
        "contentBlockStart": {
            "start": {"toolUse": {"name": name, "toolUseId": tool_use_id}}
        }
    }
    yield {"contentBlockDelta": {"delta": {"toolUse": {"input": payload}}}}
    yield {"contentBlockStop": {}}
    yield {"messageStop": {"stopReason": "tool_use"}}
    yield {"metadata": {"usage": USAGE, "metrics": METRICS}}


class ScriptedModel(Model):
    """Model that replays a fixed sequence of responses, repeating the last one."""

    def __init__(
        self, scripted: list[list[dict]], model_id: str = "test-model"
    ) -> None:
        self.config = {"model_id": model_id}
        self._scripted = scripted
        self._index = 0

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> Any:
        return self.config

    def structured_output(self, *args: Any, **kwargs: Any):
        raise NotImplementedError

    async def stream(self, *args: Any, **kwargs: Any):
        for event in self._scripted[min(self._index, len(self._scripted) - 1)]:
            yield event
        self._index += 1
