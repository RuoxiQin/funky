"""funky-client-local-server: a small REST front door for the FunkyClient orchestrator.

Wraps the local :class:`~funky_client_local.client.FunkyClient` in a JSON/REST HTTP
service so other services — or a Docker Compose stack — can drive the four Funky
backends through one endpoint instead of wiring up four. It is stateless: every
request resolves ids against the backends.

The four backend URLs come from the environment (``CONFIG_REGISTRY_URL``,
``SESSION_STORE_URL``, ``SANDBOX_RUNTIME_URL``, ``AGENT_SERVICE_URL``), each with a
localhost default, so it runs locally with no config and is pointed at sibling
containers in Compose by setting those vars. Backends are called over plain HTTP
with no auth (the Cloud Run variant, client/gcp_python, adds OIDC ID tokens).

Endpoints (JSON in, JSON out, snake_case throughout):

    GET  /health                              -> {"status": "ok"}
    POST /v1/agents                           -> {"id": "agt_..."}
    POST /v1/environments                     -> {"id": "env_..."}
    POST /v1/sessions                         -> {"id": "ses_..."}
    POST /v1/sessions/{session_id}/messages   -> {"events": [...]}

``messages`` runs one agent turn and returns the events it produced, as JSON, once
the turn completes. ``create_app`` takes a FunkyClient so tests can inject fakes;
``main`` builds the real client from the environment / flags and serves it with
uvicorn.
"""

from __future__ import annotations

import argparse
import json
import os

from connectrpc.errors import ConnectError
from google.protobuf import json_format
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from funky.type.v1 import agent_pb2, event_pb2

from .client import FunkyClient

# Local defaults match the backends' own default ports, so the server runs with no
# env set; Compose overrides each via an env var to point at the sibling services.
_URL_ENV = {
    "config_registry_url": ("CONFIG_REGISTRY_URL", "http://127.0.0.1:8080"),
    "session_store_url": ("SESSION_STORE_URL", "http://127.0.0.1:8081"),
    "sandbox_runtime_url": ("SANDBOX_RUNTIME_URL", "http://127.0.0.1:8082"),
    "agent_service_url": ("AGENT_SERVICE_URL", "http://127.0.0.1:8083"),
}


def default_urls() -> dict[str, str]:
    """The four backend URLs from the environment, each with a local fallback."""
    return {key: os.environ.get(env, default) for key, (env, default) in _URL_ENV.items()}


def create_app(client: FunkyClient) -> Starlette:
    """Build the ASGI app over a FunkyClient (injected, so tests pass fakes).

    The ConnectRPC clients are synchronous, so each handler offloads its backend
    calls to a worker thread to keep the event loop free.
    """

    async def health(_: Request) -> Response:
        return JSONResponse({"status": "ok"})

    async def create_agent(request: Request) -> Response:
        body = await _json_body(request)
        config = agent_pb2.AgentConfig(
            name=body.get("name", ""),
            model=body.get("model", ""),
            system_prompt=body.get("system_prompt", ""),
        )
        agent_id = await run_in_threadpool(client.agents.create, config)
        return JSONResponse({"id": agent_id}, status_code=201)

    async def create_environment(request: Request) -> Response:
        # EnvironmentConfig is empty today, so the body is ignored (but tolerated).
        await _json_body(request, optional=True)
        env_id = await run_in_threadpool(client.environments.create)
        return JSONResponse({"id": env_id}, status_code=201)

    async def create_session(request: Request) -> Response:
        body = await _json_body(request)
        agent_id = _require(body, "agent_id")
        environment_id = _require(body, "environment_id")
        session_id = await run_in_threadpool(
            client.sessions.create, agent_id, environment_id
        )
        return JSONResponse({"id": session_id}, status_code=201)

    async def send_message(request: Request) -> Response:
        session_id = request.path_params["session_id"]
        body = await _json_body(request)
        prompt = _require(body, "prompt")
        events = await run_in_threadpool(client.sessions.send, session_id, prompt)
        return JSONResponse({"events": [_event_dict(e) for e in events]})

    routes = [
        # NB: not "/healthz" — keep parity with the gcp variant, whose health route
        # avoids the path Google's frontend reserves.
        Route("/health", health, methods=["GET"]),
        Route("/v1/agents", create_agent, methods=["POST"]),
        Route("/v1/environments", create_environment, methods=["POST"]),
        Route("/v1/sessions", create_session, methods=["POST"]),
        Route("/v1/sessions/{session_id}/messages", send_message, methods=["POST"]),
    ]
    return Starlette(
        routes=routes,
        exception_handlers={
            _BadRequest: _bad_request_handler,
            ConnectError: _connect_error_handler,
        },
    )


def _event_dict(event: event_pb2.Event) -> dict:
    """An Event as JSON, snake_case to match this API's REST convention."""
    return json_format.MessageToDict(event, preserving_proto_field_name=True)


class _BadRequest(Exception):
    """A malformed request body or a missing required field (-> HTTP 400)."""


async def _json_body(request: Request, *, optional: bool = False) -> dict:
    """Parse the JSON body into a dict; raise _BadRequest on anything else.

    With ``optional``, an empty body becomes ``{}`` (for endpoints whose body is
    not required, like creating an environment).
    """
    raw = await request.body()
    if not raw:
        if optional:
            return {}
        raise _BadRequest("request body must be a JSON object")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as err:
        raise _BadRequest(f"invalid JSON: {err}") from err
    if not isinstance(body, dict):
        raise _BadRequest("request body must be a JSON object")
    return body


def _require(body: dict, field: str) -> str:
    value = body.get(field)
    if not isinstance(value, str) or not value:
        raise _BadRequest(f"missing required field: {field!r}")
    return value


def _bad_request_handler(_: Request, exc: _BadRequest) -> Response:
    return JSONResponse({"error": str(exc)}, status_code=400)


def _connect_error_handler(_: Request, exc: ConnectError) -> Response:
    # Map the backend's Connect status onto an HTTP status: not-found -> 404,
    # invalid argument -> 400, everything else -> 502 (a backend call failed).
    status = {"not_found": 404, "invalid_argument": 400}.get(exc.code.name, 502)
    return JSONResponse({"error": str(exc), "code": exc.code.name}, status_code=status)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    # Off the backends' 8080–8083 so the whole stack can run locally at once.
    parser.add_argument("--port", type=int, default=8000)
    urls = default_urls()
    for key, (env, _default) in _URL_ENV.items():
        parser.add_argument(
            f"--{key.replace('_', '-')}",
            default=urls[key],
            help=f"base URL of the {key[:-4].replace('_', ' ')} (defaults to ${env})",
        )
    args = parser.parse_args()

    client = FunkyClient.from_urls(
        config_registry_url=args.config_registry_url,
        session_store_url=args.session_store_url,
        sandbox_runtime_url=args.sandbox_runtime_url,
        agent_service_url=args.agent_service_url,
    )
    app = create_app(client)

    import uvicorn

    print(
        f"FunkyClient (local) REST API on http://{args.host}:{args.port}\n"
        f"  config registry  {args.config_registry_url}\n"
        f"  session store    {args.session_store_url}\n"
        f"  sandbox runtime  {args.sandbox_runtime_url}\n"
        f"  agent service    {args.agent_service_url}",
        flush=True,
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
