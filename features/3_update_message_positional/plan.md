# Plan v2 — `update_message()` posicional con allowlist (#64)

> Estado: **v2, reescrito tras revisión adversarial**. La v1 fue **RECHAZADA** por el revisor
> adversarial (Codex, informe en `adversarial-codex.md`), que verificó sus afirmaciones contra
> MongoDB 8.2.7 real. Este plan acota el alcance a lo que está **demostrado**.
> Issue: https://github.com/iguinea/mongodb-session-manager/issues/64 — sub-issue de #56.
> Rama: `update_message-puede-sobrescribir-el-mensaje-equ`.

---

## 0. Qué cambia respecto a la v1, y por qué

El adversarial tumbó tres premisas. Las tres se verificaron **también** de forma independiente
antes de reescribir esto:

| Premisa de la v1 (y de la issue) | Veredicto | Evidencia |
|---|---|---|
| «Un turno concurrente desplaza el índice leído» | **FALSA** en la práctica | El único operador de array sobre `messages` en todo `src/` es `$push` al final (`mongodb_session_repository.py:505`). No hay `$pull`, `$pop`, `$position` ni reordenación: un append no mueve los índices ya leídos. El adversarial ejecutó el escenario 50 veces sobre el código actual: 50/50 correctas |
| «`message_id` identifica un elemento» | **FALSA** | Strands calcula el siguiente ID **en memoria**: `next_index = latest_agent_message.message_id + 1` (`RepositorySessionManager.append_message`). Dos managers sobre el mismo agente pueden hacer `$push` del mismo ID, y el posicional `$` solo toca **el primero** que casa |
| «`arrayFilters` tiene soporte desigual en DocumentDB» | **FALSA** | La matriz oficial de AWS marca `$[<identifier>]` soportado en 3.6, 4.0, 5.0, 8.0 y Elastic. El argumento no vale para elegir operador (el `$` simple sigue siendo la elección correcta, pero por ser más pequeño, no por compatibilidad) |

**Lo que sí queda demostrado y justifica este PR:**

1. **Pérdida de datos real** (P0 de facto): el `$set` de `agents.<id>.messages.<índice>` con
   `session_message.__dict__` reemplaza el subdocumento y borra `event_loop_metrics`,
   `guardrail_event`, `latency_ms`, `input_tokens` y `output_tokens` — los mismos campos que
   `_filter_message_data` tiene que descartar al leer (`mongodb_session_repository.py:25-33`).
   Verificado en MongoDB real: tras `update_message()`, ambos campos inyectados **desaparecen**.
2. **Una lectura del historial completo por redacción**, evitable.
3. El selector por índice es **frágil por construcción** aunque hoy no se rompa: depende de que
   nadie añada jamás un `$pull`, un `$position` o un reemplazo de array. Filtrar por `message_id`
   elimina esa dependencia.

**Lo que este PR NO promete** (y no debe prometer en el CHANGELOG): inmunidad a concurrencia.
Mientras `message_id` pueda duplicarse, ningún selector posicional es inequívoco. Eso va en
issue aparte, y afecta igual a `_record_guardrail_event()` y `_apply_sync_update()`.

---

## 1. Cambio propuesto

Una sola `update_one` filtrada por `message_id`, con **allowlist explícito** de campos
actualizables — no derivado del `__dict__`, que es superficie abierta: el dataclass no usa
`slots`, un campo nuevo del SDK entraría en el esquema sin revisión, y una clave con `.` o `$`
colada en el `__dict__` produce rutas anidadas inesperadas o un `WriteError 40`.

```python
# Campos que update_message() reescribe. Allowlist explícito a propósito: derivarlo de
# SessionMessage.__dict__ dejaría que un campo nuevo del SDK entrase en el esquema sin
# revisión, y podría pisar los campos de extensión que este método debe preservar.
_MESSAGE_UPDATABLE_FIELDS = ("message", "redact_message")
```

