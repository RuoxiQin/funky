"""End-to-end test: boot the WSGI server on an ephemeral port and drive RunTurn
through the generated ConnectRPC client, with a fake Anthropic client standing in
for the model so the test stays hermetic — no API key, no network."""

from __future__ import annotations

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

from funky_agent_service_anthropic.service import AgentServiceAnthropic


@dataclass
class _Block:
    """A content block of an Anthropic response, shaped like the SDK's TextBlock."""

    text: str
    type: str = "text"


@dataclass
class _Message:
    """An Anthropic Messages response: a list of content blocks."""

    content: list


class _Messages:
    """The ``client.messages`` namespace: records each create() and replies canned."""

    def __init__(self, blocks: list, calls: list) -> None:
        self._blocks = blocks
        self._calls = calls

    def create(self, **kwargs) -> _Message:
        self._calls.append(kwargs)
        return _Message(content=list(self._blocks))


@dataclass
class FakeAnthropic:
    """Stands in for ``anthropic.Anthropic``: ``messages.create`` returns the given
    blocks and stashes its kwargs in ``calls`` for the test to inspect."""

    blocks: list
    calls: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self.messages = _Messages(self.blocks, self.calls)


@pytest.fixture
def serve():
    """Yields ``start(fake) -> client``: boots a server wired to the fake model and
    returns a ConnectRPC client for it. All servers are torn down at teardown."""
    started: list = []

    def start(fake: FakeAnthropic) -> AgentServiceClientSync:
        app = AgentServiceWSGIApplication(AgentServiceAnthropic(client=fake))
        server = create_server(app, host="127.0.0.1", port=0)
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
        name="researcher", model="claude-sonnet-4-6", system_prompt=system_prompt
    )


def test_run_turn_returns_all_events_at_once(serve):
    client = serve(FakeAnthropic([_Block("Hello"), _Block(" world")]))

    response = client.run_turn(
        pb.RunTurnRequest(
            agent_config=_agent_config(),
            prompt=_user("hi"),
            sandbox=sandbox_pb2.Sandbox(id="sbx_1"),
        )
    )

    # The unary RPC returns one response holding every event the turn produced —
    # one AgentMessage per text block the model returned.
    assert [
        e.agent_message.content[0].text.text for e in response.events
    ] == ["Hello", " world"]
    # The events are payload-only: id/session_id/processed_at are the
    # SessionStore's to assign when the Client appends them to history.
    assert all(
        e.id == "" and e.session_id == "" and not e.HasField("processed_at")
        for e in response.events
    )


def test_history_and_prompt_become_anthropic_messages(serve):
    fake = FakeAnthropic([_Block("ok")])
    client = serve(fake)

    history = [
        event_pb2.Event(user_message=_user("first question")),
        event_pb2.Event(agent_message=_agent_message("first answer")),
    ]
    client.run_turn(
        pb.RunTurnRequest(
            agent_config=_agent_config(),
            events=history,
            prompt=_user("second question"),
            sandbox=sandbox_pb2.Sandbox(id="sbx_1"),
        )
    )

    # The model is asked with the agent's model + system prompt, and the history
    # in order with the new prompt appended as the trailing user turn.
    [call] = fake.calls
    assert call["model"] == "claude-sonnet-4-6"
    assert call["system"] == "You are a careful research assistant."
    assert call["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "first question"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "first answer"}]},
        {"role": "user", "content": [{"type": "text", "text": "second question"}]},
    ]


def test_empty_system_prompt_is_omitted(serve):
    fake = FakeAnthropic([_Block("ok")])
    client = serve(fake)

    client.run_turn(
        pb.RunTurnRequest(
            agent_config=_agent_config(system_prompt=""),
            prompt=_user("hi"),
            sandbox=sandbox_pb2.Sandbox(id="sbx_1"),
        )
    )

    # A blank system prompt is left off the request rather than sent as "".
    [call] = fake.calls
    assert "system" not in call
