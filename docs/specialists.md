# Specialists

Agentic Harness ships 12 built-in specialists. Each is a
`(system_prompt + tools + output_schema)` bundle that runs a ReAct-style
tool-use loop with pydantic-validated structured output.

## Core specialists

| Name | Role | Default model | Tools |
|------|------|---------------|-------|
| `@planner` | Breaks a task into specialist steps. | `ollama/llama3.2` | (none) |
| `@coder` | Writes production-quality code from specs. | `ollama/llama3.2` | `fs_read`, `fs_write`, `shell` |
| `@reviewer` | Reviews code for correctness / security / perf. Also used as the default critic in review loops. | `ollama/llama3.2` | `fs_read` |
| `@tester` | Writes + runs tests, reports coverage. | `ollama/llama3.2` | `fs_read`, `fs_write`, `shell` |
| `@debugger` | Diagnoses a failing test, proposes a fix. | `ollama/llama3.2` | `fs_read`, `shell` |

## Extended specialists

| Name | Role | Default model |
|------|------|---------------|
| `@researcher` | Web and document research, summarisation. | `ollama/llama3.2` |
| `@security-auditor` | Security review of code, configs, and dependencies. | `ollama/llama3.2` |
| `@devops-engineer` | CI/CD, deployment, infrastructure-as-code. | `ollama/llama3.2` |
| `@data-scientist` | Data analysis, ML evaluation, statistical reporting. | `ollama/llama3.2` |
| `@product-manager` | Product requirements, user stories, roadmap. | `ollama/llama3.2` |
| `@market-analyst` | Market analysis, competitor research, pricing. | `ollama/llama3.2` |
| `@cost-estimator` | Token / dev / infra cost estimation. | `ollama/llama3.2` |

## Structured output

Every specialist declares an `output_schema` (JSON Schema) AND a
`pydantic_model` (strong validation). The middleware's
`VerificationLayer` forces JSON-mode and validates the response against
the schema before returning it to the caller.

Example (`@coder`):

```python
class CoderOutput(BaseModel):
    files: list[CoderFile] = Field(default_factory=list)
    summary: str
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
```

## ReAct tool-use loop

`Specialist.run()` executes:

1. Format input as user message.
2. Call LLM with tools registered.
3. If LLM returns `tool_calls`, execute each tool and append results.
4. Repeat until LLM returns final response (no `tool_calls`) or
   `max_iterations` (default 5).
5. Validate response against `pydantic_model`.
6. Return structured result.

## Streaming with tools

`Specialist.stream()` mirrors `run()` but uses
`provider.stream_complete()`. Streaming **participates in the ReAct
loop**: if the provider streams `tool_calls`,
the specialist executes the tools and starts another streaming iteration.

See [`examples/05_streaming.py`](https://github.com/frangelbarrera/agentic-harness/blob/main/examples/05_streaming.py)
for a runnable example.

## Using specialists as critics

The `@reviewer` specialist is the default critic in actor-critic review
loops. When a playbook step declares a `review:` config (or the
`--loops` CLI flag is used), `@reviewer` evaluates the step's output and
returns a verdict (`approve` / `request_changes` / `reject`) with
feedback. See the [Playbooks](playbooks.md) doc for the review loop
schema.