```python
def update_message(
    self,
    session_id: str,
    agent_id: str,
    session_message: SessionMessage,
    **kwargs: Any,
) -> None:
    """Update a Message (usually for redaction).

    The message is located by message_id with the positional operator instead of
    an index computed in the client, so no read of the whole history is needed.

    Only the fields in _MESSAGE_UPDATABLE_FIELDS are written, each on its own
    path. Setting the message subdocument as a whole would replace it and wipe
    event_loop_metrics and guardrail_event, which the session manager stores
    there but SessionMessage does not carry. created_at is never written: an
    update that does not name it leaves it alone.

    Note: message_id is not a unique key (Strands derives it in memory), so a
    duplicated id would match the first element only. See issue #78.
    """
    now = datetime.now(UTC)
    message_prefix = f"agents.{agent_id}.messages.$"

    set_operations: dict[str, Any] = {
        f"{message_prefix}.{name}": getattr(session_message, name)
        for name in _MESSAGE_UPDATABLE_FIELDS
    }
    set_operations[f"{message_prefix}.updated_at"] = now
    set_operations[f"agents.{agent_id}.updated_at"] = now
    set_operations["updated_at"] = now

    try:
        result = self.collection.update_one(
            {
                "_id": session_id,
                f"agents.{agent_id}.messages.message_id": session_message.message_id,
            },
            {"$set": set_operations},
        )

        if result.matched_count == 0:
            raise ValueError(
                f"Message {session_message.message_id} not found in agent "
                f"{agent_id} of session {session_id}"
            )

        logger.info(
            f"Updated message {session_message.message_id} for agent {agent_id}"
        )
    except PyMongoError as e:
        logger.error(f"Failed to update message: {e}")
        raise
```

Neto: 5 rutas en el `$set`, **1 escritura, 0 lecturas** (hoy: 1 lectura + 1 escritura).

### 1.1 Decisiones cerradas

| Decisión | Motivo |
|---|---|
| Allowlist explícito, no `__dict__` | Un campo nuevo del SDK debe ser una decisión consciente de persistencia y migración, no un efecto colateral |
| `redact_message` se escribe siempre, incluso `None` | Es el comportamiento actual y es un *clear* explícito, no un «campo sin cambio». `to_message()` cae a `message` |
| No escribir `created_at` | Un `$set` que no lo nombra lo deja intacto, con su valor **y** su tipo (`datetime`, escrito por `create_message`). Releerlo era justo el round-trip que sobra |
| Diagnóstico de error conservado | **Revisado tras la limpieza**: la v2 preveía un `ValueError` único, pero con un agente inexistente el mensaje «Message N not found in agent X» es *activamente engañoso*. El filtro compuesto no distingue los tres casos, así que cuando no casa —y solo entonces— se relee para nombrar el que falta. El camino feliz no paga nada |
| Sin índice nuevo | El `explain()` real usa `_id_` (`IXSCAN → FETCH`): no hay collection scan. Un índice multikey sobre rutas de agentes dinámicos no es construible ni arreglaría duplicados |

### 1.2 Política de datos legados (`created_at` ausente)

El código actual **rellena de facto** un `created_at` ausente al reescribir el subdocumento.
Este cambio deja de hacerlo. No existe ninguna ruta normal que cree un mensaje sin timestamp
(`create_message` lo escribe incondicionalmente, `:496-499`), así que solo afecta a documentos
manipulados a mano o anteriores a esa garantía.

**Decisión: no se backfillea.** Se documenta como no soportado. El riesgo adyacente —
`list_messages()` ordena con `x.get("created_at", "")` (`:628-631`) y una mezcla de `datetime`
y ausente lanza `TypeError`— es **preexistente** y no lo introduce este PR: se menciona en el
CHANGELOG y queda fuera de alcance.

---

## 2. Plan de tests (corregido: distingue RED real de test de contrato)

La v1 afirmaba que los 12 tests eran fase RED. El adversarial lo desmintió ejecutándolos.
Esta tabla separa lo que **falla sin el fix** de lo que solo fija contrato.

