# Statistical significance testing for Agentic Harness benchmarks

Agentic Harness built-in benchmark harness reports per-playbook success rate,
avg / p95 duration, tokens, and cost. These are **descriptive
statistics** — they tell you what happened in the runs you executed.
They do **not** tell you whether a difference between two runs is
real or noise.

This doc is the methodology Agentic Harness recommends for going from
descriptive statistics to **inferential statistics**: confidence
intervals, significance tests, effect sizes, and power analysis.
The `arnes benchmark --stats` flag that automates this lands in
v0.2; until then, the methodology below is what an operator should
run by hand (or in a notebook) on the JSON output of
`arnes benchmark --seeds N`.

## 1. Why p95 is not enough

`arnes benchmark` reports `p95_duration_s` per playbook. This is
useful for spotting outliers but it has three problems as a
significance measure:

1. **It is a single-point estimate.** A p95 of 0.030 s vs 0.035 s
   *looks* different, but with N=5 seeds the 95 % CI on each p95
   is so wide that the two could easily come from the same
   distribution.
2. **It is not a test.** "The new PR's p95 is 5 % higher than main"
   is a claim that demands a hypothesis test, not a side-by-side
   table.
3. **It is not comparable across runs.** Wall-clock p95 depends on
   machine load. Two runs on different machines have
   non-comparable p95s even if the underlying distribution is
   identical.

The fix is to run more seeds and apply a real significance test.
The rest of this doc walks through the recommended procedure.

## 2. The recommended procedure

### Step 1 — Run enough seeds

For a meaningful significance test, you need at least **N=30 seeds**
per configuration. With N<10, no test has enough power to detect
anything but the largest effects. With N=30, you can detect a 10 %
difference in duration with ~80 % power at α=0.05.

```bash
# Run the baseline (main branch) with 30 seeds.
git checkout main
arnes benchmark --seeds 30 --output baseline.json

# Run the candidate (your PR branch) with 30 seeds.
git checkout my-feature-branch
arnes benchmark --seeds 30 --output candidate.json
```

The mock LLM is deterministic, so for mock-only runs N=30 is fast
(seconds, not minutes). For real-LLM runs, N=30 is expensive —
budget accordingly.

### Step 2 — Compute descriptive statistics

For each playbook and each metric (duration, tokens_in, tokens_out,
cost, success_rate), compute:

- **Mean** (μ)
- **Standard deviation** (σ)
- **Median** (more robust than mean for skewed distributions)
- **95 % bootstrap confidence interval** on the mean (see §3)

The bootstrap CI is preferred over the normal-approximation CI
(`μ ± 1.96 · σ/√N`) because benchmark distributions are typically
right-skewed (a few slow outliers) and the normal approximation
underestimates the upper tail.

### Step 3 — Run a significance test

The test you run depends on what you are comparing:

| Comparison                                  | Recommended test                  | Why                                          |
|---------------------------------------------|-----------------------------------|----------------------------------------------|
| Two configurations, same playbook, duration | **Mann-Whitney U** (two-sided)    | Non-parametric; duration is right-skewed     |
| Two configurations, same playbook, tokens   | **Welch's t-test**                | Token counts are roughly normal              |
| Two configurations, same playbook, success  | **Fisher's exact test**           | Success is binary (pass/fail)                |
| Many configurations, same playbook          | **Kruskal-Wallis** + Dunn's post-hoc | Non-parametric one-way ANOVA              |

For all tests, **report the p-value AND the effect size**. A
p-value <0.05 with a 1 % effect size is statistically significant
but practically irrelevant. The effect size you should report:

- For Mann-Whitney U: the **rank-biserial correlation** (`r = 1 -
  2U / (n1·n2)`).
- For Welch's t-test: **Cohen's d** (`d = (μ1 - μ2) / s_pooled`).
- For Fisher's exact: the **odds ratio**.

### Step 4 — Apply multiple-comparison correction

If you are comparing K playbooks × M metrics, you are running
K·M tests. With K=10 playbooks and M=4 metrics, that's 40 tests —
at α=0.05, you expect 2 false positives by chance alone.

Apply a **Benjamini-Hochberg** correction (controls the false
discovery rate, less conservative than Bonferroni) to the family of
p-values you report. The corrected q-values are what you should
publish; the raw p-values go in an appendix.

### Step 5 — Report power (optional but recommended)

If you failed to detect a difference, was it because there is no
difference, or because your N was too small? A **power analysis**
answers this. For a two-sided Mann-Whitney U at α=0.05 with 80 %
power, the minimum detectable effect size (in rank-biserial `r`) is
approximately:

| N (per group) | Min detectable r |
|----------------|-------------------|
| 10             | 0.62              |
| 30             | 0.36              |
| 100            | 0.20              |
| 300            | 0.11              |

If you ran N=30 and didn't see a difference, you can only rule out
effects larger than `r=0.36` — smaller effects could still be there.

## 3. Bootstrap confidence interval (recommended CI method)

The bootstrap is a resampling procedure that does not assume a
specific distribution shape. For a sample of size N:

1. Draw a random sample of size N **with replacement** from the
   observed data.
2. Compute the mean of the resample.
3. Repeat 10 000 times.
4. The 95 % CI is the 2.5th and 97.5th percentile of the resample
   means.

Python implementation:

```python
import numpy as np

def bootstrap_ci(samples: list[float], n_resamples: int = 10_000) -> tuple[float, float]:
    rng = np.random.default_rng(seed=42)
    means = []
    for _ in range(n_resamples):
        resample = rng.choice(samples, size=len(samples), replace=True)
        means.append(resample.mean())
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))
```

Use `seed=42` (or any fixed seed) so your CIs are reproducible —
the bootstrap is itself a random procedure.

## 4. Worked example

Suppose you ran `arnes benchmark --seeds 30` on `main` and on your
PR branch, for the `audit-pr` playbook, and observed:

| Branch | Mean duration (s) | Stddev | N  |
|--------|-------------------|--------|----|
| main   | 0.0241            | 0.0030 | 30 |
| PR     | 0.0278            | 0.0035 | 30 |

Naive conclusion: "the PR is 15 % slower." But:

- **Bootstrap 95 % CI on `main` mean:** [0.0230, 0.0253]
- **Bootstrap 95 % CI on `PR` mean:** [0.0265, 0.0291]
- **Mann-Whitney U p-value:** 0.0003
- **Rank-biserial r:** 0.71 (large effect)

So the PR is **statistically significantly slower** with a **large
effect size**. This is a real regression; do not merge.

Now suppose the numbers were:

| Branch | Mean duration (s) | Stddev | N  |
|--------|-------------------|--------|----|
| main   | 0.0241            | 0.0030 | 30 |
| PR     | 0.0245            | 0.0032 | 30 |

- **Mann-Whitney U p-value:** 0.62
- **Rank-biserial r:** 0.08 (tiny effect)

Not significant. Merge.

## 5. What v0.2 will automate

The `arnes benchmark --stats` flag (v0.2) will:

1. Run each playbook N times (default 30).
2. Compute mean / stddev / median / bootstrap-95 % CI for every
   metric.
3. If a `--baseline <path>` is provided, run Mann-Whitney U /
   Welch's t-test / Fisher's exact test for each (playbook, metric)
   pair, with Benjamini-Hochberg correction across the family.
4. Print a table:

   ```
   Playbook     Metric       Baseline         Candidate        Δ        p       q       r
   audit-pr     duration     0.0241±0.0030    0.0278±0.0035    +15.4 %  0.0003  0.012   0.71
   audit-pr     tokens_in    2104±12          2108±14          +0.2 %   0.45    0.45    0.09
   ...
   ```

5. Write a `benchmark-stats.json` with the full per-test results
   (point estimates, CIs, p-values, q-values, effect sizes) so a
   notebook or paper can consume them programmatically.

Until v0.2 lands, the procedure is manual: run `arnes benchmark
--seeds 30 --output baseline.json` and `--output candidate.json`,
load both JSONs in a notebook, and run the tests in §3 / §4.

## 6. References

The methodology above follows:

- **Wasserman, L. (2004).** *All of Statistics.* Springer. —
  general reference for the tests.
- **Efron, B. & Tibshirani, R. (1993).** *An Introduction to the
  Bootstrap.* Chapman & Hall. — bootstrap CIs.
- **Benjamini, Y. & Hochberg, Y. (1995).** "Controlling the false
  discovery rate." *JRSS-B.* — FDR correction.

For the specific case of LLM benchmarking, see also:

- **Liang et al. (2022).** *Holistic Evaluation of Language Models
  (HELM).* — the methodology paper most LLM eval papers cite.
- **Chen et al. (2021).** *Evaluating Large Language Models Trained
  on Code (HumanEval).* — the canonical `pass@k` paper.

If you use Agentic Harness in published research and follow this methodology,
cite Agentic Harness via `CITATION.cff` (repo root) and include the
`benchmark-stats.json` (once v0.2 ships) as supplementary material.
