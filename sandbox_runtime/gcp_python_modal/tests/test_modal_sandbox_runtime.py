"""End-to-end test: boot the WSGI server on an ephemeral port and drive it with
the generated ConnectRPC client, exercising the real wire path against real Modal
Sandboxes (not the service object directly).

Skipped unless the ``modal`` SDK is importable *and* Modal is reachable with
configured credentials — creating a sandbox spins a real container in Modal's
cloud (and costs a little), so the suite is gated the way the Docker backend's is
gated on a reachable daemon. The sandboxes use ``python:3.12-slim`` (the backend
default, known-good on Modal) and a short timeout so any straggler a failing test
leaves behind self-terminates quickly.
"""

from __future__ import annotations

import threading

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

from funky_sandbox_runtime_modal.service import SandboxRuntimeService

modal = pytest.importorskip("modal")

# The backend default image; has a shell and `echo` — enough to exercise exec.
TEST_IMAGE = "python:3.12-slim"
# Short backstop lifetime so a sandbox a failing test forgets to destroy still
# self-terminates promptly rather than billing for the full default hour.
TEST_TIMEOUT = 120


@pytest.fixture(scope="module")
def modal_app():
    """A throwaway Modal App, or skip the whole module if Modal is unreachable.

    `App.lookup` is the lightweight authenticated call that stands in for the
    Docker backend's `client.ping()`: it confirms credentials and connectivity
    without creating a sandbox.
    """
    try:
        app = modal.App.lookup(
            "funky-sandbox-runtime-modal-test", create_if_missing=True
        )
    except Exception as exc:  # no token, no network, auth error, ...
        pytest.skip(f"Modal not available: {exc}")
    return app


@pytest.fixture
def runtime(modal_app):
    """A running SandboxRuntime server; yields a connected client.

    The test App is injected so sandboxes land under it (rather than the
    backend's default `funky-sandboxes`), keeping test traffic out of the way.
    """
    service = SandboxRuntimeService(TEST_IMAGE, timeout=TEST_TIMEOUT, app=modal_app)
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
    assert sandbox_id.startswith("sb-")

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
            pb.ExecCommandRequest(sandbox_id="sb-missing", command=["echo", "hi"])
        )
    assert excinfo.value.code == Code.NOT_FOUND


def test_destroy_unknown_sandbox_is_not_found(runtime):
    with pytest.raises(ConnectError) as excinfo:
        runtime.destroy_sandbox(pb.DestroySandboxRequest(sandbox_id="sb-missing"))
    assert excinfo.value.code == Code.NOT_FOUND
