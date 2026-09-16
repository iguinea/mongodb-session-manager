# #78 — Identidad estable de mensaje (`storage_id`)

## Contexto

`message_id` no identifica un mensaje: Strands lo deriva **en memoria**
(`repository_session_manager.py:78-86`, `next_index = latest.message_id + 1`), y cada manager
restaura su contador desde `list_messages(...)[-1]`. Dos managers que restauren el mismo agente a
la vez calculan el mismo índice y `create_message()` hace `$push` de dos mensajes con el mismo
`message_id` — no hay comprobación de unicidad ni de versión.

A partir de ahí el operador posicional `$` actualiza **solo el primer elemento que casa**. Con ids
duplicados, la redacción de Guardrails, el `guardrail_event` de auditoría y las métricas del turno
se atribuyen al mensaje equivocado: se redacta contenido inocente y el contenido bloqueado queda
visible.

El refactor de #80 dejó el terreno listo: `_update_message_document()`
(`mongodb_session_repository.py:584`) es el único sitio que construye el selector posicional, y
`get_last_message_ref` — hoy `get_last_message_id()` (`:1086`) — es el único que resuelve cuál es
el último mensaje. Este cambio es local a esos dos puntos y a sus llamantes.

**Resultado esperado:** cada mensaje nace con una identidad de almacenamiento inmutable y no
derivada del índice, y los tres updates posicionales apuntan a ella.

## Decisiones tomadas

| Decisión | Elegido |
|---|---|
| Mensajes ya almacenados | **Fallback a `message_id`**, sin migración. Campo aditivo |
| `get_last_message_id()` | **Se sustituye** por `get_last_message_ref()` (breaking, documentado) |
| Causa de los duplicados (dos managers a la vez) | **Fuera de alcance**. Se documenta |

## Diseño

**El campo.** `storage_id` (uuid4 hex) en cada documento de mensaje, escrito por `create_message()`.
Nunca se reescribe.

**El vehículo.** `SessionMessage` es una dataclass sin `__slots__`, y Strands conserva **la misma
instancia** a lo largo del turno: `append_message()` la guarda en `_latest_agent_message` y se la
pasa a `create_message()`; `redact_latest_message()` se la pasa a `update_message()`; el manager la
lee para las métricas. Verificado: `setattr` funciona y el atributo queda fuera de
`asdict()`/`to_dict()`, así que no contamina lo que Strands serializa. El `storage_id` viaja
adjunto al mensaje, sin estado extra que mantener y sin tocar la SDK.

**El fallback.** Un mensaje sin `storage_id` (escrito antes de este cambio) se localiza por
`message_id`, exactamente como hoy. La degradación es silenciosa por diseño: el histórico sigue
siendo redactable, y el riesgo se extingue solo según los agentes añaden mensajes nuevos.

## Ficheros

### Nuevo: `src/mongodb_session_manager/message_identity.py`

Un único concepto de dominio, la identidad de un mensaje:

- `MessageRef` — dataclass frozen: `message_id: int`, `storage_id: str | None = None`.
- `new_storage_id()` — `uuid4().hex`.
- `attach_storage_id(session_message, storage_id)` — encapsula el `setattr`. Si un futuro Strands
  lo impidiera (`__slots__`/`frozen`), captura `AttributeError`, loguea WARNING y sigue: el
  `storage_id` ya está en BD y el turno degrada al selector por `message_id`, que es el
  comportamiento actual.
- `ref_of(session_message) -> MessageRef` — la referencia que lleva adjunta el mensaje.

### `mongodb_session_repository.py`

- `_MESSAGE_EXCLUDED_FIELDS` += `storage_id` (si no, `SessionMessage(**data)` revienta).
- `create_message()`: genera el id, lo escribe en el documento y lo adjunta al `session_message`.
- `read_message()` / `list_messages()`: adjuntan al `SessionMessage` reconstruido el `storage_id`
  leído, para que un manager restaurado también redacte por identidad.
