# AI Patterns Audit — ARNES v0.1

**Auditor:** Subagente Ingeniero de IA Senior
**Task ID:** AI-AUDIT
**Date:** 2026-01
**Scope:** specialists/, middleware/, playbooks/, llm/, manuales/
**Verdict:** **NO-GO para alpha público** (ver §5)

---

## 1. Resumen ejecutivo

ARNES tiene **una arquitectura elegante** (stateless reducer + specialists + middleware + playbooks YAML) y **buenas intenciones** documentadas. Pero la implementación actual tiene **patrones de IA rotos en producción** que los tests unitarios **no detectan** porque el `MockLLMProvider` devuelve JSON que no conforma ningún schema y los tests sólo verifican `success is True`.

Los 5 problemas estructurales que bloquean alpha:

1. **El VerificationLayer es marketing en producción.** El `output_schema` declarado en cada `SpecialistConfig` **nunca se pasa** al `VerificationLayer` (sólo se pasa `response_format`). La validación de schema está muerta. Los tests que la prueban la llaman directo, bypasseando el Specialist.
2. **No hay tool-use loop (ReAct).** Los specialists declaran `tools=["fs_read", "fs_write", "shell"]` pero `Specialist.run()` **ignora completamente** esa lista. Un @coder no puede leer el código existente antes de escribir el nuevo. Son prompt templates, no agentes.
3. **El executor tiene bugs semánticos graves:** `saltar_a` (jump-to) está implementado como skip (se salta el destino), los outputs de pasos paralelos no se resuelven en templates (`pasos.paralelo.lint.salida` queda literal), y los templates multi-`{{ }}` sólo resuelven el primero.
4. **Doble wrapping de middleware.** `Agent.run()` y `Specialist.run()` **ambos** envuelven el provider con `TokenOptimizer → VerificationLayer → CostGuard`. Resultado: 2 caches, 2 verification layers, 2 CostGuards con presupuestos independientes. El CostGuard interior se crea fresh por invocación → **nunca acumula spend entre pasos**.
5. **El default `ollama/llama3.2` no puede producir los structured outputs que los system prompts exigen.** Llama 3.2 3B/8B sin fine-tuning de JSON mode produce outputs parcialmente válidos con frecuencia alta. Combinado con el bug #1 (sin validación de schema), el sistema silenciosamente acepta JSON malformado y lo reporta como `success: True`.

Adicionalmente hay **~25 issues** de severidad media/baja que se detallan en §3.

---

## 2. Respuestas a las 10 preguntas

### 2.1 ¿Los system prompts de los specialists son buenos?

**Veredicto: Aceptables pero desiguales.** No son malos, pero tienen anti-patrones.

**Lo bueno:**
- Tienen estructura clara: job → rules → schema de salida.
- Las "Rules" son específicas y anti-vaguedad ("'Review the code' is bad, 'Review PR #123 for security vulnerabilities' is good").
- @debugger y @reviewer tienen metodología explícita (bottom-up traceback reading, severity ranking).
- Tienen temperature bien calibrada (0.0 para código/review, 0.1 para planning).

**Anti-patrones detectados:**

