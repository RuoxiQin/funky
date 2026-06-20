"""Modal-backed core of the SandboxRuntime: Modal Sandboxes as sandboxes.

Each sandbox is a `Modal Sandbox <https://modal.com/docs/guide/sandbox>`_ — a
container running in Modal's cloud. ``create_sandbox`` starts one (with no
entrypoint command, so it stays alive idle until terminated or its timeout) so
later ``exec_command`` calls can run argv commands inside the same Sandbox;
``destroy_sandbox`` terminates it.

The Sandbox's Modal-assigned object id (``sb-...``) *is* the sandbox id, so Modal
itself is the only state this runtime keeps — there is no in-memory registry to
lose on a restart (and the service can scale to many Cloud Run instances without
sticky routing). exec/destroy resolve a sandbox by asking Modal for it by id with
``Sandbox.from_id`` — the same way the Docker backend leans on the daemon and the
JSONL backends lean on the filesystem. A Sandbox that Modal no longer has, or one
that has already finished (timed out or been terminated), reads as "gone".

Authentication is Modal's own: the ``MODAL_TOKEN_ID`` / ``MODAL_TOKEN_SECRET``
environment variables (or ``~/.modal.toml``) are read by the Modal client. On
Cloud Run they are supplied as env vars / secrets at deploy time.
"""

from __future__ import annotations

from dataclasses import dataclass

import modal
from modal.exception import InvalidError, NotFoundError

from funky.type.v1 import agent_pb2, environment_pb2, sandbox_pb2

# Default base image sandboxes are created from. EnvironmentConfig is empty
# today, so every sandbox uses this; an `image` field on EnvironmentConfig is the
# natural place to override it per-environment later. `from_registry` pulls the
# reference from Docker Hub (or any registry) the same way `python:3.12-slim`
# names an image to `docker run`.
DEFAULT_IMAGE = "python:3.12-slim"

# Modal App the sandboxes are created under (looked up / created on first use).
# Sandboxes are grouped beneath an App for organisation and billing; the name is
# how they show up in the Modal dashboard.
DEFAULT_APP_NAME = "funky-sandboxes"

# Maximum lifetime of a sandbox, in seconds. Modal's own default is a short 300s;
# a sandbox here must outlive a whole agent turn, so the default is bumped to an
# hour. Modal terminates the sandbox when this elapses, which also bounds the
# cost of one left behind by a crashed caller that never calls destroy.
DEFAULT_TIMEOUT = 3600


@dataclass
class CommandResult:
    """Outcome of a command run inside a sandbox."""

    exit_code: int
    stdout: bytes
    stderr: bytes


class ModalSandboxRuntime:
    """Sandboxes backed by Modal Sandboxes."""

    def __init__(
        self,
        image: str = DEFAULT_IMAGE,
        app_name: str = DEFAULT_APP_NAME,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        app: modal.App | None = None,
    ) -> None:
        self._image_ref = image
        self._app_name = app_name
        self._timeout = timeout
        # Looked up lazily so constructing the runtime never touches the network
        # (mirrors docker.from_env()); tests can inject an App to reuse one.
        self._app = app
        self._image: modal.Image | None = None

    def create_sandbox(
        self,
        agent_config: agent_pb2.AgentConfig,
        environment_config: environment_pb2.EnvironmentConfig,
    ) -> sandbox_pb2.Sandbox:
        """Start a Modal Sandbox and return it as a Sandbox.

        Created with no entrypoint command, so the Sandbox stays alive idle and
        ``exec_command`` can run commands in it until it is destroyed (or the
        timeout elapses). Its Modal object id is the sandbox id, which is how
        exec and destroy find it again.

        Provisioning the agent's skills onto the Sandbox's disk (per the
        CreateSandbox contract) is a no-op for now — AgentConfig carries no skills
        field yet. The agent is accepted here so this stays the place that will do
        it once it does.
        """
        sandbox = modal.Sandbox.create(
            app=self._get_app(),
            image=self._get_image(),
            timeout=self._timeout,
        )
        return sandbox_pb2.Sandbox(id=sandbox.object_id)

    def exec_command(
        self, sandbox_id: str, command: list[str]
    ) -> CommandResult | None:
        """Run ``command`` (argv, no shell) in the sandbox; ``None`` if it is gone.

        Returns the raw bytes the process wrote; the service decodes them to text
        for the response. The streams are read with ``text=False`` so non-UTF-8
        output is preserved as bytes here and degraded only at the response edge.
        """
        sandbox = self._get(sandbox_id)
        if sandbox is None:
            return None
        process = sandbox.exec(*list(command), text=False)
        # Modal buffers each stream server-side, so reading stdout fully and then
        # stderr fully does not deadlock the way draining two OS pipes in series
        # would. wait() then returns the exit code the process has by now set.
        stdout = process.stdout.read()
        stderr = process.stderr.read()
        exit_code = process.wait()
        return CommandResult(exit_code, stdout or b"", stderr or b"")

    def destroy_sandbox(self, sandbox_id: str) -> bool:
        """Terminate the sandbox's Modal Sandbox. ``False`` if it is already gone.

        ``terminate(wait=True)`` blocks until the Sandbox has actually stopped, so
        a subsequent exec/destroy of the same id reliably reads as gone (the
        teardown is synchronous, like the Docker backend's force-remove).
        """
        sandbox = self._get(sandbox_id)
        if sandbox is None:
            return False
        sandbox.terminate(wait=True)
        return True

    def _get_app(self) -> modal.App:
        """The Modal App sandboxes are created under, looked up once and cached."""
        if self._app is None:
            self._app = modal.App.lookup(self._app_name, create_if_missing=True)
        return self._app

    def _get_image(self) -> modal.Image:
        """The base image sandboxes are created from, built once and cached."""
        if self._image is None:
            self._image = modal.Image.from_registry(self._image_ref)
        return self._image

    def _get(self, sandbox_id: str) -> modal.Sandbox | None:
        """The live Sandbox ``sandbox_id`` names, or ``None`` if Modal has no
        running one — either it never existed (or the id is malformed) or it has
        already finished (terminated or timed out)."""
        try:
            sandbox = modal.Sandbox.from_id(sandbox_id)
        except (NotFoundError, InvalidError):
            return None
        # poll() is None while running and the exit code once finished; a finished
        # Sandbox lingers as a queryable object, so treat it as gone.
        if sandbox.poll() is not None:
            return None
        return sandbox
