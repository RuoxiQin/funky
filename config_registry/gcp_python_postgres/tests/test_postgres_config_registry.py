"""End-to-end test: boot the ASGI server on an ephemeral port and drive it with
the generated ConnectRPC client, exercising the real wire path (not the service
object directly).

The store's ORM is engine-agnostic, so by default this runs against an in-process
SQLite (aiosqlite) database — no Cloud SQL instance required. Point
``FUNKY_CONFIG_REGISTRY_TEST_DATABASE_URL`` at a disposable async Postgres URL
(e.g. ``postgresql+asyncpg://...``) to run the identical suite against Postgres.
"""

from __future__ import annotations

import asyncio
import os
import socket
import threading
import time

import pytest
import uvicorn
from connectrpc.code import Code
from connectrpc.errors import ConnectError
from sqlalchemy.ext.asyncio import create_async_engine

from funky.registry.v1 import config_registry_pb2 as pb
from funky.registry.v1.config_registry_connect import (
    ConfigRegistryASGIApplication,
    ConfigRegistryClientSync,
)
from funky.type.v1 import agent_pb2, environment_pb2

from funky_config_registry_postgres.models import Base
from funky_config_registry_postgres.service import ConfigRegistryService
from funky_config_registry_postgres.store import SqlConfigStore


@pytest.fixture
def client(tmp_path):
    """A running ConfigRegistry server over a fresh schema; yields the client.

    The engine, schema reset, and server all live in one event loop inside the
    server thread so the async connection pool is used where it's created.
    """
    db_url = os.environ.get(
        "FUNKY_CONFIG_REGISTRY_TEST_DATABASE_URL",
        f"sqlite+aiosqlite:///{tmp_path / 'config_registry.db'}",
    )

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

    box: dict = {}

    async def run() -> None:
        engine = create_async_engine(db_url)
        store = SqlConfigStore(engine)
        async with engine.begin() as conn:  # disposable schema, repeatable runs
            await conn.run_sync(Base.metadata.drop_all)
        await store.create_all()

        app = ConfigRegistryASGIApplication(ConfigRegistryService(store))
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        box["server"] = server
        try:
            await server.serve(sockets=[sock])
        finally:
            await engine.dispose()

    def thread_main() -> None:
        try:
            asyncio.run(run())
        except BaseException as exc:  # surface startup failures to the test
            box["error"] = exc

    thread = threading.Thread(target=thread_main, daemon=True)
    thread.start()

    deadline = time.time() + 15
    while time.time() < deadline:
        if "error" in box:
            raise box["error"]
        server = box.get("server")
        if server is not None and server.started:
            break
        time.sleep(0.02)
    else:
        raise RuntimeError("server did not start in time")

    try:
        yield ConfigRegistryClientSync(f"http://127.0.0.1:{port}")
    finally:
        if server := box.get("server"):
            server.should_exit = True
        thread.join(timeout=5)
        sock.close()


def test_agent_round_trip(client):
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


def test_environment_round_trip(client):
    created = client.create_environment(
        pb.CreateEnvironmentRequest(config=environment_pb2.EnvironmentConfig())
    )
    assert created.id.startswith("env_")

    fetched = client.get_environment(pb.GetEnvironmentRequest(id=created.id))
    assert fetched.config == environment_pb2.EnvironmentConfig()


def test_agents_and_environments_are_separate(client):
    """An agent id and an environment id never resolve across each other."""
    agent_id = client.create_agent(
        pb.CreateAgentRequest(config=agent_pb2.AgentConfig(name="solo"))
    ).id

    # The agent id is not an environment, and vice versa.
    with pytest.raises(ConnectError) as excinfo:
        client.get_environment(pb.GetEnvironmentRequest(id=agent_id))
    assert excinfo.value.code == Code.NOT_FOUND

    env_id = client.create_environment(
        pb.CreateEnvironmentRequest(config=environment_pb2.EnvironmentConfig())
    ).id
    with pytest.raises(ConnectError) as excinfo:
        client.get_agent(pb.GetAgentRequest(id=env_id))
    assert excinfo.value.code == Code.NOT_FOUND


def test_get_unknown_agent_is_not_found(client):
    with pytest.raises(ConnectError) as excinfo:
        client.get_agent(pb.GetAgentRequest(id="agt_missing"))
    assert excinfo.value.code == Code.NOT_FOUND


def test_get_unknown_environment_is_not_found(client):
    with pytest.raises(ConnectError) as excinfo:
        client.get_environment(pb.GetEnvironmentRequest(id="env_missing"))
    assert excinfo.value.code == Code.NOT_FOUND