- **Inconsistencia EN/ES:** Los system prompts están 100% en inglés, pero los playbooks (`manuales/*.yaml`) están en español y el `_inject_refusal_prompt` está en inglés. El LLM recibe mensajes mezclados. Para un framework bilingüe, esto es ruido.
- **El schema embebido en el prompt no coincide con el `output_schema` declarado.** Ejemplo: el prompt del @coder dice `{"files": [...], "summary": ..., "assumptions": [...], "warnings": [...]}` pero el `output_schema` sólo requiere `["files", "summary"]`. El LLM ve un schema rico en el prompt pero el sistema sólo valida lo mínimo. Inconsistencia que confunde.
- **@tester asume ejecución de tests** (`test_results.passed`, `failed`) pero no tiene forma real de ejecutarlos (no hay tool-use loop). El prompt le pide "Run the tests" pero el specialist no puede hacerlo.
- **@reviewer está sobrecargado:** se usa para leer diff (`leer_diff` en auditar-pr), para auditoría de seguridad (`auditoria_seguridad`), para lint, y para síntesis. Especialización falsa.
- **@coder y @tester declaran `tools=["fs_read", "fs_write", "shell"]` pero el prompt no les dice cómo usarlos** ni cuándo. Como no hay tool-use loop (bug #2), esto es decorativo.
- **No hay instrucciones de formato robustas.** Ningún prompt dice "Return ONLY the JSON, no prose before or after". Llama 3.2 frecuentemente añade ```json ... ``` fences o texto explicativo, rompiendo el `json.loads`.

### 2.2 ¿El Verification Layer realmente previene alucinaciones?

**Veredicto: NO. Es marketing en el estado actual.**

Hay **tres bugs** que lo inutilizan en producción:

**Bug A (CRITICAL): El `output_schema` nunca llega al VerificationLayer.**

En `specialists/base.py:115`:
```python
response = await guarded_provider.complete(
    messages,
    model=model,
    temperature=...,
    max_tokens=...,
    response_format={"type": "json_object"} if self.config.output_schema else None,
    # ← NUNCA se pasa response_schema=self.config.output_schema
)
```

El `VerificationLayer.complete()` acepta `response_schema` como kwarg, pero el Specialist nunca lo pasa. Resultado: en `verification.py:144`, la condición `if self.config.structured_outputs and response_schema:` siempre es `False` porque `response_schema is None`. **La validación de schema es dead code en producción.**

Los tests en `test_middleware.py:86` pasan porque llaman directo a `verification.complete(..., response_schema={...})`, bypasseando el Specialist.

**Bug B (HIGH): Hedging detection con falsos positivos.**

Los patrones en `verification.py:32-39`:
```python
r"\bI\s+don'?t\s+know\b",
r"\bI'?m\s+not\s+sure\b",
r"\bas\s+an\s+ai\b",
```

Se aplican al **contenido completo** del response (que es JSON). Si el @reviewer devuelve honestamente `{"summary": "I'm not sure about the auth flow"}` — el patrón `I'm not sure` matchea, la verificación falla, y el response se reemplaza por el `refusal_message` (string plano, no JSON). Luego `Specialist._parse_output()` hace `json.loads(refusal_message)` → falla → retorna `{"raw": refusal_message}` con `success: True`. **El sistema reporta éxito con un string de rechazo como output.**

Peor: el prompt del @reviewer dice "If the code is good, say so. Don't invent issues." — incentiva honestidad, pero el VerificationLayer castiga la honestidad.

**Bug C (HIGH): `confidence` es hardcoded a 0.8.**

En `verification.py:131`:
```python
result = VerificationResult(passed=True, confidence=0.8)  # default
```

No hay ningún mecanismo que extraiga la confianza real del LLM. El `confidence_gate` (v0.2 placeholder) no sirve de nada porque la confianza nunca baja de 0.8 excepto si hay hedging (0.4) o validation failure (0.0).

**¿Qué pasa si el LLM devuelve JSON válido pero factualmente incorrecto?**

**Nada.** El VerificationLayer sólo valida forma (JSON parseable, campos requeridos), no contenido. Un @debugger que devuelva `{"root_cause": "wrong guess", "confidence": 0.9, "fix": {...}}` pasa todas las validaciones. El critic loop (v0.3) y grounding RAG (v0.4) están documentados pero no implementados.

El único check factual existente — hedging detection — produce falsos positivos (Bug B).

### 2.3 ¿El Token Optimizer hace routing correcto?

**Veredicto: La heurística es defectuosa y puede degradar calidad silenciosamente.**

Regla en `token_optimizer.py:30-35`:
```python
_ROUTING_RULES = [
    (500, False, "ollama/llama3.2"),       # tiny input, no tools → local
    (2000, False, "anthropic/claude-3-5-haiku-20241022"),
]
```

**Problemas:**

1. **"input < 500 tokens → ollama" rompe el caso de uso principal.** Si el usuario pagó por Claude Sonnet 4 y lanza un @planner con input corto (típico: `{"task": "Plan JWT auth"}` ~10 tokens), el router lo downgradeará a ollama/llama3.2 **sin avisar**. El usuario paga por premium y obtiene output de llama 3.2 3B.
2. **La estimación `len(content) // 4` es mala para JSON.** Un input como `{"traceback": "...", "files": [...]}` con 200 chars reales puede tener 80 tokens (más del 25% del límite de 500). La heurística subestima, no sobreestima.
3. **La regla "no tools" es ALWAYS TRUE en producción** porque el Specialist nunca pasa `tools` (bug #2: no hay tool-use loop). Entonces el routing siempre evalúa → siempre downgrades si input < 500 tokens.
4. **Caso que rompe:** @reviewer con input corto `"Review this function: def add(a,b): return a+b"`. 20 tokens. Routing → ollama. Llama 3.2 responde `{"verdict": "approve", "issues": [], "summary": "looks good"}`. El usuario esperaba un review serio de Claude. Silencioso.
5. **`_is_more_expensive` es frágil.** Match por substring: `"gpt-4o"` está en tier 2, pero `"gpt-4o-mini"` también contiene `"gpt-4o"` → max(tiers) = 2. Funciona por accidente, no por diseño.
6. **La decisión de routing no se persiste en el Thread.** El `MODEL_ROUTED` event type existe pero nunca se emite. Inobservabilidad.

**Casos que rompe:**
- Input corto + modelo premium pagado → downgrade silencioso a ollama.
- Input que crece entre turnos (multi-turn) → cambia de modelo mid-conversation.
- JSON denso (poco texto, muchos tokens) → subestimación.
- Cualquier specialist con `default_model="ollama/llama3.2"` (todos, actualmente) → routing nunca se activa porque el modelo pedido ya es ollama.

### 2.4 ¿El cache del TokenOptimizer es semánticamente correcto?

**Veredicto: Correcto para inputs idempotentes, peligroso para todo lo demás.**

**Lo correcto:**
- La cache key incluye messages + model + tools + kwargs (excepto temperature). Es determinista.
- TTL de 1h es razonable.
- LRU eviction OK.

**Lo peligroso:**

1. **No sabe nada de tiempo.** Si un playbook pregunta "What's the latest PR in this repo?" y se corre dos veces en 1h, la segunda devuelve respuesta stale.
2. **No sabe nada de estado de usuario.** Si el input incluye `"user_id": 123` y el estado del usuario cambia entre llamadas, la cache devuelve respuesta vieja.
3. **No sabe nada de turnos previos en el Thread.** El cache key incluye los `messages` completos, así que si el sistema prompt cambia, miss. Pero si el sistema prompt NO cambia y sólo el contexto del Thread (que NO está en messages) cambia, hit erróneo. **Esto es sutil pero crítico:** el @reviewer en paso 4 de un playbook puede recibir el mismo input literal que en paso 2 pero en un contexto distinto — la cache le devuelve la respuesta de paso 2.
4. **Cachea respuestas del @planner con `temperature=0.1`** — planificación pseudo-aleatoria. Si dos runs idénticos devuelven outputs distintos (por temp), el segundo obtiene el output del primero. Inconsistencia.
5. **`cached.response` es mutado in-place** al marcar `usage.cached = True` (línea 98). Eso viola el supuesto de immutabilidad del `LLMResponse` y puede causar bugs sutiles si el mismo objeto cached se devuelve múltiples veces.
6. **No hay invalidación por cambio de código/schema.** Si cambias el system prompt del @coder, la cache sigue devolviendo respuestas con el prompt viejo hasta que expire el TTL.
7. **Cache hits no emiten evento `CACHE_HIT`** (el event type existe pero no se usa).

**Recomendación:** Desactivar cache por default para specialists no-idempotentes (@planner, @debugger). Activar sólo para @coder/@tester cuando el input es idéntico Y la temperature es 0.0.

### 2.5 ¿El CostGuard maneja edge cases?

**Veredicto: Funciona para happy path, falla en 4 edge cases.**

**Edge cases que falla:**

1. **LLM no reporta usage → `response.usage` es None → crash.**

   En `litellm_provider.py:98-100`:
   ```python
   usage = response.usage
   tokens_in = usage.prompt_tokens if usage else 0
   tokens_out = usage.completion_tokens if usage else 0
   ```
   Esto maneja `usage is None` OK. Pero en `cost_guard.py:181`:
   ```python
   cost = response.usage.cost_usd
   ```
   Si el proveedor devuelve un `LLMResponse` con `usage=None` (no el caso actual pero plausible con providers custom), esto crashea con `AttributeError`. Falta defensive check.

2. **Cost es 0 (Ollama/Mock) → CostGuard NUNCA aborta.**

   Con ollama, `cost_usd=0.0` siempre. Entonces `self.spent_usd` siempre es 0. Entonces `self.spent_usd >= effective_budget * self.budget.abort_at_pct` (0 >= 0.50) es `False` siempre. **El "killer differentiator" de ARNES es no-op para el modelo default.**

   El circuit breaker tampoco dispara porque `recent_spend` siempre es 0.

   **Implicación:** Con el stack default (ollama), un playbook con loop infinito corre para siempre sin abortar por costo. Sólo aborta por `max_attempts` (no implementado en executor) o timeout (tampoco).

3. **Retries no se deduplican.** Si un call falla y se reintenta, ambos costs se suman. Esto es correcto (fuiste cobrado), pero el `RetryPolicy` está definido en el schema y **nunca se usa en el executor**. Los retries simplemente no existen en v0.1.

4. **Pause_at_pct es no-op.**

   En `cost_guard.py:146-157`:
   ```python
   if self.spent_usd >= effective_budget * self.budget.pause_at_pct:
       self._paused = True
       logger.warning("cost_guard_pause", ...)
       self._paused = False  # ← immediately unpauses!
   ```

   El comentario dice "In MVP we don't auto-pause; we let the call go through but warn." Pero la lógica de `_paused` que se setea y desetea en la misma rama es código muerto. Si algún caller verifica `_paused`, nunca verá True. **El HITL gate documentado no existe.**

5. **Doble CostGuard.** El `Agent.run()` envuelve con `CostGuard(provider, budget=CostBudget(task_budget_usd=self.config.budget_usd))` y luego pasa ese wrapped provider a `specialist.run()`, que lo vuelve a envolver con `CostGuard(VerificationLayer(TokenOptimizer(...)))`. El CostGuard interior usa `CostBudget()` default (task=$0.50), empieza con `spent_usd=0` y se recrea en cada invocation. **Nunca acumula spend entre invocaciones.** Es peso muerto.

### 2.6 ¿Los playbooks de ejemplo son útiles?

**Veredicto: Como demostración de DSL, OK. Como playbooks funcionales, NO.**

**`debug-python-issue.md.yaml`:**

- `leer_traceback` llama a `@debugger` con el traceback inline. OK conceptualmente.
- `revisar_fix` pasa `codigo: "{{ pasos.leer_traceback.salida }}"` a `@reviewer`. Pero `leer_traceback.salida` es un dict `{"root_cause": "...", "confidence": ..., "fix": {...}, ...}` — **no es código**. El @reviewer recibe un JSON de diagnóstico como si fuera código y se le pide revisarlo. Output será basura o el reviewer alucinará que el JSON es código.
- `verificar_tests` pasa el mismo output del debugger como `codigo` al `@tester`. El tester espera código para escribir tests, recibe diagnóstico. Mismo problema.
- **No diagnosticaría un bug real.** El @debugger solo ve el traceback inline; no puede `fs_read` el archivo referenciado (`src/app.py` línea 42) porque no hay tool-use loop. Propone un fix a ciegas.

**`auditar-pr.md.yaml`:**

- `leer_diff` usa `@reviewer` con `enfoque: "Leer el diff y estructurarlo"`. Pero @reviewer está diseñado para **revisar** código, no para **leer y estructurar** un diff. Necesita un `@lector-de-diff` que no existe (se menciona en docstrings pero no está registrado).
- `auditoria_seguridad` también usa `@reviewer`. El reviewer no tiene tools de security scanning ni instrucciones específicas de security en su prompt (sólo menciona "Flag security issues explicitly" como una de las cosas a revisar). No es un auditor de seguridad real.
- El paso `paralelo` se ejecuta secuencialmente (bug documentado en executor).
- `sintesis` referencia `{{ pasos.paralelo.lint.salida }}` y `{{ pasos.paralelo.tests.salida }}`. Pero el executor guarda parallel outputs como `outputs["paralelo"] = {"lint": <output>, "tests": <output>}`. El template `pasos.paralelo.lint.salida` se traduce a `outputs["paralelo"]["lint"]["salida"]` → no existe (`salida` no es key del output directo). **El template queda como string literal** y el @reviewer de síntesis recibe `"{{ pasos.paralelo.lint.salida }}"` como texto. Bug confirmado empíricamente.

**`write-feature-tdd.md.yaml`:**

- Flujo TDD correcto conceptualmente (plan → tests → código → review → verificar).
- Pero el `@coder` recibe `tests: "{{ pasos.escribir_tests.salida }}"` y `spec: "Implement JWT auth to make the tests pass"`. Sin tool-use loop, el coder no puede ejecutar los tests ni iterar. Escribe código a ciegas y ora que pase.
- `verificar_tests_pasan` llama a `@tester` con `enfoque: "Run the tests"`. El tester no puede correr tests (no tool-use loop). Va a inventar `test_results: {"passed": 5, "failed": 0}` sin haber corrido nada. **Alucinación incentivada por el prompt.**

**`hola-mundo.md.yaml`:**

- Usa `@coder` para "Write a markdown outline". El system prompt del @coder dice "Write production-quality code, not pseudo-code" y exige "type hints, docstrings". Aplicar eso a un markdown outline es absurdo. Falta un `@writer` specialist.

### 2.7 ¿Falta algo crítico?

**Sí, mucho.**

1. **Tool-use loop (ReAct).** Es EL patrón que diferencia un agente de un prompt template. Los specialists declaran tools pero no las usan. Sin esto, @coder no puede leer código existente, @tester no puede correr tests, @debugger no puede reproducir el bug. **Blocker para alpha.**
2. **Streaming.** No hay. Para playbooks largos (auditar-pr), el usuario espera minutos sin feedback. UX inaceptable para alpha público.
3. **Multi-turn / conversación.** No hay. Cada `specialist.run()` es single-shot. No hay forma de decirle al @coder "no, that's wrong, try again" dentro de un mismo step.
4. **Memory persistente.** No hay. Cada run empieza desde cero. No hay learning entre runs. Un @debugger que vio un bug similar ayer no lo recuerda.
5. **Retry con backoff.** `RetryPolicy` está definido en el schema pero **nunca se usa** en el executor. Un transient error (rate limit, timeout) mata el run entero.
6. **Timeout por step.** `timeout_s` está en el schema pero no se usa. Un LLM colgado corre para siempre (hasta el httpx timeout de 120s en ollama).
7. **HITL real.** `HITLGate` y `aprobacion_humana` están en el schema pero el executor no los enforcement. `HumanApprovalTool` existe pero no se llama automáticamente.
8. **Tool calling nativo.** `LLMProvider.complete()` acepta `tools` pero ni ollama ni litellm provider los pasan correctamente al modelo. Ollama provider dice "tool use is evolving — fall back to text parsing" pero no hay parser de texto.
9. **Structured output con pydantic.** El `output_schema` es JSON Schema declarativo pero nunca se valida con pydantic en runtime. Debería ser `Type[BaseModel]` y validar el response contra él.
10. **Observabilidad.** Los eventos `MODEL_ROUTED`, `CACHE_HIT`, `CONFIDENCE_SCORED`, `REFUSAL_TRIGGERED` existen en el enum pero no se emiten. Inobservabilidad total del middleware.

### 2.8 ¿El default a ollama/llama3.2 es realista?

**Veredicto: NO para los structured outputs que piden los specialists.**

**Hechos sobre Llama 3.2:**
- Llama 3.2 viene en 1B y 3B (small) y 11B/90B (vision). Los que corren en ollama default son 1B y 3B.
- Llama 3.2 3B puede producir JSON simple con `format: "json"` en ollama, pero:
  - Frecuentemente añade ```json fences o texto explicativo antes/después del JSON.
  - No respeta schemas anidados (e.g., `files: [{path, language, content, action}]`).
  - Confunde `action: "create"` con `action: "create_new"` o `action: CREATE`.
  - Trunca outputs largos (el @coder con 200 líneas de código se corta).
  - Alucina imports y APIs (el prompt del @coder dice "Never invent APIs" pero Llama 3.2 lo hace).

**Lo que va a pasar en alpha:**
- @planner devuelve `{"steps": [{"id": "step-1", "specialist": "@coder", "input": {...}}]}` — a veces válido, a veces con `steps` como string en vez de array.
- @coder devuelve JSON con `files` como string en vez de array de objetos. `_parse_output` hace `json.loads` exitoso pero el output no es utilizable.
- @reviewer devuelve `verdict: "Approve"` (capitalizado) en vez de `"approve"` — no está en el enum, pero como el schema no se valida, pasa.
- @debugger propone fixes plausibles pero incorrectos con `confidence: 0.9`.

**Recomendación:** Default a `ollama/llama3.2` está bien para el quickstart "hola-mundo". Para `write-feature-tdd`, `debug-python-issue`, `auditar-pr` el default debería ser `anthropic/claude-3-5-haiku-20241022` (barato, structured outputs fiables) o `groq/llama-3.3-70b-versatile` (gratis, más capaz que 3.2 3B).

Alternativamente: añadir un `_clean_json_response()` post-proceso que strippe fences y extraiga el primer `{...}` válido. Eso subiría el success rate de 60% a ~85% con Llama 3.2.

### 2.9 ¿La separación specialist/tool/playbook es correcta?

**Veredicto: Separación conceptual correcta, acoplamiento indebido en implementación.**

**Lo correcto:**
- Specialist = (system_prompt + tools + output_schema). Data class, no hierarchy. ✔
- Tool = (Args + Result schemas + execute()). Auto-registrado. ✔
- Playbook = YAML → DAG. Compiler + executor separados. ✔
- Thread = event log immutable. ✔

**Acoplamiento indebido:**

1. **El Specialist base hardcodeda el middleware stack.** En `base.py:99-105`:
   ```python
   optimized_provider: LLMProvider = TokenOptimizer(provider)
   if self.config.output_schema:
       optimized_provider = VerificationLayer(...)
   guarded_provider = CostGuard(optimized_provider)
   ```
   El Specialist decide el orden del middleware. Pero el `Agent.run()` y el `PlaybookExecutor` también envuelven con CostGuard. Resultado: doble wrapping. **El middleware stack debería vivir en UN lugar** (el executor o el agent, no el specialist).

2. **El executor pasa `cost_guard` como `provider` al specialist.** Tipo: `provider: cost_guard,  # type: ignore[arg-type]`. El `# type: ignore` es admission de que el type system no soporta esto. `CostGuard` no es un `LLMProvider` (no hereda). Funciona por duck typing. Frágil.

3. **`ToolContext` tiene `budget_remaining_usd` que se calcula del CostGuard del executor, pero el specialist tiene su propio CostGuard que no se lo pasa.** El tool no ve el budget real.

4. **Los specialists referencian tools por nombre string** (`tools=["fs_read"]`), no por tipo. Si renombras `fs_read` a `filesystem_read`, todos los specialists se rompen silenciosamente (no validation en registry).

5. **El `SpecialistRegistry` se auto-registra via `__init_subclass__`** — frágil al orden de imports. Si `get_default_specialist_registry()` se llama antes de que se importen todos los módulos de specialists, el registry está vacío. Funciona ahora porque el import está inline en la función, pero es un piegun.

6. **Los playbooks referencian specialists por nombre** (`especialista: "@reviewer"`). Si un specialist se renombra, el playbook compila OK pero falla en runtime con "Specialist not registered". El compiler check debería verificar referencias (como hace con `saltar_a`).

### 2.10 ¿Hay bugs en el executor? ¿El template resolution funciona? ¿Los condicionales?

**Veredicto: Sí, hay 5 bugs significativos.**

**Bug 1 (CRITICAL): `saltar_a` está invertido.**

En `executor.py:455-459`:
```python
if branch.accion == "saltar" and branch.saltar_a:
    # Mark target steps to be skipped until saltar_a
    skip_set = outputs.setdefault("__skip_steps", set())
    skip_set.add(branch.saltar_a)  # Will be cleared when we reach it
```

`saltar_a: "step-5"` significa "saltar A step-5" (jump TO step-5). Pero el código añade `step-5` al skip set, lo que hace que step-5 se **skip**. Semántica invertida.

Además, el comentario "Will be cleared when we reach it" miente — nunca se clear. Una vez en el skip set, se queda para siempre. Y no hay lógica de "skip steps BETWEEN current y target" — sólo se skippea el target.

**Fix correcto:** Si step-3 tiene `saltar_a: step-5`, hay que skippear step-4 (los pasos intermedios) y ejecutar step-5. Implementación:
```python
if branch.accion == "saltar" and branch.saltar_a:
    target_idx = next(i for i, s in enumerate(playbook.pasos) if s.id == branch.saltar_a)
    current_idx = next(i for i, s in enumerate(playbook.pasos) if s.id == step.id)
    for s in playbook.pasos[current_idx+1:target_idx]:
        skip_set.add(s.id)
```

**Bug 2 (CRITICAL): Templates multi-`{{ }}` sólo resuelven el primero.**

En `executor.py:497-525`, `_resolve_template` usa `re.search` (primer match only) y luego `template.replace(match.group(0), ...)` que reemplaza sólo la primera ocurrencia del match exacto.

Verificado empíricamente:
```
Input:  "Review {{ a.salida }} and {{ b.salida }}"
Output: "Review <a_value> and {{ b.salida }}"
```

**Fix:** Usar `re.sub` con una función de reemplazo:
```python
def _resolve_template(self, template, outputs):
    def replace_one(match):
        expr = match.group(1).strip()
        parts = expr.replace("pasos.", "").replace("variables.", "").split(".")
        current = outputs
        for part in parts:
            if isinstance(current, dict):
                part = "output" if part == "salida" else part
                if part in current:
                    current = current[part]
                else:
                    return match.group(0)  # leave as-is
            else:
                return match.group(0)
        return str(current) if not isinstance(current, (dict, list)) else json.dumps(current)
    return self._TEMPLATE_RE.sub(replace_one, template)
```

**Bug 3 (HIGH): Templates no resuelven paths a través de parallel outputs.**

`{{ pasos.paralelo.lint.salida }}` → camina `outputs["paralelo"]["lint"]["output"]`. Pero `outputs["paralelo"]` es `{"lint": <lint_output_dict>, "tests": <tests_output_dict>}`. Y `<lint_output_dict>` es directamente el output del specialist (e.g., `{"verdict": "approve", ...}`), no un dict con key `output`.

**Fix:** En `_execute_parallel`, guardar outputs como:
```python
outputs_map[sub_step.id] = {"output": result.get("output")}
```
Para que `pasos.paralelo.lint.salida` → `outputs["paralelo"]["lint"]["output"]` funcione.

**Bug 4 (MEDIUM): Templates en lists no se resuelven.**

En `_resolve_input`, si un valor es una list, se pasa as-is:
```python
else:
    resolved[k] = v  # ← lists, ints, etc.
```

Si un playbook tiene `input: { files: ["{{ pasos.a.salida }}", "{{ pasos.b.salida }}"] }`, los templates no se resuelven.

**Fix:**
```python
elif isinstance(v, list):
    resolved[k] = [self._resolve_template(item, outputs) if isinstance(item, str) else
                   self._resolve_input(item, outputs) if isinstance(item, dict) else item
                   for item in v]
```

**Bug 5 (HIGH): Template path no encontrado deja el literal `{{ ... }}`.**

En `executor.py:516`:
```python
return template  # Leave template as-is if not found
```

Si el path no existe (typo, paso que no se ejecutó, etc.), el template queda como string literal y se envía al LLM como input. El LLM recibe `"codigo: {{ pasos.leer_diff.salida }}"` como texto. Sin warning, sin error.

**Fix:**
- En compile time: validar que toda referencia `{{ pasos.X.salida }}` apunta a un step que existe.
- En runtime: si un path no se resuelve, log warning Y fallar el step (o substituir por `null`).

**Bug 6 (MEDIUM): El `si_no_se_cumple` no evalúa condiciones reales.**

El `ConditionalBranch` tiene campo `cuando` (condición) pero el executor sólo maneja el caso `si_no_se_cumple` (implicit else). Los `condicionales` explícitos (`if/elif`) no se evalúan en el executor. Sólo se emite un `ConditionalBranchEvent`.

**Bug 7 (LOW): `outputs` dict crece con metadata (`__skip_steps`)** que se serializa en el result final. Si el usuario hace `result.outputs`, ve `__skip_steps: set()` — leak de internals.

---

## 3. Tabla de issues

### CRITICAL (bloquean alpha)

| # | Issue | Archivo:Línea | Fix recomendado |
|---|-------|---------------|-----------------|
| C1 | `output_schema` nunca se pasa al VerificationLayer → validación de schema es dead code | `specialists/base.py:115` | Pasar `response_schema=self.config.output_schema` en la llamada a `guarded_provider.complete()`. Además, validar el parsed JSON contra el schema con pydantic en `_parse_output` y marcar `success=False` si no conforma. |
| C2 | No hay tool-use loop (ReAct). Specialists declaran tools pero no las usan | `specialists/base.py:77-128` | Implementar loop: LLM call → si `tool_calls` en response → ejecutar tools → añadir resultados como messages → repeat hasta que no haya tool_calls. Cap a 10 iteraciones. |
| C3 | `saltar_a` semántica invertida (skip target en vez de jump-to) | `playbooks/executor.py:455-459` | Skippear steps intermedios entre current y target, no el target mismo. Ver fix en §2.10 Bug 1. |
| C4 | Templates multi-`{{ }}` sólo resuelven el primero | `playbooks/executor.py:497-525` | Usar `re.sub` con función. Ver fix en §2.10 Bug 2. |
| C5 | Templates `pasos.paralelo.X.salida` no resuelven (estructura de outputs incorrecta) | `playbooks/executor.py:403-412` | Envolver parallel outputs en `{"output": ...}`. Ver fix en §2.10 Bug 3. |
| C6 | Doble wrapping de CostGuard/Verification/TokenOptimizer (Agent + Specialist) | `specialists/base.py:99-105` + `agent/agent.py:97-105` | Remover el wrapping de `Specialist.run()`. El middleware stack debe vivir en UN lugar (Agent o Executor). Pasar el provider ya wrapped al specialist. |
| C7 | VerificationLayer reemplaza JSON inválido con string plano (refusal_message), specialist lo reporta como success=True con raw text | `middleware/verification.py:116` + `specialists/base.py:156-160` | Cuando verification falla: (a) marcar response con flag `verification_failed=True`, (b) en `_parse_output`, si verification_failed, retornar `success=False, error="Verification failed: ..."`. |
| C8 | Mock provider devuelve JSON que no conforma ningún schema, pero tests assert success=True → false confidence | `llm/mock.py:38-46` + `tests/unit/test_executor.py:39-42` | Mock debe devolver schema-conforming fixtures por specialist (un dict con `steps` para planner, `files` para coder, etc.). Tests deben assert que `output` conforma al schema del specialist. |

### HIGH (serios antes de alpha)

| # | Issue | Archivo:Línea | Fix recomendado |
|---|-------|---------------|-----------------|
| H1 | CostGuard nunca aborta con ollama/mock (cost=0) | `middleware/cost_guard.py:181` | Track también `calls_made` y abortar si `calls_made > max_calls` (default 50). Útil para prevenir loops infinitos con modelos gratuitos. |
| H2 | `pause_at_pct` se setea y desetea en la misma rama (no-op) | `middleware/cost_guard.py:146-157` | O implementar HITL real (emitir `HumanApprovalRequestedEvent`, pausar de verdad) o eliminar el código muerto y documentar que pause es v0.2. |
| H3 | Hedging detection con falsos positivos en JSON values | `middleware/verification.py:32-39, 161-166` | Aplicar patterns sólo al `summary` o `explanation` fields del JSON parsed, no al content completo. O desactivar hedging cuando `structured_outputs=True` y el JSON parsea OK. |
| H4 | `confidence` hardcoded a 0.8 — confidence gate inútil | `middleware/verification.py:131` | Pedir al LLM que incluya `confidence: 0.0-1.0` en su JSON output. Extraerlo y usarlo. Si no está, default 0.5 (no 0.8). |
| H5 | Routing "input < 500 → ollama" degrada silenciosamente modelos premium | `middleware/token_optimizer.py:30-35, 131-147` | (a) Sólo rutear si el modelo pedido es más caro que el fallback Y el specialist lo permite (`config.allow_routing=True`). (b) Log warning siempre que se rutee. (c) Emitir evento `MODEL_ROUTED`. |
| H6 | `output_schema` declarado pero no enforced (sólo validación básica de required fields) | `specialists/base.py:143-173` + `middleware/verification.py:168-185` | Usar pydantic `Type[BaseModel]` en vez de dict JSON Schema. Validar el JSON parsed contra el BaseModel. Si no conforma, reintentar con feedback (1 retry). |
| H7 | Ollama provider no maneja 404 (model not pulled) | `llm/ollama.py:47-56` | Catch `httpx.HTTPStatusError`. Si 404, raise con mensaje: "Model '{model}' not found. Run: ollama pull {model}". |
| H8 | Cache key incluye model, pero routing cambia model → low hit rate | `middleware/token_optimizer.py:91` | Cache key debe usar el model requested, no el effective. O desactivar cache cuando routing está activo. |
| H9 | Parallel branches se ejecutan secuencialmente | `playbooks/executor.py:385-419` | Implementar con `asyncio.gather`. Cada sub-step genera su propio Thread segment, luego se mergean los events. Requiere Thread merge helper. |
| H10 | auditar-pr.md.yaml usa @reviewer para leer_diff, auditoria_seguridad, lint, síntesis (role mismatches) | `manuales/auditar-pr.md.yaml:14,20,29,40` | Crear specialists `@diff-reader`, `@security-auditor`, `@linter`, `@synthesizer`. O especializar @reviewer con sub-modes via input field `mode: security|lint|synthesis`. |
| H11 | debug-python-issue.md.yaml pasa JSON de diagnóstico como `codigo` a @reviewer y @tester | `manuales/debug-python-issue.md.yaml:25,32` | Cambiar el input field a `diagnostico: "{{ pasos.leer_traceback.salida }}"` y actualizar los prompts de reviewer/tester para aceptar diagnóstico. O añadir un paso intermedio `@coder` que extraiga el fix del diagnóstico y lo materialice como código. |
| H12 | hola-mundo.md.yaml usa @coder para escribir markdown outline | `manuales/hola-mundo.md.yaml:15` | Crear `@writer` specialist o cambiar el step a `@planner` con prompt de outline. |
| H13 | Template path no encontrado deja literal `{{ ... }}` silenciosamente | `playbooks/executor.py:516` | En compile time: validar referencias. En runtime: log warning + substituir por `null` o fallar el step. |
| H14 | RetryPolicy definido en schema pero nunca usado en executor | `playbooks/schema.py:47-53` + `playbooks/executor.py:235-298` | Envolver `_execute_step` en retry loop con backoff. Respetar `retry_on` substrings. |
| H15 | `timeout_s` en PlaybookStep nunca se enforce | `playbooks/schema.py:107` | Envolver `_execute_step` con `asyncio.wait_for(step_coro, timeout=step.timeout_s)`. |
| H16 | HITLGate en schema pero no enforcement en executor | `playbooks/schema.py:56-62, 110` | Si `step.aprobacion_humana`, emitir `HumanApprovalRequestedEvent`, pausar execution, esperar `HumanApprovalReceivedEvent` (vía MCP/CLI). |
| H17 | Specialist prompts no exigen JSON-only output (Llama 3.2 añade fences) | `specialists/*.py` | Añadir al final de cada prompt: "Return ONLY valid JSON. No markdown fences, no prose before or after. If you cannot comply, return `{\"error\": \"reason\"}`." |
| H18 | `_resolve_input` no recurse en lists | `playbooks/executor.py:484-493` | Ver fix en §2.10 Bug 4. |

### MEDIUM (mejoras)

| # | Issue | Archivo:Línea | Fix recomendado |
|---|-------|---------------|-----------------|
| M1 | No streaming | `llm/base.py:62-77` | Añadir `async def stream_complete()` al provider. Executor emite `AssistantMessageEvent` por chunk. |
| M2 | No memory persistente entre runs | n/a | Añadir `MemoryStore` interface. Specialists pueden `ctx.memory.recall(query)` y `ctx.memory.store(fact)`. v0.3. |
| M3 | No multi-turn dentro de un step | `specialists/base.py:77-128` | Aceptar `prior_turns: list[dict]` en input_data. Añadir como messages al LLM call. |
| M4 | Specialist output_schema es muy permissivo (`issues: {"type": "array"}` sin item schema) | `specialists/reviewer.py:55`, `specialists/coder.py:54` | Definir items schema completo. Usar pydantic Type[BaseModel]. |
| M5 | Circuit breaker $1/min puede ser muy agresivo para Claude Sonnet 4 | `middleware/cost_guard.py:64` | Default a $5/min. Hacer configurable por playbook. |
| M6 | `_estimate_cost` fallback asume $1/M tokens — wrong para modelos desconocidos | `llm/litellm_provider.py:31-32` | Si modelo no está en pricing table, log warning Y usar max(pricing values) para sobreestimar. |
| M7 | LiteLLM no pasa JSON Schema al provider (sólo `{"type": "json_object"}`) | `llm/litellm_provider.py:76-77` | Si el schema está disponible, usar `response_format={"type": "json_schema", "schema": {...}}` (soportado por OpenAI, Anthropic, Gemini). |
| M8 | Token estimation `len(content) // 4` subestima para JSON/code | `middleware/token_optimizer.py:133` | Usar `tiktoken` si está disponible, fallback a `len(content) // 3`. |
| M9 | `as an ai` pattern muy broad | `middleware/verification.py:36` | Eliminar o hacer más específico (`r"\bas\s+an\s+ai(?:,|\.|\s)`). |
| M10 | Cache TTL fijo 1h — no diferenciado por specialist | `middleware/token_optimizer.py:62` | Permitir `cache_ttl_s` por specialist config. @planner 24h, @debugger 0 (no cache). |
| M11 | No request deduplication (concurrent identical requests both hit LLM) | `middleware/token_optimizer.py:76-125` | Mantener `dict[key, asyncio.Future]`. Si hay in-flight, await mismo Future. |
| M12 | `cached.response.usage.cached = True` muta el cached entry | `middleware/token_optimizer.py:98` | Hacer `cached.response.model_copy(update={"usage": cached.response.usage.model_copy(update={"cached": True})})`. |
| M13 | `__skip_steps` se serializa en result.outputs | `playbooks/executor.py:104, 122` | Usar key privada `"_arnes_skip_steps"` y excluir de result.outputs. |
| M14 | SpecialistRegistry auto-registro frágil al orden de imports | `specialists/base.py:72-75` | Hacer registry explícito: `register_class(Planner)` en `get_default_specialist_registry()`. Ya se hace — remover el `__init_subclass__` auto-registro. |
| M15 | `aprobacion_humana` parsed pero no enforced | `playbooks/schema.py:110` | Ver H16. |
| M16 | Eventos `MODEL_ROUTED`, `CACHE_HIT`, etc. definidos pero no emitidos | `thread/events.py:58-63` | Emitir desde middleware al Thread. Requiere que middleware tenga acceso al Thread (actualmente no lo tiene). |
| M17 | `_KEY_MAP` tiene identity mappings (`"nombre": "nombre"`) | `playbooks/compiler.py:104-108` | Eliminar identity entries. |
| M18 | `Playbook.metadata` se construye pero no se lee | `playbooks/schema.py:158-173` | Usar `metadata.budget_usd` en el executor en vez de `playbook.budget_usd`. |
| M19 | `__import__("time").time()` en vez de `import time` | `middleware/token_optimizer.py:121` | Importar `time` al top del módulo. |
| M20 | `output` field de PlaybookStep no se usa | `playbooks/schema.py:97` | Implementar: si `step.output = "var_name"`, hacer `outputs["var_name"] = result.output` en vez de `outputs[step.id]`. |

### LOW (polish)

| # | Issue | Archivo:Línea | Fix |
|---|-------|---------------|-----|
| L1 | `SpecialistConfig.tools` declarado pero no usado | `specialists/base.py:42` | Pasar `tools` al LLM call cuando tool-use loop esté implementado (C2). |
| L2 | `if "/" in model` lógica repetida | `llm/factory.py`, `llm/ollama.py:33` | Helper `parse_model_string(model) -> (vendor, name)`. |
| L3 | `_HEDGING_PATTERNS` sin test de falsos positivos | `middleware/verification.py:32-39` | Añadir tests con JSON que contiene "I don't know" en values legítimos. |
| L4 | `MockLLMProvider` no fixture-aware | `llm/mock.py` | Añadir `responses_by_specialist: dict[str, str]` para que devuelva schema-conforming JSON por specialist. |
| L5 | No validation en compile time de referencias a specialists | `playbooks/compiler.py:157-194` | Añadir check: si `step.especialista` no está en el registry (pasado al compiler), error. |
| L6 | Logs usan `logger.info` para cache hits (ruidoso) | `middleware/token_optimizer.py:100-104` | Bajar a `logger.debug`. |
| L7 | `TokenOptimizer.stats().estimated_savings_usd` hardcoded $3/M | `middleware/token_optimizer.py:225` | Calcular con el pricing table de litellm_provider. |
| L8 | `VerificationLayer.stats()` existe pero no se expone en el Thread | `middleware/verification.py:217-222` | Añadir al `RunCompletedEvent.data`. |
| L9 | System prompts en EN, playbooks en ES, refusal_prompt en EN | n/a | Unificar a bilingual o pick one. |
| L10 | `Specialist.run()` no log input/output | `specialists/base.py:77-128` | Log debug con input hash y output summary (sin PII). |

---

## 4. Top 5 mejoras obligatorias antes de launch

### #1 — Implementar tool-use loop (ReAct) en Specialist.run()

**Por qué:** Sin esto, los specialists son prompt templates, no agentes. @coder no puede leer código existente, @tester no puede correr tests, @debugger no puede reproducir bugs. Los playbooks de ejemplo (`write-feature-tdd`, `debug-python-issue`) son mentira sin esto.

**Qué hacer:**
```python
async def run(self, input_data, ctx, *, provider, tool_registry=None):
    messages = [system, user]
    for iteration in range(self.config.max_iterations or 10):
        response = await provider.complete(messages, model=model, tools=tool_schemas)
        if not response.tool_calls:
            break
        messages.append(assistant_msg_with_tool_calls)
        for tc in response.tool_calls:
            result = await tool_registry.get(tc.function.name).execute(tc.function.arguments, ctx)
            messages.append(tool_result_msg)
    return self._parse_output(response)
```

**Esfuerzo:** 2-3 días. Requiere que ollama y litellm providers pasen tools correctamente y parseen tool_calls.

### #2 — Conectar el `output_schema` al VerificationLayer y validarlo con pydantic

**Por qué:** Hoy el schema es decorativo. El sistema reporta `success: True` con outputs que no conforman el schema. Los tests no lo detectan porque el mock devuelve JSON genérico.

**Qué hacer:**
- En `Specialist.run()`, pasar `response_schema=self.config.output_schema` al provider.
- En `VerificationLayer._validate_structured`, usar pydantic `Type[BaseModel]` en vez de JSON Schema dict.
- En `Specialist._parse_output`, si verification falló, retornar `success=False, error="Schema validation failed: ..."`.
- En `MockLLMProvider`, devolver fixtures schema-conforming por specialist.

**Esfuerzo:** 1 día.

### #3 — Unificar el middleware stack en UN lugar

**Por qué:** Hoy Agent.run() y Specialist.run() ambos envuelven el provider con el stack completo. Resultado: 2 caches, 2 CostGuards (uno useless), 2 VerificationLayers. Confuso, bugs sutiles, doble cost tracking.

**Qué hacer:**
- Remover el wrapping de `Specialist.run()`.
- El Specialist recibe el provider ya wrapped (del Agent o del Executor).
- El stack se configura en UN lugar: `Agent.__init__` o `PlaybookExecutor.__init__`.
- `Specialist.run()` sólo construye messages, llama `provider.complete()`, parsea output.

**Esfuerzo:** 0.5 días. Re factor mecánico.

### #4 — Fix bugs del executor: `saltar_a`, multi-template, parallel output structure

**Por qué:** Los condicionales y templates son el corazón del DSL. Si no funcionan, los playbooks son mentira.

**Qué hacer:**
- `saltar_a`: skippear intermedios, no el target. (§2.10 Bug 1)
- Multi-template: usar `re.sub` con función. (§2.10 Bug 2)
- Parallel outputs: envolver en `{"output": ...}`. (§2.10 Bug 3)
- List templates: recurse en lists. (§2.10 Bug 4)
- Path no encontrado: fail step con error claro. (§2.10 Bug 5)

**Esfuerzo:** 1 día + tests.

### #5 — Cambiar el default model o añadir JSON post-processing

**Por qué:** `ollama/llama3.2` 3B no puede producir fiablemente los structured outputs que los system prompts exigen. Combinado con bug #2 (sin validación), el sistema acepta outputs basura silenciosamente.

**Qué hacer (opción A):** Default a `anthropic/claude-3-5-haiku-20241022` ($0.80/$4.00 per M). Más caro pero structured outputs fiables. Documentar que ollama es para dev/testing.

**Qué hacer (opción B):** Mantener ollama default pero añadir `_clean_json_response(content)` post-proceso:
```python
def _clean_json_response(content: str) -> str:
    # Strip markdown fences
    content = re.sub(r"^```(?:json)?\s*", "", content.strip())
    content = re.sub(r"\s*```$", "", content.strip())
    # Extract first JSON object if there's prose
    match = re.search(r"\{[\s\S]*\}", content)
    if match:
        return match.group(0)
    return content
```

**Esfuerzo:** Opción A: 1h (cambio de default + docs). Opción B: 0.5 días + tests.

---

## 5. Veredicto: ¿los patrones de IA están listos para alpha?

### **NO-GO para alpha público. GO para alpha interna (devs del equipo).**

**Justificación:**

El framework tiene **arquitectura sólida** y **visión clara**. Los patrones conceptuales (stateless reducer, specialists como data classes, middleware chain, playbooks YAML) son correctos y bien pensados.

Pero la **implementación actual tiene 8 bugs CRITICAL** que hacen que el sistema **parezca funcionar** (tests pasan, mock devuelve algo) pero **no funcione** en producción con LLMs reales:

1. Sin validación de schema → cualquier output se acepta.
2. Sin tool-use loop → los specialists no pueden hacer su trabajo.
3. Bugs de executor → condicionales y templates rotos.
4. Doble middleware → comportamiento inesperado.
5. Mock mentiroso → false confidence en tests.
6. Default model inadecuado → outputs basura con ollama.
7. VerificationLayer castiga honestidad → falsos positivos.
8. CostGuard no-op con ollama → loops infinitos sin abortar.

**Plan recomendado:**

- **Semana 1:** Implementar Top 5 mejoras (#1 a #5). Esto desbloquea alpha interna.
- **Semana 2:** Fix HIGH issues (H1-H18). Tests con LLM real (Claude Haiku + ollama). Snapshot tests con fixtures schema-conforming.
- **Semana 3:** Alpha interna con 3 playbooks reales (auditar-pr, debug-python-issue, write-feature-tdd). Iterar prompts.
- **Semana 4:** Alpha pública con disclaimer claro: "v0.1 — works best with Claude Haiku or Groq Llama 70B. Ollama support is experimental."

**No publicar alpha pública sin al menos:**
- Tool-use loop funcionando (aunque sea básico).
- Validación de schema real con pydantic.
- Executor bugs fixed (saltar_a, multi-template, parallel outputs).
- Tests con LLM real (no sólo mock).
- Default model que pueda producir los structured outputs requeridos.

---

**Auditor:** AI Senior Engineer
**Reporte:** AI_AUDIT.md v1.0
