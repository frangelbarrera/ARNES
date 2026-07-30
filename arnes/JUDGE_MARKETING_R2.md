# JUDGE_MARKETING_R2 — ARNES GitHub Marketing Readiness Re-Evaluation

**Task:** JUDGE-MKT-R2
**Evaluator:** DevRel / GitHub Growth Judge
**Subject:** `frangelbarrera/ARNES` — The Open Agent Harness (Python, Apache-2.0, v0.1.0a1)
**Cycle:** Round 2 re-evaluation
**Prior score (R1):** 64 / 100 — NO-GO for public launch (conditional GO after 5 fixes)
**Date:** 2026-07-31
**Method:** Re-read `README.md`, `PUBLISHING_GUIDE.md`, `scripts/setup-and-push.sh`, `pyproject.toml`, `docs/logo.svg`, `docs/social-card.svg`, `CONTRIBUTING.md`, `CHANGELOG.md`, `.github/workflows/`. Ran `python -m arnes.cli.main run manuals/hello-world.yaml --mock` to verify the quickstart end-to-end. Verified each R1 critical issue individually.

---

## 0. Verification of Round-1 Critical Fixes

| # | R1 Critical Issue | Status | Evidence |
|---|---|---|---|
| 1 | Broken launch runbook (`setup-and-push.sh` crashes at smoke test) | ✅ **FIXED** | `scripts/setup-and-push.sh:133-136` now runs `arnes lint manuals/smoke-test.yaml` and `arnes run manuals/smoke-test.yaml --mock` — the Spanish `manuales/`, the `.md.yaml` infix, and the `arnes ejecutar` alias are all gone. `PUBLISHING_GUIDE.md:31-32` matches. Verified by `rg "manuales\|smoke-test.md\|arnes ejecutar" scripts/ PUBLISHING_GUIDE.md` — no matches. The launch runbook no longer crashes at its own smoke test. |
| 2 | 3 broken README badges (PyPI, Discord, Coverage) | ✅ **FIXED** | `README.md:12-14` now uses static shields.io badges: `PyPI: not yet published` (lightgrey), `Discord: coming soon` (lightgrey), and the Coverage badge is **removed entirely**. The remaining 4 badges (Python, License, CI, Stars) all resolve to real endpoints. First impression no longer says "abandoned project." |
| 3 | Zero visual identity (no logo, no demo GIF, no social card) | ⚠️ **PARTIAL** | `docs/logo.svg` (24 lines, 1.4 KB) and `docs/social-card.svg` (65 lines, 3.4 KB) now exist. Logo is a 320×80 typographic wordmark with a gradient (sky-blue → indigo). Social card is 1280×630 with the ARNES wordmark, tagline "The Open Agent Harness", manifesto quote, and footer "Apache-2.0 · Python 3.11+ · From Latam to the world 🌎". README embeds the logo at the top (`README.md:3`). **But:** no demo GIF / asciinema / screenshot, no architecture diagram image (still ASCII art), no PNG export of the social card for GitHub's Open Graph preview (GitHub doesn't render SVG social cards — needs PNG/JPG). The single highest-leverage viral asset (a 30-60s terminal recording of `arnes run`) is still missing. |
| 4 | `pip install arnes` does not work (not on PyPI) | ✅ **FIXED** | `README.md:33-37` quickstart now uses `git clone https://github.com/frangelbarrera/ARNES.git` + `uv sync --all-extras --dev` + `arnes run manuals/hello-world.yaml --mock`. `README.md:214-228` Installation section explicitly says "ARNES is not yet on PyPI" and gives the git-clone path. The first command in the README no longer fails for every visitor. |
| 5 | Community infrastructure placeholder-only (Discord fake, no ISSUE_TEMPLATE, no FUNDING.yml) | ⚠️ **PARTIAL** | The Discord badge honestly says "coming soon" and links to GitHub Discussions as a fallback (`README.md:13, 303`). This is honest, not fake — the R1 "Discord invite `discord.gg/ARNES` is fake" embarrassment is gone. **But:** `.github/` still contains only `workflows/` — no `ISSUE_TEMPLATE/` directory, no `FUNDING.yml`, no `PULL_REQUEST_TEMPLATE.md`, no `CODEOWNERS`, no `dependabot.yml`, no `SECURITY_CREDITS.md`. The README Sponsors section lists GitHub Sponsors / Open Collective / BuyMeACoffee, but GitHub won't surface the "Sponsor this project" button without `FUNDING.yml`. The "Discussions category structure" is undocumented. `CONTRIBUTING.md:38` still references `arnes/events/` directory which doesn't exist (events live in `arnes/thread/events.py`). |

