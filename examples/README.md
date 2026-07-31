# ARNES Examples

This directory contains runnable example scripts that demonstrate ARNES usage.

## Quick Start

```bash
# Activate the virtual environment
source .venv/bin/activate

# Run examples (they use mock LLM — no API key needed)
python examples/01_hello_world.py
python examples/02_run_playbook.py
python examples/03_inspect_thread.py
python examples/04_mcp_server.py
```

## Examples

### 01_hello_world.py
The simplest ARNES usage — invoke a single specialist (`@planner`) and print the result.

### 02_run_playbook.py
Compile and execute a YAML playbook programmatically. Shows how to use `PlaybookCompiler` and `PlaybookExecutor`.

### 03_inspect_thread.py
Shows how to inspect the Thread (event log) after a run: filter by event type, reduce to current state, and display the timeline.

### 04_mcp_server.py
Starts the ARNES MCP server on stdio for integration with Claude Desktop, Cursor, Cline, or Zed.

### 05_streaming.py
Demonstrates token-by-token streaming using `Harness.stream()`. Shows how to consume the async generator and accumulate usage stats.

## Using Real LLMs

To use real LLMs instead of mock, replace `DemoMockProvider` with:

```python
from arnes.llm.factory import get_provider

# Ollama (local, free)
provider = get_provider("ollama/llama3.2")

# Anthropic (paid)
provider = get_provider("anthropic/claude-sonnet-4-20250514")

# OpenAI (paid)
provider = get_provider("openai/gpt-4o")
```

## Writing Your Own Playbook

```bash
# Scaffold a new playbook
arnes init --manual my-playbook

# Edit it
vim manuals/my-playbook.yaml

# Validate it
arnes lint manuals/my-playbook.yaml

# Run it (with mock for testing)
arnes run manuals/my-playbook.yaml --mock

# Run it (with real LLM)
arnes run manuals/my-playbook.yaml --model ollama/llama3.2
```
