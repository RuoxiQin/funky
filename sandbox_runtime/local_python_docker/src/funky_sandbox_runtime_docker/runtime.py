"""Docker-backed core of the SandboxRuntime: containers as sandboxes.

Each sandbox is a long-lived Docker container. ``create_sandbox`` starts one from
a base image and keeps it alive (``tail -f /dev/null``) so later
``exec_command`` calls can ``docker exec`` into the same container;
``destroy_sandbox`` force-removes it.

The container's *name* is the sandbox id (``sbx_<hex>``), so Docker itself is the
only state this runtime keeps — there is no in-memory registry to lose on a
restart, and exec/destroy resolve a sandbox by asking the daemon for the
container by name (the JSONL backends lean on the filesystem the same way). Every
container also carries a ``funky.sandbox`` label so stragglers (e.g. left behind
by a crash) are easy to find and reap.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import docker
from docker.errors import NotFound

from funky.type.v1 import agent_pb2, environment_pb2, sandbox_pb2

# Default base image for a Python sandbox. EnvironmentConfig is empty today, so
# every sandbox uses this; an `image` field on EnvironmentConfig is the natural
# place to override it per-environment later.
DEFAULT_IMAGE = "python:3.12-slim"

# Keeps an otherwise-idle container running so it can be exec'd into. `tail -f
# /dev/null` blocks forever and is portable across GNU coreutils and busybox
# (unlike `sleep infinity`, which busybox's sleep rejects).
_KEEPALIVE = ["tail", "-f", "/dev/null"]


@dataclass
class CommandResult:
    """Outcome of a command run inside a sandbox."""

    exit_code: int
    stdout: bytes
    stderr: bytes


class DockerSandboxRuntime:
    """Sandboxes backed by long-lived Docker containers."""

    def __init__(
        self,
        image: str = DEFAULT_IMAGE,
        *,
        labels: dict[str, str] | None = None,
        client: docker.DockerClient | None = None,
    ) -> None:
        # from_env() honours DOCKER_HOST and the usual Docker socket/env setup.
        self._client = client or docker.from_env()
        self._image = image
        # Always tag sandboxes so they can be found and reaped; callers (e.g.
        # tests) can add their own labels for narrower cleanup.
        self._labels = {"funky.sandbox": "true", **(labels or {})}

    def create_sandbox(
        self,
        agent_config: agent_pb2.AgentConfig,
        environment_config: environment_pb2.EnvironmentConfig,
    ) -> sandbox_pb2.Sandbox:
        """Start a container and return it as a Sandbox.

        The container name *is* the sandbox id, which is how exec and destroy
        find it again. ``containers.run`` pulls the image if it is not present
        locally.

        Provisioning the agent's skills onto the container's disk (per the
        CreateSandbox contract) is a no-op for now — AgentConfig carries no
        skills field yet. The agent is accepted here so this stays the place that
        will do it once it does.
        """
        sandbox_id = f"sbx_{uuid.uuid4().hex}"
        self._client.containers.run(
            self._image,
            command=_KEEPALIVE,
            name=sandbox_id,
            labels=self._labels,
            detach=True,
            # A worker to exec into, not a service: no TTY, no attached stdin.
            tty=False,
            stdin_open=False,
        )
        return sandbox_pb2.Sandbox(id=sandbox_id)

    def exec_command(
        self, sandbox_id: str, command: list[str]
    ) -> CommandResult | None:
        """Run ``command`` (argv, no shell) in the sandbox; ``None`` if it is gone.

        Returns the raw bytes the process wrote; the service decodes them to text
        for the response. ``demux=True`` splits stdout and stderr into separate
        streams — either is ``None`` when nothing was written to it.
        """
        container = self._get(sandbox_id)
        if container is None:
            return None
        exit_code, (stdout, stderr) = container.exec_run(list(command), demux=True)
        return CommandResult(exit_code, stdout or b"", stderr or b"")

    def destroy_sandbox(self, sandbox_id: str) -> bool:
        """Force-remove the sandbox's container. ``False`` if it does not exist."""
        container = self._get(sandbox_id)
        if container is None:
            return False
        container.remove(force=True)
        return True

    def _get(self, sandbox_id: str):
        """The container named ``sandbox_id``, or ``None`` if the daemon has none."""
        try:
            return self._client.containers.get(sandbox_id)
        except NotFound:
            return None
