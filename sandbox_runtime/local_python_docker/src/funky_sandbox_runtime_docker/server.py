"""Serve the Docker SandboxRuntime as a local ConnectRPC server.

Wraps the service in the generated WSGI application and runs it on waitress — a
pure-Python WSGI server. (The stdlib ``wsgiref`` server is not used: it hands the
app the raw, unbounded socket as ``wsgi.input``, which deadlocks connect-python's
error path when it drains the request body.) ConnectRPC speaks HTTP/1.1 + JSON
here, so the endpoints are also reachable with plain ``curl`` (see README.md).

This talks to the local Docker daemon (via ``docker.from_env()``), so a daemon
must be reachable — but the server itself is fully local.
"""

from __future__ import annotations

import argparse

from waitress.server import create_server

from funky.sandbox.v1.sandbox_runtime_connect import SandboxRuntimeWSGIApplication

from .runtime import DEFAULT_IMAGE
from .service import SandboxRuntimeService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    # Defaults off the ConfigRegistry's 8080 and SessionStore's 8081 so all
    # three can run locally at once.
    parser.add_argument("--port", type=int, default=8082)
    parser.add_argument(
        "--image",
        default=DEFAULT_IMAGE,
        help="base Docker image sandboxes are created from",
    )
    args = parser.parse_args()

    service = SandboxRuntimeService(args.image)
    app = SandboxRuntimeWSGIApplication(service)

    server = create_server(app, host=args.host, port=args.port)
    host, port = server.socket.getsockname()[:2]
    print(
        f"SandboxRuntime (docker) listening on http://{host}:{port}\n"
        f"  image: {args.image}",
        flush=True,
    )
    server.run()


if __name__ == "__main__":
    main()
