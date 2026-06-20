# SandboxRuntime backends

Implementations of the [`funky.sandbox.v1.SandboxRuntime`](../proto/funky/sandbox/v1/sandbox_runtime.proto)
service — create a sandbox from a resolved environment config, run argv commands
inside it, and destroy it.

Each backend lives in its own directory and is an independent, installable
package, so it only declares the dependencies it actually needs. Directories are
named by the three axes that distinguish a backend:

```
<deployment>_<language>_<sandbox>
```

| Directory | Deployment | Language | Sandbox |
|---|---|---|---|
| `local_python_docker` | local | Python | Docker container |
| `gcp_python_modal` | GCP (Cloud Run) | Python | Modal Sandbox |
| *(future)* `gcp_python_firecracker` | GCP | Python | Firecracker microVM |

Every backend implements the same wire contract, so the forthcoming **Client**
orchestrator — and any ConnectRPC client — can talk to any of them unchanged.

See each backend's own README to run it.