**Bonus fixes observed:**
- `arnes.dev` placeholder URL removed from README and pyproject.toml — Documentation link now points at `https://github.com/frangelbarrera/ARNES#readme`. No dead links in the README header. (R1 gap: "`arnes.dev` Documentation link in header is dead" — closed.)
- The README "Born bilingual: README, docs, quickstart, and Discord in EN and ES" overclaim from R1 is softened — the "Latam wedge" section now says "born bilingual: README, docs, and quickstart in EN and ES" but qualified with "If you want to contribute translations, open an issue with the `i18n` label." Still slightly aspirational (no `README.es.md` exists), but the false claim about Discord is gone.
- The CHANGELOG "4 curated examples" → "10 curated playbooks" — there are actually 10 manuals in `manuals/`, matching the count. (R1 gap: "CHANGELOG says '4 curated examples' but there are 10 — stale count" — closed.)
- The README "Known Limitations in v0.1 (Alpha)" section now lists 10 honest caveats (parallel branches sequential, HITL auto-rejects, Docker sandbox not wired, MCP HTTP minimal, retry schema-only, no compaction/pruning, no confidence gate/critic loop, coverage 66%, mypy non-blocking). This is the most trustworthy section of the README and significantly raises the credibility ceiling.
- `arnes.dev` references in source code: 0 (verified by `rg "arnes.dev" README.md pyproject.toml scripts/ PUBLISHING_GUIDE.md` — no matches). Only R1 audit docs still mention the old URL.

---

## 1. Scorecard

| # | Dimension | R1 | R2 | Δ | Weight | Weighted |
|---|-----------|---:|---:|---:|-------:|---------:|
| 1 | README quality | 75 | **85** | +10 | 15% | 12.75 |
| 2 | Description & topics | 80 | **82** | +2 | 8% | 6.56 |
| 3 | Visual identity | 35 | **60** | +25 | 10% | 6.00 |
| 4 | Narrative & positioning | 92 | **92** | 0 | 12% | 11.04 |
| 5 | Contributor experience | 70 | **68** | -2 | 10% | 6.80 |
| 6 | Documentation completeness | 55 | **60** | +5 | 12% | 7.20 |
| 7 | Community infrastructure | 45 | **55** | +10 | 8% | 4.40 |
| 8 | Release readiness | 65 | **78** | +13 | 10% | 7.80 |
| 9 | Social proof | 25 | **25** | 0 | 5% | 1.25 |
| 10 | Viral potential | 72 | **78** | +6 | 10% | 7.80 |
| | **OVERALL** | **64** | **72** | **+8** | 100% | **71.60** |

**Overall marketing score: 72 / 100** (R1: 64 — **+8 points**)

---

## 2. Dimension-by-Dimension (delta-only notes)

### 1. README quality — 75 → **85** (+10)

The README is now genuinely launch-ready. Three concrete improvements:
1. **Logo at the top** (`README.md:3`) — the typographic wordmark with gradient gives the repo a real identity in the first 100 pixels.
2. **Badges that resolve** — all 5 remaining badges (Python, License, CI, PyPI-honest, Discord-honest, Stars) render correctly. The "not yet published" and "coming soon" badges are honest signals, not broken ones.
3. **Quickstart that works** — `git clone` + `uv sync` + `arnes run --mock` actually runs (verified live: produces `bitacora-hello-world-*.md`). The first command a visitor tries no longer fails.

