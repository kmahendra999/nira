"""MCP (Model Context Protocol) layer for Nira."""

from nira.mcp.client import MCPClient
from nira.mcp.protocol import MCPError, MCPNotification, MCPRequest, MCPResponse
from nira.mcp.server import MCPServer
from nira.mcp.transport import (
    InProcessTransport,
    MCPTransport,
    SSETransport,
    StdioTransport,
    StreamableHTTPTransport,
)

__all__ = [
    "MCPClient",
    "MCPError",
    "MCPNotification",
    "MCPRequest",
    "MCPResponse",
    "MCPServer",
    "MCPTransport",
    "InProcessTransport",
    "SSETransport",
    "StdioTransport",
    "StreamableHTTPTransport",
]
