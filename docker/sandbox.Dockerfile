# docker/sandbox.Dockerfile — the base image for the `docker` sandbox driver.
#
# One container per session is started from this image (`docker run -d`), and the agent's
# commands run inside it via `docker exec`. Build + tag it on the host the worker's Docker
# daemon uses:
#
#   docker build -f docker/sandbox.Dockerfile -t funky-sandbox:trixie docker/
#
# then point the worker at it:  FUNKY_SANDBOX=docker  FUNKY_DOCKER_IMAGE=funky-sandbox:trixie
#
# Why debian:trixie-slim, not alpine: the idemKey shell protocol (see drivers/computesdk.ts)
# depends on GNU-coreutils semantics — `timeout <secs> CMD`, `base64` line-wrapping,
# `tail -c +N`, `nohup` — which is exactly what E2B's Debian-based template provides, so the
# docker and e2b drivers run identical semantics. glibc (not musl) also keeps agent-driven
# `pip`/`npm`/`apt install` on the happy path where prebuilt binaries just work.
FROM debian:trixie-slim

# ca-certificates so https works out of the box; curl+git because an agent reaches for them
# on command one; python3+node so the two commonest agent runtimes are ready without an
# apt/nvm detour. Kept intentionally lean — anything else the agent installs on demand.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        python3 \
        nodejs \
        npm \
    && rm -rf /var/lib/apt/lists/*

# Non-root by default. The worker reaches the daemon through a mounted socket (≈ host root
# already) — don't compound that by running the agent's commands as root inside the box too.
RUN useradd --create-home --shell /bin/bash agent
USER agent
WORKDIR /home/agent

# The driver overrides this with `sleep infinity` at `docker run`, but a sane default keeps
# the image runnable on its own for debugging (`docker run --rm -it funky-sandbox:trixie`).
CMD ["sleep", "infinity"]
