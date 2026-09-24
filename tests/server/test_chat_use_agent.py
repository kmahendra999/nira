"""Asking for a plain answer instead of an agent run.

Whether a request went through the server's agent — tools, memory, and the
learning loop that records the outcome — used to be inferred from whether the
caller sent `tools`. An empty list is falsy, so "I have no tools" and "don't
use the agent" were the same request, and both got the agent. There was no way
to ask for a straight answer.
"""

from __future__ import annotations

from nira.server.models import ChatCompletionRequest


def request(**kwargs) -> ChatCompletionRequest:
    return ChatCompletionRequest(model="m", messages=[], **kwargs)


def routes_decision(req: ChatCompletionRequest, *, agent, tools_on_agent=True) -> bool:
    """The expression from routes.chat_completions, kept in one place."""
    return (
        agent is not None
        and req.use_agent is not False
        and not req.tools
        and (not req.stream or bool(tools_on_agent))
    )


class TestDefaults:
    def test_unset_still_uses_the_agent(self) -> None:
        # Existing callers send no such field; their behaviour must not move.
        assert request().use_agent is None
        assert routes_decision(request(), agent=object()) is True

    def test_sending_tools_still_bypasses_the_agent(self) -> None:
        req = request(tools=[{"type": "function"}])
        assert routes_decision(req, agent=object()) is False


class TestExplicitChoice:
    def test_false_asks_for_a_plain_answer(self) -> None:
        assert routes_decision(request(use_agent=False), agent=object()) is False

    def test_true_asks_for_the_agent(self) -> None:
        assert routes_decision(request(use_agent=True), agent=object()) is True

    def test_false_wins_over_the_inference(self) -> None:
        # No tools sent, which on its own would have meant "use the agent".
        req = request(use_agent=False, tools=None)
        assert routes_decision(req, agent=object()) is False

    def test_it_cannot_conjure_an_agent_that_is_not_there(self) -> None:
        # Asking for the agent on a server running without one is still no.
        assert routes_decision(request(use_agent=True), agent=None) is False
