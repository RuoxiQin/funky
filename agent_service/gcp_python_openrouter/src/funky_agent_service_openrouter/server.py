"""Serve the OpenRouter AgentService as a ConnectRPC server, ready for Cloud Run.

Mirrors the other backends' servers: the generated WSGI application on waitress, a
pure-Python WSGI server. (The stdlib ``wsgiref`` server is not used: it hands the
app the raw, unbounded socket as ``wsgi.input``, which deadlocks connect-python's
error path when it drains the request body.) RunTurn is a unary RPC, so it speaks
ConnectRPC over HTTP/1.1 + JSON and is reachable with plain ``curl`` (see
README.md).

The agent calls OpenRouter, so OPENROUTER_API_KEY must be set in the environment,
and it execs its tools in a SandboxRuntime, so one must be reachable at
--sandbox-runtime-url (or the SANDBOX_RUNTIME_URL env var, which Cloud Run sets to
the runtime's service URL). Binding --host 0.0.0.0 --port $PORT satisfies Cloud
Run's contract; the defaults keep it runnable locally.
"""

from __future__ import annotations

import argparse
import os

from waitress.server import create_server

from funky.agent.v1.agent_service_connect import AgentServiceWSGIApplication
from funky.sandbox.v1.sandbox_runtime_connect import SandboxRuntimeClientSync

from ._auth import id_token_auth
from .loop import DEFAULT_MAX_TOKENS
from .service import AgentServiceOpenRouter

# Default to the local Docker SandboxRuntime, but let SANDBOX_RUNTIME_URL override
# it so a Cloud Run deploy can point at the runtime's service URL via an env var.
DEFAULT_SANDBOX_RUNTIME_URL = os.environ.get(
    "SANDBOX_RUNTIME_URL", "http://127.0.0.1:8082"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    # Off the ConfigRegistry's 8080, SessionStore's 8081, and SandboxRuntime's
    # 8082 so every backend can run locally at once. Cloud Run passes $PORT.
    parser.add_argument("--port", type=int, default=8083)
    parser.add_argument(
        "--sandbox-runtime-url",
        default=DEFAULT_SANDBOX_RUNTIME_URL,
        help="base URL of the SandboxRuntime the agent execs its tools in "
        "(defaults to $SANDBOX_RUNTIME_URL, then the local Docker backend)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help="cap on the tokens the model may produce per turn",
    )
    args = parser.parse_args()

    # A private (Cloud Run) SandboxRuntime requires a Google OIDC ID token; the
    # agent execs its tools by calling it directly, so it must authenticate that
    # hop itself. Local http runtimes are called as-is. See _auth.id_token_auth.
    sandbox_client = SandboxRuntimeClientSync(
        args.sandbox_runtime_url,
        interceptors=id_token_auth(args.sandbox_runtime_url),
    )
    service = AgentServiceOpenRouter(sandbox_client, max_tokens=args.max_tokens)
    app = AgentServiceWSGIApplication(service)

    server = create_server(app, host=args.host, port=args.port)
    host, port = server.socket.getsockname()[:2]
    print(
        f"AgentService (openrouter) listening on http://{host}:{port}\n"
        f"  sandbox runtime: {args.sandbox_runtime_url}\n"
        f"  max_tokens: {args.max_tokens}",
        flush=True,
    )
    server.run()


if __name__ == "__main__":
    main()
