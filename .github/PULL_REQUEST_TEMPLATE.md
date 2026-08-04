<!-- Thanks for contributing to Agentic Harness! Please fill out the sections below. -->

## Summary

<!-- 1–3 sentences describing what this PR changes and why. -->

## Linked issues

<!-- Use "Closes #123", "Fixes #123", or "Refs #123" as appropriate. -->

- Closes #
- Refs #

## Type of change

- [ ] `feat` — new feature
- [ ] `fix` — bug fix
- [ ] `docs` — documentation only
- [ ] `refactor` — refactor without behavior change
- [ ] `perf` — performance improvement
- [ ] `test` — adds tests
- [ ] `chore` — build, deps, ci
- [ ] `breaking` — breaking change (please describe below)

## Checklist

Please tick every box. If something does not apply, mark it `[x]` and add a
short note explaining why. PRs that skip the checklist will be sent back.

- [ ] **Tests pass** — `uv run pytest` is green.
- [ ] **Lint passes** — `uv run ruff check arnes/` is clean.
- [ ] **Types pass** — `uv run mypy arnes/ --strict` is clean (strict
      mode is enforced in CI and must stay at 0 errors).
- [ ] **Coverage ≥ 65%** — `uv run pytest --cov=arnes` stays at or above
      65%. New features include new tests.
- [ ] **Docs updated** — README / docs / examples updated if behavior
      changed.
- [ ] **CHANGELOG entry** — added under `[Unreleased]` in `CHANGELOG.md`.
- [ ] **Conventional commit** — branch and commits follow the format
      described in CONTRIBUTING.md (`feat: ...`, `fix: ...`, etc.).
- [ ] **No secrets** — no API keys, tokens, or PII are introduced in this
      diff (including in test fixtures).
- [ ] **Run-log-safe** — if I added a snapshot test or example
      run log, it does not contain real LLM responses with sensitive data.

## Screenshots / output

<!-- If this PR changes CLI output, UI, or a playbook example, paste a
before/after or terminal capture. For animated demos, see scripts/demo.sh. -->

## Notes for reviewers

<!-- Anything reviewers should pay attention to, tricky bits, open
questions, or follow-up work. -->
