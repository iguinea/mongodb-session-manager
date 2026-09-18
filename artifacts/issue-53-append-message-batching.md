# Evidencia del lote de mensajes por invocación (#53)

Fecha: 18 de septiembre de 2026

## Decisión

**Se agrupan los mensajes que produce el event loop y se vuelcan en un solo
`$push: {$each: [...]}` al cerrar la invocación. La pregunta del usuario se
sigue escribiendo al llegar.**

La issue proponía bufferizar *todos* los mensajes y volcarlos en el sync. Eso se
descarta: difiere la durabilidad de la pregunta del usuario durante todo el
turno, que con una herramienta lenta son decenas de segundos, y la pregunta es
lo único de un turno que nada puede volver a producir. El resto —`toolUse`,
`toolResult`, la respuesta— lo reproduce el modelo si hace falta reintentar.

El turno de referencia pasa de **8 a 4 escrituras** y de 14 a 10 comandos.

## Lo que hace que el lote sea seguro

`AfterInvocationEvent` sale de un `finally` en `strands/agent/agent.py`
(1.56.0, `_run_loop`, líneas 1556-1570). Una invocación que revienta —el modelo
caído, una herramienta que lanza, una cancelación— **también cierra**, así que
el lote se escribe igual. Lo que no sobrevive es el proceso muriendo de golpe, y
esa ventana es la única que el batching añade.

Tres decisiones de diseño que la issue no anticipaba, todas descubiertas
escribiendo los tests:

1. **Un mensaje añadido fuera de una invocación no espera.** Un hook registrado
   con `order=HookOrder.SDK_LAST` puede añadir mensajes después del sync de
   cierre (#69), y ahí ya no hay nada que vaya a volcarlos. El manager registra
   sus propios callbacks en `BeforeInvocationEvent` y `AfterInvocationEvent`, y
   solo difiere lo que ocurre entre ambos. El de cierre además vuelca otra vez,
   lo que cubre los dos órdenes posibles frente a un hook así.
2. **Un lote que falla no se reintenta.** Una escritura que lanza puede haberse
   aplicado igualmente — un `update` que llega al servidor y pierde el ack es el
   caso que `test_invocation_metrics.py` ya guardaba. Reintentarlo duplicaría
   los mensajes del turno, que es peor que la pérdida que evitaría. Se pierde el
   lote, exactamente como se perdía un `create_message` fallido, de uno en uno.
3. **`super().sync_agent()` va en un `try/finally`.** El estado del agente y los
   mensajes son escrituras distintas; antes de #53 un `update_agent` que fallaba
   no costaba mensajes, porque ya estaban escritos. Ahora sí los costaría, así
   que el flush corre aunque super() haya lanzado.

Regalo del rediseño: las métricas de la invocación viajan **dentro** del `$push`,
en el documento del último mensaje. El event loop solo las tiene acumuladas al
cerrar (#66), que es justo cuando se vuelca el lote, así que dejan de costar una
escritura propia.

## Presupuesto del turno de referencia

Supervisor + sub-agente + una herramienta, sesión caliente
(`tests/integration/test_write_amplification_integration.py`).

| Hito | Comandos | `update` | `find` | `aggregate` |
|---|---:|---:|---:|---:|
| v0.9.1 | 42 | 21 | 13 | — |
| #54 (v0.10.0) | 21 | 15 | 6 | — |
| #65 (v0.10.1) | 19 | 13 | 6 | — |
| #67 (v0.14.0) | 16 | 10 | 6 | — |
| #66 (v0.15.0) | 14 | 8 | 6 | — |
| **#53** | **10** | **4** | 4 | 2 |

Las 4 restantes son 2 preguntas de usuario (una por invocación: la del
supervisor y la del sub-agente) y 2 cierres. **No bajan con más herramientas**:
un agente con N tools escribía 2N+2 y ahora escribe 2.

## Medición

Harness de #60, `--profile full`, historial de 100 mensajes, 30 repeticiones
cronometradas. `base` es 5047337 (v0.22.0); `head`, el lote de esta issue.
Ficheros: `artifacts/bench-issue53-{base,head}-{mongodb,docdb}.json`.

### Comandos por operación — idénticos en los dos motores

| Operación | base | head |
|---|---:|---:|
| `turn.simple` | 7,0 | **6,0** |
| `turn.tool` | 9,0 | **6,0** |
| `turn.supervisor` | 15,5 | **11,5** |

`$push` con `$each` se comporta igual en DocumentDB 5.0 que en MongoDB 8.2.7: el
mismo número de comandos por operación en los tres escenarios. No hace falta
adaptación por motor.

### MongoDB 8.2.7 local (`h100/c1`)

| Operación | base p50 | head p50 | cambio | base op/s | head op/s |
|---|---:|---:|---:|---:|---:|
| `turn.simple` | 4,333 ms | 3,404 ms | −21,4 % | 120,5 | 154,1 |
| `turn.tool` | 12,969 ms | 5,462 ms | −57,9 % | 51,2 | 101,6 |
| `turn.supervisor` | 16,350 ms | 11,303 ms | −30,9 % | 51,0 | 67,9 |

### DocumentDB 5.0 DEV (`h100/c1`)

| Operación | base p50 | head p50 | cambio | base op/s | head op/s |
|---|---:|---:|---:|---:|---:|
| `turn.simple` | 262,008 ms | 168,023 ms | −35,9 % | 2,1 | 2,6 |
| `turn.tool` | 357,496 ms | 173,865 ms | −51,4 % | 1,7 | 2,5 |
| `turn.supervisor` | 864,436 ms | 547,493 ms | −36,7 % | 0,9 | 1,2 |

### DocumentDB 5.0 DEV bajo concurrencia (`turn.supervisor/h100/c16`)

| Métrica | base | head | cambio |
|---|---:|---:|---:|
| p50 | 5.623,9 ms | 3.803,8 ms | −32,4 % |
| p95 | 8.993,5 ms | 6.248,3 ms | −30,5 % |
| p99 | 10.046,9 ms | 7.271,5 ms | −27,6 % |
| Throughput | 1,5 op/s | 2,2 op/s | +46,7 % |
| Lag del loop p99 | 5.761,1 ms | 4.605,1 ms | −20,1 % |

El cluster DEV se arrancó para esta medición (estaba `stopped`). La primera
pasada de `head` salió con la caché fría (p99 de 3 s en `turn.simple`); la tabla
usa la segunda, tomada después de la de `base`.

### Bytes

Prácticamente iguales: 74.781 B de respuesta en `turn.supervisor` head contra
75.029 B base. El lote no transfiere menos, hace menos viajes. Es la misma
conclusión de #54: en DocumentDB lo que cuesta es el número de round-trips, no
su tamaño.

## Los cinco invariantes de la issue

Cada uno con el test que lo fija, todos ejecutados contra MongoDB **y**
DocumentDB (161 de integración en ambos motores, más 848 unitarios).

| # | Riesgo | Resultado | Dónde |
|---|---|---|---|
| 1 | Durabilidad: una invocación que revienta pierde el turno | La pregunta está en disco mientras el modelo responde; el resto se escribe en el `finally` del cierre | `TestWhatABatchMayNotCost::test_the_question_is_stored_before_the_model_answers`, `::test_a_turn_that_blows_up_keeps_its_messages` |
| 2 | `redact_latest_message()` usa el posicional sobre un mensaje que no existe | El lote se vuelca antes de redactar | `test_message_batching.py::test_a_redaction_waits_for_the_message_to_exist` |
| 3 | `get_last_message_ref()` y `count_messages()` leen del servidor lo que está en memoria | `_get_last_message_ref()` ya prefería el `SessionMessage` en memoria (#78) y no cambia; `get_message_count()` suma los pendientes del propio manager | `test_message_batching.py::test_the_message_count_sees_what_is_pending` |
| 4 | Dos managers sobre el mismo agente no se ven hasta el flush | La ventana crece, pero el `storage_id` de #78 sigue nombrando el mensaje correcto y el array sólo crece por el final | `test_an_unchanged_agent_does_not_overwrite_another_manager` (sin cambios) |
| 5 | Un lector en vivo ve el turno aparecer de golpe | **Cambio de comportamiento observable**, ver abajo |

### El único cambio que se ve desde fuera

Quien lee la colección en vivo —un visor de sesiones, que la consulta sin pasar
por la librería— veía aparecer cada mensaje del turno según ocurría. Ahora ve la
pregunta al llegar y el resto del turno junto, al cerrar la invocación.

`updated_at` de la raíz sigue avanzando con el turno, así que el «Fin» y la
«Duración» que un visor calcula con él **no cambian**: el flush es lo último que
ocurre en la invocación (`test_root_updated_at_advances_with_the_turn`).

## Dos bordes que el lote no rompe

- **Un `sync_agent()` explícito desde otro hilo** (el flujo de quien escribe el
  TTFT en el agente y sincroniza a mano) vuelca el lote que hubiera en vuelo. Se escriben los
  mismos mensajes, en el mismo orden, solo que antes de tiempo: se pierde el
  ahorro de esa invocación, no la corrección. `list.append` y `dict.pop` son
  atómicos bajo el GIL, así que no hay estado a medias.
  Fijado por `test_explicit_sync_from_another_thread_does_not_steal_the_automatic_sync`.
- **Una invocación anidada del mismo `agent_id`** —un agente registrado como
  herramienta de sí mismo— cerraría la ventana del padre al cerrar la hija, y el
  lote del padre saldría en dos escrituras en vez de una. Otra vez, escrituras de
  más, nunca pérdida ni desorden.

## Límites de tamaño de `$each`

No introduce un límite nuevo. El comando lleva solo los mensajes del turno, y el
documento de sesión donde aterrizan ya está acotado a 16 MiB por BSON: un turno
que no cupiera en el comando tampoco cabría en el documento, y habría fallado
igual escribiendo mensaje a mensaje. Un lote típico son 3 mensajes.

## Lo que la issue proponía y no se hizo

- **Bufferizar el turno entero** (incluida la pregunta): descartado por
  durabilidad, arriba.
- **`self.session_repository.collection.update_one(...)` desde el manager**, como
  en el ejemplo de la issue: el manager no toca la colección, por #80. El lote
  va por `create_messages()`, un método de dominio del repositorio, con su doble
  in-memory y sus casos en la suite de contrato.
- **Fusionar las cuatro escrituras de `sync_agent`**: ya estaba hecho por #65,
  #66 y #67 antes de esta issue.

## Lo que queda del turno de referencia

4 escrituras (2 preguntas + 2 cierres), 4 lecturas y 2 agregaciones. Las lecturas
son territorio de #57 y #58, ya cerradas; bajarlas más exigiría el cambio de
esquema de #63.
