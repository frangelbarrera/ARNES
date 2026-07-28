<div align="center">

# ARNES

### The Open Agent Harness

**Escribe el manual. ARNES lo compila en un equipo de especialistas que lo sigue al pie de la letra.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![CI](https://img.shields.io/github/actions/workflow/status/frangelbarrera/ARNES/ci.yml?branch=main&label=CI)](https://github.com/frangelbarrera/ARNES/actions)
[![Coverage](https://img.shields.io/endpoint?url=.coverage.json)](https://github.com/frangelbarrera/ARNES)
[![PyPI](https://img.shields.io/pypi/v/arnes.svg)](https://pypi.org/project/arnes/)
[![Discord](https://img.shields.io/discord/ARNES.svg?label=Discord)](https://discord.gg/ARNES)
[![GitHub stars](https://img.shields.io/github/stars/frangelbarrera/ARNES?style=social)](https://github.com/frangelbarrera/ARNES)

[Manifesto](MANIFESTO.md) · [Documentation](https://arnes.dev) · [Examples](examples/) · [Contributing](CONTRIBUTING.md)

</div>

---

> **Si tu framework necesita un debugger para tu debugger, es el framework equivocado.**

ARNES no es un framework. Es un **arnés**: la capa de control que te deja orquestar
agentes de IA sin ceder el control de tus prompts, tu contexto, tu modelo, tu dinero.

No te pedimos que aprendas clases mágicas. Te pedimos que escribas un manual en
YAML. Nosotros lo compilamos a un DAG de especialistas, lo ejecutamos con
guardrails de costo y anti-alucinación, y te devolvemos una bitácora auditable.

```bash
pip install arnes
arnes ejecutar manuales/debug-python-issue.md
```

---

## Por qué ARNES existe

Los frameworks de agentes de 2024-2026 comparten tres defectos:

1. **Son cajas negras.** No puedes leer el prompt que se envió al LLM. No puedes
   ver qué decisión tomó el router de modelos. No puedes diffear tu agent stack.
2. **Tienen vendor lock-in.** Si solo existe en OpenAI o solo en Anthropic,
   lo exponen como API de primera clase. Tu código queda amarrado.
3. **No respetan tu dinero.** Sin budget enforcement real, un agente puede
   quemar $50 en 90 segundos sin que tú lo sepas hasta que llega la factura.

ARNES ataca los tres. Y agrega algo que nadie hace: **el manual es el código**.

---

## Cómo se ve

Un manual en YAML:

```yaml
# manuales/auditar-pr.md.yaml
nombre: auditar-pr
objetivo: Auditar un Pull Request de forma estructurada
budget_usd: 0.50

pasos:
  - id: leer_diff
    especialista: @lector-de-diff
    input: { pr_number: 1234, repo: "mi-org/mi-repo" }

  - id: auditoria_seguridad
    especialista: @auditor-de-seguridad
    input: "{{ pasos.leer_diff.salida }}"
    requiere:
      - commit_firmado
      - sin_secrets_en_diff
    si_no_se_cumple:
      llamar: @comentarista-de-fallback
      terminar: rechazado

  - id: redactar_comentario
    especialista: @redactor-de-comentario
    input:
      diff: "{{ pasos.leer_diff.salida }}"
      auditoria: "{{ pasos.auditoria_seguridad.salida }}"

  - id: postear
    herramienta: github.crear_comentario_review
    input: "{{ pasos.redactar_comentario.salida }}"
```

Lo ejecutas:

```bash
arnes ejecutar manuales/auditar-pr.md.yaml
```

ARNES compila el manual a un DAG, despierta a los especialistas en secuencia,
aplica token optimization y verification layer en cada llamada, y te devuelve:

```
✅ Manual ejecutado en 23.4s
   3 especialistas activados
   4 pasos ejecutados (1 condicional activado)
   Tokens: 1,247 (ahorro 47% vs baseline)
   Costo: $0.0042 USD
   Bitácora: ./bitacora-auditar-pr-20260728-164523.md
```

La bitácora es un archivo markdown con cada paso, cada decisión, cada prompt
enviado, cada respuesta recibida. Lo puedes diffear, versionar, compartir.

---

## Características

| Categoría | Feature | Estado |
|---|---|---|
| **Agent loop** | Stateless reducer `(state, event) → state` | ✅ v0.1 |
| | ReAct + Plan-and-Execute híbrido | ✅ v0.1 |
| | Streaming AG-UI compatible | 🚧 v0.2 |
| **Specialists** | 5 pre-construidos (planner, coder, reviewer, tester, debugger) | ✅ v0.1 |
| | 5 más (security, devops, researcher, writer, optimizer) | 🚧 v0.3 |
| **Playbook DSL** | YAML declarativo compilado a DAG | ✅ v0.1 |
| | Conditional edges (if/elif/else) | ✅ v0.1 |
| | Parallel branches | ✅ v0.1 |
| | Retry con backoff | ✅ v0.1 |
| | HITL gates (pausar y pedir aprobación) | ✅ v0.1 |
| **MCP** | ARNES como MCP server (Claude Desktop, Cursor, Cline, Zed) | ✅ v0.1 |
| | ARNES como MCP cliente (consume MCP servers externos) | 🚧 v0.2 |
| **Token Optimization** | Model routing automático por complejidad | ✅ v0.1 |
| | Semantic cache | ✅ v0.1 |
| | Context compaction | 🚧 v0.2 |
| | Few-shot pruning | 🚧 v0.3 |
| **Verification Layer** | Structured outputs con pydantic | ✅ v0.1 |
| | Refusal pattern (no alucina, dice "no sé") | ✅ v0.1 |
| | Confidence gate | 🚧 v0.2 |
| | Critic loop (segunda opinión) | 🚧 v0.3 |
| | Grounding RAG opcional | 🚧 v0.4 |
| **Cost Guard** | Budget jerárquico (org → project → agent → task) | ✅ v0.1 |
| | Circuit breaker temporal (max USD/min) | ✅ v0.1 |
| | Model fallback automático | ✅ v0.1 |
| | HITL de costo (pausar al exceder X%) | ✅ v0.1 |
| **Sandbox** | Docker hardened (Tier 1 dev-local) | 🚧 v0.2 |
| | gVisor (Tier 2 production) | 🚧 v0.4 |
| **Multi-agent** | Single-agent default | ✅ v0.1 |
| | Crew (secuencial/jerárquico) | 🚧 v0.4 |
| | A2A con trust | 🚧 v0.5 |
| **Observability** | Event log estructurado | ✅ v0.1 |
| | Bitácora markdown auditable | ✅ v0.1 |
| | OpenTelemetry exporter | 🚧 v0.3 |

---

## ARNES vs el resto

| Dimensión | LangChain | CrewAI | OpenAI Agents SDK | **ARNES** |
|---|---|---|---|---|
| Forma de definir agentes | Python procedural | Clases `Agent/Crew/Task` | `@agent` decorator | **YAML declarativo** |
| Distribución | Librería pip | Librería pip | Librería pip (OpenAI-only) | **MCP server + librería** |
| Specialists pre-construidos | ❌ | ❌ | ❌ | **✅ 5-12 listos** |
| Playbooks curados | ❌ | ❌ | ❌ | **✅ 30-50 manuales** |
| Token optimization | Manual | ❌ | ❌ | **✅ Middleware automático** |
| Anti-hallucination | DIY | ❌ | ❌ | **✅ 5 capas opt-in** |
| Budget enforcement | `max_tokens` básico | `max_tokens` básico | ❌ | **✅ Jerárquico + circuit breaker** |
| Vendor-neutral | Parcial | ✅ | ❌ | **✅ 100% (default Ollama local)** |
| Prompts visibles | ❌ | ❌ | ❌ | **✅ Archivos en disco** |
| Identidad Latam | ❌ | ❌ | ❌ | **✅ README bilingüe EN/ES** |

---

## Alineación con el manifiesto 12-factor-agents

ARNES se alinea explícitamente con los [12 factores](https://github.com/humanlayer/12-factor-agents):

| Factor | Descripción | ARNES |
|---|---|---|
| 1 | Natural language > structured language | ✅ YAML declarativo |
| 2 | Tools are structured outputs | ✅ Pydantic schemas |
| 3 | Give agents composable, discrete tools | ✅ Specialist registry |
| 4 | Agents are switching loops, not while loops | ✅ Event-driven reducer |
| 5 | Simple but powerful primitives | ✅ Thread + Agent + Tool |
| 6 | Use the right tool for the job | ✅ Model routing |
| 7 | Humans are tools, not gates | ✅ HITL como tool tipada |
| 8 | Make agents easy to debug | ✅ Bitácora markdown |
| 9 | Make agents observable | ✅ Event log + OTel (v0.3) |
| 10 | Replayable from any point | ✅ Stateless reducer + checkpoint |
| 11 | Be a state machine, not a DAG | ⚠️ Por diseño somos DAG (declarativo) |
| 12 | Deploy as a server, not a library | ✅ MCP server nativo |

---

## Instalación

```bash
# Con pip
pip install arnes

# Con uv (recomendado)
uv add arnes

# Con extras para vendors específicos
pip install "arnes[ollama,anthropic,openai]"
```

## Quickstart (60 segundos)

```bash
# 1. Instala
pip install arnes

# 2. Crea tu primer manual
arnes init --manual debug-python-issue

# 3. Ejecútalo (usa Ollama local por defecto, costo $0)
arnes ejecutar manuales/debug-python-issue.md.yaml
```

Si no tienes Ollama instalado, ARNES lo detecta y te guía. Para usar
Anthropic/OpenAI, setea la env var y ARNES hace el resto:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
arnes ejecutar manuales/auditar-pr.md.yaml --model anthropic/claude-sonnet-4-20250514
```

## Quickstart en español

```bash
# 1. Instala
pip install arnes

# 2. Crea tu primer manual en español
arnes init --manual auditar-pr --idioma es

# 3. Ejecútalo
arnes ejecutar manuales/auditar-pr.md.yaml
```

---

## Arquitectura

```
┌──────────────────────────────────────────────────────────────┐
│   TÚ (Claude Desktop / Cursor / CLI / Cline / Zed)            │
└────────────────────────┬─────────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────┐
│   ARNES MCP SERVER (1 instalación, 4 tools)                   │
│   run · list · events · resume                                │
└────────────────────────┬─────────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────┐
│   PLAYBOOK RUNTIME                                            │
│   YAML → Pydantic → DAG → Executor (condicional/parallel/HITL)│
└────────────────────────┬─────────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────┐
│   SPECIALIST REGISTRY (5-12 agentes pre-construidos)          │
│   planner · coder · reviewer · tester · debugger · ...        │
└────────────────────────┬─────────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────┐
│   CROSS-CUTTING MIDDLEWARE (todos los LLM calls lo cruzan)    │
│   🧠 Token Optimizer  🛡️ Verification  💰 Cost Guard          │
└────────────────────────┬─────────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────┐
│   LLM PROVIDERS (vendor-neutral, default Ollama local)        │
│   ollama · anthropic · openai · google · groq                 │
└──────────────────────────────────────────────────────────────┘
```

---

## Roadmap

- **v0.1.0 (Q1 2026)** — MVP: 5 specialists, 10 playbooks, DSL básico, MCP server, Token Optimizer v0, Verification v0, Cost Guard.
- **v0.2.0** — MCP cliente bidireccional, HITL como tool, Streaming AG-UI, Docker sandbox.
- **v0.3.0** — Episodic memory, context compaction, critic loop, 5 specialists más.
- **v0.4.0** — Multi-agent Crew, PolicyEngine, gVisor sandbox.
- **v0.5.0** — ARNES como MCP server exponiendo playbooks a Cursor/Claude Desktop.
- **v1.0.0** — A2A con trust, skills auto-aprendizaje, marketplace de playbooks.

---

## Comunidad

- **Discord:** [discord.gg/ARNES](https://discord.gg/ARNES) — canales `#general`, `#español`, `#help`, `#showcase`
- **Discussions:** [GitHub Discussions](https://github.com/frangelbarrera/ARNES/discussions)
- **Issues:** [Bug reports y feature requests](https://github.com/frangelbarrera/ARNES/issues)
- **Contributing:** lee [CONTRIBUTING.md](CONTRIBUTING.md) — aceptamos PRs desde D-day.

### Wedge hispanohablante

500M hispanohablantes tech subatendidos por la oferta actual. ARNES nace bilingüe:
README, docs, quickstart y Discord en EN y ES. Si quieres contribuir traducciones,
abre un issue con label `i18n`.

---

## Contribuir

Lee [CONTRIBUTING.md](CONTRIBUTING.md). TL;DR:

1. Fork + clone
2. `uv sync --all-extras` para setup dev
3. `pre-commit install`
4. Crea tu rama: `feat/mi-feature`
5. Conventional commits: `feat: ...`, `fix: ...`, `docs: ...`
6. `pytest` debe pasar con >80% coverage
7. Abre PR — revisión en <48h

**Good first issues:** busca issues con label `good-first-issue`.

---

## Sponsors

ARNES es 100% open-source bajo Apache 2.0. Si te ahorra dinero o tiempo:

- [GitHub Sponsors](https://github.com/sponsors/frangelbarrera)
- [Open Collective](https://opencollective.com/arnes)
- [BuyMeACoffee](https://buymeacoffee.com/frangelbarrera)

<div align="center">

*Sponsors aquí*

</div>

---

## Licencia

Apache License 2.0. Ver [LICENSE](LICENSE).

## Agradecimientos

ARNES existe sobre los hombros de:
- [LangGraph](https://github.com/langchain-ai/langgraph) — inspiración del DAG engine
- [LiteLLM](https://github.com/BerriAI/litellm) — provider abstraction
- [MCP SDK](https://github.com/modelcontextprotocol/python-sdk) — protocol
- [12-factor-agents](https://github.com/humanlayer/12-factor-agents) — manifiesto
- [Pydantic](https://github.com/pydantic/pydantic) — structured data

---

<div align="center">

**[⭐ Star el repo](https://github.com/frangelbarrera/ARNES)** si esto te resuena.

*From Latam to the world. 🌎*

</div>
