"""SandboxRuntime service over a Modal-backed runtime.

Structurally satisfies the generated ``SandboxRuntimeSync`` protocol: each RPC
takes its request message plus a ``RequestContext`` and returns its response
message. The runtime owns Modal Sandboxes; this layer maps a missing sandbox to
NOT_FOUND and reshapes a command result into the response message.
"""

from __future__ import annotations

import modal

from connectrpc.code import Code
from connectrpc.errors import ConnectError
from connectrpc.request import RequestContext

from funky.sandbox.v1 import sandbox_runtime_pb2 as pb

from .runtime import DEFAULT_APP_NAME, DEFAULT_IMAGE, DEFAULT_TIMEOUT, ModalSandboxRuntime


class SandboxRuntimeService:
    """Modal-backed ``funky.sandbox.v1.SandboxRuntime``."""

    def __init__(
        self,
        image: str = DEFAULT_IMAGE,
        app_name: str = DEFAULT_APP_NAME,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        app: modal.App | None = None,
    ) -> None:
        self._runtime = ModalSandboxRuntime(
            image, app_name, timeout=timeout, app=app
        )

    def create_sandbox(
        self, request: pb.CreateSandboxRequest, ctx: RequestContext
    ) -> pb.CreateSandboxResponse:
        sandbox = self._runtime.create_sandbox(
            request.agent_config, request.environment_config
        )
        return pb.CreateSandboxResponse(sandbox=sandbox)

    def exec_command(
        self, request: pb.ExecCommandRequest, ctx: RequestContext
    ) -> pb.ExecCommandResponse:
        result = self._runtime.exec_command(request.sandbox_id, request.command)
        if result is None:
            raise ConnectError(
                Code.NOT_FOUND, f"sandbox {request.sandbox_id!r} not found"
            )
        # The response carries text, so decode the raw process output as UTF-8.
        # `replace` keeps a command that emits non-UTF-8 bytes from failing the
        # whole RPC — it degrades those bytes to U+FFFD rather than raising.
        return pb.ExecCommandResponse(
            exit_code=result.exit_code,
            stdout=result.stdout.decode("utf-8", errors="replace"),
            stderr=result.stderr.decode("utf-8", errors="replace"),
        )

    def destroy_sandbox(
        self, request: pb.DestroySandboxRequest, ctx: RequestContext
    ) -> pb.DestroySandboxResponse:
        if not self._runtime.destroy_sandbox(request.sandbox_id):
            raise ConnectError(
                Code.NOT_FOUND, f"sandbox {request.sandbox_id!r} not found"
            )
        return pb.DestroySandboxResponse()
