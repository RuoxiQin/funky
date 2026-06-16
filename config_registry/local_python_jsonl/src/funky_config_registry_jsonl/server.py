"""Serve the JSONL ConfigRegistry as a local ConnectRPC server.

Wraps the service in the generated WSGI application and runs it on waitress — a
pure-Python, fully local WSGI server. (The stdlib ``wsgiref`` server is not used:
it hands the app the raw, unbounded socket as ``wsgi.input``, which deadlocks
connect-python's error path when it drains the request body.) ConnectRPC speaks
HTTP/1.1 + JSON here, so the endpoints are also reachable with plain ``curl``
(see README.md).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from waitress.server import create_server

from funky.registry.v1.config_registry_connect import ConfigRegistryWSGIApplication

from .service import ConfigRegistryService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("./data"),
        help="directory for agents.jsonl and environments.jsonl",
    )
    args = parser.parse_args()

    service = ConfigRegistryService(args.data_dir)
    app = ConfigRegistryWSGIApplication(service)

    server = create_server(app, host=args.host, port=args.port)
    host, port = server.socket.getsockname()[:2]
    print(
        f"ConfigRegistry (jsonl) listening on http://{host}:{port}\n"
        f"  data dir: {args.data_dir.resolve()}",
        flush=True,
    )
    server.run()


if __name__ == "__main__":
    main()