- `_update_message_document(session_id, agent_id, ref: MessageRef, ...)`: el filtro pasa a ser
  `agents.<aid>.messages.storage_id` cuando `ref.storage_id` existe, y `...messages.message_id`
  cuando no. El prefijo posicional `$` no cambia.
- `update_message_fields()` y `record_guardrail_event()`: su tercer parámetro pasa de `message_id:
  int` a `ref: MessageRef`. Una sola forma de nombrar un mensaje en toda la interfaz; imposible
  pasar el id y olvidar la identidad.
- `update_message()` conserva su firma (es la interfaz de Strands) y saca el ref con `ref_of()`.
- `_session_guardrail_entry()`: añade `storage_id` junto a `message_id`, para que la auditoría de
  sesión sepa a qué mensaje apunta.
- `get_last_message_id()` → `get_last_message_ref()`: misma proyección `$slice: -1`, devuelve
  `MessageRef | None`.

### `mongodb_session_manager.py`

- `_get_last_message_id()` → `_get_last_message_ref()`: `ref_of(latest)` del
  `_latest_agent_message` que ya rastrea la clase padre; fallback a `get_last_message_ref()`.
- `_build_metrics_update()` / `_metrics_set_operations()` / `_apply_sync_update()` /
  `_update_last_message_metrics()`: pasan `MessageRef | None` donde hoy pasan `message_id`.
- `redact_latest_message()` y `_record_guardrail_event(agent, ref, ...)`: idem.

### `__init__.py`

Exporta `MessageRef` (aparece en la firma pública de `get_last_message_ref()`). Versión → `0.12.0`.

### Tests

- `tests/support/in_memory_session_repository.py` — espejo exacto: genera y adjunta `storage_id`,
  `_find_message` busca por identidad con fallback, `get_last_message_ref()`, firmas con
  `MessageRef`. La cabecera del módulo deja de listar #78 entre las verrugas reproducidas a
  propósito y pasa a documentar el fallback.
- `tests/support/repository_contract.py` — corre contra las dos implementaciones a la vez:
  - `test_matches_only_the_first_duplicate` se reescribe como **`test_targets_its_own_duplicate`**:
    dos mensajes con `message_id=1` y `storage_id` distintos; el update hecho con el ref del
    segundo aterriza en el segundo.
  - Nuevo `test_falls_back_to_message_id_without_storage_id`: un mensaje legacy sin el campo se
    sigue localizando por `message_id`.
  - Nuevo: `create_message()` estampa un `storage_id` distinto por mensaje y lo deja adjunto al
    `SessionMessage` recibido.
  - `test_get_last_message_id` → `test_get_last_message_ref`.
- `tests/unit/test_session_manager.py`, `test_write_amplification.py`, `test_session_repository.py`
  — adaptar a las firmas nuevas y añadir la regresión de nivel manager: con un duplicado en el
  array, redacción, métricas del turno y `guardrail_event` caen en el mensaje que creó **este**
  manager.
