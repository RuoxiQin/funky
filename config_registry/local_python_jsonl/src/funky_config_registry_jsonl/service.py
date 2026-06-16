"""ConfigRegistry service implementation over two JSONL stores.

Structurally satisfies the generated ``ConfigRegistrySync`` protocol: each RPC
takes its request message plus a ``RequestContext`` and returns its response
message. Agents and environments live in separate files; create assigns an id,
get resolves one (or raises NOT_FOUND).
"""

from __future__ import annotations

from pathlib import Path

from connectrpc.code import Code
from connectrpc.errors import ConnectError
from connectrpc.request import RequestContext

from funky.registry.v1 import config_registry_pb2 as pb
from funky.type.v1 import agent_pb2, environment_pb2

from .store import JsonlConfigStore


class ConfigRegistryService:
    """JSONL-backed ``funky.registry.v1.ConfigRegistry``."""

    def __init__(self, data_dir: Path) -> None:
        self._agents = JsonlConfigStore(data_dir / "agents.jsonl", id_prefix="agt")
        self._environments = JsonlConfigStore(
            data_dir / "environments.jsonl", id_prefix="env"
        )

    def create_agent(
        self, request: pb.CreateAgentRequest, ctx: RequestContext
    ) -> pb.CreateAgentResponse:
        config_id = self._agents.create(request.config)
        return pb.CreateAgentResponse(id=config_id)

    def get_agent(
        self, request: pb.GetAgentRequest, ctx: RequestContext
    ) -> pb.GetAgentResponse:
        config = self._agents.get(request.id, agent_pb2.AgentConfig())
        if config is None:
            raise ConnectError(Code.NOT_FOUND, f"agent {request.id!r} not found")
        return pb.GetAgentResponse(config=config)

    def create_environment(
        self, request: pb.CreateEnvironmentRequest, ctx: RequestContext
    ) -> pb.CreateEnvironmentResponse:
        config_id = self._environments.create(request.config)
        return pb.CreateEnvironmentResponse(id=config_id)

    def get_environment(
        self, request: pb.GetEnvironmentRequest, ctx: RequestContext
    ) -> pb.GetEnvironmentResponse:
        config = self._environments.get(
            request.id, environment_pb2.EnvironmentConfig()
        )
        if config is None:
            raise ConnectError(
                Code.NOT_FOUND, f"environment {request.id!r} not found"
            )
        return pb.GetEnvironmentResponse(config=config)
