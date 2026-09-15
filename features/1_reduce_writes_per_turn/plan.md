# Plan: reducir escrituras a MongoDB/DocumentDB por turno

**Estado:** implementado en v0.10.0 (issue #54). Ver §11 para el resultado medido.
**Origen:** traza OTEL del runtime `mrg_assistant_whatsapp_runtime` (dev, eu-west-1),
sesión de `genai-mrg-assistant-ov` sobre DocumentDB, colección `ov.whatsapp`, con
mongodb-session-manager v0.9.1.
**Versión objetivo:** 0.10.0 (cambio de comportamiento interno, API pública intacta)

---

## 1. Problema

Un turno real de 12,1 s ejecuta **72 operaciones Mongo** que suman ~1,35 s (11 % del turno):

| Operación | n | Tiempo |
|-----------|---|--------|
| `update` | 28 | 1.247 ms |
| `find` | 36 | 85 ms |
| `createIndexes` | 8 | 20 ms |

Reparto por dueño en la traza: 626 ms bajo el agente Supervisor, 531 ms dentro de la
tool `info_suministro_agent` (sub-agente) y 194 ms fuera de agente (apertura y cierre
de sesión). Unos 438 ms caen **después de la última llamada al LLM**, es decir en la
ruta crítica antes de devolver la respuesta al usuario.

### Dato que gobierna el diseño

En DocumentDB **cada `update` cuesta 40-55 ms sea cual sea su tamaño**; solo los
`update_agent` pequeños bajan a 11-27 ms. Medido en la traza real por el equipo
consumidor.

Consecuencia: **el objetivo es reducir el NÚMERO de escrituras, no los bytes.**
Quitar bytes ayuda a la carga del cluster, pero no a la latencia del turno. Un banco
de pruebas contra MongoDB local no puede validar este eje (allí el commit es casi
gratis), así que la verificación final exige una traza en dev.

---

## 2. Causas confirmadas

Reproducidas en local con un `pymongo.monitoring.CommandListener`, modelo falso con
respuestas programadas y el escenario supervisor + sub-agente con 1 tool call. Salen
42 ops (la traza real tiene 72 porque su turno lleva más tool calls); lo que coincide
exactamente es la **estructura**: 8 `createIndexes`, la proporción update/find y el
reparto por agente.

### 2.1 Dos callbacks sobre el mismo evento (SDK, no nuestro)

`strands/session/session_manager.py:46-49` registra `append_message` **y** `sync_agent`
sobre el mismo `MessageAddedEvent`, más otro `sync_agent` en `AfterInvocationEvent`
(línea 52). Por cada mensaje añadido al historial salen hasta 4 escrituras. No es
configurable desde fuera; lo que sí controlamos es cuántas operaciones hace cada una.

Verificado que **el streaming no influye**: mismo turno con 1 chunk y con 200 chunks
produce idénticas 7 escrituras y 47,8 KB. Escala con mensajes (2 msgs→7 updates,
6 msgs→21, 10 msgs→35), no con tiempo ni con chunks.

### 2.2 `_capture_agent_config` incondicional — 10 updates, 481 ms (39 % del tiempo de escritura)

`mongodb_session_manager.py:452-470`. Reescribe `model` y **el system_prompt entero**
en cada `sync_agent`, sin comparar con lo ya almacenado. El system_prompt no cambia
dentro de un turno, así que 9 de cada 10 escrituras son idénticas a la anterior.

### 2.3 Métricas por mensaje — 6 finds + 6 updates, 317 ms

`_update_last_message_metrics` (`mongodb_session_manager.py:425-450`) hace un
`find_one` para resolver el último `message_id` y luego un `update_one`. El `find` es
evitable: el padre ya mantiene ese dato en memoria
(`RepositorySessionManager._latest_agent_message[agent_id].message_id`).

Además el `sync_agent` de cierre reescribe las mismas métricas sobre el mismo mensaje
que el último `MessageAddedEvent` ya había escrito.

### 2.4 `_ensure_indexes` por instancia — 8 operaciones

`mongodb_session_repository.py:197` lo llama desde `__init__`, o sea en cada
`create_session_manager()`. Son 4 `create_index` (+ uno por `metadata_field`) y pymongo
no cachea: cada uno es un round-trip aunque el índice exista. 2 managers por turno
(supervisor + sub-agente) × 4 = 8.

### 2.5 `update_agent` lee para preservar `created_at`

`mongodb_session_repository.py:376-384` hace un `find_one` previo para recuperar
`created_at` y volver a escribirlo. Innecesario: el campo ya está en el documento
(lo puso `create_agent`) y un `$set` que no lo mencione no lo toca.

### 2.6 Read-after-write sobre secundarios — corrección, no solo rendimiento

El cluster de DocumentDB del consumidor va en **`secondaryPreferred`**: las lecturas
pueden devolver el estado anterior a una escritura recién confirmada. Los `update`
siempre van al primario, pero los `find` no.

Eso convierte varias lecturas de esta librería en **read-after-write sobre una réplica
potencialmente atrasada**:

1. **`_get_last_message_id`** (`mongodb_session_manager.py:414-423`) — el caso grave.
   Se ejecuta dentro de `sync_agent`, milisegundos después de que `create_message`
   haya hecho `$push` del mensaje en el primario. Si el secundario va atrasado
   devuelve el `message_id` **anterior**, y entonces:
   - las métricas del mensaje N se escriben sobre el mensaje N-1, o
   - el filtro `agents.<id>.messages.message_id` no casa con nada y el `update_one`
     no escribe nada. `_update_last_message_metrics` **no comprueba `matched_count`**
     (línea 444), así que el fallo es silencioso.

   Lo mismo aplica a `_record_guardrail_event`, que usa el mismo helper.

2. **`update_agent`** (`mongodb_session_repository.py:376-384`) — lee `created_at` para
   reescribirlo. Sobre un secundario atrasado podría no encontrar el agente y
   sustituir el `created_at` original por `now`, falseando la antigüedad del agente.

3. **`update_message`** (`mongodb_session_repository.py:484-506`) — localiza el índice
   del mensaje a redactar recorriendo el array leído. Si el array viene atrasado, el
   índice calculado apunta a otra posición y **se redacta el mensaje equivocado**, o
   se lanza `ValueError: Message not found`.

   **Severidad: alta, no cosmética.** No es «un dato feo»: el texto que el guardrail
   quería redactar **sigue visible**, y el tachón cae sobre un mensaje inocente. Es
   contenido sensible expuesto en el Session Viewer. Que solo se dispare con guardrails
   no es un atenuante — cuando falla, falla exactamente en la dirección que el guardrail
   existe para evitar. Y es **indetectable desde el visor**: no hay checksum ni marca
   con la que contrastar (confirmado por el equipo del Control Center).

Las correcciones 2 y 3 de la Fase 1 eliminan los casos 1 y 2 de raíz: no por ahorrar
un `find`, sino porque **dejan de leer lo que ya se sabe en memoria**. Ese es el
argumento más fuerte para hacerlas, por encima de la latencia.

El caso 3 (`update_message`) no lo resuelve este plan, pero **no por ser menor**: por
ser de otra naturaleza. Arreglarlo exige `$[elem]` con `arrayFilters` en vez del índice
posicional calculado en cliente, que es un cambio de corrección con su propio test de
redacción. **Issue aparte y prioritaria**, no cola de espera de esta.

Detalle que lo hace más urgente: el `ValueError: Message not found` (línea 506) es el
caso *benigno*, porque al menos es ruidoso. El caso silencioso —índice desplazado que
sí existe— es el peligroso.

Nota: si alguna de estas lecturas resultara ser imprescindible, la salida no es leer
más sino leer bien — `ReadPreference.PRIMARY` explícito en esa operación concreta. Pero
en los casos 1 y 2 no hace falta leer en absoluto.

### 2.7 Fuera del alcance de esta librería

Identificado por el equipo consumidor en su propio repo, se arregla allí:

- `context.py::sync_and_track` llama a `sync_agent` tras el cierre de invocación:
  +1 find y +3 updates por agente (~190 ms). En el Supervisor tiene motivo (el TTFT se
  rellena después de `agent()`); en los sub-agentes no.
- `set_prompt_metadata`: 2 updates, 89 ms. Es API nuestra, pero la frecuencia de
  llamada la decide el consumidor.
- 21 `find` de `get_metadata` en `server.py`, cada uno trayendo `customer_sap_data`
  entero (37 ms en total).

---

## 3. Objetivo y criterios de aceptación

**Objetivo:** bajar de 28 a ≤12 updates por turno sin cambiar la API pública ni el
esquema del documento.

**Corrección tras implementar:** ese objetivo de 12 es del **turno real completo**, que
incluye los ahorros del lado del consumidor (quitar el sync doble de `sync_and_track`
en los sub-agentes y mover el TTFT del supervisor a un hook, ~8 updates). Esta librería
por sí sola llega a **15** en el escenario aislado equivalente, partiendo de 21. Mezclar
ambas cifras llevó a fijar un criterio que ninguna implementación honesta podía cumplir
sin la Fase 3, que está descartada. Los dos números son correctos; miden cosas distintas.

| Criterio | Verificación |
|----------|--------------|
| ≤15 updates por turno de la librería sola (supervisor + sub-agente, 1 tool call) | Test de regresión con `CommandListener` |
| 0 `createIndexes` a partir del segundo manager del proceso | Test de regresión |
| 0 `find` en `_update_last_message_metrics` cuando el mensaje está en memoria (camino caliente) | Test de regresión; el fallback con `find` se testea aparte |
| 0 `find` en `update_agent` | Test de regresión |
| API pública sin cambios | Suite actual en verde sin tocar tests existentes |
| Esquema del documento sin cambios | Tests de integración actuales en verde |
| `updated_at` **raíz** refrescado en la última escritura del turno | Test de regresión (invariante, ver §6) |
| Latencia real | Traza nueva en dev tras desplegar (lo mide el consumidor) |

---

## 4. Fases

### Fase 1 — Eliminar operaciones redundantes (bajo riesgo)

Cuatro cambios independientes, cada uno con su test de regresión primero (RED → GREEN).

1. **`_ensure_indexes` idempotente por cliente.** Registro a nivel de módulo en un
   `weakref.WeakKeyDictionary` **keyed por `MongoClient`** → set de
   `(database, collection, tuple(metadata_fields))` ya indexados, con `threading.Lock`.
   Ahorro: 8 ops → 4 en el primer manager del proceso, 0 después.
   - Corregido en revisión: keyear solo por nombre de db/colección sería incorrecto con
     **dos clientes contra clusters distintos** que usen los mismos nombres (tests,
     multi-tenant): el segundo cluster se quedaría sin índices. Keyear por cliente lo
     resuelve, y `WeakKeyDictionary` limpia la entrada sola cuando el cliente se
     cierra y se recoge. Verificado que `MongoClient` admite weakref.
   - **Impacto en tests existentes:** `tests/unit/test_session_repository.py:107,
     124, 138` afirman sobre `create_index.call_args_list`. Con el registro, el orden
     de los tests importaría. Al keyear por cliente cada test con su propio mock
     queda aislado; confirmar que `MagicMock` admite weakref o añadir fixture de reset.
   - Alternativa considerada y descartada: mover la creación al factory. Rompería el
     uso directo de `MongoDBSessionManager` sin factory, que está documentado en
     CLAUDE.md y en los ejemplos.
   - Riesgo: en un proceso longevo, si alguien borra un índice a mano no se recrea.
     Aceptable; los índices son de arranque.

2. **`_get_last_message_id` sin `find`.** Leer
   `self._latest_agent_message.get(agent_id)` y caer al `find_one` actual solo si es
   `None` (sesión restaurada sin mensajes nuevos todavía). Ahorro: hasta 6 finds.
   - **Además corrige un bug latente**: elimina un read-after-write sobre un secundario
     que puede atribuir las métricas al mensaje equivocado, en silencio (ver §2.6).
     Este es el motivo principal del cambio; el ahorro de latencia es secundario.
   - Riesgo: depende de un atributo del padre. Mitigación: `getattr` defensivo y test
     que cubra el camino de fallback.
   - Añadir comprobación de `matched_count` en `_update_last_message_metrics`, que hoy
     no existe: si el update no casa, debe registrarse en el log, no desaparecer.

3. **`update_agent` sin el `find` previo.** Quitar la lectura de `created_at` y no
   incluirlo en el `$set`. Ahorro: hasta 4 finds.
   - **Además corrige** el riesgo de falsear `created_at` con una lectura atrasada
     (ver §2.6).
   - Riesgo: si `update_agent` se llamase sobre un agente inexistente, el documento
     quedaría sin `created_at`. Hoy no ocurre (`initialize` siempre crea el agente
     antes), pero el test debe fijarlo.

4. **`_capture_agent_config` condicional.** Caché en la instancia, **dict por
   `agent_id`** → `(model_id, system_prompt)` último escrito; escribir solo si cambió.
   Ahorro: ~8 de 10 updates.
   - Corregido en revisión: el prototipo usaba una única terna, lo que con **varios
     agentes sobre un mismo manager** (patrón soportado: una sesión, N agentes) haría
     que la caché se pisara en cada alternancia y escribiera siempre. Debe ser por
     agente. El test debe cubrir dos agentes alternando en el mismo manager.
   - Nota: como el manager se crea por request, seguirá habiendo 1 escritura por turno
     y por agente. Llevarlo a 0 exigiría un `find` para comparar — cambiaría un update
     por un find, lo cual **sí** interesa en DocumentDB (85 ms los 36 finds frente a
     1.247 ms los 28 updates). Se evalúa en Fase 2 con medición, no a ciegas.

### Fase 2 — Fusionar escrituras (riesgo medio, es donde está la latencia)

5. **Un solo `update_one` para métricas + config.** Ambos se ejecutan consecutivos
   dentro de `sync_agent`, sobre el mismo documento. Combinar los `$set` usando el
   filtro con `message_id` (que matchea el mismo documento) y caer al update sin filtro
   posicional cuando no haya `last_message_id`. Ahorro: 1 update por `sync_agent`.
   - Efecto acoplado a vigilar: si el filtro posicional no casa, **fallan las dos
     partes**, no solo las métricas. Por eso la comprobación de `matched_count` (Fase
     1.2) deja de ser opcional y pasa a ser prerrequisito de este punto.

6. ~~Saltar el `sync_agent` de cierre cuando nada cambió.~~ **Descartado en revisión;
   tal como estaba escrito no habría funcionado.** Verificado en el SDK: `end_cycle`
   (`event_loop.py:198`) se ejecuta *después* del `MessageAddedEvent` del último mensaje
   y *antes* del `AfterInvocationEvent` (`agent.py:864`). Por tanto `total_duration` y
   `average_cycle_time` **siempre difieren** entre el sync del último mensaje y el de
   cierre: una comparación del payload completo nunca acertaría y el ahorro sería 0.
   - Comparar solo `accumulated_usage` + `latencyMs` (que sí están cerrados al añadir el
     mensaje) sí dispararía el salto, pero a costa de **perder la duración del último
     ciclo** en `cycle_metrics`. Es una regresión de datos a cambio de 1 update por
     agente y turno. No compensa sin saber si alguien consume `cycle_metrics`.
   - **Aviso de seguridad para cualquier variante futura:** lo que se salte debe ser
     *solo* la parte nuestra (`_update_last_message_metrics`). El
     `super().sync_agent()` del padre **nunca** se salta desde aquí: ya tiene su propia
     detección de cambios y es el que persiste `conversation_manager_state` tras un
     `reduce_context`, y refresca el `updated_at` raíz.
   - Los 438 ms posteriores al último LLM se atacan con el punto 5 (fusión) y con la
     corrección 4 de Fase 1 (config condicional), que ya dejan el cierre en 1 update
     por agente.

### Fase 3 — Evaluar, no comprometer

7. **Fusionar `create_message` + `update_agent`.** Bufferizar el `$push` de
   `append_message` y emitirlo junto al `$set` del `sync_agent` que llega
   inmediatamente después. Ahorro potencial: ~4 updates/turno (~200 ms).
   - Riesgo alto: depende del orden de callbacks del SDK y de que todo `append_message`
     vaya seguido de un `sync_agent`. Un mensaje se perdería si esa invariante se
     rompe en una versión futura de Strands.
   - **Decisión: no implementar en 0.10.0.** Medir primero el resultado de Fases 1-2
     en dev. Si hace falta más, hacerlo con un flag explícito y opt-in.

---

## 5. Estrategia de test (TDD)

Test nuevo `tests/unit/test_write_amplification.py`, sin MongoDB:

- Doble de `Collection` que registre cada llamada (`update_one`, `find_one`,
  `create_index`) con su filtro y su update.
- Asserts sobre el **número** de llamadas por escenario, que es la métrica que importa.
- Escenarios: mensaje único; turno con tool call; dos managers en el mismo proceso
  (índices); sesión nueva vs existente.

Dos tipos de test, y conviene no confundirlos porque el proyecto exige RED antes de
GREEN:

- **Tests de regresión de conteo** (RED hoy): fallan contra v0.9.1 porque documentan el
  comportamiento actual como no deseado, y pasan tras cada fase. Son los TDD de verdad.
- **Test de invariante del `updated_at` raíz** (pasa hoy): no es un test RED, es un
  *guardarraíl*. Existe para que ninguna fase —ni ninguna optimización futura— pueda
  romper lo que dos consumidores externos necesitan. Que pase sin código nuevo es
  intencionado; no es un test inútil, es un contrato.

Complemento en `tests/integration/` con `CommandListener` real contra MongoDB local,
marcado `@pytest.mark.integration`. Ojo con DocumentDB 5.0: soporta menos etapas de
agregación que mongomock, y al equipo del Control Center ya le ha pasado que algo pase
CI y reviente en producción. Aquí no usamos agregaciones en la ruta de escritura, pero
cualquier `$[elem]`/`arrayFilters` que entre por la issue del caso 3 debe validarse en
dev, no solo en local.

Orden de verificación local: `ruff format .` → `ruff check .` → `pytest tests/ -v`.

---

## 6. Impacto y compatibilidad

- **API pública:** sin cambios. Ningún método cambia de firma ni de semántica externa.
- **Esquema:** sin cambios. Los mismos campos con los mismos valores; solo se escriben
  menos veces.
- **Un efecto observable:** `agents.<id>.updated_at` dejará de refrescarse en cada
  `sync_agent` redundante. **Punto cerrado: ningún consumidor depende de él.**
  - `genai-mrg-assistant-ov`: 0 lecturas en el código que despliega (strands-agent,
    testing-chat, Lambdas, CDK, skills).
  - **Session Viewer / Control Center** (repo `genai-minari-virtual-agent-control-center`,
    main, commit `ab66c36`): verificado en código. El timeline ordena por el
    `created_at` de cada mensaje (`service.py:495, 568`), con desempate por orden de
    inserción del array `messages` gracias a la estabilidad del sort de Python; el
    exportador hace lo mismo (`conversations_export.py:137-190`). `message_id` solo se
    usa para casar eventos de guardrail por `(agent_id, message_id)`, nunca para
    ordenar. Los listados, filtros y «última actividad» van todos contra campos raíz
    (`service.py:222, 250, 680`). La única lectura de `agents.<id>.updated_at` en todo
    el repo es `service.py:520`, que lo mete en `AgentSummary` del detalle de sesión y
    no lo consume nadie: el frontend no lo pinta y la API externa ni lo expone
    (`SimplifiedAgent` en `models_external.py` no tiene el campo). Sin índice, `$match`,
    `$sort` ni agregación que lo toque.

### Invariante: `updated_at` raíz

Este es el campo que **sí** importa fuera, y hay **dos consumidores confirmados**:

1. `production_chat/generar_informe_chats.py` (genai-mrg-assistant-ov): calcula «Fin» y
   «Duración» con el `updated_at` de la raíz.
2. **Session Viewer / Control Center**: «Fin» y «Duración» del detalle de sesión y del
   export (`conversations_export.py:383-384`), más las stats agregadas
   (`service.py:815-818, 1198-1201`). Si el raíz se quedase «viejo», una sesión
   mostraría una duración corta de menos.

Ese campo **no puede dejar de refrescarse al cierre del turno**.

Verificado que las fases planificadas no lo comprometen. Solo lo escriben seis
operaciones, todas en el repositorio (`mongodb_session_repository.py:257, 313, 322,
393, 429, 515, 634`): `create_session`, `create_agent`, `update_agent`,
`create_message`, `update_message` y `add_feedback`.

Las dos operaciones que esta propuesta recorta —`_capture_agent_config` y
`_update_last_message_metrics`— viven en `mongodb_session_manager.py` y **no tocan el
`updated_at` raíz en ningún caso**. Como `create_message` se ejecuta siempre para el
último mensaje del turno, el raíz queda refrescado al final pase lo que pase. La Fase
2.6 (saltar el `sync_agent` de cierre) tampoco lo afecta, porque ese sync es posterior
al último `create_message`.

Esto se fija con un test de regresión, no se deja como suposición: cualquier fase
futura que mueva escrituras debe seguir cumpliéndolo.

### Documentación y release

- Actualizar: CLAUDE.md, README.md, `docs/ARCHITECTURE.md`, CHANGELOG.md.
- Versión 0.10.0 en los tres sitios de siempre (`__init__.py`, `pyproject.toml`,
  CHANGELOG.md) más los badges de README.md, `docs/README.md` y la línea de versión de
  CLAUDE.md.

### Deuda conocida que este plan NO toca

- **`list_messages` en la apertura de sesión** (`mongodb_session_repository.py:541`)
  proyecta el array de mensajes **completo**: en el turno 11 trae los 11 turnos de
  vuelta. Es 1 sola operación, pero su coste crece con la conversación. Es lectura, no
  escritura, y la paginación real exige coordinarse con
  `conversation_manager.removed_message_count`. Queda para otra issue.
- Atribuir métricas acumuladas a un mensaje de rol `user` (ver §9).

---

## 7. Estimación

Fases 1 y 2, más los arreglos que hace el consumidor en su repo (quitar el sync doble
de los sub-agentes y mover el TTFT del Supervisor a un hook): del orden de **12 updates
por turno, ~700 ms menos**. Estimación conjunta con el equipo consumidor, sin medir.
La validación es una traza nueva en dev cuando haya versión publicada.

---

## 8. Evidencia

Banco de pruebas: `CommandListener` de pymongo + modelo falso con respuestas
programadas + escenario supervisor/sub-agente contra MongoDB local (localhost:8550).

Desglose de un turno de 4 mensajes (un agente), 26 ops / 80,9 KB enviados:

```
update  _capture_agent_config          5 ops   73,3 KB
update  _update_last_message_metrics   3 ops    2,5 KB
update  create_message ($push)         4 ops    1,8 KB
update  update_agent                   2 ops    1,2 KB
createIndexes                          4 ops    0,6 KB
find    _get_last_message_id           3 ops
find    update_agent (lee created_at)  2 ops
find    list_messages/read_agent/read_session  3 ops
```

Prototipo de Fase 1 por monkeypatch, escenario supervisor + sub-agente con 1 tool call:

```
ACTUAL (v0.9.1)          42 ops  (21 update, 13 find, 8 createIndexes)  126,5 KB
CON LAS 4 CORRECCIONES   21 ops  (15 update,  6 find, 0 createIndexes)   37,5 KB
```

A/B que descarta el streaming como causa: 1 chunk vs 200 chunks → 7 updates y 47,8 KB
en ambos casos.

**Salvedad:** los KB de este banco son orientativos. En DocumentDB el coste lo marca el
número de escrituras, no su tamaño.

---

## 9. Detección del §2.6 caso 1 sobre datos que ya existen

No hace falta esperar a la versión nueva para saber si el bug se ha materializado. En
funcionamiento correcto, **el último mensaje del array de un agente con actividad
siempre debería llevar `event_loop_metrics.accumulated_usage`**, porque el `sync_agent`
de `AfterInvocationEvent` es posterior al último `create_message`. Si no lo lleva, algo
falló.

Agregación de diagnóstico (solo lee, no devuelve contenido de mensajes ni PII):

```js
db.<coleccion>.aggregate([
  {$project: {agents_arr: {$objectToArray: "$agents"}}},
  {$unwind: "$agents_arr"},
  {$project: {
    agent_id: "$agents_arr.k",
    last_msg: {$arrayElemAt: ["$agents_arr.v.messages", -1]},
    n_msgs:   {$size: {$ifNull: ["$agents_arr.v.messages", []]}},
    any_usage: {$anyElementTrue: {$map: {
      input: "$agents_arr.v.messages", as: "m",
      in: {$gt: [{$ifNull: ["$$m.event_loop_metrics.accumulated_usage.totalTokens", 0]}, 0]}
    }}}
  }},
  {$match: {any_usage: true, "last_msg.event_loop_metrics.accumulated_usage": {$exists: false}}},
  {$project: {_id: 0, session_id: "$_id", agent_id: 1, n_msgs: 1, last_role: "$last_msg.role"}}
])
```

Firma: el agente tiene métricas en algún mensaje pero **no en el último**.

**Segunda firma equivalente:** `event_loop_metrics.tool_usage` presente en mensajes
anteriores y ausente en el último. Es también un running total, cuelga del mismo
sub-documento y se escribe en la misma operación, así que cae con el mismo fallo. Sirve
para contrastar.

**Impacto en el Control Center, corregido al alza:** no son dos agregaciones sino
**cuatro** usos del `$arrayElemAt: [..., -1]` en `service.py` (`:753` tokens por
sesión/día, `:902` atribución por modelo, `:1208` desglose por agente y export, `:1392`
uso de herramientas). El cuarto significa que el caso 1 no solo borra los tokens del
agente en sus stats: borra **su uso de herramientas entero**. Lo blindan en su issue
`minari-tech/genai-minari-virtual-agent-control-center#285`, que recoge la invariante
del `AfterInvocationEvent` y los dos escenarios que la rompen, con el turno abortado
marcado explícitamente como «este no lo corrige nadie».

**Decisión tomada:** la consulta de diagnóstico en dev **no se lanza por ahora**. Se ha
priorizado blindar el lado del visor. Este plan no depende de ese resultado.

**Un resultado no prueba el bug de esta librería, pero es una anomalía real.** El equipo
del Control Center advirtió primero de que sus agregaciones hacen
`{$arrayElemAt: [..., -1]}` a ciegas y ya dan 0 «por diseño». Revisado a la luz de la
invariante de arriba, esa advertencia se debilita: si el último mensaje *siempre* debería
llevar métricas, ese `[-1]` no es una lotería sino una lectura que debería acertar
siempre, y un 0 con métricas en mensajes anteriores es una anomalía, no ruido de fondo.

Queda en su forma fuerte esta otra: **no atribuirlo a replicación sin descartar otras
causas**. En particular, un turno que aborta entre el `create_message` y el `sync_agent`
(excepción, timeout, OOM del runtime) deja exactamente la misma firma sin que la
replicación tenga nada que ver. Antes de concluir, cruzar los `session_id` que salgan
con errores del runtime en esa ventana temporal.

**Corroboración cruzada del modelo.** El Control Center tiene documentado como gotcha
que `accumulated_usage` aparece en mensajes de **cualquier rol**, no solo `assistant`, y
por eso su backend lee de todos los roles. Esa observación, hecha de forma independiente
y antes de este análisis, es justo lo que predice el código: `_get_last_message_id`
devuelve el último mensaje del array sin mirar el rol, así que las métricas caen donde
caigan. Modelo y observación encajan.

(Efecto secundario a considerar algún día, fuera de este plan: atribuir las métricas
acumuladas a un mensaje de rol `user` —un `toolResult`— es semánticamente discutible.
**No se toca**, y ahora con motivo concreto: el visor lo lee de todos los roles a
propósito, y cambiar dónde caen las métricas le rompería los cuatro sitios de arriba a
la vez, justo mientras los está arreglando. Es un contrato de facto.)

La query excluye correctamente el 0 legítimo: un agente registrado sin mensajes produce
una fila de 0 tokens válida en el pipeline del visor (que usa
`preserveNullAndEmptyArrays: true`), y la condición `any_usage: true` la deja fuera.

Tampoco permite **distinguir los dos modos de fallo**: tanto «el update no casa con
nada» como «las métricas del N se escriben sobre el N-1» dejan el último mensaje sin
`accumulated_usage`, o sea el mismo síntoma. El detalle de sesión sí los separaría: es
robusto (`service.py:486-493` recorre todos los mensajes y se queda con el último
`accumulated_usage` que encuentre), así que enseñaría un total plausible en el segundo
modo y uno incompleto en el primero.

Si en el futuro se lanza (requiere credenciales de lectura contra DocumentDB dev), el
cruce con los errores del runtime en la ventana temporal sigue siendo obligatorio antes
de atribuir nada a replicación.

## 10. Resultado medido

Mismo banco de pruebas, mismo escenario (supervisor + sub-agente, 1 tool call), contra
MongoDB local. Turno estable (la sesión ya existe):

| | v0.9.1 | v0.10.0 |
|---|---|---|
| `update` | 21 | 15 |
| `find` | 13 | 6 |
| `createIndexes` | 8 | 0 |
| **total** | **42** | **21** |

**50 % menos operaciones.** Las 15 escrituras restantes son 6 `create_message`, 8 syncs
fusionados y 1 `update_agent`; bajar de ahí exige la Fase 3, descartada.

Validación pendiente: traza nueva en dev, que es el único sitio donde se puede medir el
eje que importa (latencia por escritura en DocumentDB).

## 11. Pendiente antes de implementar

- [ ] Revisión de este plan
- [ ] Issue en GitHub (workflow-issue-driven, Phase 0)
- [x] Confirmar que ningún consumidor depende de la granularidad de
      `agents.<id>.updated_at` — confirmado por el equipo de genai-mrg-assistant-ov
      sobre su repo; invariante del `updated_at` raíz verificada en §6
- [x] Confirmar con quien mantenga el **Session Viewer / Control Center** si su
      timeline ordena por `agents.<id>.updated_at` — **no**; verificado en código
      (commit `ab66c36`), ordena por `created_at` del mensaje. Ver §6
- [x] ~~Decidir si la Fase 2.6 necesita flag~~ — descartada en revisión (ver Fase 2.6)
- [ ] Al implementar 1.1: confirmar que `MagicMock` admite weakref, o añadir fixture de
      reset del registro de índices
