"""Serve the Postgres ConfigRegistry as a local ConnectRPC (ASGI) server.

The generated ``ConfigRegistryASGIApplication`` is async, matching the async
store, so it runs on uvicorn (an ASGI server) rather than the JSONL backend's
WSGI/waitress stack. ConnectRPC speaks HTTP/1.1 + JSON, so the endpoints are also
reachable with plain ``curl`` (see README.md).

The engine is built, the schema ensured, and the server run all inside one event
loop so the Cloud SQL connector and asyncpg connection pool live where they're
used. On shutdown the pool is disposed and the connector closed.
"""

from __future__ import annotations

import argparse
import asyncio

import uvicorn

from funky.registry.v1.config_registry_connect import ConfigRegistryASGIApplication

from .db import DatabaseConfig, create_engine
from .service import ConfigRegistryService
from .store import SqlConfigStore


async def serve(host: str, port: int) -> None:
    config = DatabaseConfig.from_env()
    engine, connector = await create_engine(config)
    try:
        store = SqlConfigStore(engine)
        await store.create_all()

        app = ConfigRegistryASGIApplication(ConfigRegistryService(store))
        server = uvicorn.Server(uvicorn.Config(app, host=host, port=port))
        print(
            f"ConfigRegistry (postgres) listening on http://{host}:{port}\n"
            f"  instance: {config.instance_connection_name}\n"
            f"  database: {config.db}",
            flush=True,
        )
        await server.serve()
    finally:
        await engine.dispose()
        await connector.close_async()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    asyncio.run(serve(args.host, args.port))


if __name__ == "__main__":
    main()
