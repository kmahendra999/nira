"""ChannelAgent — bridge between messaging channels and AI agents.

Routes incoming :class:`~nira.channels._stubs.ChannelMessage` objects
to an agent, classifies queries as "quick" or "deep", and delivers responses
either inline or as a preview with an escalation link to a full report.
"""

from __future__ import annotations

import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from nira.channels._stubs import BaseChannel, ChannelMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Query classifier
# ---------------------------------------------------------------------------

_QUICK_PREFIXES = re.compile(
    r"^(when\b|where\b|find\b|who\b|what's\b)",
    re.IGNORECASE,
)

_DEEP_KEYWORDS = re.compile(
    r"\b(summarize|research|context|compare|analyze|overview|timeline|history)\b",
    re.IGNORECASE,
)

_TIME_RANGE = re.compile(
    r"\blast\s+(week|month|quarter|year)\b",
    re.IGNORECASE,
)


def classify_query(text: str) -> str:
    """Return ``'quick'`` or ``'deep'`` based on heuristics.

    Deep signals take priority over quick signals.  A query is classified as
    deep if it contains deep keywords, a time-range phrase, or is longer than
    20 words.  Otherwise it is quick.
    """
    words = text.split()
    if _DEEP_KEYWORDS.search(text):
        return "deep"
    if _TIME_RANGE.search(text):
        return "deep"
    if len(words) > 20:
        return "deep"
    return "quick"


# ---------------------------------------------------------------------------
# ChannelAgent
# ---------------------------------------------------------------------------

_ESCALATION_TEMPLATE = "{preview}...\n\n---\nFull report ready — open in Nira:\nnira://research/{session_id}"
_LONG_RESPONSE_THRESHOLD = 500


class ChannelAgent:
    """Bridge between a :class:`BaseChannel` and an agent.

    On each incoming message the agent is invoked in a background thread so
    that :meth:`_handle_message` never blocks the channel's event loop.
    Quick queries with short responses are delivered inline; deep queries or
    long responses trigger a preview + escalation link.

    Parameters
    ----------
    channel:
        A connected :class:`BaseChannel` instance.
    agent:
        Any object that exposes a ``run(input: str) -> AgentResult``-compatible
        method (typically a :class:`~nira.agents._stubs.BaseAgent`
        subclass).
    max_workers:
        Size of the background :class:`~concurrent.futures.ThreadPoolExecutor`.
    research_store:
        Where escalated reports are kept so the link in the reply resolves.
        Defaults to the shared store; pass one explicitly in tests, or
        ``False`` to disable storage entirely.
    """

    def __init__(
        self,
        channel: BaseChannel,
        agent: Any,
        *,
        max_workers: int = 2,
        research_store: Any = None,
    ) -> None:
        self._channel = channel
        self._agent = agent
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._research_store = research_store
        channel.on_message(self._handle_message)

    def _store(self) -> Any:
        """The research store, opened on first use.

        Lazily, because most messages are short answers that never escalate
        and opening a database for them would be work done for nothing.
        """
        if self._research_store is False:
            return None
        if self._research_store is None:
            try:
                from nira.research import ResearchStore

                self._research_store = ResearchStore()
            except Exception:  # noqa: BLE001 - a reply is worth more than a link
                logger.warning("research store unavailable; link will not resolve")
                self._research_store = False
                return None
        return self._research_store

    def _remember(self, session_id: str, query: str, report: str) -> bool:
        """Persist a report under the id the reply is about to quote."""
        store = self._store()
        if store is None:
            return False
        try:
            store.save(
                query=query,
                report=report,
                report_id=session_id,
                channel=getattr(self._channel, "channel_type", "") or "",
            )
            return True
        except Exception:  # noqa: BLE001 - never lose the reply over storage
            logger.exception("could not store research report %s", session_id)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _handle_message(self, msg: ChannelMessage) -> Optional[str]:
        """Submit *msg* to the background pool and return ``None`` immediately."""
        self._pool.submit(self._process_message, msg)
        return None

    def _process_message(self, msg: ChannelMessage) -> None:
        """Classify, run the agent, and reply to the channel."""
        query_type = classify_query(msg.content)
        session_id = msg.session_id or uuid.uuid4().hex[:16]

        try:
            result = self._agent.run(msg.content)
            response_text: str = getattr(result, "content", str(result))
        except Exception as exc:  # noqa: BLE001
            friendly = (
                f"Sorry, I ran into an error while processing your request: {exc}"
            )
            # First positional arg is the DESTINATION (per-adapter native
            # ID — Discord channel ID, Slack channel ID, etc.); not the
            # channel TYPE label. The `conversation_id=` kwarg is the
            # native message ID for reply threading (per DiscordChannel
            # / SlackChannel / etc. send() contract — see #459).
            self._channel.send(
                msg.conversation_id,
                friendly,
                conversation_id=msg.message_id,
            )
            return

        is_long = len(response_text) > _LONG_RESPONSE_THRESHOLD

        if query_type == "deep" or is_long:
            # Write the report down *before* promising it. The link used to
            # carry a fresh uuid that referred to nothing: the full text went
            # out of scope the moment the preview was cut from it, so the
            # reader was offered something already thrown away.
            stored = self._remember(session_id, msg.content, response_text)
            if stored:
                preview = response_text[:_LONG_RESPONSE_THRESHOLD]
                reply = _ESCALATION_TEMPLATE.format(
                    preview=preview,
                    session_id=session_id,
                )
            else:
                # No store, so no link. Sending the whole thing is worse than
                # a preview but far better than a promise that will not open.
                reply = response_text
        else:
            reply = response_text

        # Same field-mapping as the error path above (#459).
        self._channel.send(
            msg.conversation_id,
            reply,
            conversation_id=msg.message_id,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Shut down the background thread pool."""
        self._pool.shutdown(wait=True)


__all__ = ["ChannelAgent", "classify_query"]
