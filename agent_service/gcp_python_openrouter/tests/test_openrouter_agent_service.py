"""End-to-end test: boot the WSGI server on an ephemeral port and drive RunTurn
through the generated ConnectRPC client, with a fake OpenAI/OpenRouter client and
a fake SandboxRuntime standing in for the model and the sandbox so the test stays
hermetic — no API key, no Docker, no network."""

from __future__ import annotations

import copy
import json
import threading
from dataclasses import dataclass, field

import pytest
from waitress.server import create_server

from funky.agent.v1 import agent_service_pb2 as pb
from funky.agent.v1.agent_service_connect import (
    AgentServiceClientSync,
    AgentServiceWSGIApplication,
)
from funky.type.v1 import agent_pb2, event_pb2, sandbox_pb2

from funky_agent_service_openrouter.service import AgentServiceOpenRouter


# --- fake OpenRouter (Chat Completions) model -----------------------------


@dataclass
class _Function:
    """The ``function`` of a tool_call: a name and JSON-string arguments."""

    name: str
    arguments: str


@dataclass
class _ToolCall:
    """A tool_call, shaped like the SDK's ChatCompletionMessageToolCall."""

    id: str
    function: _Function
    type: str = "function"


@dataclass
class _Message:
    """An assistant message: text content and/or a list of tool_calls."""

    content: str | None = None
    tool_calls: list | None = None


@dataclass
class _Choice:
    message: _Message
    finish_reason: str = "stop"


@dataclass
class _Response:
    """A Chat Completions response: one choice carrying the assistant message."""

    choices: list


def _completion(content=None, tool_calls=None) -> _Response:
    return _Response([_Choice(_Message(content=content, tool_calls=tool_calls))])


class _Completions:
    """``client.chat.completions``: returns the canned responses in order, one per
    create() call, and records each call's kwargs for inspection."""

    def __init__(self, responses: list, calls: list) -> None:
        self._responses = list(responses)
        self._calls = calls

    def create(self, **kwargs) -> _Response:
        # Snapshot the kwargs: the loop keeps mutating the messages list in place
        # after the call, and the real SDK serializes the request, so a live
        # reference would not reflect what was actually sent.
        self._calls.append(copy.deepcopy(kwargs))
        return self._responses.pop(0)


@dataclass
class FakeOpenAI:
    """Stands in for ``openai.OpenAI`` pointed at OpenRouter: ``chat.completions.
    create`` returns the next canned response and stashes its kwargs in ``calls``."""

    responses: list
    calls: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self.chat = type("_Chat", (), {})()
        self.chat.completions = _Completions(self.responses, self.calls)


# --- fake SandboxRuntime --------------------------------------------------


@dataclass
class _ExecResult:
    """An ExecCommandResponse stand-in."""

    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""


class FakeSandbox:
    """Stands in for the SandboxRuntime client: ``exec_command`` returns a canned
    result and records each request."""

    def __init__(self, result: _ExecResult | None = None) -> None:
        self._result = result or _ExecResult()
        self.calls: list = []

    def exec_command(self, request) -> _ExecResult:
        self.calls.append(request)
        return self._result


# --- harness --------------------------------------------------------------


@pytest.fixture
def serve():
    """Yields ``start(model, sandbox) -> client``: boots a server wired to the fake
    model and sandbox, returns a ConnectRPC client. Servers torn down at teardown."""
    started: list = []

    def start(model: FakeOpenAI, sandbox: FakeSandbox) -> AgentServiceClientSync:
        service = AgentServiceOpenRouter(sandbox, client=model)
        server = create_server(
            AgentServiceWSGIApplication(service), host="127.0.0.1", port=0
        )
        port = server.socket.getsockname()[1]
        stopping = threading.Event()

        def run():
            try:
                server.run()
            except OSError:
                # close() shuts the listening socket out from under waitress's
                # select loop; that EBADF is expected only during teardown.
                if not stopping.is_set():
                    raise

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        started.append((server, thread, stopping))
        return AgentServiceClientSync(f"http://127.0.0.1:{port}")

    try:
        yield start
    finally:
        for server, thread, stopping in started:
            stopping.set()
            server.close()
            thread.join(timeout=5)


def _user(text: str) -> event_pb2.UserMessage:
    return event_pb2.UserMessage(
        content=[event_pb2.ContentBlock(text=event_pb2.TextBlock(text=text))]
    )


def _agent_message(text: str) -> event_pb2.AgentMessage:
    return event_pb2.AgentMessage(
        content=[event_pb2.ContentBlock(text=event_pb2.TextBlock(text=text))]
    )


def _agent_config(system_prompt: str = "You are a careful research assistant.") -> agent_pb2.AgentConfig:
    return agent_pb2.AgentConfig(
        name="researcher", model="openai/gpt-4o-mini", system_prompt=system_prompt
    )


def _request(events=(), prompt="hi", sandbox_id="sbx_1", system="You are a careful research assistant.") -> pb.RunTurnRequest:
    return pb.RunTurnRequest(
        agent_config=_agent_config(system),
        events=list(events),
        prompt=_user(prompt),
        sandbox=sandbox_pb2.Sandbox(id=sandbox_id),
    )


# --- tests ----------------------------------------------------------------