### 2.1 RED real — fallan hoy, pasan con el fix

| # | Test | Fichero | Qué asserta |
|---|---|---|---|
| U1 | `test_update_message_does_not_read_first` | unit | `find_one.call_count == 0` |
| U2 | `test_update_message_matches_by_message_id` | unit | la query lleva `_id` **y** `agents.a1.messages.message_id` |
| U3 | `test_update_message_uses_positional_paths` | unit | toda clave del `$set` que apunte al mensaje empieza por `agents.a1.messages.$.`; ninguna clave con índice numérico |
| U5 | `test_update_message_raises_when_not_found` (**modificar**) | unit | con `update_one.return_value.matched_count = 0` → `ValueError`. Sin mockear `find_one` |
| U6 | `test_update_message_with_redact_message` (**modificar**) | unit | `set_data["agents.a1.messages.$.redact_message"]` (hoy comprueba `messages.0`) |
| U7 | `test_update_message` (**modificar**) | unit | sin `find_one` mockeado, `update_one` llamado una vez |
| U8 | `test_update_message_ignores_unknown_attributes` | unit | un atributo extra inyectado en el `SessionMessage` **no** aparece en el `$set` (blinda el allowlist) |
| I1 | `test_update_message_preserves_manager_fields` | integración | inyectar `event_loop_metrics` y `guardrail_event` → redactar → **ambos siguen ahí**. Es la regresión que importa |
| W1 | `test_redaction_costs_one_write_and_no_read` | write-amplification | con `CommandCounter`: `find == 0`, `update == 1` |

### 2.2 Tests de contrato — ya pasan hoy; se añaden para que no se rompan

Se etiquetan como tales en el docstring, sin fingir que son RED:

| # | Test | Qué fija |
|---|---|---|
| I2 | `test_update_message_preserves_created_at` | `created_at` idéntico en valor y tipo (`datetime`); `updated_at` mayor |
| I3 | `test_update_message_raises_for_unknown_message` | `ValueError` con `message_id` inexistente |
| I4 | `test_update_message_raises_for_unknown_agent` | `ValueError` con agente inexistente (el texto se unifica) |

### 2.3 Eliminado: el test de concurrencia de la v1

`I5` (dos redacciones paralelas sobre mensajes distintos) **pasa ya con el código actual**
(50/50 en la verificación del adversarial) porque un `$push` al final no desplaza nada: no es
una regresión, es teatro. Y parchear `_agent_exists` para forzar la ventana sería peor, porque
tras el fix ese hook ya no se ejecuta y el test pasaría **sin ejecutar ninguna mutación
concurrente**.

En su lugar, un test que **documenta el límite conocido**:

| # | Test | Qué documenta |
|---|---|---|
| I5' | `test_duplicate_message_id_updates_only_the_first` | con dos elementos del mismo `message_id`, el update posicional toca solo el primero. No es el comportamiento deseado: es el contrato actual, y el test enlaza a #78 para que el día que se arregle, falle y obligue a revisarlo |

---

## 3. Documentación y versión

| Fichero | Cambio |
|---|---|
| `docs/architecture/data-model.md:700-726` | reescribir «Update Message (Redaction)» con el posicional y el allowlist |
| `docs/architecture/design-decisions.md:1093-1104` | «Same Pattern for Messages» cita el `enumerate`: sustituir por «no se escribe `created_at`; el `$set` que no lo nombra lo deja intacto» |
| `docs/api-reference/mongodb-session-repository.md:481-524` | `Raises`: un único `ValueError`; nota de que preserva los campos de extensión y de que `message_id` no es clave única |
| `CLAUDE.md` | línea gemela a la de `update_agent`: `update_message()` localiza por `message_id` con el posicional y escribe un allowlist de campos |
| `CHANGELOG.md` | entrada `[0.10.2] - Fixed`, **redactada con honestidad** (ver abajo) |
| Versión → **0.10.2** | `__init__.py`, `pyproject.toml`, `CHANGELOG.md`, badge de `README.md`, `docs/README.md` |

