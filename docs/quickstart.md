# Quickstart

## Install

```bash
# From source (PyPI publish lands in v0.2 after OIDC migration)
pip install -e .

# Optional: pull a local model so the default provider works offline
ollama pull llama3.2
```

## Scaffold a project

```bash
arnes init
# Creates:
#   manuals/
#   run_logs/
#   manuals/hello-world.yaml
```

## Run your first playbook

```bash
arnes run manuals/hello-world.yaml --mock   # $0, no network
arnes run manuals/hello-world.yaml          # uses ollama/llama3.2 by default
arnes run manuals/hello-world.yaml --stream # stream step events as they complete
arnes run manuals/hello-world.yaml --loops  # actor-critic review loop

# Proactive planning (classifies your request into a domain template)
arnes plan "Build an Android dating app"
arnes plan "OSINT investigation on a company" --save
arnes plan --list-templates                  # see all 13 domain templates
arnes plan "..." --template osint            # force a specific template
```

## Stream a specialist

```bash
arnes stream @planner --task "Plan a blog post about ARNES" --mock
```

## List specialists / playbooks

```bash
arnes list specialists
arnes list playbooks --dir manuals
```

## Benchmark

```bash
arnes benchmark --seeds 3 --concurrent 2
```

## Start the MCP server

```bash
arnes mcp serve                  # stdio (Claude Desktop)
arnes mcp serve --transport http # http://127.0.0.1:8765/mcp + /events SSE
```
