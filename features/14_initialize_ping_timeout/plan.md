# Plan: techo de arranque para el ping de initialize() (#122)

Aceptado el 18 de septiembre de 2026. Pendiente de implementar.

## Objetivo

Acotar en el tiempo el `ping` que `MongoDBConnectionPool.initialize()` hace al
crear el cliente. Ese ping corre sin `pymongo.timeout`: con un servidor que
acepta TCP y luego se queda mudo, el arranque de la aplicación (el lifespan de
FastAPI, vía `initialize_global_factory()`) puede bloquearse ~35 s, porque los
presupuestos de fase —selección 5 s, socket 30 s— son independientes y se
acumulan. El resto del módulo ya acota sus comandos (`health_check()`,
`_cached_server_version()`); `initialize()` es el que se quedó sin proteger.

## Evidencia

Medida contra servidores falsos que hablan OP_MSG real, dos veces por cada
número (investigación propia y verificación adversarial independiente), con
pymongo 4.18.1. Los números que mandan en cada decisión:

| Hecho | Medido |
|---|---|
| Ping sin deadline, servidor mudo desde el arranque | 5,035 s (`ServerSelectionTimeoutError`) |
| Ping sin deadline, handshake ok y luego mudo | 30,005 s (`NetworkTimeout`) |
| Ping sin deadline, handshake retrasado 2,5 s y luego mudo | 35,015 s (reproducido dos veces: 35,011 s) |
| El mismo escenario con `pymongo.timeout(5)` | 5,004 s |
| `pymongo.timeout(0)` es «sin deadline», no «inmediato» | ping bajo `timeout(0)` bloquea los 30 s completos |
| `client.options.timeout` con `timeoutMS=0` | `0.0` (por eso un `min()` ingenuo produce `timeout(0)`) |
| Un wrapper más laxo que el `timeoutMS` del cliente lo afloja | `timeoutMS=1000` + wrapper 5 s → 5,002 s (pymongo solo instala el del cliente si no hay contexto, `_csot.py:119-126`) |
| Bajo CSOT pymongo sustituye los presupuestos de fase, no los recorta | `sst=0.5 s` + `socket=0.1 s` + `timeoutMS=3000` → falla a 3,023 s |
| `close()` del cliente antiguo en reinicialización | 30,002 s contra servidor mudo (`endSessions`), bajo el lock del singleton |
| DNS SRV de `parse_uri` en `_resolve_options()` | usa el default DNS de pymongo (20 s), no el `connectTimeoutMS` del pool; las opciones TXT no pueden llevar ninguna opción del pool |
| El ping no se reintenta | `Database.command` usa `_retryable_read(retryable=False)`; los reintentos no duplican el tiempo |
| Constructor `MongoClient` con `mongodb+srv://` | perezoso (0,006 s sin DNS): el único DNS bloqueante es el `parse_uri` previo |
| Excepciones de vencimiento | `NetworkTimeout`, `ExecutionTimeout`, `ServerSelectionTimeoutError`, `WaitQueueTimeoutError`: todas `PyMongoError` con `timeout=True` |

## Verificación

Diagnóstico confirmado por auditoría adversarial independiente (Codex,
2026-09-18), que reprodujo todas las mediciones. El diseño pasó una consulta
dual (Codex + Opus, misma especificación, sin contaminación cruzada) y una ronda
focalizada (Codex + Fable) sobre la única cuestión discrepante, la regla de
combinación del deadline. En todo lo demás hubo consenso. La divergencia
persistente —si el techo puede recortar una configuración explícita del que
llama más laxa que 5 s— la resolvió el mantenimiento eligiendo la Regla A
(techo de arranque por `min`), con el agujero del `timeoutMS=0` parcheado y los
puntos consensuados de las tres rondas incorporados.

## La regla

    I = initialize_timeout_ms          # nuevo parámetro, default 5000, None desactiva
    T = client.options.timeout         # leído del cliente construido (None | 0.0 | segundos)

    I_eff = I / 1000                   # ms → s, como health_check()
    T_eff = T if (T is not None and T > 0) else sin presupuesto
    D_eff = min(I_eff, T_eff)

    I is None  →  sin wrapper (el timeoutMS del cliente gobierna, como hoy)
    I not None →  with pymongo_timeout(D_eff): client.admin.command("ping")

Con el default: `timeoutMS` ausente o 0 → techo 5 s; `timeoutMS=1000` → 1 s
(nunca se afloja un deadline estricto); `timeoutMS=60000` → 5 s (recorte
intencional y documentado). `initialize_timeout_ms` explícito vence a todo
(`3000` bate a un `timeoutMS=60000`).

## Decisiones

1. **Un techo de arranque, no otro default de driver.** El deadline es un SLA
   del método, de la librería hacia el arranque: acota cuánto puede tardar el
   ping sea cual sea la configuración del que llama. Los valores explícitos más
   laxos (`timeoutMS=60000`, `timeoutMS=0`, `serverSelectionTimeoutMS=30000`)
   dejan de gobernar este ping concreto, y quien los necesite sube o desactiva
   el techo. Coste asumido y que hay que documentar: un servidor que tarda más
   de 5 s en estar accesible falla `initialize()` donde hoy llegaba a entrar.
