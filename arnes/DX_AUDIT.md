# DX AUDIT — ARNES v0.1.0a1

**Auditor:** Subagente ingeniero de software senior (DX / arquitectura de librerías Python)
**Fecha:** 2026-07-28
**Scope:** API pública, CLI, Playbook DSL, MCP, Thread, Specialists, Tools, Middleware, Docs, Tests
**Método:** Lectura completa de los 12 archivos indicados + tests + manuales + ejecución real del quickstart documentado + `mypy --strict`

---

## Resumen ejecutivo

ARNES tiene **una idea excelente** (YAML declarativo → DAG de especialistas, bitácora auditable, presupuesto jerárquico, vendor-neutral) y **una arquitectura interna sana** (Thread immutable + reducer puro, middleware como wrappers, specialists como datos). El diseño a nivel de módulos está bien pensado y los nombres conceptuales (Thread, Specialist, Playbook, Tool) son correctos.

Pero **el quickstart documentado no funciona**. Ejecutar literalmente los 3 comandos del README produce un `YAML parse error` en el archivo que el propio `arnes init` acaba de generar. Ese solo hecho convierte el "hello world en 60 segundos" en un NO-GO para alpha pública. No es el único bug crítico: hay 5 issues que silenciosamente hacen que el showcase principal (`auditar-pr.md.yaml`) entregue resultados incorrectos sin avisar, que el middleware se aplique dos veces, y que la integración MCP anunciada como ✅ v0.1 **no tenga comando CLI para arrancarla**.

La DX está a 4–6 fixes pequeños (la mayoría < 30 líneas) de estar lista para alpha. Tal cual está hoy, publicarla dañaría la reputación del proyecto en la primera hora.

---

## Tabla de issues