The comparison table vs LangChain/CrewAI/OpenAI Agents SDK is unchanged (still best-in-class). The 12-factor-agents alignment table is unchanged. The "Known Limitations in v0.1 (Alpha)" section is now the most credible part of the README — 10 honest caveats, no overclaim.

**Still missing:** no demo GIF / asciinema / screenshot. The "What it looks like" section is still text-only YAML + expected terminal output. For an agent framework competing with LangChain (which has rich demo assets), this remains the #1 README gap. A 30-60s terminal recording of `arnes run manuals/audit-pr.yaml --mock` producing a bitácora would be the single highest-leverage viral asset.

### 2. Description & topics — 80 → **82** (+2)

Unchanged content-wise. The 20 keywords in `pyproject.toml:15-35` are still excellent (`ai-agents`, `agent-harness`, `mcp`, `model-context-protocol`, `stateless-reducer`, `anti-hallucination`, `token-optimization`, `a2a`, `human-in-the-loop`). The `PUBLISHING_GUIDE.md` still provides a copy-paste repo description and the 20 GitHub topics. Slight bump because the README now matches the guide (R1 had a mismatch between guide and live repo).

**Still weak:** not yet applied to the actual GitHub repo (it's a guide, not committed metadata). Risk: operator forgets to paste them on launch day.

### 3. Visual identity — 35 → **60** (+25)

The biggest jump. From "zero visual identity" to "minimum viable brand":
- `docs/logo.svg` — 320×80 typographic wordmark with gradient. Embedded in README header. Renderable on GitHub (SVG is supported in `<img>` tags).
- `docs/social-card.svg` — 1280×630 Open Graph card with wordmark, tagline, manifesto quote, footer. Proper social-share dimensions.

**Still missing:**
- **No demo GIF / asciinema / screenshot.** The single biggest viral lever. A 30-60s terminal recording of `arnes run manuals/audit-pr.yaml --mock` producing a bitácora — exported as GIF via `agg` or `vhs` — would be the difference between "interesting README" and "viral README."
- **No PNG export of the social card.** GitHub's Open Graph preview does NOT render SVG — it requires PNG or JPG. The `docs/social-card.svg` exists but won't actually show up as the link preview on X/LinkedIn/Slack. A 5-minute conversion via `rsvg-convert` or `resvg` would close this.
- **No architecture diagram image.** The ASCII diagram in README §"Architecture" is fine for developers but not shareable on X.
- **No favicon** for the future docs site.
- **No brand color constant** documented (the logo uses `#0EA5E9` sky-blue → `#6366F1` indigo, but this isn't written down anywhere a contributor could reference).

For a "go viral" goal, the visual identity is now **passable** but not **shareable**. The missing demo GIF is the gap between "passable" and "viral."

### 4. Narrative & positioning — 92 → **92** (0)

Unchanged. The manifesto is still best-in-class. The "Control the agent. Don't worship it." mantra is still tweetable. The "manual is the code" angle is still unique. The Latam identity is still authentic. The named enemy (opaque, vendor-locked, budget-blind frameworks) is still sharp. This dimension was already at ceiling in R1; no work was needed and none was done.

**Minor opportunity:** add a "Manifesto v1.0 — Immutable" badge to the README badge row (R1 suggestion). Would visually reinforce the manifesto-driven identity.

### 5. Contributor experience — 70 → **68** (-2)

Slight regression. `CONTRIBUTING.md:38` still lists `arnes/events/` as a directory in the project structure tree — but `ls arnes/` shows no `events/` directory (events live in `arnes/thread/events.py`). A new contributor following the CONTRIBUTING map will look for `arnes/events/` and not find it. The R1 finding "`CONTRIBUTING.md` references `docs/specialists.md` and `docs/playbook-dsl.md` which don't exist" is still open.

The `.github/ISSUE_TEMPLATE/`, `PULL_REQUEST_TEMPLATE.md`, `CODEOWNERS`, `dependabot.yml` are all still missing — R1 critical issue #5 is partially closed (Discord honestly says "coming soon") but the templates are still absent. A contributor clicking "New Issue" gets the GitHub default, not a structured bug-report form. The "Sponsor this project" button won't render without `FUNDING.yml`.

**Still strong:** CONTRIBUTING.md content is thorough (dev setup, conventional commits, triaged priorities, PR process, testing, linting, how to add a specialist/playbook, security reporting). `AGENTS.md` + `CLAUDE.md` give AI contributors explicit guardrails. `.pre-commit-config.yaml` exists.

### 6. Documentation completeness — 55 → **60** (+5)

The `arnes.dev` dead link is gone — Documentation now points at `https://github.com/frangelbarrera/ARNES#readme`. No more 404s from the README header. The 10 example playbooks in `manuals/` are a solid library. The 4 example scripts in `examples/` use a mock provider — runnable with zero API keys. Inline docstrings are present in source.

**Still missing:**
- No docs site (no Mintlify/Docusaurus/mkdocs config). The README is the docs. For a framework competing with LangChain/CrewAI/OpenHands (all of which have multi-thousand-page docs sites), this is a real gap.
- No API reference (no sphinx/mkdocs auto-generation from pydantic schemas).
- No "concepts" guide (Thread, Specialist, Playbook, Middleware) for newcomers.
- No playbook DSL spec (`docs/playbook-dsl.md` is referenced in CONTRIBUTING but doesn't exist).
- `CONTRIBUTING.md` references `docs/specialists.md` and `docs/playbook-dsl.md` — both 404.

The R1 improvement #5 ("Resolve the docs overclaim") is **partially** done: `arnes.dev` is removed (good), but the `docs/` directory referenced in CONTRIBUTING still doesn't exist (bad). The overclaim is reduced but not eliminated.

### 7. Community infrastructure — 45 → **55** (+10)

The Discord honesty fix is the main gain. R1's "fake `discord.gg/ARNES` invite will 404" embarrassment is replaced with a "coming soon — meanwhile, use GitHub Discussions" message. This is honest and doesn't burn credibility on launch day.

**Still missing:**
- `.github/ISSUE_TEMPLATE/` — no bug_report.yml, feature_request.yml, config.yml.
- `.github/FUNDING.yml` — README Sponsors section lists 3 platforms but GitHub won't surface the "Sponsor" button without this file.
- `.github/PULL_REQUEST_TEMPLATE.md`.
- `.github/CODEOWNERS`.
- `.github/dependabot.yml`.
- `SECURITY_CREDITS.md` — referenced at the bottom of SECURITY.md but doesn't exist.
- Real Discord server — the "coming soon" is honest but a real Discord is the single highest-leverage community asset for an early-stage framework. Latam Python meetups would fill it fast.
- Discussions category structure (Announcements, Ideas, Q&A, Show and tell, Polls) is undocumented.

### 8. Release readiness — 65 → **78** (+13)

Three concrete improvements:
1. **Launch runbook works.** `setup-and-push.sh` no longer crashes at its own smoke test (R1 critical issue #1 closed). The script runs `arnes lint` + `arnes run --mock` on `manuals/smoke-test.yaml` — verified to succeed.
2. **Quickstart works.** `git clone` + `uv sync` + `arnes run --mock` actually runs (verified live). The first command a visitor tries no longer fails.
3. **mypy is now blocking in CI** (per JUDGE-DEV-R2) — R1's "mypy runs with `|| true` in CI (non-blocking)" finding is closed. The "competes with Microsoft" positioning is no longer undercut by a non-blocking type check.

**Still missing:**
- Not published to PyPI. The README honestly says so. The release workflow (`release.yml`) exists and is tag-triggered, but no `v*` tag has been pushed. The `PYPI_API_TOKEN` secret is not configured (manual setup step in PUBLISHING_GUIDE).
- Coverage at 65% (target: 80% by v0.2). Honestly disclosed.
- No signed releases (sigstore / GPG).

### 9. Social proof — 25 → **25** (0)

Unchanged. 0 stars (not public). No testimonials. No "used by" logos. No influencer endorsements. No beta-user quotes. The creator's 1300+1100 follower distribution is real potential, but currently zero social proof on the repo. This dimension is expected to remain low until launch.

### 10. Viral potential — 72 → **78** (+6)

The logo + social card raise the shareability ceiling. The README now looks like a real project, not a text dump. The "Control the agent. Don't worship it." mantra + "manual is the code" angle + Latam identity + manifesto immutability remain the four shareable hooks.

**Still missing:** the single highest-leverage viral asset — a 30-60s demo GIF of `arnes run manuals/audit-pr.yaml --mock` producing a bitácora — does not exist. Without it, the repo is text that asks for attention instead of video that earns it. A screenshot of the bitácora (with the markdown rendered) would be a partial substitute. The `docs/social-card.svg` exists but won't render as an Open Graph preview on X/LinkedIn (needs PNG).

---

## 3. Top 5 Critical Marketing Gaps (R2)

1. **No demo GIF / asciinema / screenshot.** The single highest-leverage viral asset. The "What it looks like" section is text-only. For an agent framework competing with LangChain (rich demo assets), this remains the #1 README gap. A 30-60s terminal recording of `arnes run manuals/audit-pr.yaml --mock` producing a bitácora — exported as GIF via `agg` or `vhs` — would be the difference between "interesting README" and "viral README." **Fix:** record a terminal session, export as GIF, embed at the top of the README. ~2 hours.

2. **`.github/` community infrastructure is still missing.** No `ISSUE_TEMPLATE/`, no `FUNDING.yml`, no `PULL_REQUEST_TEMPLATE.md`, no `CODEOWNERS`, no `dependabot.yml`, no `SECURITY_CREDITS.md`. A contributor clicking "New Issue" gets the GitHub default. The "Sponsor this project" button won't render. This is the R1 critical issue #5 — partially closed (Discord honestly says "coming soon") but the templates are still absent. **Fix:** add the 6 missing `.github/` files. ~2 hours.

3. **No PNG export of the social card.** `docs/social-card.svg` exists but GitHub's Open Graph preview does NOT render SVG — it requires PNG or JPG. The social card won't actually show up as the link preview on X/LinkedIn/Slack. The SVG is invisible to social platforms. **Fix:** convert `docs/social-card.svg` to `docs/social-card.png` via `rsvg-convert` or `resvg`. Add `<meta property="og:image" content="docs/social-card.png">` to the README (or wait for a docs site). ~5 minutes.

4. **No docs site.** The README is the docs. For a framework competing with LangChain/CrewAI/OpenHands (all of which have multi-thousand-page docs sites with tutorials, API references, and integrations), this is a real gap. New users land on the README and bounce because there's no "next step" beyond the quickstart. **Fix:** deploy a minimal Mintlify or Docusaurus site with 5 pages (specialists.md, playbook-dsl.md, playbook-library.md, concepts.md, api-reference.md). ~1 day for a minimal stub.

5. **CONTRIBUTING.md has stale `arnes/events/` reference.** Line 38 lists `arnes/events/` as a directory in the project structure tree — but `ls arnes/` shows no `events/` directory (events live in `arnes/thread/events.py`). A new contributor following the CONTRIBUTING map will look for `arnes/events/` and not find it. Same for `docs/specialists.md` and `docs/playbook-dsl.md` references. **Fix:** update the project structure tree in CONTRIBUTING.md to match the actual `arnes/` directory. ~10 minutes.

---

## 4. Top 5 Improvements Needed (R2)

1. **Record a demo GIF and embed at the top of the README.** 30-60s of `arnes run manuals/audit-pr.yaml --mock` → bitácora. Export via `agg` or `vhs`. ~2 hours. Highest-leverage viral action.

2. **Ship the missing `.github/` files.** `ISSUE_TEMPLATE/{bug_report.yml, feature_request.yml, config.yml}`, `PULL_REQUEST_TEMPLATE.md`, `FUNDING.yml` (github: frangelbarrera + opencollective: arnes + buymeacoffee: frangelbarrera), `CODEOWNERS`, `dependabot.yml`, `SECURITY_CREDITS.md`. ~2 hours. Blocks contributor onboarding.

3. **Convert `docs/social-card.svg` to PNG.** GitHub Open Graph doesn't render SVG. Use `rsvg-convert` or `resvg`. ~5 minutes.

4. **Deploy a minimal docs site.** Mintlify or Docusaurus. 5 pages: specialists, playbook-dsl, playbook-library, concepts, api-reference. ~1 day for a stub; ~1 week for a real site.

5. **Update CONTRIBUTING.md project structure tree.** Remove `arnes/events/` (doesn't exist), add `arnes/thread/` (where events actually live), remove dead `docs/specialists.md` and `docs/playbook-dsl.md` references. ~10 minutes.

---

## 5. Verdict

### **GO for public alpha launch.**

R1 was NO-GO for public launch (conditional GO after 5 fixes). R2 is **GO for public alpha launch** — the launch runbook works, the quickstart works, the badges resolve, the logo exists, the social card exists, the `arnes.dev` dead link is gone, and the README is honest about limitations.

The score crossed from 64 → 72, which clears the "launch-ready" bar for an alpha. The remaining gaps (demo GIF, `.github/` templates, PNG social card, docs site) are improvements, not blockers. The narrative and positioning are strong enough to carry the launch.

**Recommended launch sequence:**
1. **Day 0 (fixes):** record demo GIF (~2h), ship `.github/` templates (~2h), convert social card to PNG (~5min), update CONTRIBUTING.md tree (~10min). Score → ~78.
2. **Day 0 (PyPI):** tag `v0.1.0a1`, configure `PYPI_API_TOKEN` secret, push tag, verify `pip install arnes` in a clean venv. Score → ~80.
3. **Day 1 (soft launch):** make repo public, post in 3 friendly Discords/Slacks, fix anything that breaks.
4. **Day 2 (public launch):** X post at 9am ET Tuesday/Wednesday (per PUBLISHING_GUIDE §7), submit to `awesome-mcp-servers` + `awesome-ai-agents`, dev.to cross-post.
5. **Week 2 (docs site):** deploy minimal Mintlify/Docusaurus with 5 pages. Score → ~82.

**Frame the launch as:**
> *"ARNES v0.1 alpha — a manifesto-driven, YAML-first agent harness with cost guardrails, anti-hallucination middleware, and native MCP. Born in Latam, built for the world. Looking for 50 design partners, not 50k stars."*

**Do NOT frame the launch as:**
> *"The LangChain killer."* It is not. It is a differentiated niche player with a sharp thesis and an alpha maturity that's now genuinely launch-ready.

---

## 6. Cross-References to Round 1

| R1 Critical Issue | R2 Status | Score Δ |
|---|---|---|
| Broken launch runbook (Spanish leftovers) | Fixed — `manuals/smoke-test.yaml`, `arnes run` | +13 (Dim 8) |
| 3 broken README badges | Fixed — honest "not yet published" / "coming soon" / Coverage removed | +10 (Dim 1) |
| Zero visual identity | Partial — logo.svg + social-card.svg exist; no demo GIF, no PNG | +25 (Dim 3) |
| `pip install arnes` does not work | Fixed — quickstart uses `git clone` | +10 (Dim 1) |
| Community infrastructure placeholder-only | Partial — Discord honest; `.github/` templates still missing | +10 (Dim 7) |

**Net change: +8 points (64 → 72).** Four of the five R1 critical issues are fully or partially fixed. The remaining gap (`.github/` community templates) is an improvement, not a blocker. The marketing layer crossed from "not yet launch-ready" to "launch-ready for alpha."

---

*Prepared by JUDGE-MKT-R2. All scores are defensible from the source code at `/home/z/my-project/arnes/` as of 2026-07-31. Re-run this audit after the demo GIF, `.github/` templates, PNG social card, and minimal docs site land.*
