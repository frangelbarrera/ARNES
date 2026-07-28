#!/usr/bin/env bash
# ============================================================
# ARNES — Setup and Push Script
# ============================================================
# Este script te permite:
#   1. Verificar que el código está listo para publicar
#   2. Inicializar el repo git local
#   3. Hacer el primer commit
#   4. Push a tu repo GitHub privado
#
# USO:
#   cd /home/z/my-project/arnes
#   bash scripts/setup-and-push.sh
#
# IMPORTANT: NO uses el PAT que compartiste en el chat.
# Genera un NEW PAT en https://github.com/settings/tokens
# con scope "repo" (fine-grained al repo ARNES preferiblemente).
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
    echo -e "${RED}✗ No estás en el directorio raíz de ARNES.${NC}"
    echo "  Ejecuta: cd /home/z/my-project/arnes"
    exit 1
fi

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python 3 no encontrado. Instala Python 3.11+.${NC}"
    exit 1
fi

# Check uv
if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}⚠ uv no encontrado. Instalando...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source $HOME/.local/bin/env
fi

# Check git
if ! command -v git &> /dev/null; then
    echo -e "${RED}✗ git no encontrado. Instálalo primero.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Pre-flight checks OK${NC}"
echo ""

# ============================================================
# Step 1: Install dependencies
# ============================================================
echo -e "${YELLOW}[1/6] Instalando dependencias con uv...${NC}"

# Create venv if not exists
if [[ ! -d ".venv" ]]; then
    uv venv --python 3.12
fi

# Install
uv pip install -e ".[dev]" --python .venv/bin/python

echo -e "${GREEN}✓ Dependencias instaladas${NC}"
echo ""

# ============================================================
# Step 2: Run tests
# ============================================================
echo -e "${YELLOW}[2/6] Ejecutando tests...${NC}"

source .venv/bin/activate
python -m pytest tests/ --tb=short

if [[ $? -ne 0 ]]; then
    echo -e "${RED}✗ Tests fallaron. Fix antes de push.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Todos los tests pasan${NC}"
echo ""

# ============================================================
# Step 3: Run linters
# ============================================================
echo -e "${YELLOW}[3/6] Ejecutando linters...${NC}"

echo "  → ruff check..."
ruff check arnes/ tests/ || {
    echo -e "${YELLOW}⚠ ruff check tuvo warnings. Auto-fixing...${NC}"
    ruff check --fix arnes/ tests/
}

echo "  → ruff format check..."
ruff format --check arnes/ tests/ || {
    echo -e "${YELLOW}⚠ ruff format diff. Formateando...${NC}"
    ruff format arnes/ tests/
}

echo -e "${GREEN}✓ Lint OK${NC}"
echo ""

# ============================================================
# Step 4: Quickstart smoke test
# ============================================================
echo -e "${YELLOW}[4/6] Smoke test del quickstart...${NC}"

# Create temp dir for test
SMOKE_DIR=$(mktemp -d)
cd "$SMOKE_DIR"

# Init project
arnes init --manual smoke-test

# Lint the generated playbook
arnes lint manuales/smoke-test.md.yaml

# Execute with mock
arnes ejecutar manuales/smoke-test.md.yaml --mock

# Verify bitácora was created
if ! ls bitacora-smoke-test-*.md 1> /dev/null 2>&1; then
    echo -e "${RED}✗ Smoke test falló: no se generó bitácora${NC}"
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
    echo -e "${YELLOW}⚠ Git user.name o user.email no configurados.${NC}"
    echo "  Configúralos con:"
    echo "    git config --global user.name 'Frangel Barrera'"
    echo "    git config --global user.email 'tu@email.com'"
    echo ""
    read -p "  ¿Configurar ahora con frangelbarrera? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        git config user.name "Frangel Barrera"
        git config user.email "frangelbarrera@users.noreply.github.com"
    else
        echo -e "${RED}✗ Configura git user antes de continuar.${NC}"
        exit 1
    fi
fi

# Add all files
git add -A