**Redacción del CHANGELOG** — lo que NO se puede decir y lo que sí:

- ❌ «arregla una condición de carrera que redactaba el mensaje equivocado» → no reproducible
  con las operaciones actuales del repositorio.
- ❌ «redactar un mensaje borraba su `guardrail_event`» → el evento de *esa* redacción
  sobrevive, porque `_record_guardrail_event()` corre **después** de `super()`
  (`mongodb_session_manager.py:242-259`). Se pierde un evento **anterior** del mismo mensaje.
- ❌ «se perdían siempre las métricas» → es condicional: en el primer turno el mensaje
  redactado aún no tiene métricas acumuladas.
- ✅ «`update_message()` dejaba de conservar los campos de extensión ya presentes en el mensaje
  (`event_loop_metrics`, `guardrail_event`, contadores legados), porque escribía el
  subdocumento entero. Ahora escribe un allowlist de campos, cada uno en su ruta».
- ✅ «localiza el mensaje por `message_id` en el servidor en vez de calcular su índice en el
  cliente: una escritura, cero lecturas, y el selector deja de depender de que nadie reordene
  el array».

---

## 4. Fuera de alcance (issues aparte, acordado con el usuario)

1. **`message_id` no es una identidad estable (#78).** Strands lo deriva en memoria; dos managers
   concurrentes pueden duplicarlo. Afecta a `update_message()`, `_record_guardrail_event()` y
   `_apply_sync_update()`. Arreglo real: identidad inmutable (UUID) por mensaje + migración.
2. **`agent_id` con `.` o `$` (#79).** Strands solo rechaza separadores de ruta
   (`strands/_identifier.py`), así que admite `a.b`, que rompe toda la dot notation del
   repositorio (`create_agent`, `read_agent`, `create_message`, métricas, guardrails,
   `update_metadata`). Defecto transversal preexistente.
3. **`create_agent()` reemplaza `agents.<id>` entero** con `messages: []` (`:361-369`): dos
   inicializaciones concurrentes de un agente ausente pueden borrarse mensajes mutuamente.
   Esta sí es una vía real de pérdida de datos, y no está en #64.
4. **`list_messages()` peta al ordenar** si conviven `created_at` `datetime` y ausente.
5. **Write concern**: `matched_count` y la durabilidad dependen de la config heredada de la
   colección; no está declarado un mínimo para una operación de seguridad como la redacción.

---

## 5. Criterios de aceptación

De la issue, ajustados a lo verificable:

- [x] ~~Test de regresión de concurrencia~~ → sustituido por I5' (documenta el límite real);
      el escenario original no es reproducible (§0)
- [ ] `update_message` no llama a `find_one`; la query incluye `messages.message_id`; el `$set`
      usa `messages.$.` (U1, U2, U3, W1)
- [ ] `created_at` del mensaje se conserva en valor y tipo (I2)
- [ ] `message_id` inexistente → `ValueError` (I3, U5)
- [ ] Tras `update_message()`, `event_loop_metrics` y `guardrail_event` siguen presentes (I1)
- [ ] Un atributo desconocido del `SessionMessage` no entra en el esquema (U8)

## 6. Secuencia

1. RED: U1, U2, U3, U5, U6, U7, U8, I1, W1 → comprobar que fallan de verdad
2. GREEN: el cambio de §1 + `_MESSAGE_UPDATABLE_FIELDS`
3. Contrato: I2, I3, I4, I5'
4. `uv run ruff format .` → `uv run ruff check .` → `uv run python -m pytest tests/unit -v`
   (los comandos de CLAUDE.md valen tal cual: verificado, **275 unit tests en verde** sin flags
   extra. El `--extra dev` que reclamaba el informe adversarial era un artefacto de haber
   corrido antes de que `uv` creara el venv)
5. Integración contra `localhost:8550`
6. `/simplify` → `/code-review`
7. Docs + versión 0.10.2 + CHANGELOG
8. PR con `Closes #64`, enlazando el informe adversarial y las issues nuevas
