#!/usr/bin/env bash
# ============================================================
# ARNES — Setup and Push Script
# ============================================================
# This script lets you:
#   1. Verify the code is ready to publish
#   2. Initialize the local git repo
#   3. Make the first commit
#   4. Push to your private GitHub repo
#
# USAGE:
#   cd /home/z/my-project/arnes
#   bash scripts/setup-and-push.sh
#
# IMPORTANT: Do NOT use the PAT you shared in chat.
# Generate a NEW PAT at https://github.com/settings/tokens
# with scope "repo" (fine-grained to the ARNES repo preferably).
# ============================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  ARNES — Setup & Push Script                               ║${NC}"
echo -e "${CYAN}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ============================================================
# Step 0: Pre-flight checks
# ============================================================
echo -e "${YELLOW}[0/6] Pre-flight checks...${NC}"

# Check we're in the right directory
if [[ ! -f "pyproject.toml" ]] || [[ ! -d "arnes" ]]; then
    echo -e "${RED}✗ You are not in the ARNES root directory.${NC}"
    echo "  Run: cd /home/z/my-project/arnes"
    exit 1
fi

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python 3 not found. Install Python 3.11+.${NC}"
    exit 1
fi

# Check uv
if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}⚠ uv not found. Installing...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source $HOME/.local/bin/env
fi

# Check git
if ! command -v git &> /dev/null; then
    echo -e "${RED}✗ git not found. Install it first.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Pre-flight checks OK${NC}"
echo ""

# ============================================================
# Step 1: Install dependencies
# ============================================================
echo -e "${YELLOW}[1/6] Installing dependencies with uv...${NC}"

# Create venv if not exists
if [[ ! -d ".venv" ]]; then
    uv venv --python 3.12
fi

# Install
uv pip install -e ".[dev]" --python .venv/bin/python

echo -e "${GREEN}✓ Dependencies installed${NC}"
echo ""

# ============================================================
# Step 2: Run tests
# ============================================================
echo -e "${YELLOW}[2/6] Running tests...${NC}"

source .venv/bin/activate
python -m pytest tests/ --tb=short

if [[ $? -ne 0 ]]; then
    echo -e "${RED}✗ Tests failed. Fix before push.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ All tests pass${NC}"
echo ""

# ============================================================
# Step 3: Run linters
# ============================================================
echo -e "${YELLOW}[3/6] Running linters...${NC}"

echo "  → ruff check..."
ruff check arnes/ tests/ || {
    echo -e "${YELLOW}⚠ ruff check had warnings. Auto-fixing...${NC}"
    ruff check --fix arnes/ tests/
}

echo "  → ruff format check..."
ruff format --check arnes/ tests/ || {
    echo -e "${YELLOW}⚠ ruff format diff. Formatting...${NC}"
    ruff format arnes/ tests/
}

echo -e "${GREEN}✓ Lint OK${NC}"
echo ""

# ============================================================
# Step 4: Quickstart smoke test
# ============================================================
echo -e "${YELLOW}[4/6] Quickstart smoke test...${NC}"

# Create temp dir for test
SMOKE_DIR=$(mktemp -d)
cd "$SMOKE_DIR"

# Init project
arnes init --manual smoke-test

# Lint the generated playbook
arnes lint manuals/smoke-test.yaml

# Execute with mock
arnes run manuals/smoke-test.yaml --mock

# Verify bitácora was created
if ! ls bitacora-smoke-test-*.md 1> /dev/null 2>&1; then
    echo -e "${RED}✗ Smoke test failed: no bitácora generated${NC}"
    cd -
    rm -rf "$SMOKE_DIR"
    exit 1
fi

echo -e "${GREEN}✓ Smoke test OK${NC}"
cd -
rm -rf "$SMOKE_DIR"
echo ""

# ============================================================
# Step 5: Git init + first commit
# ============================================================
echo -e "${YELLOW}[5/6] Git setup...${NC}"

# Init git if not already
if [[ ! -d ".git" ]]; then
    git init
    git branch -M main
fi

# Check git user
GIT_USER=$(git config user.name || echo "")
GIT_EMAIL=$(git config user.email || echo "")

if [[ -z "$GIT_USER" ]] || [[ -z "$GIT_EMAIL" ]]; then
    echo -e "${YELLOW}⚠ Git user.name or user.email not configured.${NC}"
    echo "  Configure them with:"
    echo "    git config --global user.name 'Frangel Barrera'"
    echo "    git config --global user.email 'your@email.com'"
    echo ""
    read -p "  Configure now with frangelbarrera? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        git config user.name "Frangel Barrera"
        git config user.email "frangelbarrera@users.noreply.github.com"
    else
        echo -e "${RED}✗ Configure git user before continuing.${NC}"
        exit 1
    fi
fi

