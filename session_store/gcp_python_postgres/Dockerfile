# Container image for the GCP Cloud SQL (Postgres) SessionStore, for Cloud Run.
#
# IMPORTANT: build with the REPOSITORY ROOT as the context, not this directory —
# the backend resolves `funky-protos` from the uv workspace (gen/python) and the
# ConnectRPC stubs are generated from proto/ at build time. From the repo root:
#
#   docker build -f session_store/gcp_python_postgres/Dockerfile \
#     --platform linux/amd64 -t funky-session-store-postgres .
#
# `buf generate` reaches Buf's remote plugins, so the build needs network access.

FROM python:3.12-slim

# uv for locked, reproducible dependency installation.
COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /uvx /bin/

# buf, to generate the *_pb2 / *_connect stubs from proto/ at build time (they're
# gitignored — the .proto files are the source of truth).
ARG BUF_VERSION=1.70.0
ARG TARGETARCH=amd64
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && buf_arch="$(case "$TARGETARCH" in arm64) echo aarch64 ;; *) echo x86_64 ;; esac)" \
 && curl -fsSL "https://github.com/bufbuild/buf/releases/download/v${BUF_VERSION}/buf-Linux-${buf_arch}" \
      -o /usr/local/bin/buf \
 && chmod +x /usr/local/bin/buf \
 && apt-get purge -y --auto-remove curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

# Generate the stubs, then install just this backend (plus funky-protos) from the
# committed lockfile into /app/.venv. --no-dev drops the test-only deps.
RUN buf generate \
 && uv sync --frozen --no-dev --package funky-session-store-postgres

ENV PATH="/app/.venv/bin:$PATH"

# Cloud Run routes requests to $PORT (default 8080); the server must bind all
# interfaces. INSTANCE_CONNECTION_NAME / DB_USER / DB_NAME and DB_PASS (or
# DB_IAM_AUTH) are supplied as Cloud Run env vars / secrets at deploy time; the
# connector authenticates with the service account's ambient credentials.
EXPOSE 8080
CMD ["sh", "-c", "funky-session-store-postgres --host 0.0.0.0 --port ${PORT:-8080}"]
