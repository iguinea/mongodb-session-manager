# #67 — No reescribir un agente que no ha cambiado

**Estado:** implementado; aceptado tras revisión adversarial (Codex + OpenCode/GLM 5.3); diseño elegido por Iñaki
el 16/09/2026 frente a la siembra que proponía la issue.
**Issue:** #67, sub-issue de #56. Sale de `features/2_hydrate_agent_config_cache/plan.md` §9.
**Base:** `main` en `4b8ef84` (v0.13.0), `strands-agents` 1.30.0 en el lock (`>=1.30.0` en `pyproject.toml`).
**Informes:** `/tmp/review67/opencode/informe.md` (GLM 5.3). Codex agotó su cuota antes de escribir el
informe; sus sondeos (`/tmp/review67/codex/probe_loss.py`) se reprodujeron en esta sesión.

---

## 1. Objetivo

Que `update_agent()` no emita un `update_one` cuando el agente que recibe es, campo a campo y sin
contar los timestamps, el que el repositorio acaba de leer o escribir. Turno de referencia
(supervisor + sub-agente, una tool): **13 → 10 updates**, medido contra MongoDB.

## 2. Por qué no la siembra que proponía la issue

La issue proponía sembrar `RepositorySessionManager._last_synced_internal_state` en `initialize()`
para que el primer `sync_agent()` de cada manager no escribiera. Prototipo medido: 13 → 11. La
revisión adversarial tumbó su premisa central, «falla hacia escribir de más, nunca hacia perder»:

| Hallazgo | Evidencia (reproducida en esta sesión) |
|---|---|
| Un hook que **reasigna** `agent.state` en `AgentInitializedEvent` o `BeforeInvocationEvent` deja de persistirse | `probe_loss.py`: hoy `stored_state = replacement`; con siembra `original`, 0 `update_agent`. El `initialize()` del session manager corre antes que los hooks de usuario (orden de registro en `agent.py:305-325`), así que la siembra no ve la reasignación, y `AgentState(...)` nace en versión 0 |
| Un conversation manager que migra su estado al restaurar no persiste la migración | `probe_loss.py` MIGRATION: hoy `stored_schema 2`; con siembra `1` |
| La siembra de 3 claves es inerte desde strands **1.34.0**, que añade `model_state` | GLM, con venvs 1.31–1.56. Con `>=1.30.0`, una instalación nueva resuelve 1.56 y ahorra 0 |
| El test de contrato «siembra == instantánea del SDK» da verde en falso | `probe_loss.py` CONTRACT: iguales aunque el estado persistido difiera, porque ambos comparan versiones |
| Los tests de «un cambio real escribe» son vacuos con `MagicMock` | GLM H3: `state.set()` no sube `_get_version()` en un mock |

## 3. Diseño: deduplicar por contenido en el repositorio

### 3.1 La regla, en un módulo propio

