# Audits

ARNES has been evaluated by a 9-judge panel across 15 rounds (R1 → R15).
This page indexes the audit reports under `docs/audits/`.

## Final reports (current)

| Round | Average | Notes |
|-------|---------|-------|
| [R15](audits/JUDGE_FINAL_R15.md) | TBD | Streaming + ReAct wired; SSE stub; cli split; +2 cassettes; mkdocs. |
| [R14](audits/JUDGE_FINAL_R14.md) | 89.8 | +97 tests on `tools/builtin.py`; executor split; `arnes stream` → `Thread.to_markdown()`. |
| [R13](audits/JUDGE_FINAL_R13.md) | 88.9 | First Tier-1 quick-win sweep; `_drain_event_to_sink` DRY helper; audit archive. |
| [R12](audits/JUDGE_FINAL_R12.md) | 87.6 | Streaming layer (5 layers); `parallel.py` extracted. |
| [R11](audits/JUDGE_FINAL_R11.md) | 85.4 | Benchmark runner + multi-seed; vcrpy cassette for `@planner`. |
| [R10](audits/JUDGE_FINAL_R10.md) | — | Snapshot testing foundation. |
| [R9](audits/JUDGE_FINAL_R9.md)  | — | FIX-R9-FINAL: streaming + audit trail. |
| [R8](audits/JUDGE_FINAL_R8.md)  | — | HTTP transport + auth + rate limit. |
| [R7](audits/JUDGE_FINAL_R7.md)  | — | CostGuard + circuit breaker. |
| [R6](audits/JUDGE_FINAL_R6.md)  | — | VerificationLayer + refusal pattern. |
| [R5](audits/JUDGE_FINAL_R5.md)  | — | Initial 6-judge panel. |
