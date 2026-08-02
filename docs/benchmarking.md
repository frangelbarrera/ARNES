# Benchmarking

ARNES ships a benchmark harness for measuring playbook success rate,
duration, tokens, and cost across multiple seeds and concurrent runs.

## Quick run

```bash
# 1 seed, 1 concurrent — fastest sanity check
arnes benchmark

# 3 seeds per playbook, 2 playbooks at once — statistical signal
arnes benchmark --seeds 3 --concurrent 2

# 5 seeds, 4-way parallel — fuller picture
arnes benchmark --seeds 5 --concurrent 4
```

## What it measures

For each playbook in `manuals/`:

| Metric           | Description                                         |
|------------------|-----------------------------------------------------|
| `runs`           | Number of runs (seeds).                             |
| `success_rate`   | Fraction of runs that succeeded.                    |
| `avg_duration_s` | Mean wall-clock duration.                           |
| `p95_duration_s` | 95th percentile duration.                           |
| `avg_tokens_in`  | Mean input tokens.                                  |
| `avg_tokens_out` | Mean output tokens.                                 |
| `avg_cost_usd`   | Mean USD cost (always $0 with the mock LLM).        |

Plus aggregate `overall_*` metrics across all playbooks.

## Determinism

The mock LLM (`_SchemaValidMockLLMProvider`) is fully deterministic —
same input ⇒ same output. So:

- Same seed + same suite ⇒ same metrics.
- Diffing benchmark JSON across commits is meaningful.

Real-LLM benchmarks (with `--model openai/gpt-4o` etc.) are
non-deterministic by design — the benchmark harness still works, but
diffing across commits is not meaningful.

## Output

Results are saved to `benchmark-results.json` (or `--output <path>`)
in a diff-stable JSON format. The CLI also prints a rich table:

```
 Benchmark Results — basic suite
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ Playbook           ┃ Runs ┃ Success ┃ Avg dur(s) ┃ P95 dur(s) ┃ Avg tokens ┃ Avg cost  ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ hello-world        │    3 │     100% │     0.0123 │     0.0145 │        148 │ $0.000000 │
│ code-review        │    3 │     100% │     0.0145 │     0.0167 │        192 │ $0.000000 │
└────────────────────┴──────┴─────────┴────────────┴────────────┴────────────┴───────────┘

Overall: success=100%, avg_dur=0.0134s, avg_tokens=170, avg_cost=$0.000000
```

## vcrpy cassettes

ARNES uses [vcrpy](https://vcrpy.readthedocs.io/) to record real LLM HTTP
traffic once, then replay it on every test run — no API spend, fully
deterministic.

ARNES ships 3 cassettes under `tests/snapshot/cassettes/`:

| Cassette                    | Specialist | Provider         |
|-----------------------------|------------|------------------|
| `test_planner_basic.yaml`   | `@planner` | `openai/gpt-4o`  |
| `test_coder_basic.yaml`     | `@coder`   | `openai/gpt-4o`  |
| `test_reviewer_basic.yaml`  | `@reviewer`| `openai/gpt-4o`  |

To regenerate a cassette, see the regeneration instructions in
`tests/snapshot/test_litellm_cassette.py` (set `OPENAI_API_KEY`, flip
`record_mode` to `'once'`, delete the cassette, re-run).
