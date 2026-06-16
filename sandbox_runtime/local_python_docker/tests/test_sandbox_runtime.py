"""End-to-end test: boot the WSGI server on an ephemeral port and drive it with
the generated ConnectRPC client, exercising the real wire path against a real
local Docker daemon (not the service object directly).

Skipped unless the ``docker`` SDK is importable and a daemon is reachable. The
backend's default image is ``python:3.12-slim``; the tests use ``alpine`` instead
— a few MB versus a few hundred — since they only need a shell and ``echo``.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from connectrpc.code import Code
from connectrpc.errors import ConnectError
from waitress.server import create_server

from funky.sandbox.v1 import sandbox_runtime_pb2 as pb
from funky.sandbox.v1.sandbox_runtime_connect import (
    SandboxRuntimeClientSync,
    SandboxRuntimeWSGIApplication,
)
from funky.type.v1 import agent_pb2, environment_pb2

from funky_sandbox_runtime_docker.service import SandboxRuntimeService

docker = pytest.importorskip("docker")

# Small image with a shell and busybox `echo` — enough to exercise exec.
TEST_IMAGE = "alpine"


@pytest.fixture(scope="module")
def docker_client():
    """A live Docker client, or skip the whole module if none is reachable."""
    try:
        client = docker.from_env()
        client.ping()
    except Exception as exc:  # daemon down, no socket, permission denied, ...
        pytest.skip(f"Docker not available: {exc}")
    return client


@pytest.fixture
def runtime(docker_client):
    """A running SandboxRuntime server; yields a connected client.

    Every container this server creates is tagged with a per-test label so the
    fixture can reap any a failing test leaves behind without touching unrelated
    sandboxes.
    """
    label = f"funky-test-{uuid.uuid4().hex}"
    service = SandboxRuntimeService(TEST_IMAGE, labels={label: "true"})
    app = SandboxRuntimeWSGIApplication(service)
    server = create_server(app, host="127.0.0.1", port=0)
    port = server.socket.getsockname()[1]
    stopping = threading.Event()

    def serve():
        try:
            server.run()
        except OSError:
            # close() shuts the listening socket out from under waitress's
            # asyncore select loop; that EBADF is expected only during teardown.
            if not stopping.is_set():
                raise

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield SandboxRuntimeClientSync(f"http://127.0.0.1:{port}")
    finally:
        stopping.set()
        server.close()
        thread.join(timeout=5)
        for container in docker_client.containers.list(
            all=True, filters={"label": label}
        ):
            container.remove(force=True)


def _create_sandbox(client) -> str:
    created = client.create_sandbox(
        pb.CreateSandboxRequest(
            agent_config=agent_pb2.AgentConfig(
                name="researcher",
                model="gemini-3.5-flash",
                system_prompt="You are a careful research assistant.",
            ),
            environment_config=environment_pb2.EnvironmentConfig(),
        )
    )
    return created.sandbox.id


def test_create_exec_destroy_round_trip(runtime):
    sandbox_id = _create_sandbox(runtime)
    assert sandbox_id.startswith("sbx_")

    result = runtime.exec_command(
        pb.ExecCommandRequest(sandbox_id=sandbox_id, command=["echo", "hello"])
    )
    assert result.exit_code == 0
    assert result.stdout == "hello\n"
    assert result.stderr == ""

    runtime.destroy_sandbox(pb.DestroySandboxRequest(sandbox_id=sandbox_id))

    # The sandbox is gone after destroy: exec can no longer find it.
    with pytest.raises(ConnectError) as excinfo:
        runtime.exec_command(
            pb.ExecCommandRequest(sandbox_id=sandbox_id, command=["echo", "hi"])
        )
    assert excinfo.value.code == Code.NOT_FOUND


def test_exec_captures_stdout_stderr_and_exit_code(runtime):
    sandbox_id = _create_sandbox(runtime)
    try:
        # argv is run directly; the inner `sh -c` is the program under test, not
        # a host shell — it lets one command touch all three result fields.
        result = runtime.exec_command(
            pb.ExecCommandRequest(
                sandbox_id=sandbox_id,
                command=["sh", "-c", "echo out; echo err 1>&2; exit 7"],
            )
        )
        assert result.exit_code == 7
        assert result.stdout == "out\n"
        assert result.stderr == "err\n"
    finally:
        runtime.destroy_sandbox(pb.DestroySandboxRequest(sandbox_id=sandbox_id))


def test_exec_in_unknown_sandbox_is_not_found(runtime):
    with pytest.raises(ConnectError) as excinfo:
        runtime.exec_command(
            pb.ExecCommandRequest(sandbox_id="sbx_missing", command=["echo", "hi"])
        )
    assert excinfo.value.code == Code.NOT_FOUND


def test_destroy_unknown_sandbox_is_not_found(runtime):
    with pytest.raises(ConnectError) as excinfo:
        runtime.destroy_sandbox(pb.DestroySandboxRequest(sandbox_id="sbx_missing"))
    assert excinfo.value.code == Code.NOT_FOUND