# Show what will be committed
echo ""
echo -e "${CYAN}Archivos a commitear:${NC}"
git status --short
echo ""

read -p "¿Hacer el primer commit? (y/N) " -n 1 -r
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
- CLI: init, ejecutar, lint, eval, list, mcp serve
- Tests: 74 passing, 66% coverage
- Docs: MANIFESTO, README (bilingual EN/ES), CONTRIBUTING, SECURITY,
  CODE_OF_CONDUCT, AGENTS.md, CLAUDE.md
- CI/CD: GitHub Actions matrix (Python 3.11/3.12/3.13 × Ubuntu/macOS/Windows)

ARNES — Control the agent. Don't worship it."

echo -e "${GREEN}✓ Commit creado${NC}"
echo ""

# ============================================================
# Step 6: Push to GitHub
# ============================================================
echo -e "${YELLOW}[6/6] Push a GitHub...${NC}"

REPO_URL="https://github.com/frangelbarrera/ARNES"

# Check if remote exists
if ! git remote get-url origin &> /dev/null; then
    echo -e "${YELLOW}⚠ No hay remote 'origin' configurado.${NC}"
    echo ""
    echo "  Opción A (HTTPS con PAT):"
    echo "    git remote add origin https://github.com/frangelbarrera/ARNES.git"
    echo "    git push -u origin main"
    echo "    # Te pedirá usuario/password. Usa tu PAT como password."
    echo ""
    echo "  Opción B (SSH, si tienes SSH key configurada):"
    echo "    git remote add origin git@github.com:frangelbarrera/ARNES.git"
    echo "    git push -u origin main"
    echo ""
    echo -e "${RED}  IMPORTANTE: NO uses el PAT que compartiste en el chat.${NC}"
    echo -e "${RED}  Genera uno nuevo en https://github.com/settings/tokens${NC}"
    echo -e "${RED}  con scope 'repo' (fine-grained al repo ARNES).${NC}"
    echo ""
    read -p "  ¿Agregar remote origin ahora? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        read -p "  ¿Usar SSH? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            git remote add origin git@github.com:frangelbarrera/ARNES.git
        else
            git remote add origin https://github.com/frangelbarrera/ARNES.git
        fi
        echo -e "${GREEN}✓ Remote origin agregado${NC}"
    else
        echo -e "${YELLOW}Skip. Agrega el remote manualmente y ejecuta:${NC}"
        echo "  git push -u origin main"
        exit 0
    fi
fi

# Push
echo ""
read -p "¿Hacer git push -u origin main? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    git push -u origin main
    if [[ $? -eq 0 ]]; then
        echo ""
        echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║  ✅ ARNES pushed exitosamente a GitHub!                    ║${NC}"
        echo -e "${GREEN}║                                                             ║${NC}"
        echo -e "${GREEN}║  Repo: https://github.com/frangelbarrera/ARNES             ║${NC}"
        echo -e "${GREEN}║                                                             ║${NC}"
        echo -e "${GREEN}║  Próximos pasos:                                            ║${NC}"
        echo -e "${GREEN}║  1. Verifica que el repo se ve bien en GitHub              ║${NC}"
        echo -e "${GREEN}║  2. Configura GitHub Actions (ya están en .github/)       ║${NC}"
        echo -e "${GREEN}║  3. Add topics en GitHub repo settings (ver README.md)    ║${NC}"
        echo -e "${GREEN}║  4. Update repo description en GitHub settings            ║${NC}"
        echo -e "${GREEN}║  5. Cuando listo, cambia el repo de private a public      ║${NC}"
        echo -e "${GREEN}║  6. Comparte en X con el hashtag #AgentHarness            ║${NC}"
        echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
    else
        echo -e "${RED}✗ Push falló. Revisa el error arriba.${NC}"
        exit 1
    fi
else
    echo -e "${YELLOW}Skip push. Hazlo manualmente con:${NC}"
    echo "  git push -u origin main"
fi

echo ""
echo -e "${CYAN}Done. 🚀${NC}"
