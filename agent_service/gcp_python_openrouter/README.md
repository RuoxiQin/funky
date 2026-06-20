# gcp_python_openrouter

An [`AgentService`](../../proto/funky/agent/v1/agent_service.proto) that runs one
agent turn against [OpenRouter](https://openrouter.ai/) — so a single backend can
drive **any model OpenRouter routes to** (OpenAI, Anthropic, Google, Llama, Qwen,
DeepSeek, …), picked per request. It is the natural front door for letting users
choose the model for their agent swarms freely. Packaged for **Cloud Run** (see
[Deploy](#deploy-to-cloud-run)); otherwise it runs anywhere.

`RunTurn` takes the agent, the conversation so far, and a new prompt, and runs one
turn of an agentic loop: it converts the prior events plus the prompt into chat
messages (with the agent's `model` and `system_prompt`), gives the model a `bash`
tool, and calls the API. Every command the model runs is executed in the request's
`Sandbox` and fed back, looping until the model stops calling tools. It is unary —
one request, one response holding all of the turn's events: an `AgentMessage` per
assistant reply, and an `AgentToolUse` + `AgentToolResult` pair per command.

The turn is stateless, exactly as the contract requires — the prior events are
passed in, never stored — and the events it emits are payload-only: the
`SessionStore` assigns their Event id, session_id, and processed_at when the
Client appends them to history. (A result is matched to its call by the call's own
`AgentToolUse.id`, which the loop sets — distinct from the Event id.)

## OpenRouter, on the OpenAI wire format

OpenRouter exposes the **OpenAI Chat Completions API**, so this backend talks in
that shape rather than Anthropic's Messages shape — the one real difference from
the [`local_python_anthropic`](../local_python_anthropic) backend:

- the system prompt is a `role: system` message, not a top-level field;
- the `bash` tool is an OpenAI `type: function` tool;
- tool calls come back in `message.tool_calls`, with their arguments as a JSON
  *string*;
- tool results go back as `role: tool` messages keyed by `tool_call_id` (there is
  no `is_error` field, so a failed command's exit code rides along in the result
  text).

The Events it produces are provider-agnostic and identical to the Anthropic
backend's, so it is a drop-in `AgentService`. The default client is the official
[`openai`](https://github.com/openai/openai-python) SDK pointed at OpenRouter's
`base_url` — OpenRouter's own recommended integration.

Model ids are OpenRouter's namespaced ids, e.g. `openai/gpt-4o-mini`,
`anthropic/claude-sonnet-4`, `google/gemini-2.0-flash`, `meta-llama/llama-3.3-70b-instruct`.

## Tools: running in the sandbox

The agent gets one tool, `bash`: run a shell command in the sandbox. When the
model calls it, the loop execs `bash -c <command>` in the request's sandbox
through a `SandboxRuntime` client (`--sandbox-runtime-url`), packages the combined
stdout/stderr as an `AgentToolResult` (`is_error` set on a non-zero exit or a
failed exec), and feeds it back to the model — this is the
`AgentService ..> SandboxRuntime : exec` edge from the architecture. The loop caps
the number of tool rounds per turn so a model can't loop forever. The sandbox
image must have `bash`; the Docker runtime's default `python:3.12-slim` does.

## Configure

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `OPENROUTER_API_KEY` | yes | — | the OpenRouter API key the model call uses |
| `OPENROUTER_BASE_URL` | no | `https://openrouter.ai/api/v1` | override for a proxy |
| `SANDBOX_RUNTIME_URL` | no | `http://127.0.0.1:8082` | SandboxRuntime base URL (also `--sandbox-runtime-url`) |
| `OPENROUTER_HTTP_REFERER` | no | — | app URL for OpenRouter's leaderboard attribution |
| `OPENROUTER_X_TITLE` | no | — | app title for OpenRouter's leaderboard attribution |

The model named in each request's `AgentConfig.model` must be one OpenRouter can
serve, and a [`SandboxRuntime`](../../proto/funky/sandbox/v1/sandbox_runtime.proto)
must be reachable for the agent to exec its tools in. Otherwise everything runs
locally.

## Run it

From the repository root:

```bash
buf generate            # regenerate the protobuf/ConnectRPC stubs into gen/python
uv sync                 # create the workspace venv and install the backend + deps
export OPENROUTER_API_KEY=sk-or-...

# In one shell: a SandboxRuntime for the agent to exec tools in.
uv run funky-sandbox-runtime-docker --port 8082

# In another: the AgentService, pointed at it.
uv run funky-agent-service-openrouter --port 8083 --sandbox-runtime-url http://127.0.0.1:8082
```

The server runs on [waitress](https://github.com/Pylons/waitress) (pure Python)
and speaks ConnectRPC over HTTP/1.1 + JSON. `RunTurn` is unary, so it is a plain
JSON POST — no special content type, no framing — and is reachable with `curl`. It
returns one JSON object whose `events` array holds the whole turn (note proto3
JSON uses camelCase field names, e.g. `agentConfig`, `systemPrompt`). Each call
makes a real, billed request to OpenRouter:

```bash
curl -X POST http://127.0.0.1:8083/funky.agent.v1.AgentService/RunTurn \
  -H 'Content-Type: application/json' \
  -d '{
        "agentConfig": {"name":"coder","model":"openai/gpt-4o-mini","systemPrompt":"You are a careful coding assistant."},
        "prompt": {"content":[{"text":{"text":"Use bash to print the Python version, then tell me what it is."}}]},
        "sandbox": {"id":"sbx_..."}
      }'
# -> {"events":[{"agentToolUse":{...}},{"agentToolResult":{...}},{"agentMessage":{...}}]}
```

The `sandbox.id` must be a live sandbox from the same `SandboxRuntime` — create one
first with its `CreateSandbox` (see that backend's README). A prompt the agent can
answer without a tool never touches the sandbox.

## Test

```bash
uv run pytest agent_service/gcp_python_openrouter
```

The test boots the server on an ephemeral port and drives `RunTurn` through the
generated ConnectRPC client, covering a text-only turn, a tool-use turn (the bash
command reaching the sandbox with the right argv, the `AgentToolUse`/
`AgentToolResult` events, and the result fed back as a `role: tool` message), a
failed command flagged with `is_error` and surfaced in the fed-back text, prior
tool events round-tripping back into a valid Chat Completions exchange, the history
translation, and the empty-system-prompt case. A fake OpenAI/OpenRouter client and
a fake SandboxRuntime stand in for the model and the sandbox, so it needs no API
key, no Docker, and no network.

## Deploy to Cloud Run

The [`Dockerfile`](./Dockerfile) builds a self-contained image: it runs
`buf generate` and installs this backend from the committed lockfile, then serves
on `$PORT` bound to all interfaces (Cloud Run's contract).

> **The build context must be the repository root, not this directory.** The
> backend resolves `funky-protos` from the uv workspace, and `buf generate` reads
> `buf.gen.yaml`, `buf.yaml`, and `proto/` — all at the repo root. Building with
> the package directory as the context fails with
> `read buf.gen.yaml: file does not exist`.

**Cloud Build / Cloud Run trigger** — [`cloudbuild.yaml`](./cloudbuild.yaml)
mirrors the SessionStore backend's (build → push to Artifact Registry → deploy),
with the same fix: the Docker build context is the repository root (`.`), not the
package directory. The `_AR_*`, `_SERVICE_NAME`, and `_DEPLOY_REGION` substitutions
carry defaults in the file and are set by the trigger; `$REPO_NAME` / `$COMMIT_SHA`
are Cloud Build built-ins. To run it by hand from the repository root, supply the
built-ins the trigger would inject:

```bash
gcloud builds submit \
  --config agent_service/gcp_python_openrouter/cloudbuild.yaml \
  --substitutions=REPO_NAME=funky,COMMIT_SHA=manual
```

**Or build locally** and push (Cloud Run is linux/amd64):

```bash
# From the repository root.
IMAGE="REGION-docker.pkg.dev/PROJECT/REPO/funky-agent-service-openrouter"
docker build -f agent_service/gcp_python_openrouter/Dockerfile --platform linux/amd64 -t "$IMAGE" .
docker push "$IMAGE"
```

Then deploy the image, wiring the API key in as a secret and pointing the agent at
a reachable SandboxRuntime:

```bash
gcloud run deploy funky-agent-service-openrouter \
  --image "$IMAGE" --region REGION \
  --set-secrets OPENROUTER_API_KEY=openrouter-api-key:latest \
  --set-env-vars SANDBOX_RUNTIME_URL=https://your-sandbox-runtime.run.app
```
