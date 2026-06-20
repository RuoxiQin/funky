"""AgentService over the OpenRouter-backed agent loop.

Structurally satisfies the generated ``AgentServiceSync`` protocol: ``run_turn``
takes its request plus a ``RequestContext`` and returns a ``RunTurnResponse``. The
loop owns the model call and the sandbox tool calls and produces the Events; this
layer unpacks the request, collects the events into the response, and builds the
default OpenRouter client (the OpenAI SDK pointed at OpenRouter) when one isn't
injected.
"""

from __future__ import annotations

import os

import openai

from connectrpc.request import RequestContext

from funky.agent.v1 import agent_service_pb2 as pb

from .loop import DEFAULT_MAX_TOKENS, OpenRouterAgentLoop

# OpenRouter exposes the OpenAI Chat Completions API at this base; the OpenAI SDK
# talks to it unchanged once pointed here. Overridable for a proxy or a test.
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


def _default_client() -> openai.OpenAI:
    """The OpenAI SDK aimed at OpenRouter, keyed by OPENROUTER_API_KEY.

    OpenRouter's optional ranking headers (the referring app's URL and title) are
    sent when OPENROUTER_HTTP_REFERER / OPENROUTER_X_TITLE are set, and omitted
    otherwise — they affect only attribution on OpenRouter's leaderboards.
    """
    headers = {}
    if referer := os.environ.get("OPENROUTER_HTTP_REFERER"):
        headers["HTTP-Referer"] = referer
    if title := os.environ.get("OPENROUTER_X_TITLE"):
        headers["X-Title"] = title
    return openai.OpenAI(
        base_url=os.environ.get("OPENROUTER_BASE_URL", DEFAULT_BASE_URL),
        api_key=os.environ.get("OPENROUTER_API_KEY"),
        default_headers=headers or None,
    )


class AgentServiceOpenRouter:
    """OpenRouter-backed ``funky.agent.v1.AgentService``."""

    def __init__(
        self,
        sandbox_client,
        *,
        client: openai.OpenAI | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        # sandbox_client is a SandboxRuntime client the agent execs its tools in.
        # The default model client is the OpenAI SDK pointed at OpenRouter and keyed
        # by OPENROUTER_API_KEY. Both clients are injectable so tests can drive the
        # turn with a fake model and a fake sandbox instead of the real services.
        self._loop = OpenRouterAgentLoop(
            client or _default_client(), sandbox_client, max_tokens=max_tokens
        )

    def run_turn(
        self, request: pb.RunTurnRequest, ctx: RequestContext
    ) -> pb.RunTurnResponse:
        events = self._loop.run_turn(
            request.agent_config, request.events, request.prompt, request.sandbox
        )
        return pb.RunTurnResponse(events=events)
