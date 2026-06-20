"""The agent turn itself: prior history + a new prompt -> the agent's events.

This is a real tool-use loop. The agent is given a single ``bash`` tool; each
round it calls the model, and for every tool call the model makes it runs the
command in the sandbox through a SandboxRuntime client and feeds the result back,
looping until the model stops calling tools. This is the
``AgentService ..> SandboxRuntime : exec`` edge from the architecture.

The model is reached through OpenRouter, which speaks the OpenAI **Chat
Completions** wire format — so this loop talks in that shape (a ``system`` role
message instead of a top-level ``system`` field, ``tools`` of ``type: function``,
tool calls returned in ``message.tool_calls`` with their arguments as a JSON
*string*, and tool results sent back as ``role: tool`` messages keyed by
``tool_call_id``). That is the one real difference from the Anthropic backend; the
Events it emits are identical, since Events are provider-agnostic.

The turn is stateless, as the AgentService contract requires — prior events are
passed in, never stored — and the Events it yields are payload-only: their Event
id, session_id, and processed_at are the SessionStore's to assign on append.
(``AgentToolUse.id`` is a different thing — the tool call's own handle, used to
pair a result with its call within the turn.)

Both clients are injected so the turn can run against the real OpenRouter API and
a real SandboxRuntime in production, and against fakes in tests. The module speaks
the Chat Completions API's data shapes (a ``chat.completions.create`` call, a
response whose ``.choices[0].message`` carries ``.content`` and ``.tool_calls``)
rather than importing ``openai``, which keeps it trivially fakeable.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence

from connectrpc.errors import ConnectError
from google.protobuf import json_format

from funky.sandbox.v1 import sandbox_runtime_pb2
from funky.type.v1 import agent_pb2, event_pb2, sandbox_pb2

# Chat Completions takes an optional output cap; we always send one so a turn
# can't run away. 4096 is generous for a single chat turn and under every common
# model's ceiling; a `max_tokens` field on AgentConfig is the natural place to
# make this per-agent later.
DEFAULT_MAX_TOKENS = 4096

# Safety cap on tool-use rounds in one turn, so a model that keeps calling tools
# can't loop forever. Each round is one model call plus the tool calls it makes.
DEFAULT_MAX_ITERATIONS = 50

# The one tool the agent gets: run a shell command in the sandbox. OpenAI-style
# function tool — the model fills in `command` per the JSON-schema parameters.
BASH_TOOL = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": (
            "Run a shell command inside the sandbox and return its combined "
            "stdout and stderr."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to run.",
                },
            },
            "required": ["command"],
        },
    },
}


class OpenRouterAgentLoop:
    """One agent turn backed by an OpenRouter (Chat Completions) model and a sandbox."""

    def __init__(
        self,
        client,
        sandbox_client,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
    ) -> None:
        self._client = client
        self._sandbox = sandbox_client
        self._max_tokens = max_tokens
        self._max_iterations = max_iterations

    def run_turn(
        self,
        agent_config: agent_pb2.AgentConfig,
        events: Sequence[event_pb2.Event],
        prompt: event_pb2.UserMessage,
        sandbox: sandbox_pb2.Sandbox,
    ) -> Iterator[event_pb2.Event]:
        """Run one turn and yield the Events the agent produces, in order.

        Text the model writes becomes an AgentMessage; every tool call becomes an
        AgentToolUse followed by the AgentToolResult from running it in the
        sandbox. The loop ends when the model finishes a response without calling
        a tool (or the iteration cap is hit).
        """
        messages = _to_messages(events, prompt, agent_config.system_prompt)
        request = {
            "model": agent_config.model,
            "max_tokens": self._max_tokens,
            "tools": [BASH_TOOL],
        }

        for _ in range(self._max_iterations):
            response = self._client.chat.completions.create(
                messages=messages, **request
            )
            message = response.choices[0].message
            tool_calls = list(message.tool_calls or [])

            # The assistant's turn replayed back to the model: its text (if any)
            # and the tool calls it made, in one message, as Chat Completions wants.
            assistant_message: dict = {"role": "assistant", "content": message.content}
            if message.content:
                yield _agent_text_event(message.content)
            if tool_calls:
                assistant_message["tool_calls"] = [
                    _tool_call_dict(call.id, call.function.name, call.function.arguments)
                    for call in tool_calls
                ]
            messages.append(assistant_message)

            # No tool calls this round -> the turn is done.
            if not tool_calls:
                return

            for call in tool_calls:
                yield _agent_tool_use_event(call)
                output, is_error = self._run_tool(sandbox.id, call)
                yield _agent_tool_result_event(call.id, output, is_error)
                # Chat Completions has no is_error on a tool result; the failure is
                # already carried in the text by _format_output ([exit code N]).
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": output}
                )

    def _run_tool(self, sandbox_id: str, call) -> tuple[str, bool]:
        """Run a tool call in the sandbox; return (output, is_error).

        Only ``bash`` exists today. A failed RPC or a non-zero exit is surfaced as
        an errored result so the model can react, rather than aborting the turn.
        """
        command = _arguments(call.function.arguments).get("command", "")
        argv = ["bash", "-c", command]
        try:
            result = self._sandbox.exec_command(
                sandbox_runtime_pb2.ExecCommandRequest(
                    sandbox_id=sandbox_id, command=argv
                )
            )
        except ConnectError as err:
            return f"sandbox exec failed: {err}", True
        return _format_output(result), result.exit_code != 0


def _to_messages(
    events: Sequence[event_pb2.Event],
    prompt: event_pb2.UserMessage,
    system_prompt: str,
) -> list[dict]:
    """Build the Chat Completions message list: a system message (when non-empty),
    the prior events, then the new prompt.

    Each event maps to a role and content; a prior AgentToolUse becomes an
    assistant message carrying a ``tool_calls`` entry and a prior AgentToolResult
    becomes a ``role: tool`` message — the same shapes the live loop appends, so a
    resumed conversation reconstructs into a valid exchange.
    """
    messages: list[dict] = []
    # A blank system prompt is a no-op; leaving it off keeps the request minimal.
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for event in events:
        message = _event_to_message(event)
        if message is not None:
            messages.append(message)
    messages.append({"role": "user", "content": _join_text(prompt.content)})
    return messages


def _event_to_message(event: event_pb2.Event) -> dict | None:
    """An event as one Chat Completions message, or None if it carries no turn."""
    kind = event.WhichOneof("payload")
    if kind == "user_message":
        return {"role": "user", "content": _join_text(event.user_message.content)}
    if kind == "agent_message":
        return {"role": "assistant", "content": _join_text(event.agent_message.content)}
    if kind == "agent_tool_use":
        use = event.agent_tool_use
        arguments = json.dumps(json_format.MessageToDict(use.input))
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [_tool_call_dict(use.id, use.name, arguments)],
        }
    if kind == "agent_tool_result":
        res = event.agent_tool_result
        return {
            "role": "tool",
            "tool_call_id": res.tool_use_id,
            "content": _blocks_text(res.content),
        }
    return None


def _tool_call_dict(call_id: str, name: str, arguments: str) -> dict:
    """A Chat Completions tool_call entry; arguments stays the model's JSON string."""
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def _arguments(raw: str) -> dict:
    """Parse a tool call's JSON-string arguments to a dict; {} if absent or invalid."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _join_text(blocks: Sequence[event_pb2.ContentBlock]) -> str:
    """Flatten content blocks to a string — Chat Completions content is text, today."""
    return "".join(
        block.text.text for block in blocks if block.WhichOneof("block") == "text"
    )


# A tool_result's content is also a flat string, so it shares _join_text's shape.
_blocks_text = _join_text


def _format_output(result: sandbox_runtime_pb2.ExecCommandResponse) -> str:
    """Combine a command's stdout/stderr, noting a non-zero exit code."""
    parts = [stream for stream in (result.stdout, result.stderr) if stream]
    text = "\n".join(parts)
    if result.exit_code != 0:
        note = f"[exit code {result.exit_code}]"
        text = f"{text}\n{note}" if text else note
    return text


def _agent_text_event(text: str) -> event_pb2.Event:
    """A payload-only AgentMessage Event wrapping a single text block."""
    return event_pb2.Event(
        agent_message=event_pb2.AgentMessage(
            content=[event_pb2.ContentBlock(text=event_pb2.TextBlock(text=text))]
        )
    )


def _agent_tool_use_event(call) -> event_pb2.Event:
    """A payload-only AgentToolUse Event for a model tool_call."""
    use = event_pb2.AgentToolUse(id=call.id, name=call.function.name)
    use.input.update(_arguments(call.function.arguments))
    return event_pb2.Event(agent_tool_use=use)


def _agent_tool_result_event(
    tool_use_id: str, output: str, is_error: bool
) -> event_pb2.Event:
    """A payload-only AgentToolResult Event for a tool call's outcome."""
    return event_pb2.Event(
        agent_tool_result=event_pb2.AgentToolResult(
            tool_use_id=tool_use_id,
            content=[event_pb2.ContentBlock(text=event_pb2.TextBlock(text=output))],
            is_error=is_error,
        )
    )