| #  | Severity | Título corto | Archivo: línea (aprox) |
|----|----------|--------------|------------------------|
| 1  | CRITICAL | Quickstart del README no funciona: scaffold produce YAML inválido | `arnes/cli/main.py:287-310` (template `_MANUAL_TEMPLATE_ES`) |
| 2  | CRITICAL | Comando `arnes mcp serve` documentado pero no implementado | `arnes/cli/main.py` (sin grupo `mcp`) |
| 3  | CRITICAL | Templates `{{ pasos.paralelo.X.salida }}` no resuelven — salida silenciosamente incorrecta | `arnes/playbooks/executor.py:497-525` + `_execute_parallel:385-419` |
| 4  | CRITICAL | Middleware se envuelve dos veces (Agent + Specialist) — costos, tokens y verificación duplicados | `arnes/agent/agent.py:99-105` + `arnes/specialists/base.py:99-105` |
| 5  | CRITICAL | Manifesto #2 roto: existe clase `Agent` en API pública | `arnes/__init__.py:9,33` + `arnes/agent/agent.py:48` |
| 6  | HIGH     | `arnes init --manual <name>` no carga el ejemplo real (crea template roto en vez de copiar `manuales/<name>.md.yaml`) | `arnes/cli/main.py:50-62, 250-263` |
| 7  | HIGH     | VerificationLayer nunca recibe `response_schema` → "structured outputs" no valida nada | `arnes/specialists/base.py:110-116` + `arnes/middleware/verification.py:79-119` |
| 8  | HIGH     | Parallel branches se ejecutan secuencialmente pese a estar marcados ✅ v0.1 | `arnes/playbooks/executor.py:385-419` (comentario lo admite) |
| 9  | HIGH     | `saltar_a` está mal implementado: agrega destino a `__skip_steps` y nunca lo limpia | `arnes/playbooks/executor.py:122, 455-459` |
| 10 | HIGH     | Prompts de specialists embebidos en `.py` (manifesto #6 exige archivos en disco) | `arnes/specialists/*.py` |
| 11 | HIGH     | `mypy --strict` falla con 31 errores (AGENTS.md exige que pase) | 8 archivos (ver detalles abajo) |
| 12 | HIGH     | Dependencia `mcp>=1.0,<2` declarada pero nunca importada (1+ MB de dead weight) | `pyproject.toml:59` vs uso real |
| 13 | MEDIUM   | `SpecialistRegistry.list` / `ToolRegistry.list` sombrean builtin `list` → mypy confundido | `arnes/specialists/base.py:197`, `arnes/tools/base.py:181` |
| 14 | MEDIUM   | `Playbook.metadata` es `Optional` pero CLI/MCP acceden sin chequear (6 mypy errors) | `arnes/playbooks/schema.py:150` |
| 15 | MEDIUM   | `__skip_steps` (clave mágica) contamina el namespace de outputs del usuario | `arnes/playbooks/executor.py:122, 457` |
| 16 | MEDIUM   | Errores de YAML muestran `ScannerError` crudo sin sugerir fix (quote `@`, indentación, etc.) | `arnes/playbooks/compiler.py:60-70` |
| 17 | MEDIUM   | `arnes lint` no detecta specialists inexistentes (solo valida sintaxis) | `arnes/playbooks/compiler.py:156-193` |
| 18 | MEDIUM   | `arnes ejecutar --interactive` no hace nada útil (HITL gate nunca se pausa, no hay input TTY en MCP) | `arnes/playbooks/executor.py` (sin uso de `aprobacion_humana`) + `arnes/cli/main.py:70` |
| 19 | MEDIUM   | README miente sobre cantidades: "30-50 playbooks" → solo 4; "5-12 specialists" → solo 5 | `README.md:122, 159-160` |
| 20 | MEDIUM   | README quickstart EN ejecuta `arnes init --manual debug-python-issue` y luego `arnes ejecutar manuales/debug-python-issue.md` (sin `.yaml`) — path no existe | `README.md:33-35, 211-214` |
| 21 | MEDIUM   | `examples/` y `docs/` referenciados en CONTRIBUTING.md pero no existen | `CONTRIBUTING.md` |
| 22 | MEDIUM   | `executor.py` tiene 525 líneas (AGENTS.md: ">500 líneas = haciendo demasiado") | `arnes/playbooks/executor.py` |
| 23 | MEDIUM   | `Thread.reduce()` es O(n) y se llama implícitamente en cada append en el futuro (no hoy, pero la API invita a ello) | `arnes/thread/thread.py:108-131` |
| 24 | LOW      | `__import__("time").time()` y `__import__("sys").stdin` son anti-patrones | `arnes/middleware/token_optimizer.py:121`, `arnes/mcp/server.py:258` |
| 25 | LOW      | `Event` base permite `data: dict[str, Any]` sin tipos — tipos de eventos específicos no validan shape | `arnes/thread/events.py:74-85, 96-217` |
| 26 | LOW      | Cache de `TokenOptimizer` no tiene tamaño máximo en bytes (solo cuenta de entradas) → riesgo de OOM en runs largos | `arnes/middleware/token_optimizer.py:69, 198-206` |
| 27 | LOW      | Costos hardcodeados en `litellm_provider.py` se desactualizan; no hay mecanismo de actualización | `arnes/llm/litellm_provider.py:13-24` |
| 28 | LOW      | `OllamaProvider` no reintentará en `httpx.ConnectError`; lanza `RuntimeError` que el executor no captura específicamente | `arnes/llm/ollama.py:52-56`, `arnes/playbooks/executor.py:288-298` |
| 29 | LOW      | Errores en `specialist.run` devuelven `{"success": False, "error": str(e)}` — traga el traceback original | `arnes/agent/agent.py:124-126`, `arnes/playbooks/executor.py:288-298` |
| 30 | LOW      | Tests no cubren: HITL gates, retry policy, condicionales `cuando` reales, parallel branches con dependencias cruzadas, fallback `llamar` | `tests/` |
| 31 | LOW      | `arnes list playbooks --dir` falla silenciosamente si el dir no existe (warning amarillo, no error) | `arnes/cli/main.py:121-146` |
| 32 | LOW      | `_PRICING_USD_PER_1M_TOKENS` tiene typos: `claude-sonnet-4-20250514` no existe, `o1` está mal listado | `arnes/llm/litellm_provider.py:13-24` |

---

## Detalle de issues críticos y altos

### Issue #1 — Quickstart del README no funciona (CRITICAL)

**Archivo:** `arnes/cli/main.py:287-310`

**Descripción:**
El template `_MANUAL_TEMPLATE_ES` (y `_MANUAL_TEMPLATE_EN`) genera YAML con:
```yaml
especialista: @planner
```
YAML 1.1 rechaza `@` al inicio de un valor escalar no quoteado. Esto ya está documentado en `CLAUDE.md:17` ("Quote specialist names: `"@planner"`, not `@planner` (YAML quirk)"), pero el propio scaffold no aplica la regla.

**Reproducción:**
```bash
$ cd /tmp && arnes init --manual test
$ arnes ejecutar manuales/test.md.yaml --mock
✗ Compile error:
YAML parse error: while scanning for the next token
found character '@' that cannot start any token
  in "<unicode string>", line 10, column 19:
        especialista: @planner
                      ^
```

El error que ve el usuario no sugiere la causa ni el fix. Un dev nuevo se atasca aquí en el segundo comando del quickstart.

**Fix recomendado:**
```python
_MANUAL_TEMPLATE_ES = """\
# {name}.md.yaml — Manual de ARNES

nombre: {name}
objetivo: Describe qué hace este manual
budget_usd: 0.50

pasos:
  - id: paso_1
    especialista: "@planner"   # <-- comillas dobles obligatorias
    input:
      task: "Describe la tarea a planificar"
  ...
"""
```

Y en `compiler.py:60-70`, detectar el patrón `found character '@'` y emitir:
```
YAML parse error: el valor '@planner' debe ir entre comillas.
Hint: en YAML, los valores que empiezan con @, :, -, etc. deben quotearse.
Ejemplo:  especialista: "@planner"
```

---

### Issue #2 — Comando `arnes mcp serve` documentado pero no existe (CRITICAL)

**Archivo:** `arnes/cli/main.py` (no hay grupo `mcp`); `arnes/mcp/server.py:11-18` (docstring muestra `arnes mcp serve`); `README.md:127, 281` (lo anuncian como ✅ v0.1).

**Descripción:**
El README y el docstring del MCP server prometen que Claude Desktop puede configurar ARNES como MCP server con:
```json
{"mcpServers": {"arnes": {"command": "arnes", "args": ["mcp", "serve"]}}}
```
Pero el CLI no registra ningún subcomando `mcp`. Ejecutar `arnes mcp serve` produce `Error: No such command 'mcp'`. La función `serve_stdio()` existe en `arnes/mcp/server.py:251` pero no está conectada al CLI.

Adicionalmente, la implementación de `serve_stdio` usa JSON-RPC **newline-delimited**:
```python
line = await reader.readline()
request = json.loads(line.decode("utf-8"))
```
El MCP spec usa framing con header `Content-Length: N\r\n\r\n` (igual que LSP). Incluso si se cableara el comando, Claude Desktop no podría hablar con este server.

**Fix recomendado:**
1. Agregar a `cli/main.py`:
   ```python
   @cli.group()
   def mcp() -> None:
       """MCP server commands."""
       pass

   @mcp.command("serve")
   def mcp_serve() -> None:
       """Start the MCP server (stdio transport)."""
       asyncio.run(serve_stdio())
   ```
2. **Reemplazar** la implementación custom de stdio por el SDK oficial `mcp` (que ya está en `pyproject.toml` pero **no se importa en ningún lado** — ver issue #12). Eso resuelve el framing, el handshake `initialize`, las notificaciones `notifications/initialized`, etc.
3. Hasta que se haga eso, cambiar el README y el docstring a "🚧 v0.2" en vez de "✅ v0.1".

---

### Issue #3 — Templates `{{ pasos.paralelo.X.salida }}` no resuelven (CRITICAL)

**Archivo:** `arnes/playbooks/executor.py:497-525` (`_resolve_template`) y `385-419` (`_execute_parallel`).

**Descripción:**
El playbook `manuales/auditar-pr.md.yaml` (el showcase principal del README) tiene:
```yaml
- id: sintesis
  especialista: "@reviewer"
  input:
    lint: "{{ pasos.paralelo.lint.salida }}"
    tests: "{{ pasos.paralelo.tests.salida }}"
```

Pero `_execute_parallel` guarda `outputs['paralelo'] = {'lint': <parsed_json>, 'tests': <parsed_json>}` (sin wrapper `output`), mientras `_resolve_template` espera navegar `outputs['paralelo']['lint']['output']`. Como no encuentra la clave `output`, devuelve la cadena literal sin resolver.

**Reproducción (ejecutada):**
```python
RESOLVED use input: {'a_out': '{{ pasos.par.a.salida }}', 'b_out': '{{ pasos.par.b.salida }}'}
```
El especialista recibe el texto literal `{{ pasos.par.a.salida }}` en vez del output real. La ejecución "tiene éxito" porque el LLM no sabe que es basura.

**Fix recomendado:**
Opción A (consistencia): en `_execute_parallel`, envolver cada sub-output como los specialists:
```python
outputs_map[sub_step.id] = result.get("output")  # igual que specialist
```
Y normalizar el almacenamiento en `outputs[step.id]` para que siempre sea o bien el dict completo `{"output": ..., "usage": ...}` o bien solo `output`. Hoy hay inconsistencia: specialist guarda `result.get("output")` (parseado), parallel guarda `{"sub_id": result.get("output")}` (parseado), tool guarda `result.output if result.success else None`.

Opción B (más robusta): en `_resolve_template`, aceptar que si `current` es un dict sin `output`, devolver `current` mismo (el valor parseado).

Y agregar un test E2E que verifique que `sintesis` recibe inputs no-templatizados.

---

### Issue #4 — Middleware se envuelve dos veces (CRITICAL)

**Archivos:** `arnes/agent/agent.py:99-105` y `arnes/specialists/base.py:99-105`.

**Descripción:**
`Agent.run()` envuelve el provider con `CostGuard(VerificationLayer(TokenOptimizer(provider)))` y se lo pasa al specialist. Pero `Specialist.run()` vuelve a envolverlo con `CostGuard(VerificationLayer(TokenOptimizer(provider)))`.

Resultado: cada LLM call atraviesa **2 CostGuards, 2 VerificationLayers, 2 TokenOptimizers**. Evidencia en los logs (ejecución real de `hola-mundo.md.yaml --mock`):
```
llm_call_tracked  budget=0.5  ...  # specialist's CostGuard
llm_call_tracked  budget=0.5  ...  # (mismo call duplicado)
```
4 eventos `llm_call_tracked` para 2 calls reales.

Consecuencias:
- El system prompt anti-hallucination se inyecta dos veces (más tokens, degradación leve).
- El cache se particiona entre dos instancias → menos hits.
- El presupuesto se descuenta dos veces (aunque mock sea $0, con providers pagos se cobraría/descartaría en ambos).
- `stats()` de cada middleware reporta números parciales.

Misma duplicación ocurre en `PlaybookExecutor`: el executor crea su propio `CostGuard` (línea 109) y lo pasa al specialist, que lo vuelve a envolver.

**Fix recomendado:**
Elegir **un solo punto** de wrapping. Recomendado: el specialist NO envuelve; el `Agent` / `PlaybookExecutor` son responsables de construir el stack de middleware una sola vez. Eliminar las líneas 96-105 de `specialists/base.py` y exigir que el `provider` que entra al specialist ya esté envuelto.

Alternativa: si se quiere que el specialist sea usable standalone, agregar un flag `wrap_middleware: bool = False` (default False) y solo envolver si el caller no lo hizo.

---

### Issue #5 — Manifesto #2 roto: clase `Agent` en API pública (CRITICAL)

**Archivos:** `MANIFESTO.md:38-39`, `AGENTS.md:23-24`, `CLAUDE.md:8`, `arnes/__init__.py:9,33`, `arnes/agent/agent.py:48`.

**Descripción:**
Declaración #2 del manifesto: *"ARNES nunca va a tener una clase llamada `Runnable`, `Chain`, `Workflow` o `Agent`. Composición = funciones."*

`AGENTS.md:23` y `CLAUDE.md:8` lo repiten: *"No classes named `Runnable`, `Chain`, `Workflow`, or `Agent`."*

Pero `arnes.Agent` existe, se exporta desde `__init__.py`, y es la **primera clase** mencionada en la docstring del módulo:
```python
from arnes.agent import Agent, AgentConfig
```

Esto es una violación directa del contrato con la comunidad. Si se publica así, el primer issue que abrirá cualquier contribuidor que haya leído el manifesto será este.

**Fix recomendado:**
Renombrar a `arnes.Harness` o `arnes.run_specialist(...)` (función). `AgentConfig` → `RunConfig` o `HarnessConfig`. Actualizar README y tests. Es un rename mecánico de ~10 archivos.

Si se decide mantener `Agent` (porque el nombre es másdiscoverable), entonces **enmendar el manifesto** con una discusión pública. Pero hacerlo sin avisar rompe el contrato social.

---

### Issue #6 — `arnes init --manual <name>` no carga el ejemplo real (HIGH)

**Archivo:** `arnes/cli/main.py:50-62, 250-263`.

**Descripción:**
El README quickstart dice:
```bash
arnes init --manual debug-python-issue
arnes ejecutar manuales/debug-python-issue.md.yaml
```
El usuario razonablemente espera que este comando **copie el playbook `manuales/debug-python-issue.md.yaml`** que viene en el repo. En realidad, `arnes init --manual X` siempre genera el template `_MANUAL_TEMPLATE_ES` sin importar el nombre. Así que el usuario termina con un playbook de 3 pasos genéricos (que además está roto por issue #1), no con el playbook de debug que vio en el README.

**Fix recomendado:**
Si el nombre coincide con uno de los playbooks curados en `manuales/`, copiar ese archivo. Si no, generar el template. Código:
```python
def _scaffold_manual(name: str, idioma: str) -> None:
    curated = Path(__file__).parent.parent.parent / "manuales" / f"{name}.md.yaml"
    target = Path("manuales") / f"{name}.md.yaml"
    if curated.exists():
        shutil.copy(curated, target)
        console.print(f"[green]✓[/green] Copied curated playbook: [cyan]{target}[/cyan]")
        return
    # ... fallback al template
```

---

### Issue #7 — VerificationLayer nunca valida `output_schema` (HIGH)

**Archivos:** `arnes/specialists/base.py:110-116`, `arnes/middleware/verification.py:79-119`.

**Descripción:**
Cada specialist declara `output_schema={"type": "object", "required": [...]}` en su config. `Specialist.run()` lo usa solo para decidir si pasar `response_format={"type": "json_object"}` al provider. Pero **nunca** pasa `response_schema=<self.config.output_schema>` a `VerificationLayer.complete()`.

La firma de `VerificationLayer.complete` sí acepta `response_schema: dict | None = None`, pero como nobody lo pasa, el branch `if self.config.structured_outputs and response_schema:` en línea 144 nunca se ejecuta. La validación contra schema es código muerto.

Resultado: si el LLM devuelve JSON válido pero sin los campos requeridos, ARNES lo acepta como éxito. La feature "Structured outputs with pydantic ✅ v0.1" del README no funciona como se anuncia.

**Fix recomendado:**
En `specialists/base.py:110`:
```python
response = await guarded_provider.complete(
    messages,
    model=model,
    temperature=self.config.temperature,
    max_tokens=self.config.max_tokens,
    response_format={"type": "json_object"} if self.config.output_schema else None,
    response_schema=self.config.output_schema,  # <-- agregar
)
```
Y para que esto no se trague el kwarg en providers que no lo acepten (`MockLLMProvider`, `OllamaProvider`, `LiteLLMProvider`), agregar `**kwargs` a sus firmas o filtrar el kwarg en `VerificationLayer` antes de delegar.

---

### Issue #8 — Parallel branches se ejecutan secuencialmente (HIGH)

**Archivo:** `arnes/playbooks/executor.py:385-419`.

**Descripción:**
El comentario en línea 397-399 lo admite:
> "Note: parallel sub-steps share the same thread_holder, but since each appends to the immutable Thread, we need to merge results back. For MVP, parallel steps are executed sequentially (true parallelism requires a different state model — coming in v0.2)."

Pero el README (línea 124) marca `Parallel branches ✅ v0.1`. Esto es misleading: el feature "funciona" (los pasos corren, los outputs se agregan) pero no hace lo que el nombre promete. Si el usuario depende de paralelismo para latencia (e.g. lint + tests en paralelo), se lleva una sorpresa.

**Fix recomendado:**
Dos opciones:
- **A (rápida):** marcar como 🚧 v0.2 en el README. Honestidad.
- **B (correcta):** usar `asyncio.gather` + un `thread_holder` por rama + merge al final. Necesita que el modelo de Thread soporte append concurrente (hoy es O(n) por la lista interna; cambiar a estructura de árbol o a un `asyncio.Lock` + append serial). Para MVP, opción A.

---

### Issue #9 — `saltar_a` está mal implementado (HIGH)

**Archivo:** `arnes/playbooks/executor.py:122, 455-459`.

**Descripción:**
Cuando un step falla y su `si_no_se_cumple` tiene `accion: saltar, saltar_a: step_3`, el código hace:
```python
skip_set = outputs.setdefault("__skip_steps", set())
skip_set.add(branch.saltar_a)  # Will be cleared when we reach it
```
Dos bugs:
1. La semántica de "saltar a" es "ir a" (goto), no "saltar este paso". Pero agregar `step_3` a `__skip_steps` hace que cuando el loop llegue a `step_3`, lo **skip** en vez de ejecutarlo. Exactamente al revés.
2. El comentario dice "Will be cleared when we reach it" pero **no hay código** que lo limpie. `__skip_steps` crece monótonamente.

Además, `__skip_steps` se comprueba con `outputs.get("__skip_steps", set())` (línea 122), pero `outputs` es el dict público del usuario. Si el usuario define `variables: {__skip_steps: ...}` colisiona.

**Fix recomendado:**
Si la semántica es "goto", implementar un índice de loop y un `goto`:
```python
step_index = {s.id: i for i, s in enumerate(playbook.pasos)}
i = 0
while i < len(playbook.pasos):
    step = playbook.pasos[i]
    ...
    if branch.accion == "saltar" and branch.saltar_a in step_index:
        i = step_index[branch.saltar_a]
        continue
    i += 1
```
Y mover `__skip_steps` a un atributo privado del executor (`self._skip_set`), no a `outputs`.

---

### Issue #10 — Prompts embebidos en `.py` (HIGH)

**Archivos:** `arnes/specialists/planner.py:10-41`, `coder.py:10-40`, etc.

**Descripción:**
Manifesto #6: *"ARNES no esconde el prompt del LLM. Cada prompt que se envía es un archivo en disco que puedes abrir, diffear y versionar."*

Hoy los prompts son strings multilinea dentro de archivos `.py`. Técnicamente están "en disco" (el `.py` es un archivo), pero el espíritu del manifesto es que sean **archivos editables sin tocar código** — típicamente `prompts/planner.md`, `prompts/coder.md`, etc. Así un dev puede iterar el prompt sin reiniciar Python, puede ver el diff en un PR sin leer Python, y puede versionarlos independientemente.

**Fix recomendado:**
```
arnes/specialists/prompts/
  planner.md
  coder.md
  reviewer.md
  tester.md
  debugger.md
```
Y en `base.py`:
```python
def _load_prompt(name: str) -> str:
    prompt_path = Path(__file__).parent / "prompts" / f"{name}.md"
    return prompt_path.read_text(encoding="utf-8")
```
Cargar en `__init_subclass__` o lazy en `run()`. Esto también permite a usuarios overridear prompts vía env var (`ARNES_PROMPTS_DIR=...`).

---

### Issue #11 — `mypy --strict` falla con 31 errores (HIGH)

**Comando ejecutado:** `mypy arnes/` → 31 errores en 8 archivos.

**Categorías:**
- `no-any-return` (3): `compiler.py:138, 196`, `tools/base.py:132` — devuelven `Any` desde `yaml.safe_load` o `model_dump()`.
- `valid-type` (3): `tools/base.py:193`, `specialists/base.py:203`, `playbooks/compiler.py:196` — por sombra del builtin `list` (ver issue #13).
- `assignment` (5): `agent.py:99,101,105`, `specialists/base.py:99,101` — los middleware no son subclases de `LLMProvider` (no heredan, son duck-typed). El type system no sabe que `TokenOptimizer` es usable como `LLMProvider`.
- `attr-defined` (2): `mcp/server.py:210`, `cli/main.py:103` — consecuencia del `list` shadowing.
- `union-attr` (10): `mcp/server.py:226-243`, `cli/main.py:139-245` — `playbook.metadata` es `Optional` y se accede sin check.
- `no-untyped-def` (2): `executor.py:421, 495` — `_handle_conditional_branch` sin tipos, `_resolve_input` con rama inalcanzable.
- `import-untyped` (1): `compiler.py:19` — falta `types-PyYAML`.
- `unreachable` (1): `executor.py:495`.
- `type-abstract` (1): `tools/registry.py:17` — pasar clase abstracta `Tool` a `register_class`.

AGENTS.md:35 dice: "`mypy --strict` must pass". No pasa. Cualquier PR que arregle algo va a chocar con estos errores preexistentes.

**Fix recomendado:**
Hacer que los middleware hereden de `LLMProvider` (o declarar un `Protocol`) — resuelve 5 errors de assignment + hace el código más obvio. Renombrar `Registry.list` → `Registry.names` (issue #13) resuelve 3. Validar `metadata is not None` en CLI/MCP resuelve 10. Instalar `types-PyYAML` en dev deps. Los demás son fixes puntuales.

---

### Issue #12 — Dependencia `mcp` declarada pero nunca usada (HIGH)

**Archivos:** `pyproject.toml:59` (`"mcp>=1.0,<2"`), búsqueda `import mcp` → 0 resultados.

**Descripción:**
El SDK oficial de MCP está en dependencies pero nunca se importa. El MCP server es hand-rolled (y roto, ver issue #2). Esto es:
- 1+ MB de código que se instala para nada.
- Una oportunidad perdida: el SDK oficial resuelve handshake, framing, notificaciones, sampling, resources.
- Misleading para contribuidores que esperan que `mcp` sea el transport.

**Fix recomendado:**
O bien usar el SDK oficial (recomendado, resuelve issue #2 de paso), o quitar la dependencia hasta v0.2.

---

## Top 5 mejoras obligatorias antes del launch

1. **Fix #1 (scaffold template roto).** Sin esto, el quickstart del README no funciona. 1 línea de cambio (`@planner` → `"@planner"`). Mejora también el mensaje de error de YAML parser para sugerir el fix. **Sin esto, no hay alpha.**

2. **Fix #4 (middleware doble).** Cada llamada al LLM atraviesa 2 CostGuards y 2 VerificationLayers. Esto invalida las stats de costos, duplica tokens, y rompe el cache. Decidir un único punto de wrapping (recomendado: el specialist no envuelve). 5 líneas removidas de `specialists/base.py:96-105`.

3. **Fix #2 + #12 (MCP server realmente funciona).** Implementar `arnes mcp serve` usando el SDK oficial que ya está en deps. Sin esto, el claim "MCP ✅ v0.1" del README es falso y la integración con Claude Desktop no funciona en absoluto.

4. **Fix #3 (templates de parallel branches).** El showcase `auditar-pr.md.yaml` del README entrega resultados silenciosamente incorrectos. Es el playbook que la gente va a copiar primero. Sin fix, la primera impresión del proyecto es "funciona pero produce basura".

5. **Fix #5 (violación del manifesto).** Renombrar `Agent` → `Harness` o función `run_specialist`. Sin esto, el contrato social del proyecto (un manifesto que el autor puso como "inmutable") se rompe en la primera línea de la API pública. Daña credibilidad.

**Bonus obligatorio para alpha honesta:** actualizar el README para reflejar realidad (4 manuales, no 30-50; parallel es 🚧 v0.2; HITL no implementado). Marcar features no implementadas como 🚧.

---

## Veredicto

### ¿La DX está lista para alpha? **NO-GO** (condicional a 5 fixes).

La arquitectura es correcta, los conceptos son buenos, los tests existen y pasan con mock, el CLI es discoverable. Pero tres de los cinco fixes obligatorios son **roturas del contrato público** (quickstart no funciona, MCP no funciona, manifesto roto). Publicar alpha con esos tres bugs va a generar issues en GitHub en la primera hora que serán muy difíciles de recuperar.

Los 5 fixes son pequeños (probablemente < 200 líneas totales de cambio, sin contar el SDK oficial de MCP). Una vez aplicados, ARNES estaría listo para una alpha **honestamente etiquetada** (con features no implementadas marcadas como 🚧).

**Recomendación:** aplazar la publicación 2-3 días, aplicar los 5 fixes, re-ejecutar el quickstart del README end-to-end con `--mock` y con Ollama real, y entonces publicar como `0.1.0a1`.

---

## Notas adicionales

### Cosas que están bien (para que conste)

- **Thread + reducer puro**: diseño correcto, immutabilidad respetada, tests sólidos.
- **ToolResult.ok / .fail**: API limpia, fingerprint rug-pull defense es buena idea.
- **SSRF / path traversal protection**: implementado y testeado.
- **Cost guard con circuit breaker temporal**: el feature más diferenciador, bien estructurado.
- **Bilingual key translation ES/EN**: detalle fino, funciona.
- **`arnes ejecutar --mock`**: excelente para CI y desarrollo sin red.
- **Tests como documentación**: `test_playbook_compiler.py` y `test_executor.py` son legibles y muestran el DSL en acción.
- **Docstrings**: mayoría con ejemplos de uso.
- **`pyproject.toml`**: configuración completa y profesional (ruff, mypy, bandit, pytest, coverage).

### Lo que falta para MVP (issue #12 del prompt original)

- **Logging configurado por defecto**: structlog está importado pero no configurado. Los logs van a stderr en formato dev. Falta `structlog.configure(...)` en `arnes/__init__.py` o un `arnes.logging.setup()`.
- **Configuración global**: no hay `arnes.config.Settings` con pydantic-settings (que sí está en deps). Un usuario no puede setear `ARNES_DEFAULT_MODEL`, `ARNES_BUDGET_USD`, etc. vía env sin tocar código.
- **Examples más completos**: el dir `examples/` referenciado en CONTRIBUTING no existe. Faltan ejemplos de: specialist custom, tool custom, playbook con HITL real, integración MCP.
- **`docs/`**: no existe. El README enlaza `https://arnes.dev` que probablemente no exista aún.
- **Retry policy**: declarado en schema (`RetryPolicy`) pero el executor **nunca** lo aplica. Bug silencioso.
- **HITL gate**: declarado en schema (`HITLGate`, `aprobacion_humana`) pero el executor nunca lo invoca. El flag `--interactive` del CLI no hace nada.
- **Condicionales `cuando`**: `ConditionalBranch.cuando` está en el schema pero el executor no evalúa la expresión. Solo maneja `si_no_se_cumple` (que tampoco evalúa condición, solo dispara cuando el step falla).
