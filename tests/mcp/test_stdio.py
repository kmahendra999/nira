"""Serving Nira's tools over MCP on stdio.

MCPServer had been complete for a long time — initialize, tools/list,
tools/call, auto-discovery, destructive-hint annotations — and was never
served. It existed only as an in-process tool registry, with no transport and
no entry point, so no MCP client could reach it at all.
"""

from __future__ import annotations

import io
import json

import pytest

from nira.mcp.server import MCPServer
from nira.mcp.stdio import handle_line, serve_stdio


@pytest.fixture
def server():
    return MCPServer()


def _request(method: str, request_id=1, **params) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    )


class TestRequests:
    def test_initialize_is_answered(self, server) -> None:
        reply = json.loads(handle_line(server, _request("initialize")))

        assert reply["id"] == 1
        assert reply["result"]["serverInfo"]["name"] == "nira"

    def test_tools_list_exposes_the_builtin_tools(self, server) -> None:
        reply = json.loads(handle_line(server, _request("tools/list")))

        names = {tool["name"] for tool in reply["result"]["tools"]}
        assert "calculator" in names
        assert len(names) > 1

    def test_a_tool_can_be_called(self, server) -> None:
        reply = json.loads(
            handle_line(
                server,
                _request(
                    "tools/call", name="calculator", arguments={"expression": "6 * 7"}
                ),
            )
        )

        assert reply["result"]["isError"] is False
        assert "42" in reply["result"]["content"][0]["text"]

    def test_an_unknown_method_is_a_protocol_error(self, server) -> None:
        reply = json.loads(handle_line(server, _request("nope/nope")))

        assert reply["error"]["code"] == -32601


class TestNotifications:
    def test_a_notification_gets_no_reply(self, server) -> None:
        """Answering one desynchronises a client matching replies to ids.

        notifications/initialized arrives on every handshake, so getting this
        wrong breaks every session immediately.
        """
        line = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})

        assert handle_line(server, line) is None

    def test_a_notification_for_an_unknown_method_is_still_silent(self, server) -> None:
        line = json.dumps({"jsonrpc": "2.0", "method": "notifications/whatever"})

        assert handle_line(server, line) is None


class TestMalformedInput:
    def test_invalid_json_returns_a_parse_error(self, server) -> None:
        reply = json.loads(handle_line(server, "not json at all"))

        assert reply["error"]["code"] == -32700
        # The id is genuinely unknown here; inventing one would collide with
        # a real request the client is waiting on.
        assert reply["id"] is None

    def test_a_json_scalar_is_rejected(self, server) -> None:
        reply = json.loads(handle_line(server, "42"))

        assert reply["error"]["code"] == -32700

    def test_blank_lines_are_ignored(self, server) -> None:
        assert handle_line(server, "   \n") is None

    def test_a_crashing_handler_does_not_end_the_session(self, server) -> None:
        """The client should lose one call, not its connection."""

        def _explode(_request):
            raise RuntimeError("tool registry on fire")

        server.handle = _explode  # type: ignore[method-assign]

        reply = json.loads(handle_line(server, _request("tools/list")))

        assert reply["error"]["code"] == -32603
        assert "on fire" in reply["error"]["message"]


class TestLoop:
    def test_reads_until_stdin_closes(self, server) -> None:
        stdin = io.StringIO(
            _request("initialize", 1)
            + "\n"
            + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
            + "\n"
            + _request("tools/list", 2)
            + "\n"
        )
        stdout = io.StringIO()

        assert serve_stdio(server, stdin=stdin, stdout=stdout) == 0

        replies = [json.loads(line) for line in stdout.getvalue().splitlines()]
        assert [reply["id"] for reply in replies] == [1, 2], (
            "the notification should not have produced a reply"
        )

    def test_each_reply_is_one_line(self, server) -> None:
        """The framing is newline-delimited; a pretty-printed reply breaks it."""
        stdout = io.StringIO()

        serve_stdio(
            server, stdin=io.StringIO(_request("tools/list") + "\n"), stdout=stdout
        )

        assert len(stdout.getvalue().strip().splitlines()) == 1

    def test_empty_input_exits_cleanly(self, server) -> None:
        assert serve_stdio(server, stdin=io.StringIO(""), stdout=io.StringIO()) == 0
