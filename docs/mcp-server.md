# MCP Server

ARNES exposes itself as an MCP (Model Context Protocol) server so you can
use it from Claude Desktop, Cursor, Cline, Zed, or any MCP-compatible
client.

## Tools exposed

| Tool                    | Description                                |
|-------------------------|--------------------------------------------|
| `arnes_run_playbook`    | Execute a playbook YAML.                   |
| `arnes_list_specialists`| List the 5 built-in specialists.           |
| `arnes_list_playbooks`  | List playbooks in a directory.             |
| `arnes_validate_playbook`| Validate a playbook without executing.   |

## Claude Desktop config

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "arnes": {
      "command": "arnes",
      "args": ["mcp", "serve"]
    }
  }
}
```

## HTTP transport + SSE (R15)

```bash
# Loopback only — no auth required
arnes mcp serve --transport http

# Expose to the local network — bearer token REQUIRED
ARNES_MCP_TOKEN="sk-..." arnes mcp serve --transport http --host 0.0.0.0 --port 8765
```

### Endpoints

| Method | Path       | Description                                                  |
|--------|------------|--------------------------------------------------------------|
| POST   | `/`        | JSON-RPC dispatcher (the MCP tools).                         |
| POST   | `/mcp`     | Alias for `/`.                                               |
| GET    | `/events`  | SSE stream — `event: <name>\ndata: <json>\n\n` frames.       |
| GET    | `/sse`     | Alias for `/events`.                                         |

### SSE wire format (R15 stub)

```http
GET /events HTTP/1.1
Accept: text/event-stream

HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
Connection: keep-alive

event: server_info
data: {"server": "arnes", "version": "0.1.0a1", "protocol": "2024-11-05", "ts": 1700000000.0}

: ping

: ping
```

R15 emits a single `server_info` event up-front, then idles on `: ping`
heartbeats (15 s interval). v0.2 will replace the heartbeat loop with a
real subscription to `PlaybookExecutor.stream` so subscribers see
step-level transitions in real time.

### Security

- **Bearer token**: if `ARNES_MCP_TOKEN` is set, every request must carry
  `Authorization: Bearer <token>`. Constant-time comparison.
- **Loopback-only binding**: if no token is configured, the server
  refuses to bind on anything other than `127.0.0.1` / `::1`.
- **Rate limit**: 100 requests/minute per client IP (sliding window).
- **Body size cap**: 1 MiB.
- **Path traversal**: `_validate_playbook_path` rejects anything in
  `/etc`, `/root`, `/var`, `/proc`, `/sys`, `/dev`.