# Add all files
git add -A

# Show what will be committed
echo ""
echo -e "${CYAN}Files to commit:${NC}"
git status --short
echo ""

read -p "Make the first commit? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Skip commit.${NC}"
    exit 0
fi

# First commit
git commit -m "feat: initial ARNES v0.1.0a1 — The Open Agent Harness

- Core: Thread (immutable event log) + stateless reducer
- Events: 14 typed events for full agent lifecycle
- Tools: 5 built-in (shell, http, fs_read, fs_write, human_approval)
  with SSRF protection, path traversal protection, dangerous command blocking
- Specialists: 5 pre-built (@planner, @coder, @reviewer, @tester, @debugger)
  with ReAct tool-use loop and pydantic schema validation
- Playbook DSL: YAML declarative compiled to DAG with
  conditional branches, parallel branches, HITL gates
- LLM Providers: vendor-neutral via LiteLLM, default Ollama (local, \$0)
- Middleware: Token Optimizer + Verification Layer + Cost Guard
  with budget enforcement and circuit breaker
- MCP Server: stdio transport, 4 tools for Claude Desktop/Cursor/Cline/Zed
- CLI: init, run, lint, eval, list, mcp serve
- Tests: 74 passing, 66% coverage
- Docs: MANIFESTO, README (bilingual EN/ES), CONTRIBUTING, SECURITY,
  CODE_OF_CONDUCT, AGENTS.md, CLAUDE.md
- CI/CD: GitHub Actions matrix (Python 3.11/3.12/3.13 × Ubuntu/macOS/Windows)

ARNES — Control the agent. Don't worship it."

echo -e "${GREEN}✓ Commit created${NC}"
echo ""

# ============================================================
# Step 6: Push to GitHub
# ============================================================
echo -e "${YELLOW}[6/6] Push to GitHub...${NC}"

REPO_URL="https://github.com/frangelbarrera/ARNES"

# Check if remote exists
if ! git remote get-url origin &> /dev/null; then
    echo -e "${YELLOW}⚠ No 'origin' remote configured.${NC}"
    echo ""
    echo "  Option A (HTTPS with PAT):"
    echo "    git remote add origin https://github.com/frangelbarrera/ARNES.git"
    echo "    git push -u origin main"
    echo "    # It will ask for user/password. Use your PAT as password."
    echo ""
    echo "  Option B (SSH, if you have SSH key configured):"
    echo "    git remote add origin git@github.com:frangelbarrera/ARNES.git"
    echo "    git push -u origin main"
    echo ""
    echo -e "${RED}  IMPORTANT: Do NOT use the PAT you shared in chat.${NC}"
    echo -e "${RED}  Generate a new one at https://github.com/settings/tokens${NC}"
    echo -e "${RED}  with scope 'repo' (fine-grained to the ARNES repo).${NC}"
    echo ""
    read -p "  Add remote origin now? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        read -p "  Use SSH? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            git remote add origin git@github.com:frangelbarrera/ARNES.git
        else
            git remote add origin https://github.com/frangelbarrera/ARNES.git
        fi
        echo -e "${GREEN}✓ Remote origin added${NC}"
    else
        echo -e "${YELLOW}Skip. Add the remote manually and run:${NC}"
        echo "  git push -u origin main"
        exit 0
    fi
fi

# Push
echo ""
read -p "Run git push -u origin main? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    git push -u origin main
    if [[ $? -eq 0 ]]; then
        echo ""
        echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║  ✅ ARNES pushed successfully to GitHub!                   ║${NC}"
        echo -e "${GREEN}║                                                             ║${NC}"
        echo -e "${GREEN}║  Repo: https://github.com/frangelbarrera/ARNES             ║${NC}"
        echo -e "${GREEN}║                                                             ║${NC}"
        echo -e "${GREEN}║  Next steps:                                               ║${NC}"
        echo -e "${GREEN}║  1. Verify the repo looks good in GitHub                  ║${NC}"
        echo -e "${GREEN}║  2. Configure GitHub Actions (already in .github/)       ║${NC}"
        echo -e "${GREEN}║  3. Add topics in GitHub repo settings (see README.md)   ║${NC}"
        echo -e "${GREEN}║  4. Update repo description in GitHub settings           ║${NC}"
        echo -e "${GREEN}║  5. When ready, change the repo from private to public   ║${NC}"
        echo -e "${GREEN}║  6. Share on X with the hashtag #AgentHarness            ║${NC}"
        echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
    else
        echo -e "${RED}✗ Push failed. Check the error above.${NC}"
        exit 1
    fi
else
    echo -e "${YELLOW}Skip push. Do it manually with:${NC}"
    echo "  git push -u origin main"
fi

echo ""
echo -e "${CYAN}Done. 🚀${NC}"
