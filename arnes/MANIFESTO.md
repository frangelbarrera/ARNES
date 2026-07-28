# Manifiesto ARNES

> *El arnés, no el caballo.*
> *The harness, not the horse.*

Los marcos de agentes de hoy te piden tres cosas: que abstraigas tu lógica detrás
de clases opacas, que dependas de un proveedor de LLM, y que traces con funciones
mágicas que no puedes debuggear. A cambio te ofrecen "productividad". Lo que
entregan es deuda.

Un agente no debería ser una caja negra. Tus prompts, tu contexto, tu decisión de
modelo, tu dinero — todo eso debería ser visible, sustituible y tuyo.

ARNES no es un framework. Es un **arnés**: el equipo que te conecta a un motor
potente sin soltar las riendas. Diseñado para que puedas leer cada llamada,
cambiar de proveedor en una línea, y razonar sobre tu sistema como lo haces con
cualquier código procedural.

Creemos que la era de los agentes será escrita por desarrolladores que se rehúsan
a ceder control. Que eligen verbos sobre magia. Que prefieren 50 líneas que
entienden sobre 5 líneas que no.

ARNES nació al sur del Ecuador, donde hacer más con menos no es estética: es
supervivencia.

---

**Control the agent. Don't worship it.**
**Controla el agente. No lo adores.**

---

## Diez declaraciones que no vamos a romper

1. **ARNES no expone como APIs de primera clase features que solo existen en un vendor.**
   Si solo existe en OpenAI o solo en Anthropic, es un leak, no una feature.

2. **ARNES nunca va a tener una clase llamada `Runnable`, `Chain`, `Workflow` o `Agent`.**
   Composición = funciones. La herencia es deuda.

3. **ARNES trae un contador de tokens por defecto.**
   Si no sabés qué gastaste, no shippeaste.

4. **ARNES nunca va a tener una versión hosted.**
   El día que hosteemos, perdemos el derecho moral de argumentar contra el lock-in.

5. **ARNES no optimiza para "time to hello world".**
   Optimiza para "time to I understand this codebase".

6. **ARNES no esconde el prompt del LLM.**
   Cada prompt que se envía es un archivo en disco que puedes abrir, diffear y versionar.

7. **ARNES no tiene magia.**
   Si una línea hace algo que no entiendes, es un bug. Repórtalo.

8. **ARNES no va a soportar vendors que no permitan structured outputs.**
   Si tu modelo no puede devolver JSON válido, no es un modelo para producción.

9. **ARNES no te va a pedir nunca tu API key.**
   Las API keys viven en tu entorno. ARNES las lee, no las almacena.

10. **ARNES va a morir antes que cambiar el manifesto.**
    Si algún día rompemos una de estas líneas, es porque ARNES dejó de ser ARNES.

---

*Manifiesto v1.0 — Fijado el primer commit. Inmutable.*
