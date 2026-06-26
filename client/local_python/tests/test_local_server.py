"""Drive the REST server against a FunkyClient over the in-memory fakes, asserting
the JSON surface: the four endpoints round-trip ids, a turn returns the agent's
events as JSON, and bad input maps to 400. The orchestration itself is covered by
test_local_client; here the HTTP layer on top of it is the thing under test, so the
same fakes are reused."""

from __future__ import annotations

from starlette.testclient import TestClient

from funky_client_local import FunkyClient
from funky_client_local.server import create_app

# Reuse the four in-memory fakes (and the event helper) from the client tests.
from test_local_client import (
    FakeAgentService,
    FakeConfigRegistry,
    FakeSandboxRuntime,
    FakeSessionStore,
    _agent_event,
)


def _app(agent_responses):
    agent = FakeAgentService(agent_responses)
    client = FunkyClient(
        FakeConfigRegistry(), FakeSessionStore(), FakeSandboxRuntime(), agent
    )
    return TestClient(create_app(client)), agent


def test_health():
    client, _ = _app([])
    assert client.get("/health").json() == {"status": "ok"}


def test_create_agent_environment_session_round_trip():
    client, _ = _app([])

    agent = client.post(
        "/v1/agents", json={"name": "coder", "model": "m", "system_prompt": "s"}
    )
    assert agent.status_code == 201
    agent_id = agent.json()["id"]
    assert agent_id.startswith("agt_")

    env = client.post("/v1/environments", json={})
    assert env.status_code == 201
    env_id = env.json()["id"]
    assert env_id.startswith("env_")

    # Environment body is optional — no body works too.
    assert client.post("/v1/environments").status_code == 201

    session = client.post(
        "/v1/sessions", json={"agent_id": agent_id, "environment_id": env_id}
    )
    assert session.status_code == 201
    assert session.json()["id"].startswith("ses_")


def test_send_message_returns_events_as_json():
    client, agent = _app([[_agent_event("hi there")]])
    session_id = _start_session(client)

    resp = client.post(f"/v1/sessions/{session_id}/messages", json={"prompt": "hello"})
    assert resp.status_code == 200
    events = resp.json()["events"]
    # The agent's reply comes back, snake_case, with its assigned id.
    assert events[0]["agent_message"]["content"][0]["text"]["text"] == "hi there"
    assert events[0]["id"]
    # The turn saw the prompt.
    assert agent.requests[0].prompt.content[0].text.text == "hello"


def test_missing_required_field_is_400():
    client, _ = _app([])
    assert client.post("/v1/sessions", json={"agent_id": "agt_1"}).status_code == 400
    assert client.post("/v1/agents", content=b"not json").status_code == 400
    session_id = _start_session(client)
    assert client.post(f"/v1/sessions/{session_id}/messages", json={}).status_code == 400


def _start_session(client: TestClient) -> str:
    agent_id = client.post(
        "/v1/agents", json={"name": "c", "model": "m", "system_prompt": "s"}
    ).json()["id"]
    env_id = client.post("/v1/environments", json={}).json()["id"]
    return client.post(
        "/v1/sessions", json={"agent_id": agent_id, "environment_id": env_id}
    ).json()["id"]
