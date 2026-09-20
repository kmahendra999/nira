"""Serve Nira's tools over MCP on stdio.

``MCPServer`` has been complete for a long time — initialize, tools/list,
tools/call, auto-discovery of built-in tools, destructive-hint annotations —
and was never actually *served*. It was instantiated only as an in-process tool
registry, with no transport and no entry point, so nothing outside the process
could reach it. Any MCP client, Claude Desktop included, had no way in.

This is that entry point: newline-delimited JSON-RPC on stdin/stdout, which is
what stdio MCP clients speak.

Two rules the transport has to respect, both easy to get wrong:

*   **stdout carries protocol, nothing else.** A stray ``print`` corrupts the
    stream and the client's parser gives up on the session. Logging is pinned
    to stderr here for that reason.
*   **A notification gets no reply.** JSON-RPC notifications (no ``id``) are
    fire-and-forget; answering one desynchronises a client that is matching
    responses to request ids. ``notifications/initialized`` arrives on every
    single handshake, so getting this wrong breaks every session immediately.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Optional, TextIO

from nira.mcp.protocol import INTERNAL_ERROR, PARSE_ERROR, MCPRequest, MCPResponse
from nira.mcp.server import MCPServer

logger = logging.getLogger(__name__)


def _error(request_id: Any, code: int, message: str) -> str:
    return MCPResponse.error_response(request_id, code, message).to_json()


def handle_line(server: MCPServer, line: str) -> Optional[str]:
    """Process one JSON-RPC line, returning the reply or None to stay silent.

    Kept separate from the loop so the protocol behaviour is testable without
    driving real file objects.
    """
    line = line.strip()
    if not line:
        return None

    try:
        message = json.loads(line)
    except (ValueError, TypeError):
        # id is unknown at this point, so the spec's null is the only honest
        # answer — inventing one would collide with a real request.
        return _error(None, PARSE_ERROR, "Invalid JSON")

    if not isinstance(message, dict):
        return _error(None, PARSE_ERROR, "Expected a JSON object")

    request_id = message.get("id")
    if request_id is None:
        # A notification. Dispatch for the side effect, answer nothing.
        try:
            server.handle(
                MCPRequest(
                    method=message.get("method", ""),
                    params=message.get("params") or {},
                    id=None,
                )
            )
        except Exception:
            logger.exception("notification handler failed")
        return None

    try:
        response = server.handle(
            MCPRequest(
                method=message.get("method", ""),
                params=message.get("params") or {},
                id=request_id,
            )
        )
    except Exception as exc:
        # A crashing tool must not take the session down with it: the client
        # gets an error for this call and keeps its connection.
        logger.exception("request handler failed")
        return _error(request_id, INTERNAL_ERROR, str(exc))

    return response.to_json()


def serve_stdio(
    server: Optional[MCPServer] = None,
    *,
    stdin: Optional[TextIO] = None,
    stdout: Optional[TextIO] = None,
) -> int:
    """Read requests until stdin closes. Returns a process exit code."""
    active = server if server is not None else MCPServer()
    source = stdin if stdin is not None else sys.stdin
    sink = stdout if stdout is not None else sys.stdout

    for line in source:
        reply = handle_line(active, line)
        if reply is None:
            continue
        sink.write(reply + "\n")
        # Flush per message: a client blocks waiting for this reply, so
        # sitting in a buffer until the next write reads as a hang.
        sink.flush()
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.WARNING,
        stream=sys.stderr,  # never stdout: that is the protocol channel
        format="%(levelname)s %(name)s %(message)s",
    )
    return serve_stdio()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = ["handle_line", "main", "serve_stdio"]
