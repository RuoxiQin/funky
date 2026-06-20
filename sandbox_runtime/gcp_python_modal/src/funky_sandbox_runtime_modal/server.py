"""Serve the Modal SandboxRuntime as a ConnectRPC server.

Wraps the service in the generated WSGI application and runs it on waitress — a
pure-Python WSGI server. The Modal SDK is synchronous (create/exec/terminate
block), so this is a sync WSGI stack like the Docker backend, not the async
uvicorn stack the Postgres SessionStore needs. (The stdlib ``wsgiref`` server is
not used: it hands the app the raw, unbounded socket as ``wsgi.input``, which
deadlocks connect-python's error path when it drains the request body.)
ConnectRPC speaks HTTP/1.1 + JSON, so the endpoints are also reachable with plain
``curl`` (see README.md).

The sandboxes themselves run in Modal's cloud, so this server is just a thin
front door: it needs Modal credentials (``MODAL_TOKEN_ID`` / ``MODAL_TOKEN_SECRET``)
to reach Modal, but holds no sandbox state of its own. That makes it a natural fit
for Cloud Run — bind ``$PORT`` on all interfaces (the Dockerfile does) and scale
out without sticky routing.

Configuration comes from the environment (with CLI flags overriding) under a
``FUNKY_`` prefix, kept clear of Modal's own reserved ``MODAL_`` config namespace.
"""

from __future__ import annotations

import argparse
import os

from waitress.server import create_server

from funky.sandbox.v1.sandbox_runtime_connect import SandboxRuntimeWSGIApplication

from .runtime import DEFAULT_APP_NAME, DEFAULT_IMAGE, DEFAULT_TIMEOUT
from .service import SandboxRuntimeService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    # Defaults off the ConfigRegistry's 8080 and SessionStore's 8081 so all
    # three can run locally at once.
    parser.add_argument("--port", type=int, default=8082)
    parser.add_argument(
        "--app-name",
        default=os.environ.get("FUNKY_MODAL_APP_NAME", DEFAULT_APP_NAME),
        help="Modal App the sandboxes are created under",
    )
    parser.add_argument(
        "--image",
        default=os.environ.get("FUNKY_MODAL_IMAGE", DEFAULT_IMAGE),
        help="base image (registry reference) sandboxes are created from",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("FUNKY_SANDBOX_TIMEOUT", DEFAULT_TIMEOUT)),
        help="maximum lifetime of a sandbox, in seconds",
    )
    args = parser.parse_args()

    service = SandboxRuntimeService(
        args.image, args.app_name, timeout=args.timeout
    )
    app = SandboxRuntimeWSGIApplication(service)

    server = create_server(app, host=args.host, port=args.port)
    host, port = server.socket.getsockname()[:2]
    print(
        f"SandboxRuntime (modal) listening on http://{host}:{port}\n"
        f"  app:     {args.app_name}\n"
        f"  image:   {args.image}\n"
        f"  timeout: {args.timeout}s",
        flush=True,
    )
    server.run()


if __name__ == "__main__":
    main()
