# Security Policy

## Versiones soportadas

ARNES sigue versionado semántico. Solo la última versión minor recibe
actualizaciones de seguridad.

| Versión | Soporte de seguridad |
|---------|---------------------|
| 0.1.x   | ✅ Activo            |
| < 0.1   | ❌ No soportado      |

## Reportar una vulnerabilidad

**NO abras un issue público de GitHub para reportar vulnerabilidades de
seguridad.**

ARNES utiliza la funcionalidad de
[GitHub Security Advisories](https://github.com/frangelbarrera/ARNES/security/advisories/new)
para recibir reportes privados de vulnerabilidades.

### Proceso

1. **Reporta** vía [GitHub Security Advisory privado](https://github.com/frangelbarrera/ARNES/security/advisories/new)
   o email a `security@arnes.dev`.
2. **Acknowledge**: respondemos en <72 horas confirmando recepción.
3. **Investigación**: te mantendremos informado del progreso cada 7 días.
4. **Fix**: si la vulnerabilidad es válida, publicamos un patch en <30 días
   (o un workaround inmediato si el fix es complejo).
5. **Divulgación**: publicamos advisory público en GitHub + CVE si aplica.
6. **Crédito**: te damos crédito en el advisory (a menos que prefieras
   permanecer anónimo).

## Scope de seguridad

ARNES ejecuta código (vía tools `shell`, `fs_write`) y llama APIs externas.
Cualquier issue que permita:

- Ejecución de código arbitrario fuera del sandbox
- Filtración de API keys, tokens o secrets
- Bypass de CostGuard (denial-of-wallet)
- Bypass de verification layer (alucinaciones forzadas)
- Path traversal en tool `fs_*`
- SSRF en tool `http`
- Prompt injection persistente que sobreviva entre sesiones

es una vulnerabilidad de seguridad y debe ser reportada privadamente.

## Medidas de seguridad implementadas

### Sandbox de ejecución (Tier 1 dev-local default)

ARNES ejecuta tools de código en contenedores Docker hardened:

```bash
docker run --rm \
  --security-opt=no-new-privileges \
  --cap-drop=ALL \
  --network=none \
  --read-only \
  --tmpfs /workspace:size=100M \
  arnes-sandbox:latest
```

### Secret broker

Las API keys **nunca** entran en el context window del LLM. ARNES las lee
del entorno y las inyecta just-in-time en las llamadas HTTP. El agente solo
ve `<api_key_set: true>`.

### Input validation

Todas las tools aceptan inputs validados por pydantic schemas. Las tools
`fs_read`/`fs_write` validan paths contra allowlist. Las tools `http`
validan URLs contra SSRF blacklist (localhost, 169.254.169.254, etc.).

### Cost Guard

Cada run tiene un budget USD declarado. Al exceder 95%, ARNES pausa y pide
aprobación humana. Al exceder 100%, ARNES aborta. Circuit breaker temporal:
si el gasto excede $X/minuto, aborta inmediatamente.

### Audit log

Cada llamada al LLM, cada tool execution, cada decisión de CostGuard se
loguea en la bitácora markdown. La bitácora es auditable y re-ejecutable.

## Agradecimientos

Agradecemos a quienes reportan vulnerabilidades responsablemente. Lista de
reportes en [SECURITY_CREDITS.md](SECURITY_CREDITS.md).
