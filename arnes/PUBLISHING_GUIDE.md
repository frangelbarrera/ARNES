# Guía de Publicación — ARNES v0.1.0a1

Esta guía te lleva paso a paso desde el código listo en `/home/z/my-project/arnes/`
hasta un repo público en GitHub listo para viralizar.

## ⚠️ Antes de empezar

**REVOCAR EL PAT EXPUESTO.** Ve a https://github.com/settings/tokens y elimina
cualquier token que empiece con `github_pat_11BQAR7JY0...`. Genera uno NUEVO
con scope mínimo (`repo` fine-grained al repo ARNES).

## Paso 1 — Verifica el código localmente

```bash
cd /home/z/my-project/arnes

# Activa el venv
source .venv/bin/activate

# Run tests
python -m pytest tests/ --no-cov -q
# Expected: 74 passed

# Run linters
ruff check arnes/ tests/
ruff format --check arnes/ tests/

# Smoke test del quickstart
cd /tmp && rm -rf arnes-smoke && mkdir arnes-smoke && cd arnes-smoke
arnes init --manual smoke-test
arnes lint manuales/smoke-test.md.yaml
arnes ejecutar manuales/smoke-test.md.yaml --mock
# Expected: ✅ Manual ejecutado, 3 steps, bitácora generada
```

Si todo pasa, continúa. Si algo falla, NO publiques aún.

## Paso 2 — Push al repo GitHub privado

```bash
cd /home/z/my-project/arnes

# Opción fácil: usa el script automático
bash scripts/setup-and-push.sh
```

El script:
1. Verifica dependencias
2. Corre tests
3. Corre linters
4. Hace smoke test del quickstart
5. Inicializa git + primer commit
6. Agrega remote origin
7. Hace `git push -u origin main`

Te pedirá confirmación en cada paso.

### Opción manual (si prefieres controlar cada comando)

```bash
cd /home/z/my-project/arnes

# Git init
git init
git branch -M main
git config user.name "Frangel Barrera"
git config user.email "frangelbarrera@users.noreply.github.com"

# Add todos los archivos
git add -A

# Primer commit
git commit -m "feat: initial ARNES v0.1.0a1 — The Open Agent Harness

- Core: Thread + stateless reducer
- Specialists: 5 pre-built with ReAct tool-use loop
- Playbook DSL: YAML declarative compiled to DAG
- Middleware: Token Optimizer + Verification + Cost Guard
- MCP Server: stdio transport for Claude Desktop/Cursor/Cline/Zed
- Tests: 74 passing, 66% coverage

ARNES — Control the agent. Don't worship it."

# Agrega remote (HTTPS con PAT nuevo)
git remote add origin https://github.com/frangelbarrera/ARNES.git

# Push (te pedirá credenciales — usa tu NUEVO PAT como password)
git push -u origin main
```

## Paso 3 — Configura el repo en GitHub

Después del push, ve a https://github.com/frangelbarrera/ARNES/settings y:

### 3.1 Topics SEO (en la página principal del repo)

Copia y pega estos 20 topics en el campo "Topics":

```
ai-agents agent-framework agent-harness llm-agents llm python mcp
model-context-protocol multi-agent react-agent a2a human-in-the-loop
stateless-reducer arnes agent-runtime agentic-ai self-hosted
token-optimization anti-hallucination
```

(En octubre, añade también `hacktoberfest`)

### 3.2 Repo Description

Pega esto en el campo "Description":

```
ARNES — The Open Agent Harness. A Python runtime for production AI agents: stateless reducer, first-class HITL, bidirectional MCP, native A2A. Apache-2.0. Bilingual EN/ES.
```

### 3.3 Repo settings

- **Default branch**: `main`
- **Allow issues**: ✓
- **Allow discussions**: ✓ (crítico para comunidad)
- **Allow sponsorships**: ✓
- **Projects**: ✓
- **Wiki**: ✗ (mantén docs en `/docs`)

### 3.4 GitHub Actions

Las workflows ya están en `.github/workflows/`. En GitHub Settings → Actions:
- **Allow all actions**: ✓
- **Workflow permissions**: Read and write
- **Status checks**: requiere `CI` para pull requests a `main`

### 3.5 Branch protection (cuando tengas primeros contributors)

Settings → Branches → Add rule for `main`:
- Require pull request before merging
- Require status checks to pass: `CI`, `security`
- Require branches to be up to date
- Do NOT require linear history (allow merge commits)

## Paso 4 — Verifica el CI

Ve a https://github.com/frangelbarrera/ARNES/actions

Deberías ver el workflow `CI` corriendo. Espera a que pase en los 9 jobs
(3 OS × 3 Python versions). Si falla algo, revisa los logs.

## Paso 5 — Test con un LLM real (opcional pero recomendado)