- `tests/integration/test_repository_integration.py` —
  `test_duplicate_message_id_updates_only_the_first` se reescribe contra MongoDB real (el propio
  test dice que debe fallar cuando #78 se arregle), más el caso de fallback legacy.

### Documentación (obligatoria, misma PR)

`CLAUDE.md` (§2 del repositorio + esquema), `docs/architecture/data-model.md` (campo nuevo y
caveat de `message_id` reescrito), `docs/api-reference/mongodb-session-repository.md` (firmas y las
dos notas que hoy apuntan a #78), `docs/development/testing.md` (qué reproduce ahora el doble),
`CHANGELOG.md` (entrada 0.12.0 con el breaking change), `README.md` y `docs/README.md` (badge y
versión).

## Orden de trabajo (TDD)

1. **RED** — contrato (duplicado propio, fallback legacy, `storage_id` estampado) y regresión de
   manager. Deben fallar contra el código actual.
2. **GREEN** — `message_identity.py`, repositorio, manager, doble in-memory.
3. **REFACTOR** — `/simplify` y releer el resultado; los tests siguen verdes.
4. Gate de calidad: `/code-review` y revisión de dominio.
5. Docs, CHANGELOG y bump de versión.

## Verificación

```bash
uv run ruff format . && uv run ruff check .
uv run python -m pytest tests/unit -v
export MONGODB_CONNECTION_STRING="mongodb://<user>:<pass>@localhost:8550/"
uv run python -m pytest tests/integration -v     # requiere el MongoDB local
```

Prueba end-to-end del bug original (script temporal, no se commitea): dos
`MongoDBSessionManager` sobre la misma sesión y agente, ambos restaurados antes de escribir, cada
uno añade su mensaje (mismo `message_id`) y redacta el suyo; comprobar en el documento que cada
redacción está en su mensaje y que ninguna pisó al otro. Antes del fix, las dos caen en el primero.

Si el MongoDB local no está levantado, se dice explícitamente y se entregan solo los resultados de
unitarios.

## Fuera de alcance

- Impedir que dos managers concurrentes generen el mismo `message_id`. La identidad estable hace
  que cada uno escriba sobre el mensaje correcto, pero el historial sigue conteniendo dos mensajes
  con el mismo índice. Se documenta en el CHANGELOG y, si el usuario quiere, se abre issue aparte.
- Migrar los mensajes ya almacenados.

---

## Desviaciones sobre el plan, tras el gate de simplificación

El plan se implementó completo. Cuatro revisiones en paralelo (reuso, simplificación,
eficiencia, altitud) señalaron convergentemente lo mismo, y de ahí salieron estos cambios sobre
lo planificado:

- **No hay `_message_selector()` en el repositorio.** La regla "identidad si la hay, índice si
  no" quedaba enunciada en tres sitios (repositorio, doble in-memory y la entrada de auditoría).
  Ahora vive una sola vez, en `MessageRef.locator()`, y las dos implementaciones del repositorio
  preguntan ahí: una construye una dot-path, la otra recorre una lista, pero ambas buscan lo
  mismo.
- **`MessageRef.from_document()`**, porque reconstruir la referencia desde un documento
  almacenado aparecía tres veces.
- **`redact_latest_message()` no vuelve a preguntar por el último mensaje.** Toma la referencia
  del mismo `SessionMessage` que `super()` acaba de redactar, así que el evento de auditoría
  nombra lo que se redactó por construcción y no por coincidencia. El fixture `stored_message`
  de los tests se ajustó para registrar el mensaje en `_latest_agent_message`, que es lo que
  Strands hace siempre en producción.
- **`attach_storage_id()` no captura `AttributeError`.** Era una rama inalcanzable y sin
  cobertura. En su lugar, `tests/unit/test_message_identity.py` fija el contrato con la SDK: si
  una versión futura de Strands deja de aceptar el atributo, falla ahí y no en producción.
- **`_missing_message_error()` conserva su firma** con `message_id: int`: solo usa ese campo.

Descartado a conciencia:

- **Acortar el `storage_id`.** Un uuid4 hex cuesta 49 bytes BSON por mensaje y un token de 12
  caracteres bastaría (29). Se mantiene el uuid4 por ser lo aprobado y reconocible al abrir un
  documento; el ahorro es <5% de un mensaje con métricas.
- **Eliminar el fallback `get_last_message_ref()`.** Solo se alcanza cuando este proceso no ha
  visto ningún mensaje del agente, y entonces el último mensaje almacenado es, por definición,
  de otro proceso: la identidad hace la escritura precisa, pero sobre un mensaje ajeno. Es un
  problema distinto al de #78 y merece issue propia.
- **Mover el mapeo documento↔dominio fuera del adaptador de MongoDB.** El doble in-memory
  importa helpers del repositorio real desde antes de este cambio, a propósito. Reorganizarlo es
  un refactor de arquitectura que excede el alcance de #78.
