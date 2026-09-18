# #66 — Las métricas de una invocación, una sola vez y en su último mensaje

**Estado:** implementado (tests en verde: 515 unit + 122 integración). Revisado tras la revisión adversarial (Codex: rechazar; OpenCode/GLM 5.3: aprobar con cambios).
El contrato D′ que eligió Iñaki el 16/09/2026 no cambia. Cambia el mecanismo: la marca por `agent_id`
de la primera versión se sustituye por una etiqueta de contexto (§4.2), porque la revisión demostró
dos fallos propios de la marca.
**Issue:** #66, sub-issue de #56.
**Base:** `main` en `3465861` (v0.14.0). `strands-agents` 1.30.0 en el lock (`>=1.30.0` en `pyproject.toml`).
**Sondas:**
- Del autor: `/tmp/probe66/`. `verify/patch_d3.py` es el prototipo del mecanismo final;
  `verify/scenarios.py` y `verify/race.py` contienen los casos de fallo.
- Informes y sondas de los revisores: `/tmp/review66/{codex,opencode}/`.

---

## 1. Objetivo

Que el sync que Strands lanza en cada `MessageAddedEvent` deje de escribir métricas, porque en ese
momento todavía son las del ciclo anterior. Las escriben el sync de cierre (`AfterInvocationEvent`)
y cualquier llamada explícita a `sync_agent()`.

- Turno de referencia (supervisor + sub-agente + una tool) contra MongoDB: **10 → 8 updates**.
- Con N herramientas en ciclos sucesivos, un agente pasa de **2N+1 a 1** escrituras de métricas.
  Codex lo midió para N = 0..5: 1, 3, 5, 7, 9 y 11 frente a 1 en todos los casos.

## 2. Evidencia

### 2.1 Orden de eventos en Strands

`_handle_model_execution` añade el mensaje, dispara `MessageAddedEvent` y **después** acumula uso y
métricas (1.30.0: `event_loop.py:409-414`; 1.56.0: `:699-703`, vía `agent._append_messages()`).
`SessionManager.register_hooks()` registra `append_message` y `sync_agent` sobre `MessageAddedEvent`,
en ese orden, y `sync_agent` sobre `AfterInvocationEvent` (1.30.0: `session/session_manager.py:46-52`;
1.56.0: `:53-59`).

Sobre `MessageAddedEvent` los callbacks corren en orden de registro. Sobre `AfterInvocationEvent`,
en orden inverso (`hooks/events.py:109-111`): en 1.30, el sync de cierre del manager es el último en
correr, después de los hooks de usuario. `AfterInvocationEvent` se lanza en un `finally`
(`agent/agent.py:861-864`), pero **después de `conversation_manager.apply_management()`**, dentro del
mismo `finally`.

### 2.2 Sonda contra MongoDB, turno caliente de v0.14.0

```
 1. $push supervisor             msg=4 user
 2. $push supervisor             msg=5 assistant(tool_use)          ← sync sin métricas (latencyMs=0)
 3. $push info_suministro_agent  msg=2 user
 4. $push info_suministro_agent  msg=3 assistant
 5. métricas sub-agente          cycles=1 tokens=1280               ← AfterInvocation del sub-agente
 6. $push supervisor             msg=6 user(toolResult)
 7. métricas supervisor msg=6    cycles=1 tokens=1280               ← snapshot del ciclo 1
 8. $push supervisor             msg=7 assistant(final)
 9. métricas supervisor msg=7    cycles=2 tokens=1280               ← OBSOLETA
10. métricas supervisor msg=7    cycles=2 tokens=2560               ← AfterInvocation la corrige
```

Con el mecanismo final desaparecen la 7 y la 9, y quedan **8**. `msg=7` se queda con
`cycles=2 tokens=2560 tools=[info_suministro_agent]` y ningún otro mensaje lleva métricas. Lo midieron
el autor, Codex y OpenCode, cada uno con su propia sonda.

### 2.3 Casos (doble in-memory)

