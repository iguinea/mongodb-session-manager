# Plan: hidratar la caché de configuración del agente desde `read_agent()`

**Estado:** aceptado, en implementación (issue #65).
**Origen:** informe `artifacts/analisis-rendimiento.md`, §"P0 — Reducir el presupuesto de escrituras
por turno", recomendación 1. Sub-issue de #56.
**Alcance acordado:** un único PR que cierra #65 e incluye, como primer commit, el arreglo de
`update_agent()` (§2). Sin issue aparte: el hallazgo se documenta en #65 y en el PR.

---

## 1. Objetivo

No reescribir `agent_data.model` / `agent_data.system_prompt` al comienzo de cada request cuando la
configuración persistida es idéntica. En el turno de referencia (supervisor + subagente, una tool)
son 2 de las 15 escrituras, y las más pesadas (~14 KB cada una).

## 2. Hallazgo previo: `update_agent()` borra la configuración

Verificado contra MongoDB 8.2.7 local con un `CommandListener` sobre `main` (`0413ada`).

`update_agent()` hace `$set` de `agents.<id>.agent_data` completo. Eso reemplaza el subdocumento y
borra los campos que el manager escribe aparte: `model`, `system_prompt` y `prompt_metadata`.

| Escenario | Resultado en `main` |
|---|---|
| `update_agent()` sobre un agente con config | `model`, `system_prompt` y `prompt_metadata` a `None` |
| Mismo manager, `agent.state` cambia entre invocaciones | config borrada y no reescrita |
| `set_prompt_metadata()` tras el turno 1, turno 2 con manager nuevo | `prompt_metadata` borrado |
| Turno de referencia | el supervisor termina **sin `model` ni `system_prompt`** |

**Por qué ya ocurre en `main`:** Strands incrementa la versión de `interrupt_state` al ejecutar
tools, así que el agente que las ejecuta hace un segundo `update_agent` dentro del turno. Desde #54
la caché ya está llena en ese punto y nadie reescribe la configuración. En v0.9.1 se reescribía en
cada sync y el borrado quedaba tapado.

**Por qué bloquea #65:** hoy el primer sync de cada request borra la configuración y la reescribe
acto seguido, porque la caché está vacía. Con la caché hidratada esa reescritura desaparecería y la
configuración quedaría borrada en reposo.

v0.10.0 no está etiquetada ni publicada (última release: v0.9.1). No etiquetarla hasta que entre
este arreglo.

## 3. Diseño

### 3.1 `update_agent()` campo a campo

`$set` de `agents.<id>.agent_data.<campo>` por cada campo de `SessionAgent`, en lugar del
subdocumento entero. Los campos del agente (`state`, `conversation_manager_state`,
`_internal_state`…) se siguen reemplazando completos; los de auditoría quedan intactos.

- Sin operadores nuevos: el mismo `$set` con rutas con punto que ya usa el manager (DocumentDB,
  igual que #54).
- Sin lecturas: sigue siendo un único `update_one`.
- `updated_at` raíz y `agents.<id>.updated_at` se siguen refrescando; `agents.<id>.created_at`
  sigue fuera del `$set`.

### 3.2 Hidratación

- `read_agent()` ya recibe `model` / `system_prompt` y los descarta (`SessionAgent` no los admite).
  Pasa a guardarlos por `(session_id, agent_id)`.
- `pop_read_agent_config(session_id, agent_id)` los entrega una sola vez. La clave incluye la sesión
  para que un repositorio usado con varias sesiones no siembre la caché con la configuración de
  otra.
- `MongoDBSessionManager.initialize()` llama a `super().initialize(agent)` y siembra
  `_agent_config_cache[agent_id]` con lo leído. Si la sesión es nueva o el agente no existía,
  `read_agent()` no encuentra nada y la caché queda vacía: el primer sync escribe, como hasta ahora.
- `_build_agent_config_update()` no cambia.

Alternativas descartadas:

- Leer la configuración aparte en `initialize()`: añade una lectura que no hace falta, porque
  `read_agent()` ya trae los campos.
- Reimplementar `initialize()` sin llamar al padre: duplicaría la restauración del SDK.

## 4. Tests (TDD: RED antes de cada cambio)

| Test | Nivel | Falla hoy |
|---|---|---|
| El `$set` de `update_agent` no reemplaza `agent_data` | unit | sí |
| `model`, `system_prompt` y `prompt_metadata` sobreviven a `update_agent` | integración (repositorio) | sí |
| La configuración sigue presente al terminar un turno con tool call | integración (turno) | sí |
| `read_agent` entrega la configuración leída una sola vez y por sesión | unit | sí |
| Segundo manager, misma configuración → el `$set` de `sync_agent` no incluye `agent_data.model` / `system_prompt` | unit | sí |
| Configuración distinta entre despliegues → sí escribe | unit | no (guardarraíl) |
| Agente nuevo en sesión existente → sí escribe | unit | no (guardarraíl) |
| Turno caliente ≤9 `update` (`TestTurnWriteBudget`; el de sesión nueva sigue en ≤10) | unit | sí |
| Turno de referencia ≤13 `update`, y ninguno reenvía `system_prompt` | integración | sí |
| `updated_at` raíz avanza en cada turno | unit + integración | no (invariante existente) |

## 5. Presupuesto

Traza real del turno caliente de referencia en `main`:

| | `$push` | `update_agent` | config | métricas | total |
|---|---:|---:|---:|---:|---:|
| `main` (v0.10.0 sin etiquetar) | 6 | 3 | 2 | 4 | 15 |
| con #65 | 6 | 3 | 0 | 4 | **13** |

El desglose documentado en #54 (6 `create_message` + 8 syncs + 1 `update_agent`) no cuadra con la
traza; se corrige en `docs/architecture/performance.md` y en el docstring del test de integración.

## 6. Riesgos

- **`secondaryPreferred`.** La hidratación lee de la misma réplica que la restauración del
  historial: no añade lecturas ni supuestos de frescura. Único caso: despliegue con versiones
  mezcladas y réplica atrasada; el campo puede quedarse con la configuración de la otra versión
  hasta el siguiente request con configuración distinta. El documento guarda una sola configuración
  por agente, así que en ese escenario nunca fue exacto.
- **`prompt_metadata` persiste entre turnos.** Antes desaparecía en el primer sync de cada request;
  los consumidores que lo vuelven a sellar en cada turno siguen funcionando igual.
- **Coordinación con #57.** Cualquier proyección mínima de `read_agent()` debe seguir incluyendo
  `agent_data.model` y `agent_data.system_prompt`. Lo protege el assert de integración que prohíbe
  reenviar `system_prompt` en el turno caliente.

## 7. Documentación

- `docs/architecture/performance.md`: tabla y desglose de escrituras por turno.
- `docs/api-reference/mongodb-session-repository.md`: `read_agent`, `update_agent`,
  `pop_read_agent_config`.
- `docs/api-reference/mongodb-session-manager.md`: `initialize`.
- CHANGELOG: al final, con confirmación.
