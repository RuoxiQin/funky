"""Async, ORM-backed persistence for agent and environment configs.

``SqlConfigStore`` wraps a SQLAlchemy :class:`AsyncEngine` and speaks the same
contract as the JSONL backend's store: configs are write-once specs, so each kind
gets a ``create`` (mint an id, persist, return the id) and a ``get`` (resolve an
id back to the stored spec). It is engine-agnostic — the Cloud SQL + asyncpg
wiring lives in :mod:`db`, and the hermetic tests point it at SQLite — so this
layer is just proto↔row mapping.

Agents and environments are identical in shape (an id plus a JSON config), so the
two public method pairs delegate to one private ``_create`` / ``_get`` keyed by
the row type and id prefix, the way :mod:`models` declares two identical tables.
"""

from __future__ import annotations

import uuid

from google.protobuf import json_format
from google.protobuf.message import Message
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from funky.type.v1 import agent_pb2, environment_pb2

from .models import AgentRow, Base, EnvironmentRow


class SqlConfigStore:
    """Agent and environment configs, persisted via SQLAlchemy ORM over Postgres."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._session = async_sessionmaker(engine, expire_on_commit=False)

    async def create_all(self) -> None:
        """Create the ``agents`` and ``environments`` tables if they don't exist."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def create_agent(self, config: agent_pb2.AgentConfig) -> str:
        """Persist ``config`` under a fresh ``agt_`` id and return that id."""
        return await self._create(AgentRow, "agt", config)

    async def get_agent(self, config_id: str) -> agent_pb2.AgentConfig | None:
        """Return the agent config stored under ``config_id``, or ``None``."""
        return await self._get(AgentRow, config_id, agent_pb2.AgentConfig())

    async def create_environment(
        self, config: environment_pb2.EnvironmentConfig
    ) -> str:
        """Persist ``config`` under a fresh ``env_`` id and return that id."""
        return await self._create(EnvironmentRow, "env", config)

    async def get_environment(
        self, config_id: str
    ) -> environment_pb2.EnvironmentConfig | None:
        """Return the environment config stored under ``config_id``, or ``None``."""
        return await self._get(
            EnvironmentRow, config_id, environment_pb2.EnvironmentConfig()
        )

    async def _create(self, row_type, id_prefix: str, config: Message) -> str:
        config_id = f"{id_prefix}_{uuid.uuid4().hex}"
        async with self._session.begin() as db:
            db.add(
                row_type(
                    id=config_id,
                    config=json_format.MessageToDict(
                        config, preserving_proto_field_name=True
                    ),
                )
            )
        return config_id

    async def _get(self, row_type, config_id: str, into: Message) -> Message | None:
        async with self._session() as db:
            row = await db.get(row_type, config_id)
            if row is None:
                return None
            json_format.ParseDict(row.config, into)
            return into