| Caso | v0.14.0 | Mecanismo final |
|---|---|---|
| 3 herramientas en ciclos sucesivos | 7 escrituras; el `assistant(tool_use)` del ciclo 2 guarda `cycles=2` con los tokens del ciclo 1 | 1 escritura, `(4, 5120)` en el `assistant` final |
| Mismo `Agent`, dos invocaciones | 4 escrituras; el `user` de la 2.ª hereda las métricas de la 1.ª | 2; el `user` sin métricas |
| El modelo falla en el ciclo 2 | 2 escrituras; el `toolResult` con `(2, 1280)` | 1 escritura, mismo documento final |
| Flujo de un consumidor: TTFT en el agente + `sync_agent()` a mano | TTFT 321 | 321 (con D, solo `AfterInvocation`: **0**) |
| `create_message` del final lanza **antes** de guardar | La escritura de cierre apunta a un mensaje inexistente y no casa | Ninguna escritura |
| `create_message` del final **se aplica y después lanza** (ack perdido) | 1280 en `toolResult` y en el final | 1280 en el final (con la marca de la v1 del plan: **nada**) |
| `sync_agent()` explícito desde otro hilo mientras se persiste un mensaje | — | El explícito escribe; el automático, no (con la marca: el explícito no escribía y el automático sí) |
| Hook de usuario que lanza en `AfterInvocationEvent` | 1280 en `toolResult` y en el final (el total real es 2560) | **Sin métricas** (§4.4) |
| `interrupt` y reanudación; `AfterInvocationEvent.resume`; hook que añade un mensaje en el cierre; dos agentes en un manager; cancelación de `stream_async` durante una tool; `structured_output_async` | — | Cada cierre escribe una vez sobre su último mensaje (sondas de Codex y OpenCode) |

### 2.4 `accumulated_*` es del objeto `Agent`, no de la sesión

`EventLoopMetrics` nace con el `Agent` y ninguna versión lo persiste ni lo restaura.
`reset_usage_metrics()` solo abre una `AgentInvocation` nueva (`telemetry/metrics.py:343-349`), así que
`get_summary()` devuelve lo acumulado en toda la vida del objeto. Con un `Agent` por petición, como en
la factoría, tres turnos dan 1280, 1280 y 1280 (`probe_running_total.py`).

### 2.5 Strands 1.56 atribuye cada ciclo a su mensaje

