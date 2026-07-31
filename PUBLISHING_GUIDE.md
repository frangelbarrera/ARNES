# Publishing Guide — ARNES v0.1.0a1

This guide walks you step by step from the code ready in `/home/z/my-project/arnes/`
to a public GitHub repo ready to share.

## ⚠️ Before you start

**REVOKE THE EXPOSED PAT.** Go to https://github.com/settings/tokens and delete
any token starting with `github_pat_11BQAR7JY0...`. Generate a NEW one with
minimum scope (`repo` fine-grained to the ARNES repo).

## Step 1 — Verify the code locally

```bash
cd /home/z/my-project/arnes

# Activate the venv
source .venv/bin/activate

# Run tests
python -m pytest tests/ --no-cov -q
# Expected: all tests pass

# Run linters
ruff check arnes/ tests/
ruff format --check arnes/ tests/

# Quickstart smoke test
cd /tmp && rm -rf arnes-smoke && mkdir arnes-smoke && cd arnes-smoke
arnes init --manual smoke-test
arnes lint manuals/smoke-test.yaml
arnes run manuals/smoke-test.yaml --mock
# Expected: ✅ Manual executed, 3 steps, run log generated
```

If everything passes, continue. If anything fails, do NOT publish yet.

## Step 2 — Push to the private GitHub repo

```bash
cd /home/z/my-project/arnes

# Easy option: use the automated script
bash scripts/setup-and-push.sh
```

The script:
1. Verifies dependencies
2. Runs tests
3. Runs linters
4. Runs the quickstart smoke test
5. Initializes git + first commit
6. Adds remote origin
7. Runs `git push -u origin main`

It will ask for confirmation at each step.

### Manual option (if you prefer to control each command)

```bash
cd /home/z/my-project/arnes

# Git init
git init
git branch -M main
git config user.name "Frangel Barrera"
git config user.email "frangelbarrera@users.noreply.github.com"

# Add all files
git add -A

# First commit
git commit -m "feat: initial ARNES v0.1.0a1 — The Open Agent Harness

- Core: Thread + stateless reducer
- Specialists: 5 pre-built with ReAct tool-use loop
- Playbook DSL: YAML declarative compiled to DAG
- Middleware: Token Optimizer + Verification + Cost Guard
- MCP Server: stdio transport for Claude Desktop/Cursor/Cline/Zed
- Tests: 74 passing, 66% coverage

ARNES — Control the agent. Don't worship it."

# Add remote (HTTPS with new PAT)
git remote add origin https://github.com/frangelbarrera/ARNES.git

# Push (it will ask for credentials — use your NEW PAT as password)
git push -u origin main
```

## Step 3 — Configure the repo on GitHub

After the push, go to https://github.com/frangelbarrera/ARNES/settings and:

### 3.1 SEO Topics (on the repo main page)

Copy and paste these 20 topics in the "Topics" field:

```
ai-agents agent-framework agent-harness llm-agents llm python mcp
model-context-protocol multi-agent react-agent a2a human-in-the-loop
stateless-reducer arnes agent-runtime agentic-ai self-hosted
token-optimization anti-hallucination
```

(In October, also add `hacktoberfest`)

### 3.2 Repo Description

Paste this in the "Description" field:

```
ARNES — The Open Agent Harness. A Python runtime for production AI agents: stateless reducer, first-class HITL, bidirectional MCP, native A2A. Apache-2.0. Bilingual EN/ES.
```

### 3.3 Repo settings

- **Default branch**: `main`
- **Allow issues**: ✓
- **Allow discussions**: ✓ (critical for community)
- **Allow sponsorships**: ✓
- **Projects**: ✓
- **Wiki**: ✗ (keep docs in `/docs`)

### 3.4 GitHub Actions

The workflows are already in `.github/workflows/`. In GitHub Settings → Actions:
- **Allow all actions**: ✓
- **Workflow permissions**: Read and write
- **Status checks**: require `CI` for pull requests to `main`

### 3.5 Branch protection (when you have first contributors)

Settings → Branches → Add rule for `main`:
- Require pull request before merging
- Require status checks to pass: `CI`, `security`
- Require branches to be up to date
- Do NOT require linear history (allow merge commits)

## Step 4 — Verify the CI

Go to https://github.com/frangelbarrera/ARNES/actions

You should see the `CI` workflow running. Wait for it to pass on the 9 jobs
(3 OS × 3 Python versions). If anything fails, check the logs.

## Step 5 — Test with a real LLM (optional but recommended)

Before making the repo public, test with a real LLM to make sure the
specialists return useful outputs:

### 5.1 With Ollama (free, local)

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Download a model
ollama pull llama3.2

# Verify it runs
ollama run llama3.2 "Hello"

# Run a playbook with ARNES
cd /home/z/my-project/arnes
arnes run manuals/hello-world.yaml
# (without --mock, it uses ollama/llama3.2 by default)
```

### 5.2 With Anthropic (paid, better quality)

```bash
export ANTHROPIC_API_KEY=sk-ant-...  # your NEW key

