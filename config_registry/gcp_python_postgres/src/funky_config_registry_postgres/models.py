"""SQLAlchemy ORM models for the two kinds of stored config.

Two tables, mirroring the JSONL backend's two files:

  - ``agents``       — one row per stored ``AgentConfig``
  - ``environments`` — one row per stored ``EnvironmentConfig``

Both have the same shape: a registry-assigned id (the ``agt_`` / ``env_`` handle
returned from create and supplied to get) and the config itself kept as its
proto3-JSON form in a JSON column. Storing the whole spec as JSON — rather than a
column per proto field — keeps the round trip exact and lets the configs grow
new fields without a schema migration.

The ``JSONB`` column degrades to plain ``JSON`` on non-Postgres engines (the
hermetic SQLite test path); production runs Postgres and gets real ``JSONB``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

# JSONB on Postgres, ordinary JSON everywhere else (e.g. SQLite under test).
JsonDict = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    """Declarative base for the ConfigRegistry schema."""


class AgentRow(Base):
    """A stored ``AgentConfig``: its ``agt_`` id and the spec as proto3 JSON."""

    __tablename__ = "agents"

    # The ``agt_`` identifier, assigned by the store on create.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    # AgentConfig as proto3 JSON.
    config: Mapped[dict[str, Any]] = mapped_column(JsonDict)


class EnvironmentRow(Base):
    """A stored ``EnvironmentConfig``: its ``env_`` id and the spec as proto3 JSON."""

    __tablename__ = "environments"

    # The ``env_`` identifier, assigned by the store on create.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    # EnvironmentConfig as proto3 JSON (``{}`` while the message is empty).
    config: Mapped[dict[str, Any]] = mapped_column(JsonDict)