2. **Parámetro pool-owned.** `initialize_timeout_ms` es keyword-only, se
   retira de `**kwargs` antes de `_resolve_options()`, no llega nunca a
   `MongoClient` (`ConfigurationError: Unknown option`, medido) ni a
   `_user_kwargs`: la clave del singleton no cambia, es un control por intento,
   y el camino rápido (`:93-100`) devuelve el cliente existente sin re-ping.
   Documentado como deliberado.
3. **Validación antes de tocar ningún cliente.** Solo int > 0 o `None`; `0`,
   negativos, `bool` y no-int son `ValueError` antes de cerrar el cliente
   antiguo (`:102-109`) o construir el nuevo: un error después escaparía del
   `except PyMongoError` dejando un cliente vivo.
4. **La política de fallo no cambia.** close-and-re-raise (`:145-162`), como
   hoy. Todas las excepciones de vencimiento caen en el `except PyMongoError`
   existente. `WARNING` como `health_check()` está descartado: el camino rápido
   devolvería para siempre un cliente cuyo ping falló, y el readiness de FastAPI
   sería deshonesto.
5. **El log nombra el deadline y su origen** («nada se descarta en silencio»,
   #111): el `ERROR` del fallo y el `INFO` del éxito dicen qué presupuesto rigió
   (`initialize_timeout_ms=5000 (default)`, `capped by client timeoutMS=1.0s`).
6. **Alcance ping-only.** El wrapper rodea solo la línea 129. El `close()` del
   cliente antiguo y el DNS SRV de `parse_uri` son otros dos bloqueos reales
   (medidos arriba) y van en issues de seguimiento: un CSOT del ping no puede
   cubrirlos honestamente.
7. **Docstrings que no mientan.** Bajo CSOT pymongo sustituye los presupuestos
   de fase por el tiempo restante (no los recorta a ellos): ni la documentación
   ni los tests deben afirmar lo contrario. En el mismo PR, el docstring de
   `health_check()` deja el «20 s» (número heredado) por los 30 s de los
   defaults actuales, y la documentación de connection-pooling recoge el
   parámetro y el edge de compatibilidad.

## Descartado

- **Degradar a `WARNING` como `health_check()`.** El radio de daño es distinto:
  `health_check()` devuelve un resultado y sigue; `initialize()` cierra el
  cliente y relanza. Cambiar a warning-and-continue dejaría el singleton
  devolviendo sin re-ping un cliente cuyo ping falló.
- **`min()` sin normalizar.** `min(5000, 0.0)` = 0 → `pymongo.timeout(0)` = sin
  deadline: peor que hoy. `None` y `0.0` se tratan como «sin presupuesto» antes
  del `min()`.
- **Regla B (explícito gana, propuesta por Opus y Fable).** No pisaría nunca una
  configuración explícita, pero dejaría a un `timeoutMS=60000` bloqueando el
  arranque 60 s con un servidor mudo sin protección salvo que el que configura
  se acuerde de pasar `initialize_timeout_ms`. Descartada por decisión del
  mantenimiento a favor del techo de arranque.
- **Cubrir `close()` y el DNS SRV en este PR.** Son problemas de ciclo de vida
  y de resolución distintos; meterlos aquí alarga el cambio y mezcla
  presupuestos que no comparten contexto.

## Criterios de aceptación

- [ ] El ping de `initialize()` no puede superar el deadline en ningún caso:
      servidor mudo 30-35 s → ~5 s, medido contra OP_MSG real, no solo mock.
- [ ] `timeoutMS=1000` da un deadline de 1 s, `timeoutMS=0` uno de 5 s, y
      `pymongo_timeout` nunca se llama con 0.
- [ ] `initialize_timeout_ms=3000` vence a un `timeoutMS=60000`; `None`
      desactiva el wrapper y el comportamiento es el de hoy.
- [ ] `0`, negativos, `bool` y no-int levantan `ValueError` sin construir ni
      cerrar ningún cliente (asertado con mocks).
- [ ] El parámetro no aparece en los kwargs de `MongoClient` ni en
      `_user_kwargs`; una segunda `initialize()` igual no recrea el cliente.
- [ ] Un ping que vence el deadline cierra el cliente y relanza; los tres tests
      existentes del ping (`:110-140`) siguen verdes.
- [ ] El `ERROR` de fallo y el `INFO` de éxito nombran el deadline y su origen
      (tests de `caplog`).
- [ ] Docstrings y `docs/user-guide/connection-pooling.md` documentan el
      parámetro, el edge de compatibilidad y la sustitución (no recorte) de
      presupuestos bajo CSOT.
- [ ] `ruff` y la suite de unitarios en verde; los de integración sin cambio de
      comportamiento en MongoDB y DocumentDB (el deadline solo aprieta casos que
      hoy ya fallan, o llega antes al mismo fallo).
