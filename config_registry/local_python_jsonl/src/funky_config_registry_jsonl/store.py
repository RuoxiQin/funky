"""Append-only JSONL persistence for config specs.

One store wraps one file. Each stored config is a single line holding an
envelope of ``{"id": ..., "config": {...}}``, where ``config`` is the proto3
JSON form of the message. Configs are write-once: ``create`` appends a fresh
line, ``get`` scans for a matching id, nothing is ever mutated in place.

The envelope (rather than flattening the config's fields to the top level) keeps
the id separate from the spec and generalizes as messages like EnvironmentConfig
grow fields — an empty config is simply ``{}``.
"""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

from google.protobuf import json_format
from google.protobuf.message import Message


class JsonlConfigStore:
    """A single JSONL file holding one kind of config."""

    def __init__(self, path: Path, *, id_prefix: str) -> None:
        self._path = path
        self._id_prefix = id_prefix
        # Guards append/scan so the threaded WSGI server can't interleave a
        # partial write with a read.
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)

    def create(self, config: Message) -> str:
        """Append ``config`` under a freshly minted id and return that id."""
        config_id = f"{self._id_prefix}_{uuid.uuid4().hex}"
        record = {
            "id": config_id,
            "config": json_format.MessageToDict(
                config, preserving_proto_field_name=True
            ),
        }
        line = json.dumps(record, separators=(",", ":"))
        with self._lock, self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        return config_id

    def get(self, config_id: str, into: Message) -> Message | None:
        """Parse the config stored under ``config_id`` into ``into``.

        Returns ``into`` on a hit, ``None`` if no line carries that id.
        """
        with self._lock, self._path.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                record = json.loads(raw)
                if record.get("id") == config_id:
                    json_format.ParseDict(record["config"], into)
                    return into
        return None