`src/mongodb_session_manager/agent_content.py`, compartido por el adaptador de MongoDB y por el doble
in-memory (el mismo patrón que `field_names.py`, #79):

- `LastPersistedAgents`: recuerda, por `(session_id, agent_id)`, el contenido del último
  `SessionAgent` leído o escrito.
  - `remember(session_id, session_agent)`: guarda una **copia profunda** de todos los campos salvo
    `created_at` / `updated_at`. La copia no es decorativa: `read_agent()` devuelve un `SessionAgent`
    cuyos dicts acaban vivos dentro del agente (`_InterruptState.from_dict()` se queda con `context`
    sin copiarlo), así que guardar la referencia haría que la memoria mutara con el agente y diera
    por persistido lo que no lo está.
  - `unchanged(session_id, session_agent) -> bool`: compara con lo recordado, sin copiar.
  - `forget(session_id, agent_id)`.
  - Solo guarda los agentes de una sesión, la última recordada: la factoría crea un repositorio por
    manager, y uno reutilizado entre sesiones no acumula el estado de todos (el mismo cuidado que
    `_last_read_agent_config`). Olvidar solo cuesta una reescritura.
- Se compara `vars(session_agent)` menos los timestamps, no una lista de claves: los campos que
  añada una versión nueva del SDK entran solos (en 1.56 `model_state` viaja dentro de
  `_internal_state`).

### 3.2 `MongoDBSessionRepository`

- `create_agent()`: tras escribir, `remember`.
- `read_agent()`: si encuentra el agente, `remember`; si no, `forget`.
- `update_agent()`: primero `_agent_path()` (el `agent_id` se valida antes de cualquier retorno, #79);
  si `unchanged`, log debug y `return` sin round-trip; si no, escribe como hoy y, **solo si el
  `update_one` casó**, `remember`. Una escritura que lanza o no casa no se recuerda, y el siguiente
  sync lo reintenta.
- El doble in-memory aplica la misma regla en los mismos puntos.

### 3.3 Por qué no se pierde ninguna escritura

`update_agent()` solo se salta la llamada cuando el contenido que se escribiría es idéntico al que
este repositorio sabe persistido, porque lo acaba de leer o de escribir con éxito. Da igual cómo
llegara el agente a ese contenido (`set()`, reasignación, migración o hooks): lo que se compara es el
resultado, no las versiones.

## 4. Efectos y casos límite

1. **Ahorro:** los dos primeros syncs (estado recién restaurado o creado) y el `update_agent` que
   provoca `_interrupt_state.deactivate()` tras cada tool, que sube la versión sin cambiar el
   contenido cuando no había interrupción. 13 → 10 en el turno de referencia.
2. **Diferencias falsas por el viaje BSON** (tupla → lista, etc.): comparan distinto y se escribe,
   como hoy. Con los tipos que admite `AgentState` y el turno de referencia no aparece ninguna (medido).
3. **Concurrencia (managers de requests distintas, un repositorio por manager, como hace la
   factoría):** un manager que no cambia el agente ya no lo reescribe, así que no pisa lo que otro
   escribió entretanto. Antes lo pisaba en su primer sync y tras cada tool.
4. **Un repositorio compartido por varios managers** recuerda la última escritura de cualquiera de
   ellos: con contenido distinto se escribe, como hoy. Sin regresión.
5. **Escrituras que no pasan por `read_agent/create_agent/update_agent`** (un `update_agent_fields`
   sobre `agent_data.state`, o un cambio externo) no se ven: `update_agent` puede saltarse la
   reescritura de un contenido que el agente no ha cambiado. Es la semántica buscada (el agente no
   tiene nada nuevo que decir), y el manager no escribe esos campos por otras vías.
6. **Contrato público de `update_agent`:** con contenido idéntico no toca `agent_data.*`, ni
   `agents.<id>.updated_at`, ni el `updated_at` raíz, y no lanza «Session not found». Quien llame a
   `read_agent()` → modificar → `update_agent()` (el ejemplo de la documentación) sigue escribiendo.
7. **`agent_data.created_at/updated_at`** avanzan solo cuando el contenido cambia. Hoy los regenera
   `SessionAgent.from_agent()` en cada sync (`types/session.py:123-124`), así que significaban
   «último sync». `agents.<id>.updated_at` y el `updated_at` raíz siguen avanzando con cada mensaje.
8. **BidiAgent:** `sync_bidi_agent()` también pasa por `update_agent()`, así que deja de reescribir un
   agente bidi sin cambios. Misma regla, mismo razonamiento.
9. **Memoria:** una copia del contenido de cada agente leído o escrito de la última sesión tocada,
   durante la vida del repositorio, que con la factoría es la de una request. Medido (revisión de
   eficiencia): `deepcopy` de 0,6 ms con 33 KiB de estado y 15,6 ms con 824 KiB, frente a 40-55 ms
   por round-trip en DocumentDB.

## 5. Tests (TDD: RED antes de cada GREEN)

### 5.1 Contrato (`tests/support/repository_contract.py`, doble y MongoDB)

1. `update_agent` con el contenido recién creado → el documento no cambia (ni `updated_at`).
2. `read_agent` → `update_agent` del mismo `SessionAgent` → no cambia.
3. Contenido distinto → escribe; volver al anterior → vuelve a escribir.
4. Mutar en sitio el `SessionAgent` devuelto por `read_agent` → `update_agent` escribe (aliasing).

### 5.2 Unit del módulo (`tests/unit/test_agent_content.py`)

Timestamps ignorados, campo nuevo desconocido cuenta, copia profunda, `forget`, clave por sesión y agente.

### 5.3 Unit del repositorio sobre colección mock

Una escritura que lanza no se recuerda: el mismo contenido vuelve a emitir `update_one`. Lo mismo
cuando no casa (`matched_count == 0` → `ValueError`).

### 5.4 Manager con `Agent` real + doble + `ScriptedModel`

Turno caliente sin cambios: `agent_data.updated_at` no se mueve. Se persiste: `state.set()`, hook
que reasigna `agent.state` en `AgentInitializedEvent` y en `BeforeInvocationEvent`, y conversation
manager que migra al restaurar. Los cuatro últimos son las regresiones que tumbaron la siembra.

### 5.5 Presupuestos

- Unit `test_warm_turn_stays_within_budget`: **≤9 → ≤8**. Para que compare contenido real, el agente
  mock lleva un `_InterruptState` de verdad y el agente persistido su `_internal_state`.
- Integración `test_turn_stays_within_write_budget`: **≤13 → ≤10**, y ningún `agent_data.state`
  escrito en el turno caliente.
- Integración nueva: un manager que no cambia el agente no pisa lo que escribió otro manager.
- Integración nueva: `state.set()` en un turno se lee al restaurar en el siguiente.

## 6. Documentación

- `docs/api-reference/mongodb-session-repository.md` → `update_agent` (nueva semántica, §4.6).
- `docs/architecture/data-model.md` → semántica de actualización y de `agent_data.created_at/updated_at`.
- `docs/api-reference/mongodb-session-manager.md` → `sync_agent`.
- `docs/development/testing.md` → el doble aplica la misma regla.
- `CLAUDE.md` (bullet del repositorio).
- `CHANGELOG.md` y versión: **preguntar antes**. Comentario en #67 con la premisa corregida y fila
  de #56 (13 → 10): preguntar antes.

## 7. Compatibilidad

- **DocumentDB:** sin operadores ni consultas nuevas; solo deja de emitirse un `update_one`.
- **Forma de los documentos:** sin cambios de esquema ni migración.
- **Versiones mezcladas:** un manager antiguo sigue reescribiendo; uno nuevo solo escribe cambios.
  Escriben la misma forma de documento.
- **Session Viewer del Control Center:** lee `agents.<id>.created_at/updated_at`
  (`backend/src/session_viewer/service.py:519-520`), no los de `agent_data`, y de `agent_data` solo
  `model`, `system_prompt` y `prompt_metadata`. GLM lo confirmó también en el workspace de Orca.
- **Versiones del SDK:** la regla no depende de atributos privados de Strands; vale igual en 1.30 y 1.56.
- **Entradas que dejan de funcionar:** ninguna. Cambio observable: §4.6 y §4.7.

## 8. Fuera de alcance

- El bump de strands: #69. Esta regla no depende de atributos privados del SDK, así que no añade
  trabajo a ese bump; los presupuestos medidos allí con 1.56 no se han vuelto a medir con ella.
- Deduplicar `update_message()` o las métricas: #66.
