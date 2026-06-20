"""ConfigRegistry service implementation over a Postgres-backed store.

Structurally satisfies the generated async ``ConfigRegistry`` protocol: each RPC
is a coroutine taking its request message plus a ``RequestContext`` and returning
its response message. Configs are write-once specs — create assigns an id, get
resolves one (or raises NOT_FOUND).
"""

from __future__ import annotations

from connectrpc.code import Code
from connectrpc.errors import ConnectError
from connectrpc.request import RequestContext

from funky.registry.v1 import config_registry_pb2 as pb

from .store import SqlConfigStore


class ConfigRegistryService:
    """Postgres-backed ``funky.registry.v1.ConfigRegistry``."""

    def __init__(self, store: SqlConfigStore) -> None:
        self._store = store

    async def create_agent(
        self, request: pb.CreateAgentRequest, ctx: RequestContext
    ) -> pb.CreateAgentResponse:
        config_id = await self._store.create_agent(request.config)
        return pb.CreateAgentResponse(id=config_id)

    async def get_agent(
        self, request: pb.GetAgentRequest, ctx: RequestContext
    ) -> pb.GetAgentResponse:
        config = await self._store.get_agent(request.id)
        if config is None:
            raise ConnectError(Code.NOT_FOUND, f"agent {request.id!r} not found")
        return pb.GetAgentResponse(config=config)

    async def create_environment(
        self, request: pb.CreateEnvironmentRequest, ctx: RequestContext
    ) -> pb.CreateEnvironmentResponse:
        config_id = await self._store.create_environment(request.config)
        return pb.CreateEnvironmentResponse(id=config_id)

    async def get_environment(
        self, request: pb.GetEnvironmentRequest, ctx: RequestContext
    ) -> pb.GetEnvironmentResponse:
        config = await self._store.get_environment(request.id)
        if config is None:
            raise ConnectError(
                Code.NOT_FOUND, f"environment {request.id!r} not found"
            )
        return pb.GetEnvironmentResponse(config=config)
