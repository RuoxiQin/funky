"""Authenticate the agent's calls to the SandboxRuntime with a Cloud Run ID token.

The agent service runs as its own Cloud Run service and execs its tools by calling
the SandboxRuntime directly (see ``loop._run_tool``). That hop is separate from the
client's: the client's OIDC token authenticates client->agent and client->sandbox
(create), but never travels into this agent->sandbox (exec) call. So when the
SandboxRuntime is deployed private (``--no-allow-unauthenticated``, only callers
granted ``roles/run.invoker``), the agent must mint and attach its own token here,
or every ``exec_command`` is rejected 403.

This mirrors ``funky_client.client._id_token_auth`` — kept local so the agent
service doesn't depend on the client package (the dependency runs the other way).
"""

from __future__ import annotations

import time


def id_token_auth(url: str) -> tuple:
    """ConnectRPC interceptors that authenticate the agent's calls to *url*.

    A private (``--no-allow-unauthenticated``) Cloud Run SandboxRuntime rejects any
    caller without a Google-signed OIDC ID token whose audience is its URL. Those
    backends are always https; the local-dev SandboxRuntime is plain http and needs
    no auth — so this returns nothing for http, leaving local runs and the tests
    (which inject a fake sandbox client through the constructor) untouched.
    """
    if not url.startswith("https://"):
        return ()
    try:
        import google.auth.transport.requests  # noqa: F401
        import google.oauth2.id_token  # noqa: F401
    except ModuleNotFoundError as err:  # pragma: no cover - deploy-time dependency
        raise RuntimeError(
            f"Calling the https SandboxRuntime {url!r} needs a Cloud Run ID token, "
            "which requires google-auth (the Cloud Run image installs it). Install "
            "it with: pip install 'google-auth[requests]'."
        ) from err
    return (_IdTokenAuth(url),)


class _IdTokenAuth:
    """Attaches a Cloud Run ID token to every request to the SandboxRuntime.

    A ConnectRPC *metadata* interceptor: it implements ``on_start_sync`` /
    ``on_end_sync``, so the runtime applies it to unary and streaming calls alike.
    On Cloud Run, ``fetch_id_token`` mints an OIDC token for the agent service's
    runtime service account via the metadata server, with the SandboxRuntime's URL
    as the audience — exactly what the receiving service verifies. Tokens last an
    hour; we cache and refresh five minutes early so we don't mint one per RPC.
    """

    def __init__(self, audience: str) -> None:
        import google.auth.transport.requests

        self._audience = audience
        self._request = google.auth.transport.requests.Request()
        self._token: str | None = None
        self._refresh_at = 0.0

    def on_start_sync(self, ctx):
        ctx.request_headers()["authorization"] = f"Bearer {self._id_token()}"
        return None

    def on_end_sync(self, token, ctx, error) -> None:
        return None

    def _id_token(self) -> str:
        if self._token is None or time.time() >= self._refresh_at:
            import google.oauth2.id_token

            self._token = google.oauth2.id_token.fetch_id_token(
                self._request, self._audience
            )
            self._refresh_at = _jwt_expiry(self._token) - 300
        return self._token


def _jwt_expiry(token: str) -> float:
    """The ``exp`` (epoch seconds) claim of a JWT, read without verifying it.

    Used only to decide when to refresh a token we just minted ourselves, so
    reading the claim without signature verification is fine here.
    """
    import base64
    import json

    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)  # restore base64 padding
    return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
