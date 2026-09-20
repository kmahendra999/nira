"""The report is written down before the link to it is sent.

A long reply over Telegram used to become a preview plus
``nira://research/<uuid>``, and the full text went out of scope in the same
breath. The reader was offered something that had already been discarded.
"""

from __future__ import annotations

import pytest

from nira.agents.channel_agent import ChannelAgent
from nira.research import ResearchStore


class FakeChannel:
    channel_type = "telegram"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self._handler = None

    def on_message(self, handler) -> None:  # noqa: ANN001
        self._handler = handler

    def send(self, destination: str, text: str, **kwargs) -> None:  # noqa: ANN003
        self.sent.append((destination, text))

    @property
    def last(self) -> str:
        return self.sent[-1][1] if self.sent else ""


class FakeAgent:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    def run(self, prompt: str):  # noqa: ANN201
        from types import SimpleNamespace

        return SimpleNamespace(content=self.reply)


def message(content: str, session_id: str = "sess_1"):  # noqa: ANN201
    from nira.channels._stubs import ChannelMessage

    return ChannelMessage(
        channel="telegram",
        sender="u1",
        content=content,
        conversation_id="chat_1",
        message_id="msg_1",
        session_id=session_id,
    )


LONG = "word " * 400


@pytest.fixture
def store(tmp_path):
    research = ResearchStore(tmp_path / "research.db")
    yield research
    research.close()


def run_once(channel, agent, store, content=LONG, session_id="sess_1") -> None:
    bridge = ChannelAgent(channel, agent, research_store=store)
    bridge._process_message(message(content, session_id))


class TestEscalatedReplies:
    def test_the_report_is_stored_under_the_id_in_the_link(self, store) -> None:
        channel = FakeChannel()
        run_once(channel, FakeAgent(LONG), store, session_id="sess_abc")

        assert "nira://research/sess_abc" in channel.last
        # The whole point: the id in the message resolves to the text the
        # preview was cut from.
        saved = store.get("sess_abc")
        assert saved is not None
        assert saved.report == LONG

    def test_the_query_is_stored_with_the_report(self, store) -> None:
        channel = FakeChannel()
        bridge = ChannelAgent(channel, FakeAgent(LONG), research_store=store)
        bridge._process_message(message("what is quantum computing", "sess_q"))

        # A report with no question is hard to place days later.
        assert store.get("sess_q").query == "what is quantum computing"

    def test_the_channel_is_recorded(self, store) -> None:
        channel = FakeChannel()
        run_once(channel, FakeAgent(LONG), store, session_id="sess_c")

        assert store.get("sess_c").channel == "telegram"

    def test_a_short_reply_is_sent_whole_and_not_stored(self, store) -> None:
        channel = FakeChannel()
        run_once(channel, FakeAgent("Sydney."), store, content="capital of NSW?")

        assert channel.last == "Sydney."
        assert "nira://" not in channel.last
        # Nothing was escalated, so there is nothing to keep.
        assert store.count() == 0


class TestWhenStorageIsUnavailable:
    def test_no_link_is_promised_without_somewhere_to_store_it(self) -> None:
        channel = FakeChannel()
        bridge = ChannelAgent(channel, FakeAgent(LONG), research_store=False)

        bridge._process_message(message(LONG))

        # Sending the whole thing is worse than a preview and far better than
        # a promise that cannot be kept.
        assert "nira://research" not in channel.last
        assert channel.last == LONG

    def test_a_failing_store_does_not_lose_the_reply(self) -> None:
        class Exploding:
            def save(self, **kwargs):  # noqa: ANN003, ANN201
                raise RuntimeError("disk is full")

        channel = FakeChannel()
        bridge = ChannelAgent(channel, FakeAgent(LONG), research_store=Exploding())

        bridge._process_message(message(LONG))

        # The answer matters more than the link to it.
        assert channel.sent
        assert "nira://research" not in channel.last

    def test_an_agent_error_still_reaches_the_user(self, store) -> None:
        class Broken:
            def run(self, prompt: str):  # noqa: ANN201
                raise RuntimeError("model is down")

        channel = FakeChannel()
        bridge = ChannelAgent(channel, Broken(), research_store=store)

        bridge._process_message(message("anything"))

        assert "error" in channel.last.lower()
        assert store.count() == 0
