"""The agent turn itself: prior history + a new prompt -> the agent's events.

Stateless by construction, exactly as the AgentService contract requires — the
turn holds nothing across calls. Each ``run_turn`` converts the Events passed in
into Anthropic Messages, asks the model for one response, and yields it back as
``AgentMessage`` Events (the service collects them into the RunTurn response).

The Anthropic client is injected rather than constructed here, so the turn can be
driven by the real Messages API in production and a fake in tests — the same seam
the Docker runtime uses for its Docker client. This module never imports
``anthropic``: it only speaks the Messages API's data shapes (a ``messages.create``
call and a response whose ``.content`` is a list of typed blocks), which keeps it
trivially fakeable.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from funky.type.v1 import agent_pb2, event_pb2, sandbox_pb2

# Anthropic requires an explicit output cap on every request. 4096 is generous
# for a single chat turn and well under every current Claude model's ceiling; a
# `max_tokens` field on AgentConfig is the natural place to make this per-agent
# later, the same way an `image` field on EnvironmentConfig would override the
# sandbox base image.
DEFAULT_MAX_TOKENS = 4096


class AnthropicAgentLoop:
    """One agent turn backed by the Anthropic Messages API."""

    def __init__(self, client, *, max_tokens: int = DEFAULT_MAX_TOKENS) -> None:
        self._client = client
        self._max_tokens = max_tokens

    def run_turn(
        self,
        agent_config: agent_pb2.AgentConfig,
        events: Sequence[event_pb2.Event],
        prompt: event_pb2.UserMessage,
        sandbox: sandbox_pb2.Sandbox,
    ) -> Iterator[event_pb2.Event]:
        """Run one turn and yield the agent's reply as ``AgentMessage`` Events.

        ``sandbox`` is accepted but not yet acted in: the agent has no tools to
        run there. Tool use — the ``AgentService ..> SandboxRuntime : exec`` edge
        in the architecture — lands once the Event proto grows tool-use and
        tool-result blocks to carry it; until then this is a text-only turn and
        the sandbox is the documented seam for that next step. (The Docker runtime
        accepts an agent whose skills it can't load yet for the same reason.)

        The yielded Events carry only their payload. id, session_id, and
        processed_at are the SessionStore's to assign when the Client appends the
        events to history, so they are deliberately left unset here.
        """
        messages: list[dict] = []
        for event in events:
            message = _to_message(event)
            if message is not None:
                messages.append(message)
        messages.append(_user_message(prompt))

        request: dict = {
            "model": agent_config.model,
            "max_tokens": self._max_tokens,
            "messages": messages,
        }
        # Omit `system` when empty rather than sending "": a blank system prompt
        # is a no-op, and leaving it off keeps the request minimal.
        if agent_config.system_prompt:
            request["system"] = agent_config.system_prompt

        response = self._client.messages.create(**request)
        for block in response.content:
            if getattr(block, "type", None) == "text":
                yield _agent_text_event(block.text)


def _to_message(event: event_pb2.Event) -> dict | None:
    """An Event as an Anthropic message, or ``None`` if it carries no known turn."""
    kind = event.WhichOneof("payload")
    if kind == "user_message":
        return {"role": "user", "content": _content(event.user_message.content)}
    if kind == "agent_message":
        return {"role": "assistant", "content": _content(event.agent_message.content)}
    return None


def _user_message(prompt: event_pb2.UserMessage) -> dict:
    """The new prompt as the turn's final user message."""
    return {"role": "user", "content": _content(prompt.content)}


def _content(blocks: Sequence[event_pb2.ContentBlock]) -> list[dict]:
    """Funky content blocks as Anthropic content blocks (text only, for now)."""
    out: list[dict] = []
    for block in blocks:
        if block.WhichOneof("block") == "text":
            out.append({"type": "text", "text": block.text.text})
    return out


def _agent_text_event(text: str) -> event_pb2.Event:
    """A payload-only AgentMessage Event wrapping a single text block."""
    return event_pb2.Event(
        agent_message=event_pb2.AgentMessage(
            content=[event_pb2.ContentBlock(text=event_pb2.TextBlock(text=text))]
        )
    )