def test_text_only_turn_returns_an_agent_message(serve):
    sandbox = FakeSandbox()
    client = serve(FakeOpenAI([_completion(content="Hello world")]), sandbox)

    response = client.run_turn(_request())

    assert [
        e.agent_message.content[0].text.text for e in response.events
    ] == ["Hello world"]
    # No tool calls -> the sandbox is never touched.
    assert sandbox.calls == []
    # Events are payload-only: id/session_id/processed_at are the SessionStore's.
    assert all(
        e.id == "" and e.session_id == "" and not e.HasField("processed_at")
        for e in response.events
    )


def test_agent_runs_a_tool_in_the_sandbox(serve):
    model = FakeOpenAI(
        [
            _completion(
                tool_calls=[
                    _ToolCall("call_1", _Function("bash", '{"command": "echo hi"}'))
                ]
            ),
            _completion(content="It printed hi."),
        ]
    )
    sandbox = FakeSandbox(_ExecResult(exit_code=0, stdout="hi\n"))
    client = serve(model, sandbox)

    response = client.run_turn(_request(prompt="run echo hi", sandbox_id="sbx_42"))

    # The command ran in the right sandbox, wrapped for a shell.
    [exec_call] = sandbox.calls
    assert exec_call.sandbox_id == "sbx_42"
    assert list(exec_call.command) == ["bash", "-c", "echo hi"]

    # The turn's events: the tool call, its result, then the agent's reply.
    use, result, message = response.events
    assert use.agent_tool_use.id == "call_1"
    assert use.agent_tool_use.name == "bash"
    assert use.agent_tool_use.input["command"] == "echo hi"
    assert result.agent_tool_result.tool_use_id == "call_1"
    assert result.agent_tool_result.content[0].text.text == "hi\n"
    assert result.agent_tool_result.is_error is False
    assert message.agent_message.content[0].text.text == "It printed hi."

    # The second model call carried the tool_call back and the tool result in.
    second = model.calls[1]["messages"]
    assert second[-2] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "bash", "arguments": '{"command": "echo hi"}'},
            }
        ],
    }
    assert second[-1] == {"role": "tool", "tool_call_id": "call_1", "content": "hi\n"}


def test_failed_command_is_flagged_as_an_error(serve):
    model = FakeOpenAI(
        [
            _completion(
                tool_calls=[_ToolCall("call_x", _Function("bash", '{"command": "false"}'))]
            ),
            _completion(content="That failed."),
        ]
    )
    sandbox = FakeSandbox(_ExecResult(exit_code=1, stderr="boom"))
    client = serve(model, sandbox)

    response = client.run_turn(_request())

    result = response.events[1].agent_tool_result
    assert result.is_error is True
    assert "boom" in result.content[0].text.text
    assert "[exit code 1]" in result.content[0].text.text
    # Chat Completions tool results carry no is_error field, so the error rides
    # along in the content fed back to the model.
    assert "boom" in model.calls[1]["messages"][-1]["content"]
    assert "[exit code 1]" in model.calls[1]["messages"][-1]["content"]


def test_history_with_tool_events_round_trips_to_the_model(serve):
    model = FakeOpenAI([_completion(content="ok")])
    sandbox = FakeSandbox()
    client = serve(model, sandbox)

    use = event_pb2.AgentToolUse(id="call_h", name="bash")
    use.input.update({"command": "ls"})
    result = event_pb2.AgentToolResult(
        tool_use_id="call_h",
        content=[event_pb2.ContentBlock(text=event_pb2.TextBlock(text="a\nb"))],
    )
    history = [
        event_pb2.Event(user_message=_user("list files")),
        event_pb2.Event(agent_tool_use=use),
        event_pb2.Event(agent_tool_result=result),
    ]
    client.run_turn(_request(events=history, prompt="thanks"))

    # The prior tool call and its result reconstruct into a valid Chat Completions
    # exchange: a tool_calls entry on an assistant message, then a role:tool
    # message keyed by tool_call_id.
    messages = model.calls[0]["messages"]
    assert messages[0] == {"role": "system", "content": "You are a careful research assistant."}
    assert messages[1] == {"role": "user", "content": "list files"}
    assert messages[2] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_h",
                "type": "function",
                "function": {"name": "bash", "arguments": json.dumps({"command": "ls"})},
            }
        ],
    }
    assert messages[3] == {"role": "tool", "tool_call_id": "call_h", "content": "a\nb"}
    assert messages[4] == {"role": "user", "content": "thanks"}


def test_history_and_prompt_become_chat_messages(serve):
    model = FakeOpenAI([_completion(content="ok")])
    client = serve(model, FakeSandbox())

    history = [
        event_pb2.Event(user_message=_user("first question")),
        event_pb2.Event(agent_message=_agent_message("first answer")),
    ]
    client.run_turn(_request(events=history, prompt="second question"))

    [call] = model.calls
    assert call["model"] == "openai/gpt-4o-mini"
    assert call["messages"] == [
        {"role": "system", "content": "You are a careful research assistant."},
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second question"},
    ]


def test_empty_system_prompt_is_omitted(serve):
    model = FakeOpenAI([_completion(content="ok")])
    client = serve(model, FakeSandbox())

    client.run_turn(_request(system=""))

    [call] = model.calls
    # No system prompt -> no system message at all; the turn opens on the user.
    assert all(m["role"] != "system" for m in call["messages"])
    assert call["messages"][0] == {"role": "user", "content": "hi"}
