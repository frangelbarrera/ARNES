# Contributing to ARNES

¡Gracias por considerar contribuir a ARNES! Este documento te guía a través del proceso.

## Código de Conducta

Al participar, aceptas cumplir nuestro [Code of Conduct](CODE_OF_CONDUCT.md). TL;DR: sé respetuoso, inclusivo y profesional. ARNES nació en Latam y damos especial bienvenida a contribuyentes hispanohablantes.

## Setup de desarrollo

```bash
# 1. Fork + clone
git clone https://github.com/TU-USUARIO/ARNES.git
cd ARNES

# 2. Instala uv (gestor de paquetes)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Instala dependencias
uv sync --all-extras

# 4. Instala pre-commit hooks
uv run pre-commit install

# 5. Verifica que todo funciona
uv run pytest
```

## Estructura del proyecto

```
arnes/
├── arnes/
│   ├── agent/           # Agent class + stateless reducer
│   ├── thread/          # Thread + Event[] stateless
│   ├── tools/           # Tool registry + BaseTool
│   ├── events/          # Event types (Pydantic)
│   ├── llm/             # LLM provider abstraction
│   ├── middleware/      # Token Optimizer, Verification, Cost Guard
│   ├── mcp/             # MCP server
│   ├── specialists/     # 5+ pre-built specialists
│   ├── playbooks/       # Playbook DSL + 10 curated manuals
│   └── cli/             # arnes CLI
├── tests/
├── examples/
├── docs/
└── pyproject.toml
```

## Conventional Commits

Usamos [Conventional Commits](https://www.conventionalcommits.org/):

- `feat: ...` — nueva feature
- `fix: ...` — bug fix
- `docs: ...` — solo documentación
- `style: ...` — formato, no afecta código
- `refactor: ...` — refactor sin cambios de comportamiento
- `perf: ...` — mejora de performance
- `test: ...` — añade tests
- `chore: ...` — tareas de build, deps, etc.

Ejemplo: `feat(specialists): add @security-auditor with SAST integration`

## Tipos de contribuciones bienvenidas

### 🥇 Alta prioridad
- **Nuevos specialists** — abre issue primero para discutir el rol
- **Nuevos playbooks** — curados, no triviales
- **Bug fixes** con test que lo reproduzca
- **Mejoras de performance** con benchmark antes/después

### 🥈 Media prioridad
- **Traducciones** — README, docs, quickstart a otros idiomas
- **Mejoras de DX** — mejor error messages, better CLI UX
- **Más tests** — busca `# pragma: no cover` y cubre esos caminos

### 🥉 Baja prioridad (pero bienvenidas)
- **Typo fixes**
- **Mejoras de docs**
- **Refactors cosméticos**

## Proceso de PR

1. **Abre issue primero** para features grandes (>"good first issue" scope)
2. **Fork + branch**: `feat/mi-feature` o `fix/issue-123`
3. **Tests**: todos los PRs deben mantener >80% coverage
4. **Docs**: actualiza README/docs si tu feature lo requiere
5. **Changelog**: añade entrada en `CHANGELOG.md` bajo `[Unreleased]`
6. **CLA**: al primer PR, firma el CLA (automático vía cla-assistant)

## Testing

```bash
# Todos los tests
uv run pytest

# Solo unit tests
uv run pytest tests/unit

# Con coverage report
uv run pytest --cov=arnes --cov-report=html
open htmlcov/index.html

# Tests específicos
uv run pytest tests/unit/test_thread.py -v

# Tests lentos (que llaman a LLM real)
uv run pytest -m slow
```

### Snapshot tests con VCRpy

ARNES usa [vcrpy](https://github.com/kevin1024/vcrpy) para grabar respuestas de
LLM y replayearlas en tests. Esto permite tests reproducibles sin gastar tokens.

```python
@pytest.mark.snapshot
def test_specialist_responds(vcr):
    with vcr.use_cassette("tests/snapshot/cassettes/specialist_basic.yaml"):
        result = my_specialist.run("Hello")
        assert result.confidence > 0.7
```

Para regenerar cassettes (cuando cambias un prompt), borra el archivo y re-corre
el test con `--record-mode=new`.

## Linting y type checking

```bash
# Ruff (lint + format)
uv run ruff check arnes/
uv run ruff format arnes/

# Mypy (types)
uv run mypy arnes/

# Bandit (security)
uv run bandit -r arnes/

# pip-audit (vulnerabilities)
uv run pip-audit
```

Pre-commit ejecuta todo esto automáticamente.

## Añadir un nuevo specialist

1. Crea `arnes/specialists/mi_specialist.py`:

```python
from arnes.specialists.base import Specialist, SpecialistConfig

class MiSpecialist(Specialist):
    """Descripción de qué hace este especialista."""
    
    config = SpecialistConfig(
        name="@mi-specialist",
        description="Hace X cosa",
        system_prompt="Eres un experto en X...",
        tools=["shell", "fs_read"],
        output_schema=MiOutput,  # pydantic
    )
```

2. Regístralo en `arnes/specialists/__init__.py`
3. Añade test en `tests/unit/test_mi_specialist.py`
4. Añade ejemplo en `examples/usar_mi_specialist.py`
5. Documenta en `docs/specialists.md`

## Añadir un nuevo playbook

1. Crea `manuales/mi-playbook.md.yaml` (sigue la spec en `docs/playbook-dsl.md`)
2. Añade test en `tests/integration/test_mi_playbook.py`
3. Valida con `arnes lint manuales/mi-playbook.md.yaml`

## Reportar bugs

Abre un [issue](https://github.com/frangelbarrera/ARNES/issues/new?template=bug_report.md) con:

1. **Versión de ARNES**: `arnes --version`
2. **Versión de Python**: `python --version`
3. **OS**: Linux/macOS/Windows + versión
4. **Reproducción mínima**: código mínimo que reproduzca el bug
5. **Output esperado vs actual**
6. **Logs**: pega el contenido de la bitácora si aplica

## Reportar vulnerabilidades de seguridad

**NO abras un issue público para vulnerabilidades de seguridad.**

Envía un email a `security@arnes.dev` con:
- Descripción del problema
- Pasos para reproducir
- Impacto estimado
- PoC si tienes

Respondemos en <72h. Si la vulnerabilidad es válida, publicamos advisory en
[GitHub Security Advisories](https://github.com/frangelbarrera/ARNES/security/advisories)
y te damos crédito (a menos que prefieras permanecer anónimo).

## Licencia

Al contribuir, aceptas que tus contribuciones se licencien bajo Apache 2.0.
