# Specialists

ARNES ships 5 built-in specialists. Each is a
`(system_prompt + tools + output_schema)` bundle that runs a ReAct-style
tool-use loop with pydantic-validated structured output.

| Name         | Role                                            | Default model     | Tools                          |
|--------------|-------------------------------------------------|-------------------|--------------------------------|
| `@planner`   | Breaks a task into specialist steps.            | `ollama/llama3.2` | (none)                         |
| `@coder`     | Writes production-quality code from specs.      | `ollama/llama3.2` | `fs_read`, `fs_write`, `shell` |
| `@reviewer`  | Reviews code for correctness / security / perf. | `ollama/llama3.2` | `fs_read`                      |
| `@tester`    | Writes + runs tests, reports coverage.          | `ollama/llama3.2` | `fs_read`, `fs_write`, `shell` |
| `@debugger`  | Diagnoses a failing test, proposes a fix.       | `ollama/llama3.2` | `fs_read`, `shell`             |

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

## Streaming with tools (R15)

`Specialist.stream()` mirrors `run()` but uses
`provider.stream_complete()`. R15 closes the R11→R14 gap: streaming now
**participates in the ReAct loop**. If the provider streams `tool_calls`,
the specialist executes the tools and starts another streaming iteration.

See [`examples/05_streaming.py`](https://github.com/frangelbarrera/ARNES/blob/main/examples/05_streaming.py)
for a runnable example.