`MessageMetadata` (`types/content.py:215-250`) lleva `usage` y `metrics` del ciclo en cada `assistant`
antes de `MessageAddedEvent`, y se «persiste junto al mensaje». Al subir de versión (#69), el coste por
mensaje llegará de serie en `message.metadata`, sin escrituras adicionales.

## 3. Decisión

| Opción | Referencia | N tools | Por qué no |
|---|---:|---:|---|
| A — no escribir en `MessageAdded` de un `assistant` | 9 | N+1 | Sigue escribiendo un snapshot por ciclo en el `toolResult` y las métricas obsoletas en el `user` de un agente de vida larga. Además necesita distinguir `MessageAdded` de `AfterInvocation`, y el rol no basta |
| B — atribuir al `assistant` que generó el ciclo | 9 | N+1 | Más estado por agente para dar lo que Strands 1.56 ya da en `message.metadata` |
| C — no escribir si `(message_id, usage, tool_usage)` no cambió | 10 | 2N+1 | Tal como está escrita no quita la 9, porque cambia el `message_id` |
| D — métricas solo en `AfterInvocationEvent` | 8 | 1 | Rompe a un consumidor que escribe el TTFT y llama a `sync_agent()` a mano |
| **D′ — el sync de `MessageAdded` no escribe métricas; el resto, sí** | **8** | **1** | — |

Premisas de la issue que este plan corrige:

1. A y B no llegan a −2: se quedan en −1.
2. C, tal como está escrita, no quita la escritura obsoleta.
3. Los consumidores no leen solo el último mensaje (§7).
4. Que `msg=3` no tenga métricas pasa a ser el contrato, no un fallo.

## 4. Diseño

### 4.1 Contrato

- Cuando una invocación **llega a cerrar**, su último mensaje lleva `event_loop_metrics`. Los valores
  son los acumulados del objeto `Agent`, que con un `Agent` por petición coinciden con los de la
  invocación (§2.4).
- Los mensajes intermedios no llevan métricas.
- Una llamada explícita a `sync_agent()` escribe las métricas del momento en el último mensaje, sea
  cual sea el hilo desde el que se haga.
- No hay campos nuevos ni cambia la forma de `event_loop_metrics`.
- Excepciones, documentadas en §4.4: las invocaciones que no llegan a cerrar y las que no tienen
  latencia medida.

### 4.2 Mecanismo: etiquetar los callbacks de `MessageAddedEvent`

Strands registra el mismo `sync_agent` para `MessageAddedEvent` y para `AfterInvocationEvent`, y no le
dice de cuál viene. El manager no lo adivina con estado propio: **envuelve los callbacks que Strands
registra para `MessageAddedEvent`**, de modo que mientras corren una variable de contexto dice «este
sync es el de un mensaje recién añadido».

Nuevo módulo `src/mongodb_session_manager/sync_origin.py`, con el mismo patrón que `field_names.py` o
`agent_content.py`. `mongodb_session_manager.py` ya tiene 1028 líneas y no debe crecer:

```python
_syncing_added_message: ContextVar[bool] = ContextVar(
    "syncing_added_message", default=False
)


def syncing_added_message() -> bool: ...


class MessageAddedTagging:
    """Registry wrapper: callbacks registered for MessageAddedEvent run with the tag set."""

    def __init__(self, registry: HookRegistry) -> None: ...
    def add_callback(self, event_type, callback, *args, **kwargs):
        # Wraps only when event_type is MessageAddedEvent; set() / try / finally reset().
        ...

    def __getattr__(self, name): ...  # everything else goes to the real registry
```

```python
# MongoDBSessionManager
def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
    super().register_hooks(MessageAddedTagging(registry), **kwargs)


def sync_agent(self, agent: Agent, **kwargs: Any) -> None:
    super().sync_agent(agent, **kwargs)
    metrics_ops, message_ref = (
        ({}, None) if syncing_added_message() else self._build_metrics_update(agent)
    )
    config_ops, config_cache_entry = self._build_agent_config_update(agent)
    self._apply_sync_update(
        agent, metrics_ops, config_ops, message_ref, config_cache_entry
    )
```

Por qué así, frente a lo descartado:

- **No hay estado que sobreviva al callback.** El `finally` restaura la etiqueta aunque `append_message`
  o `sync_agent` lancen. La marca por `agent_id` de la primera versión se quedaba puesta si
  `create_message` lanzaba después de aplicarse, y se tragaba las métricas del cierre (Codex, P1).
- **La etiqueta es del contexto, no del manager.** Un `sync_agent()` explícito desde otro hilo no la ve
  ni la consume. Con la marca compartida, ese sync no escribía y el automático escribía métricas
  obsoletas en el `user` (Codex, P1). Dos invocaciones reentrantes (`UNSAFE_REENTRANT`) tienen cada una
  su contexto (OpenCode, P3).
- **No se duplica la lista de hooks de Strands.** El prototipo de Codex, con callbacks propios, copiaba
  `SessionManager.register_hooks()`; lo que añada una versión nueva (1.56 añade `BidiAgentStopEvent`)
  quedaría fuera. El envoltorio solo toca `MessageAddedEvent` y reenvía todo lo demás.
- Solo usa API pública: `HookProvider.register_hooks`, `HookRegistry.add_callback` (en 1.56 con
  `order=` por palabra clave, que se reenvía) y `MessageAddedEvent`. Los callbacks del session manager
  son síncronos en 1.30 y en 1.56; si alguno fuera `async`, la etiqueta se restauraría antes de que
  corriera. Un test lo fija (§5.1).

### 4.3 Casos que cubre

- **Interrupción:** el último mensaje es el `assistant(tool_use)` y recibe las métricas en el cierre.
  Al reanudar, la invocación nueva acaba con las suyas.
- **`AfterInvocationEvent.resume`:** cada vuelta cierra con sus métricas.
- **Hook que añade mensajes en `AfterInvocationEvent`** (1.30): por el orden inverso, el sync de cierre
  corre el último y escribe sobre ese mensaje.
- **Structured output forzado:** el prompt forzado es un mensaje más. `structured_output_async`
  (deprecado) reescribe el mismo snapshot, igual que hoy.
- **Varios agentes en un manager:** cada sync escribe sobre el último mensaje de su agente.
- **El sync de `MessageAdded` sigue guardando estado y configuración**, sin cambiar cuándo llegan.

### 4.4 Límites, que se documentan en CHANGELOG y en `data-model.md`

1. **Invocación que no llega a cerrar.** Si un hook de usuario lanza en `AfterInvocationEvent` antes
   del sync del manager, o si `conversation_manager.apply_management()` lanza (va antes que el evento,
   `agent.py:861-865`), no hay sync de cierre y la invocación queda sin métricas. Hoy quedaba el
   snapshot de un ciclo anterior, que tampoco era el total (1280 frente a 2560). En ese mismo caso
   Strands tampoco guarda el estado final del agente ni el de su conversation manager. Ningún diseño
   que escriba una sola vez puede evitarlo.
2. **Sin latencia medida no hay métricas**, igual que hoy: una cancelación antes de que llegue la
   metadata del modelo deja `latencyMs = 0` (`streaming.py:398-413`) y el guard de
   `_build_metrics_update` no escribe. No lo introduce este cambio.
3. **Strands 1.56 y los hooks con prioridad.** Con `HookOrder`, un hook de usuario en `SDK_LAST` corre
   después del sync de cierre. Si añade un mensaje, ese último mensaje se queda sin métricas (Codex,
   P1, modelado sobre el `HookRegistry` de 1.56). En 1.30 no pasa porque no hay prioridades. Queda
   como caso de prueba en #69.

## 5. Tests (TDD: RED antes de cada GREEN)

### 5.1 `tests/unit/test_invocation_metrics.py` (nuevo)

Con un `Agent` real, el doble in-memory y `ScriptedModel`, como `test_agent_rewrites.py`. El doble es
una subclase que registra cada `update_message_fields`.

**Fallan contra v0.14.0:**

1. `test_only_the_last_message_of_the_invocation_carries_metrics`: con una tool, el `assistant` final
   lleva `cycle_count=2`, `totalTokens=2560` y la tool en `tool_usage`; ningún otro mensaje lleva
   métricas.
2. `test_metrics_are_written_once_per_invocation_with_their_final_values`, parametrizado para N = 0,
   1 y 3 herramientas: exactamente una escritura de métricas, con los valores finales.
3. `test_a_new_prompt_does_not_inherit_the_previous_invocation_metrics`: mismo `Agent`, dos
   invocaciones.
4. `test_a_message_stored_despite_a_failing_append_still_gets_the_closing_metrics`: `create_message`
   se aplica y lanza. El último mensaje lleva métricas y los intermedios no. Tumba la marca por
   `agent_id`.
5. `test_explicit_sync_from_another_thread_does_not_steal_the_automatic_sync`: la barrera de Codex.
   El explícito escribe y el automático del hilo del agente no escribe métricas.

**Guardarraíles (pasan desde el primer día):**

6. `test_explicit_sync_agent_writes_the_current_metrics`: el flujo de un consumidor (TTFT). Tumba D.
7. `test_a_failed_invocation_records_its_metrics_on_its_last_message`: el modelo falla en el ciclo 2.
8. `test_a_failing_sync_on_a_message_does_not_cost_the_closing_metrics`: `update_agent` lanza en el
   sync de un mensaje y el cierre escribe igual (OpenCode, P2).
9. `test_config_of_a_new_agent_is_persisted_before_the_first_model_call`: el modelo falla en el ciclo 1
   y `model`/`system_prompt` ya están guardados.
10. `test_each_resumed_invocation_closes_with_its_metrics`: un hook con `AfterInvocationEvent.resume`.
11. `test_a_message_added_by_a_closing_hook_gets_the_metrics`: un hook añade un mensaje en
    `AfterInvocationEvent`.
12. `test_an_interrupted_invocation_puts_its_metrics_on_the_tool_use_message`.
13. **Límite documentado, en positivo:** `test_an_invocation_that_does_not_close_leaves_no_metrics`: un
    hook de usuario lanza en `AfterInvocationEvent`. Fija §4.4.1 para que un cambio futuro no lo altere
    sin darse cuenta.

**Del módulo `sync_origin` (`tests/unit/test_sync_origin.py`):**

14. La etiqueta está activa dentro de un callback de `MessageAddedEvent` y no dentro del de otro evento.
15. Se restaura aunque el callback lance.
16. `add_callback` reenvía `order=` y cualquier otro argumento, y el resto de atributos llega al registry
    real.
17. Todos los callbacks que el `SessionManager` del SDK instalado registra para `MessageAddedEvent` son
    síncronos. Si una versión nueva registra uno `async`, este test falla antes que la etiqueta.

### 5.2 Tests existentes

- `TestTurnWriteBudget` (`tests/unit/test_write_amplification.py`) simula el SDK llamando a mano a
  `append_message` + `sync_agent`, así que no pasa por `register_hooks`. Se reescribe para que los
  eventos pasen por un `HookRegistry` (`mgr.register_hooks(registry)` + `registry.invoke_callbacks(...)`):
  - Turno caliente de 4 mensajes: **≤8 → ≤5** (4 `$push` + 1 de métricas). Falla contra v0.14.0.
  - `test_turn_with_tool_call_stays_within_budget`: se recalcula con el mismo criterio.
  - Estos dos tests solo cuentan. El orden del ciclo de vida lo prueba §5.1, con un `Agent` real
    (Codex, P2).
- `TestSyncAgent`, `TestSyncAgentWriteCount`, `TestDuplicatedMessageIndex` y
  `TestAgentConfigHydratedOnRestore` llaman a `sync_agent()` directamente y siguen valiendo tal cual:
  son el contrato de la llamada explícita. OpenCode lo comprobó pasando la suite con el mecanismo
  aplicado: 496 unit y 121 de integración.
- `tests/integration/test_write_amplification_integration.py`:
  - `test_turn_stays_within_write_budget`: **≤10 → ≤8**, con el desglose 6 `create_message` + 2 de
    métricas.
  - Nuevo `test_intermediate_messages_carry_no_metrics`, contra MongoDB.
  - `test_metrics_land_on_the_last_message` se queda como está.

## 6. Documentación

- `CLAUDE.md`: qué mensaje lleva las métricas, en «MongoDB Schema» y en la descripción del manager;
  el módulo `sync_origin`; versión.
- `docs/architecture/performance.md` («Writes per Turn»): la tabla sigue en #65 (13). Se añaden #67
  (10) y #66 (8), con el desglose y el orden de eventos.
- `docs/architecture/data-model.md` (`event_loop_metrics`): el contrato de §4.1 y los límites de §4.4.
  La agregación de ejemplo, que suma todos los mensajes, se corrige.
- `docs/api-reference/mongodb-session-manager.md` (`sync_agent`, `register_hooks`): el sync automático
  de cada mensaje no escribe métricas; el de cierre y el explícito, sí.
- Donde hoy dice «only for assistant messages» (`docs/faq.md:231`,
  `docs/user-guide/session-management.md:570`, `docs/getting-started/basic-concepts.md:327`) pasa a
  decir «último mensaje de cada invocación». `docs/faq.md:838-843` suma sobre `list_messages()`, que
  filtra las métricas y daría 0; se sustituye por la lectura correcta.
- `CHANGELOG.md` 0.15.0, con confirmación previa. Versión en `__init__.py`, `pyproject.toml`,
  `README.md` (badge), `docs/README.md` y `CLAUDE.md`.

## 7. Compatibilidad

- **DocumentDB:** no hay operadores nuevos. Las métricas siguen yendo por `update_message_fields()`
  (`$set` posicional, validado en #54); solo hay menos escrituras. Probado en MongoDB local, no en
  DocumentDB.
- **Forma de los documentos:** sin campos nuevos ni migración. En las invocaciones nuevas, los mensajes
  intermedios no llevan `event_loop_metrics`; los documentos anteriores conservan las suyas.
- **Convivencia de versiones:** managers 0.14 y 0.15 pueden escribir en la misma sesión, y en los dos
  casos el último mensaje de cada invocación cerrada lleva métricas.
- **Un visor de sesiones consumidor**, verificado en su código por los dos revisores:
  - Las stats (`$arrayElemAt: -1`) y el total del detalle no cambian.
  - El timeline, su burbuja por mensaje y su API externa mostrarán métricas solo en el último
    mensaje de cada invocación.
  - Límite de §4.4.1: una invocación que no cierra cuenta 0 en sus stats (antes, un total parcial).
  - Aparte, sin relación con #66: sus stats suponen que `accumulated_usage` es de la sesión (lo
    sigue una issue de su repositorio). Con un `Agent` por petición es de la invocación, así que
    cuentan solo la última de cada agente.
- **Un consumidor con runtime propio**:
  - El runtime sigue funcionando: el TTFT llega por `sync_agent()` explícito.
  - Su script de análisis de latencia separa invocaciones cuando `latencyMs` baja. Con un punto por
    invocación, fusiona las consecutivas de latencia creciente; Codex lo reprodujo con una sonda
    propia. Con datos 0.15, cada punto es una invocación.
  - Otro script suyo toma el máximo de latencia en ventana y sigue funcionando.
- **Otro consumidor**: su visor se queda con el último `assistant` que tenga métricas y sigue
  funcionando. Sus scripts de análisis de feedback y de selección de muestras suman todos los
  mensajes: darán cifras menos infladas, y `n_calls` contará invocaciones. Ningún revisor lo
  verificó; viene del informe de consumidores.
- **API de la librería:** nada deja de funcionar. Lo observable es que menos mensajes llevan métricas.
  Quien sobrescriba `register_hooks()` en una subclase recibirá el registry envuelto.
- **Versión:** 0.15.0.

## 8. Fuera de alcance

- Métricas por invocación en agentes de vida larga (`latest_agent_invocation.usage` en vez del
  acumulado).
- En #69, sin abrir issue nueva: el caso `HookOrder.SDK_LAST` de §4.4.3, `BidiAgentStopEvent → sync_agent()`
  y la persistencia de `message.metadata`.
- Adaptar el script de latencia de un consumidor y avisar al visor de sesiones del alcance real de sus
  stats: son repos ajenos y se decide con Iñaki.
- Deduplicar syncs explícitos repetidos con las mismas métricas (C).

## 9. Revisión adversarial: qué se hizo con cada hallazgo

| Hallazgo | Revisor | Verificado aquí | Resolución |
|---|---|---|---|
| La marca se queda puesta si `create_message` se aplica y lanza → cierre sin métricas | Codex P1 | Sí (`verify/scenarios.py`) | Mecanismo nuevo (§4.2); test 4 |
| Un `sync_agent()` explícito desde otro hilo roba la marca | Codex P1 | Sí (`verify/race.py`) | Mecanismo nuevo; test 5 |
| Un hook de usuario que lanza en `AfterInvocationEvent` deja la invocación sin métricas | Codex P1 | Sí; hoy dejaba 1280 de 2560 | Límite §4.4.1; test 13 |
| `apply_management` que lanza impide `AfterInvocationEvent` | Codex P1 | Por lectura (`agent.py:861-865`) | Límite §4.4.1 |
| 1.56: un hook `SDK_LAST` añade el último mensaje después del cierre | Codex P1 | Por lectura; modelado por Codex | Límite §4.4.3; a #69 |
| Cancelación antes de la metadata: sin métricas | Codex P2 | Por lectura; ya pasaba | Límite §4.4.2 |
| La matriz de tests deja verdes falsos | Codex P2, OpenCode P2 | — | §5.1 ampliada (5, 8, 10-16); presupuestos solo cuentan |
| Las tablas venían de un prototipo que consumía la marca después de `super()` | OpenCode P2 | Sí | §2 medido con el mecanismo final |
| Emparejamiento `append_message` → `sync_agent` sin red | OpenCode P3 | — | Desaparece: la etiqueta no depende del emparejamiento |
| `UNSAFE_REENTRANT` | OpenCode P3 | — | Cubierto: la etiqueta es por contexto |
| Cita de `basic-concepts.md` sin ruta | OpenCode P3 | Sí | Corregida en §6 |