Antes de hacer público el repo, prueba con un LLM real para asegurarte
de que los specialists devuelven outputs útiles:

### 5.1 Con Ollama (gratis, local)

```bash
# Instala Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Descarga un modelo
ollama pull llama3.2

# Verifica que corre
ollama run llama3.2 "Hello"

# Ejecuta un playbook con ARNES
cd /home/z/my-project/arnes
arnes ejecutar manuales/hola-mundo.md.yaml
# (sin --mock, usará ollama/llama3.2 por defecto)
```

### 5.2 Con Anthropic (paid, mejor calidad)

```bash
export ANTHROPIC_API_KEY=sk-ant-...  # tu key NUEVA

arnes ejecutar manuales/debug-python-issue.md.yaml \
    --model anthropic/claude-sonnet-4-20250514 \
    --budget 0.50
```

Verifica que:
- Los specialists devuelven JSON válido conforme a sus schemas
- La bitácora markdown se genera correctamente
- El cost guard reporta el gasto correcto
- Los events se acumulan en el thread

## Paso 6 — Cambia el repo de privado a público

Cuando TODO esto pase:

1. Ve a https://github.com/frangelbarrera/ARNES/settings
2. Scroll al final → "Danger Zone"
3. "Change repository visibility" → **Public**
4. Confirma con tu password

## Paso 7 — Anuncia en X (tu canal principal)

Con tus 1100 followers de X, este es el momento crítico. Template sugerido:

```
🚀 Después de meses de trabajo, hoy lanzo ARNES — The Open Agent Harness.

Un runtime Python para agentes de IA que respeta tus prompts, tu contexto, tu modelo y tu dinero. No es un framework más. Es un arnés.

✅ Manual YAML → DAG de especialistas
✅ 5 specialists pre-construidos (@planner, @coder, @reviewer, @tester, @debugger)
✅ MCP server nativo (Claude Desktop, Cursor, Cline, Zed)
✅ Budget enforcement con circuit breaker
✅ Anti-hallucination layer con structured outputs
✅ Default: Ollama local ($0 costo)
✅ Vendor-neutral: Apache 2.0

From Latam to the world. 🌎

github.com/frangelbarrera/ARNES

#AgentHarness #AI #OpenSource #Python
```

### Hashtags sugeridos
- #AgentHarness (canonizado por Microsoft/LangChain)
- #AI #OpenSource #Python
- #MCP #ModelContextProtocol
- #LocalAI #Ollama
- #LatamTech

### Timing óptimo
- Martes o miércoles (no lunes ni viernes)
- 9am ET / 10am BRT / 2pm UK
- NO durante holidays US

## Paso 8 — Post-launch (24-48h)

1. **Responde a todos los issues/PRs en <4h**. Crítico para momentum.
2. **Si alguien tweetea sobre ARNES**, dale like + RT + comentario.
3. **Si aparece un bug crítico**, fix + release v0.1.1 en <24h.
4. **Track métricas**: stars, forks, clones (GitHub Insights), PyPI downloads.

## Paso 9 — Siguientes milestones

- **100 stars**: envía PR a `awesome-mcp-servers` y `awesome-ai-agents`
- **500 stars**: publica en dev.to un tutorial "How to build a multi-agent system with ARNES"
- **1000 stars**: aplica a Anthropic Open Source Program para credits
- **5000 stars**: considera levantar pre-seed

## Estructura final del repo

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
├── manuales/               # 4 example playbooks
├── docs/                   # Mintlify source (placeholder)
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
    └── setup-and-push.sh   # Este script
```

## Troubleshooting

### "Tests fallan en CI pero pasan localmente"
- Verifica versión de Python (CI usa 3.11/3.12/3.13)
- Verifica OS (CI usa Ubuntu/macOS/Windows)
- Revisa si hay dependencias no declaradas

### "Push rechazado por authentication"
- NO uses el PAT expuesto en el chat
- Genera uno nuevo en https://github.com/settings/tokens
- Usa el PAT como password (username puede ser cualquier cosa)

### "arnes: command not found"
- Activa el venv: `source .venv/bin/activate`
- O instala globalmente: `pip install -e .`

### "Ollama not found"
- Instala: `curl -fsSL https://ollama.com/install.sh | sh`
- Pull modelo: `ollama pull llama3.2`
- Verifica: `ollama list`

### "Module not found: arnes"
- Reinstala en editable mode: `uv pip install -e .`
- Verifica PYTHONPATH: `echo $PYTHONPATH`

## Soporte

Si algo no funciona, abre un issue en:
https://github.com/frangelbarrera/ARNES/issues

O escribe en Discussions:
https://github.com/frangelbarrera/ARNES/discussions

---

**Recuerda:** ARNES compite contra Microsoft. La calidad del código y la
claridad de la narrativa son nuestras únicas ventajas. No las desperdicies.

*Control the agent. Don't worship it.*