arnes run manuals/debug-python-issue.yaml \
    --model anthropic/claude-sonnet-4-20250514 \
    --budget 0.50
```

Verify that:
- Specialists return valid JSON conforming to their schemas
- The markdown run log is generated correctly
- The cost guard reports the correct spend
- Events accumulate in the thread

## Step 6 — Change the repo from private to public

When ALL of this passes:

1. Go to https://github.com/frangelbarrera/ARNES/settings
2. Scroll to the bottom → "Danger Zone"
3. "Change repository visibility" → **Public**
4. Confirm with your password

## Step 7 — Announce on X (your main channel)

With your 1100 X followers, this is the critical moment. Suggested template:

```
🚀 After months of work, today I'm launching ARNES — The Open Agent Harness.

A Python runtime for AI agents that respects your prompts, your context, your model, and your money. It's not another framework. It's a harness.

✅ YAML manual → DAG of specialists
✅ 5 pre-built specialists (@planner, @coder, @reviewer, @tester, @debugger)
✅ Native MCP server (Claude Desktop, Cursor, Cline, Zed)
✅ Budget enforcement with circuit breaker
✅ Anti-hallucination layer with structured outputs
✅ Default: local Ollama ($0 cost)
✅ Vendor-neutral: Apache 2.0

github.com/frangelbarrera/ARNES

#AgentHarness #AI #OpenSource #Python
```

### Suggested hashtags
- #AgentHarness (canonized by Microsoft/LangChain)
- #AI #OpenSource #Python
- #MCP #ModelContextProtocol
- #LocalAI #Ollama

### Optimal timing
- Tuesday or Wednesday (not Monday or Friday)
- 9am ET / 10am BRT / 2pm UK
- NOT during US holidays

## Step 8 — Post-launch (24-48h)

1. **Respond to all issues/PRs in <4h**. Critical for momentum.
2. **If someone tweets about ARNES**, like + RT + comment.
3. **If a critical bug appears**, fix + release v0.1.1 in <24h.
4. **Track metrics**: stars, forks, clones (GitHub Insights), PyPI downloads.

## Step 9 — Next milestones

- **100 stars**: submit PR to `awesome-mcp-servers` and `awesome-ai-agents`
- **500 stars**: publish on dev.to a tutorial "How to build a multi-agent system with ARNES"
- **1000 stars**: apply to the Anthropic Open Source Program for credits
- **5000 stars**: consider raising pre-seed

## Final repo structure

```
ARNES/
├── arnes/                  # Source code (Python package)
│   ├── agent/              # Harness class
│   ├── thread/             # Thread + Events (stateless reducer)
│   ├── tools/              # 5 built-in tools
│   ├── llm/                # Provider abstraction (Ollama, LiteLLM, Mock)
│   ├── middleware/         # TokenOptimizer, Verification, CostGuard
│   ├── specialists/        # 5 pre-built specialists
│   ├── playbooks/          # DSL + compiler + executor
│   ├── mcp/                # MCP server
│   └── cli/                # arnes CLI
├── tests/                  # 74 tests (66% coverage)
├── manuals/                # 10 example playbooks
├── docs/                   # Logo, social card (placeholder)
├── .github/workflows/      # CI/CD
├── MANIFESTO.md            # 10 immutable declarations
├── README.md               # Bilingual EN/ES
├── CONTRIBUTING.md
├── SECURITY.md
├── CODE_OF_CONDUCT.md
├── AGENTS.md               # System prompt for AI contributors
├── CLAUDE.md               # Claude-specific guidance
├── CHANGELOG.md
├── LICENSE                 # Apache 2.0
├── pyproject.toml
└── scripts/
    └── setup-and-push.sh   # This script
```

## Troubleshooting

### "Tests fail in CI but pass locally"
- Verify the Python version (CI uses 3.11/3.12/3.13)
- Verify the OS (CI uses Ubuntu/macOS/Windows)
- Check for undeclared dependencies

### "Push rejected by authentication"
- Do NOT use the PAT exposed in chat
- Generate a new one at https://github.com/settings/tokens
- Use the PAT as password (username can be anything)

### "arnes: command not found"
- Activate the venv: `source .venv/bin/activate`
- Or install globally: `pip install -e .`

### "Ollama not found"
- Install: `curl -fsSL https://ollama.com/install.sh | sh`
- Pull a model: `ollama pull llama3.2`
- Verify: `ollama list`

### "Module not found: arnes"
- Reinstall in editable mode: `uv pip install -e .`
- Verify PYTHONPATH: `echo $PYTHONPATH`

## Support

If something doesn't work, open an issue at:
https://github.com/frangelbarrera/ARNES/issues

Or post in Discussions:
https://github.com/frangelbarrera/ARNES/discussions

---

**Remember:** ARNES competes against Microsoft. The quality of the code and the
clarity of the narrative are our only advantages. Don't waste them.

*Control the agent. Don't worship it.*
