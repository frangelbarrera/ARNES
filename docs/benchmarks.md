# Benchmarks & Evaluation

## Built-in Benchmark Suite

Agentic Harness includes a benchmark runner that measures playbook performance with
statistical rigor.

### Quick Start

```bash
# Run all playbooks with 5 seeds, 4 concurrent
arnes benchmark --seeds 5 --concurrent 4

# Results saved to benchmark-results.json
```

### Metrics

| Metric | Description |
|---|---|
| Success rate | Percentage of runs that completed successfully |
| Avg duration | Mean wall-clock time per run (seconds) |
| P95 duration | 95th percentile duration (nearest-rank method) |
| Avg tokens in | Mean input tokens per run |
| Avg tokens out | Mean output tokens per run |
| Avg cost | Mean USD cost per run |

### Multi-Seed Runs

The `SeededMockLLMProvider` produces deterministic-but-varied responses across
seeds. Same seed → same output. Different seed → different output. This enables:

- **Reproducibility**: Fix a seed, share it, anyone can reproduce your results
- **Statistical significance**: Run N seeds, compare distributions
- **Variance analysis**: Measure how sensitive your playbook is to LLM variation

### Concurrent Execution

The `--concurrent N` flag runs N playbooks simultaneously via `asyncio.Semaphore`.
This tests:
- Thread safety of the executor
- CostGuard under concurrent budget pressure
- TokenOptimizer cache hit rate under load

## Standard Benchmark Suites (Roadmap)

Agentic Harness does not yet integrate with standard evaluation suites. Planned for v0.2:

| Suite | What it tests | Status |
|---|---|---|
| HumanEval | Code generation correctness | 🚧 v0.2 |
| MBPP | Multi-step programming | 🚧 v0.2 |
| GAIA | General AI assistant | 🚧 v0.3 |
| SWE-bench | Software engineering tasks | 🚧 v0.3 |
| AgentBench | Multi-task agent evaluation | 🚧 v0.4 |

## Statistical Rigor

### Current Capabilities
- ✅ Multi-seed runs for variance estimation
- ✅ P95 duration (nearest-rank method)
- ✅ Deterministic mock LLM for reproducible results
- ✅ VCRpy cassettes for real-LLM replay

### Planned (v0.2-v0.3)
- 🚧 Confidence intervals (bootstrap)
- 🚧 Mann-Whitney U test for comparing configurations
- 🚧 Effect size (Cohen's d)
- 🚧 Multi-run comparison reports

## Reproducibility Guidelines

For research papers using Agentic Harness:

1. **Fix the seed**: `arnes benchmark --seeds 42`
2. **Record the environment**: Python version, OS, Agentic Harness version
3. **Use vcrpy cassettes**: For real-LLM experiments, record and commit cassettes
4. **Share the run log**: The markdown audit trail is your reproducibility artifact
5. **Cite Agentic Harness**: Use the
   [CITATION.cff](https://github.com/frangelbarrera/agentic-harness/blob/main/CITATION.cff)
   file

### Example Citation

```bibtex
@software{arnes,
  author = {Barrera, Frangel},
  title = {Agentic Harness — The Open Agent Harness},
  version = {0.1.0a1},
  year = {2026},
  url = {https://github.com/frangelbarrera/agentic-harness},
  license = {Apache-2.0}
}
```
