"""End-to-end test: boot the WSGI server on an ephemeral port and drive it with
the generated ConnectRPC client, exercising the real wire path (not the service
object directly)."""

from __future__ import annotations

import threading

import pytest
from connectrpc.code import Code
from connectrpc.errors import ConnectError
from waitress.server import create_server

from funky.registry.v1 import config_registry_pb2 as pb
from funky.registry.v1.config_registry_connect import (
    ConfigRegistryClientSync,
    ConfigRegistryWSGIApplication,
)
from funky.type.v1 import agent_pb2, environment_pb2

from funky_config_registry_jsonl.service import ConfigRegistryService


@pytest.fixture
def registry(tmp_path):
    """A running ConfigRegistry server; yields (client, data_dir)."""
    app = ConfigRegistryWSGIApplication(ConfigRegistryService(tmp_path))
    server = create_server(app, host="127.0.0.1", port=0)
    port = server.socket.getsockname()[1]
    stopping = threading.Event()

    def serve():
        try:
            server.run()
        except OSError:
            # close() shuts the listening socket out from under waitress's
            # asyncore select loop; that EBADF is expected only during teardown.
            if not stopping.is_set():
                raise

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield ConfigRegistryClientSync(f"http://127.0.0.1:{port}"), tmp_path
    finally:
        stopping.set()
        server.close()
        thread.join(timeout=5)


def test_agent_round_trip(registry):
    client, data_dir = registry

    created = client.create_agent(
        pb.CreateAgentRequest(
            config=agent_pb2.AgentConfig(
                name="researcher",
                model="gemini-3.5-flash",
                system_prompt="You are a careful research assistant.",
            )
        )
    )
    assert created.id.startswith("agt_")

    fetched = client.get_agent(pb.GetAgentRequest(id=created.id))
    assert fetched.config.name == "researcher"
    assert fetched.config.model == "gemini-3.5-flash"
    assert fetched.config.system_prompt == "You are a careful research assistant."

    # Persisted as exactly one JSONL line.
    assert (data_dir / "agents.jsonl").read_text().splitlines() != []


def test_environment_round_trip(registry):
    client, data_dir = registry

    created = client.create_environment(
        pb.CreateEnvironmentRequest(config=environment_pb2.EnvironmentConfig())
    )
    assert created.id.startswith("env_")

    fetched = client.get_environment(pb.GetEnvironmentRequest(id=created.id))
    assert fetched.config == environment_pb2.EnvironmentConfig()
    assert (data_dir / "environments.jsonl").exists()


def test_unknown_id_is_not_found(registry):
    client, _ = registry

    with pytest.raises(ConnectError) as excinfo:
        client.get_agent(pb.GetAgentRequest(id="agt_missing"))
    assert excinfo.value.code == Code.NOT_FOUND
