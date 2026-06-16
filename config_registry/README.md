# ConfigRegistry backends

Implementations of the [`funky.registry.v1.ConfigRegistry`](../proto/funky/registry/v1/config_registry.proto)
service — store agent and environment configs, hand them back by id.

Each backend lives in its own directory and is an independent, installable
package, so it only declares the dependencies it actually needs. Directories are
named by the three axes that distinguish a backend:

```
<deployment>_<language>_<storage>
```

| Directory | Deployment | Language | Storage |
|---|---|---|---|
| `local_python_jsonl` | local | Python | JSONL files |
| *(future)* `gcp_python_postgres` | GCP (Cloud SQL) | Python | Postgres |

Every backend implements the same wire contract, so the forthcoming **Client**
orchestrator — and any ConnectRPC client — can talk to any of them unchanged.

See each backend's own README to run it.
