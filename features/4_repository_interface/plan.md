# Issue #80 — El manager deja de saltarse la interfaz del repositorio

## Contexto

`MongoDBSessionManager` accede a `self.session_repository.collection` —el objeto colección de
pymongo— en **ocho** métodos, construyendo a mano filtros con dot-notation, `$set`/`$push` y
leyendo `matched_count`. Contradice `.claude/rules/workflow-persistence.md` («todo acceso a datos
pasa por una interfaz; el dominio NUNCA importa el cliente de DB») y contradice la propia
documentación: el diagrama de `docs/architecture/overview.md:29-69` ya dibuja
`MANAGER → REPO → POOL → MONGO`, sin arista del manager a Mongo. El código incumple lo que el
diagrama promete.

Dos consecuencias concretas:

1. **El manager no se puede testear sin MongoDB.** Los ~30 tests unitarios del manager no
   comprueban qué queda guardado, sino qué comando de pymongo se emitió: asertan cadenas literales
   como `"agents.test-agent.messages.$.event_loop_metrics.cycle_metrics"`. Verifican la forma del
   comando, no el efecto.
2. **El mecanismo de escritura posicional está triplicado**: `MongoDBSessionRepository.update_message()`
   (repo:578, reescrito en PR #81), `_record_guardrail_event` (mgr:296) y `_apply_sync_update`
   (mgr:486) construyen el mismo filtro y el mismo `$set` sobre `agents.<id>.messages.$.*`. Justo
   el umbral de la regla DRY del proyecto.

**Resultado buscado:** `grep -rn "session_repository.collection" src/` devuelve cero, el selector
posicional vive en un solo sitio (lo que convierte #78 en un cambio mecánico y tipado en vez de una
caza de rutas duplicadas), y los tests del manager corren contra un repositorio in-memory que
afirma sobre el estado resultante.

Es deuda de arquitectura, no una corrección: **no debe cambiar ningún comportamiento observable**.
Conviene hacerlo antes de #78, que tendrá que modificar exactamente ese mecanismo.

## Decisiones tomadas

| Decisión | Valor |
|---|---|
| Alcance | Los tres entregables de la issue |
| Forma de las escrituras | Híbrido: primitivos genéricos con **claves relativas** + el guardarraíl como método de dominio |
| Lecturas | Métodos de dominio (`get_agent_config`, `list_agent_configs`, `count_messages`, `get_last_message_id`) |
| In-memory | En `tests/`, no en `src/`. No es API pública: no se versiona ni se documenta en `api-reference` |
| `repo.collection` | Se queda público y sin tocar. `docs/user-guide/metadata-management.md` y `async-streaming.md` quedan **intactos** |
| Versión | Bump a **0.11.0** (aditivo → minor, `workflow-contracts.md`), en los 5 sitios |

## Restricciones duras

1. **Write amplification.** `sync_agent` cuesta **una** escritura y la config del agente solo se
   escribe si cambió. Tiene tests (`TestSyncAgentWriteCount`: `update_one.call_count == 1`;
   `TestAgentConfigWrittenOnlyOnChange`: 0/1/0) y un juez de integración incorruptible
   (`test_turn_stays_within_write_budget`, `CommandListener` real: `update <= 13`, `find <= 6`).
   El plan no puede añadir un solo round-trip.
2. **El caso mixto**: `_apply_sync_update` mezcla en la misma escritura operaciones posicionales
   (métricas del mensaje) y no posicionales (config del agente); `_record_guardrail_event` mezcla
   `$set` de mensaje con `$push` de sesión. Esa fusión no desaparece: **baja una capa**.
3. **Textos de error intactos**: los tests asertan `match="Session test-session not found"` y
   `match="Message 99 not found"`. El `ValueError` lo sigue lanzando el manager (contrato público).
4. No arreglar aquí #78 ni #79, pero dejar ambos más fáciles.

## Diseño

### 1. Primitivo posicional (privado) y sus tres usuarios

En `mongodb_session_repository.py`, un único método con el filtro posicional y el prefijo
`agents.<id>.messages.$.`:

```python
def _update_message_document(
    self,
    session_id: str,
    agent_id: str,
    message_id: int,
    message_fields: Mapping[str, Any],
    *,
    extra_set: Mapping[str, Any] | None = None,
    push: Mapping[str, Any] | None = None,
    touch_timestamps: bool = False,
) -> bool:
    """Write fields onto one message, located server-side by message_id."""
```

- Es **privado** porque `push` toma rutas desde la raíz del documento, sin prefijo que el
  repositorio controle: esa es la fuga que no debe salir de la clase.
- Devuelve `bool` (`matched_count > 0`): `matched_count` es vocabulario de pymongo y muere aquí.
  **No lanza** por no-match — los tres llamadores tienen políticas distintas (uno lanza, otro
  loguea, otro ignora).
- El filtro queda inline, con un comentario que lo marca como el único sitio de identidad de
  mensaje y referencia #78.

Encima de él, tres usuarios:

| Método | Visibilidad | Uso |
|---|---|---|
| `update_message_fields(sid, aid, msg_id, set_operations, agent_set_operations=None, touch_timestamps=False)` | público | Métricas del turno. `set_operations` con claves **relativas al mensaje** (`"event_loop_metrics.cycle_metrics"`); `agent_set_operations` relativas al agente (`"agent_data.model"`) |
| `record_guardrail_event(sid, aid, msg_id, event)` | público | **Deriva el evento de sesión del de mensaje** dentro del repositorio. Hoy el manager los construye por duplicado (mgr:280-294), incluida la regla «el `trace` completo no va al array de sesión», que tiene test propio. Al bajarla, queda en un sitio |
| `update_message()` (SDK) | público | Conserva firma, allowlist, textos de error y su única escritura; pasa a delegar |

Hermano no posicional, para el caso «solo config»:

```python
def update_agent_fields(
    self, session_id: str, agent_id: str, set_operations: Mapping[str, Any]
) -> bool:
    """Write fields under agents.<agent_id> without touching its messages."""
```

### 2. Lecturas de dominio

`get_agent_config`, `list_agent_configs`, `count_messages`, `get_last_message_id` — con la
convención de lecturas custom ya existente (`get_metadata`, `get_feedbacks`). `count_messages`
conserva la implementación actual (proyecta y hace `len`): optimizarla a `$size` es un cambio de
comportamiento medible y va en issue aparte. `get_last_message_id` conserva la proyección
`{"$slice": -1}` y es la segunda ruta de identidad de mensaje, por eso vive junto a la primera.

`_pop_read_agent_config` **no se renombra** (churn sin valor), pero el fake está obligado a
implementarlo.

**Sin `Protocol` ni dataclasses**, por KISS/YAGNI, ahora que el in-memory no es API pública. El
contrato se garantiza con las tres capas de §4.

### 3. El caso mixto de `sync_agent`, sin round-trips extra

`sync_agent` deja de fusionar `{**metrics_ops, **config_ops}` y los pasa por separado.
`_apply_sync_update` bifurca:

- hay métricas y `message_id` → `update_message_fields(..., agent_set_operations=config_ops)`:
  la config viaja de polizón en la escritura de métricas;
- no hay métricas → `update_agent_fields(..., config_ops)`: la config va sola.

Ramas excluyentes, **exactamente un `update_one` en cualquiera**. Es el mismo árbol de decisión de
hoy: el `if message_id is not None` que condicionaba el *filtro* ahora condiciona el *método*.
`_update_last_message_metrics` y `_capture_agent_config` conservan su firma pública (la usan 5
tests). Los prefijos de `_metrics_set_operations` y `_build_agent_config_update` pasan de absolutos
a relativos: una línea cada uno.

### 4. Repositorio in-memory y cómo se evita que mienta

`tests/support/in_memory_session_repository.py`. `tests/` y `tests/unit/` ya tienen `__init__.py`,
así que `from tests.support...` resuelve sin tocar configuración. Estado: un `dict` con la **misma
forma** que el documento Mongo, para que los asertos sean comparables con los de integración.

Dos piezas donde puede mentir, y que por tanto van escritas a conciencia:

1. **Semántica de `$set` con dot-notation**: helper `_set_dotted()` que camina el path y reemplaza
   solo la hoja — es lo que hace que escribir `event_loop_metrics.accumulated_usage` no borre
   `event_loop_metrics.cycle_metrics`.
2. **El posicional casa solo el primer elemento**: el fake reproduce a propósito el bug de #78. Un
   fake «mejor» que el original miente; si alguien lo «arregla», el caso 9 del contrato fallará
   contra MongoDB, que es justo lo que queremos.

Tres capas contra la deriva, de barata a cara:

| Capa | Qué detecta |
|---|---|
| **Guardia estructural** (~8 líneas): los métodos públicos de `MongoDBSessionRepository` ⊆ los del fake | Alguien añade un método al repo real y se olvida del fake |
| **Suite de contrato compartida**: clase base en `tests/support/repository_contract.py` con ~14 casos, heredada por una subclase unit (fake) y otra de integración (**MongoDB real**) | Semánticas divergentes. Es lo único que prueba de verdad que el fake no miente |
| **`Mock(spec=MongoDBSessionRepository)`** en las fixtures que sigan siendo mock | `.collection` es atributo de **instancia**, no de clase: con `spec` deja de existir. Si el manager vuelve a tocarlo, `AttributeError` |

Aviso explícito en el módulo del fake: su manejo de paths difiere de MongoDB si un `agent_id`
contiene `.` o `$` (#79), así que no sirve como evidencia sobre ese caso.

## Fases (TDD, cada una deja la suite verde)

Rama `refactor/issue-80-repository-interface`. Los commits 1-4 son aditivos y reversibles por
separado; el riesgo se concentra en el 6, único que puede alterar los round-trips, y por eso va
último con todos los tests de presupuesto ya en su sitio.

1. **RED**: tests de contrato de `update_message_fields` y `update_agent_fields`.
2. **GREEN/REFACTOR**: implementa el primitivo privado y los dos públicos; `update_message()` pasa
   a delegar. **Criterio de parada: los 10 tests existentes de `update_message` deben pasar sin
   editar ni uno.** Si alguno requiere edición, el refactor cambió comportamiento — parar.
3. Lecturas de dominio (RED→GREEN), sin tocar el manager.
4. Fake + suite de contrato + guardia estructural + fixtures. Producción intacta.
5. **El manager lee por la interfaz**: los 4 puntos de lectura (532, 812, 943, 983) + reescritura
   de `TestAgentConfigOperations`.
6. **El manager escribe por la interfaz**: los 4 de escritura (296, 486, 882, 913), el split de
   `_apply_sync_update`, el cambio de prefijos, `spec=` en la fixture, y la reescritura de
   `TestSyncAgent` + `TestRedactLatestMessage` + `TestSetPromptMetadata` + `TestSyncAgentWriteCount`.
7. Docs, CHANGELOG, bump a 0.11.0 y PR con `Closes #80`.

### Migración de los 31 tests rotos

Los 31 son los mismos en cualquier diseño que quite `.collection` del manager. Lo que este enfoque
salva son **21 tests de `test_write_amplification.py` que sobreviven verbatim** (usan el
repositorio real sobre cliente falso y asertan rutas absolutas, que el repositorio sigue emitiendo).

- **Reescritos contra el fake (~28)**: `TestSyncAgent`, `TestAgentConfigOperations`,
  `TestSetPromptMetadata`, `TestRedactLatestMessage`. Con dos helpers de lectura en el fake
  (`session()`, `message()`) los cuerpos caen de ~15 líneas a ~4, y pasan de verificar *cómo se
  escribe* a *qué queda escrito*.
- **La fixture `manager` se parte en dos**: `manager` con `Mock(spec=...)` para los tests de pura
  delegación (metadata, hooks, close — no se tocan) y `manager_fake` con el in-memory para el resto.
- **`TestSyncAgentWriteCount` (2)**: deja de contar `collection.update_one` y cuenta las llamadas al
  repositorio. Es un test mejor: mide el contrato que la optimización defiende.
- **Se fusionan 2 en 1**: `test_no_update_when_no_agents` y `test_no_update_when_no_messages` no
  tienen un solo `assert`.
- **Nuevos**: ~12 en `test_session_repository.py`, 14 de contrato (×2 subclases), ~6 del fake, 1
  guardia estructural.

## Verificación

1. `uv run ruff format .` && `uv run ruff check .`
2. `uv run python -m pytest tests/unit/ -v` — baseline medido al abrir la rama: **283 pasan**.
3. `uv run python -m pytest tests/integration/ -v` con
   `MONGODB_CONNECTION_STRING=mongodb://mongodb:mongodb@localhost:8550/` — **obligatorio**:
   `test_turn_stays_within_write_budget` es el único juez real de que no se coló un round-trip.
4. `grep -rn "session_repository.collection" src/` → cero. `repo.collection` sigue declarado.
5. `uv run pytest --cov=src tests/` — la cobertura del repositorio debe subir.
6. `/simplify` y `/code-review` antes del PR.

## Riesgos

| # | Riesgo | Verificación |
|---|---|---|
| R1 | Round-trip extra en `sync_agent` | `TestSyncAgentWriteCount` + `TestTurnWriteBudget` ×2 intactos + presupuesto de integración |
| R2 | Round-trip extra en el guardarraíl (`$set` y `$push` separados) | `test_guardrail_event_costs_one_write` (nuevo; hoy esa laguna existe) |
| R3 | Se rompe la caché y el system prompt vuelve a escribirse cada turno (regresión de #65, ~14 KB/turno) | `TestAgentConfigWrittenOnlyOnChange` (0/1/0) + `TestAgentConfigHydratedOnRestore`, ambos intactos |
| R4 | El `bool` se interpreta al revés y la caché se puebla tras un no-match (corrupción silenciosa: la config no se persistiría nunca) | Test nuevo: `False` → la caché no contiene al agente → el siguiente sync sí escribe |
| R5 | El fake miente respecto a MongoDB | Contrato ejecutado contra ambos + guardia estructural |
| R6 | **`touch_timestamps` es una bandera booleana**: si un llamador la olvida, el `updated_at` raíz deja de avanzar en silencio | `TestRootUpdatedAtInvariant` (unit) + `test_root_updated_at_advances_with_the_turn` (integración). Es el punto más frágil del diseño; va dicho en el docstring |
| R7 | Romper `update_message()` al meterlo en el primitivo | Sus 10 tests deben pasar sin editarlos (§Fase 2) |

## Fuera de alcance

#78 (identidad de mensaje), #79 (`agent_id` con `.`/`$`), reorganizar el paquete en
`domain/`+`infrastructure/`, optimizar `count_messages` a `$size`, y reescribir las guías de
usuario que consultan Mongo a pelo.
