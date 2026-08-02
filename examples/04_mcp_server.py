#!/usr/bin/env python3
"""
ARNES Example: MCP Server Integration

Shows how to start the ARNES MCP server for Claude Desktop / Cursor integration.

Usage:
    python examples/04_mcp_server.py

Then in Claude Desktop config:
{
  "mcpServers": {
    "arnes": {
      "command": "python",
      "args": ["examples/04_mcp_server.py"]
    }
  }
}
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from arnes.mcp.server import ArnesMCPServer


async def main():
    print("ARNES MCP Server starting on stdio...", file=sys.stderr)
    print("Configure in Claude Desktop with:", file=sys.stderr)
    print('  {"mcpServers": {"arnes": {"command": "python", "args": ["examples/04_mcp_server.py"]}}}', file=sys.stderr)
    print(file=sys.stderr)

    server = ArnesMCPServer()
    await server.serve_stdio()


if __name__ == "__main__":
    asyncio.run(main())
