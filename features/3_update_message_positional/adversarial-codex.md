# Revisión adversarial del plan de `update_message()` posicional (#64)

## Veredicto

**RECHAZADO.** El `$set` posicional propuesto es sintácticamente correcto y arregla la sustitución del subdocumento completo, pero no garantiza actualizar *el* mensaje correcto mientras `message_id` pueda duplicarse y su supuesto test de concurrencia pase ya con el código actual. Antes de implementar hay que definir una identidad de mensaje estable, limitar explícitamente los campos actualizables, corregir las afirmaciones sobre la carrera y las métricas, y convertir el plan de tests en una regresión realmente discriminante.

## Hallazgos

1. **P1 — `message_id` no es una identidad única bajo la concurrencia que el plan dice soportar; el posicional puede seguir redactando el mensaje equivocado.**

   - MongoDB documenta que `$` representa **el primer elemento** que casa con la consulta, no un elemento único ([documentación oficial](https://www.mongodb.com/docs/manual/reference/operator/update/positional/)). Lo confirmé contra MongoDB 8.2.7 con exactamente la forma propuesta:

     ```text
     duplicate_result: {'matched': 1, 'modified': 1,
       'messages': [
         {'message_id': 7, 'tag': 'first', 'redact_message': 'X'},
         {'message_id': 7, 'tag': 'second'}]}
     ```

   - Los duplicados no son una corrupción meramente hipotética. En `strands-agents==1.30.0` (fijado en `uv.lock:1738-1739`), cada `RepositorySessionManager` restaura localmente el último mensaje (`.venv/lib/python3.12/site-packages/strands/session/repository_session_manager.py:215-221`) y calcula el siguiente ID como `latest.message_id + 1` en memoria (`:77-86`). Dos managers/procesos que restauren a la vez el mismo agente pueden hacer `$push` del mismo ID; `create_message()` no comprueba unicidad ni versión (`src/mongodb_session_manager/mongodb_session_repository.py:488-511`).
   - El mismo supuesto afecta ya a `_record_guardrail_event()` y `_apply_sync_update()`, que localizan por `message_id` y `$` (`src/mongodb_session_manager/mongodb_session_manager.py:296-307` y `:482-488`). Por tanto, cambiar solo `update_message()` no cierra la vía de atribuir redacción, auditoría o métricas al primer duplicado.
   - **Corrección propuesta:** introducir al crear cada elemento una identidad de almacenamiento inmutable y no derivada del índice (por ejemplo, UUID), conservarla en el objeto cacheado y al reconstruirlo, y usarla en todos los updates posicionales. Si no se amplía el alcance, el plan debe declarar que dos managers no pueden escribir el mismo agente, hacer cumplir esa exclusión y añadir un test que la demuestre; no puede prometer seguridad bajo turnos concurrentes.

2. **P1 — I5 no reproduce el defecto y la premisa de que cualquier cambio concurrente desplaza el índice es falsa para las operaciones reales del repositorio.**

   - `create_message()` solo hace `$push` al final del array (`mongodb_session_repository.py:502-510`); no hay método que inserte al principio, elimine ni reordene mensajes. Un append no cambia el índice de los elementos ya leídos. Un mensaje de otro agente vive en otra ruta. Una réplica atrasada ve un prefijo más corto: si ve el objetivo, su índice sigue siendo el mismo; si aún no lo ve, el código actual falla con `ValueError` en vez de escribir otro elemento.
   - Ejecuté la I5 descrita —dos repositorios, dos mensajes con IDs distintos y dos `update_message()` paralelos— cincuenta veces sobre el código actual:

     ```text
     I5_current_code_smoke: {'correct_runs': 50, 'total': 50}
     ```

     Esto no prueba ausencia universal de carreras, pero sí demuestra que I5 no es RED y que su interleaving no desplaza nada.
   - También forcé un `$push` normal entre el `find_one` y el `update_one` parcheando `_agent_exists`, precisamente una de las ideas de §5.2. El código viejo siguió actualizando el ID 2 y dejó intacto el append:

     ```text
     append_forced_between_read_write_current:
       [(1, None), (2, {'role': 'user', 'content': [{'text': 'R2'}]}), (99, None)]
     ```

   - Sí existe una ventana si un escritor externo hace prepend, `$pull`, reordena/reemplaza el array o `create_agent()` sustituye el agente entero. El plan no identifica cuál de esas operaciones forma parte del contrato ni aporta una traza real de producción.
   - **Corrección propuesta:** separar los dos bugs demostrados —pérdida de campos y round-trip innecesario— de la amenaza de desplazamiento. Si los escritores externos que reordenan están soportados, crear una regresión determinista con barrera: el updater lee; un segundo hilo ejecuta, por ejemplo, `$push` con `$position: 0`; solo entonces se libera el update viejo. No parchear únicamente `_agent_exists`: tras el fix ese hook ya no se ejecutaría y el test pasaría sin realizar ninguna mutación concurrente. Añadir además el caso concurrente realmente peligroso de dos managers generando el mismo `message_id`.

3. **P1 — derivar el esquema de escritura de `session_message.__dict__` es una superficie abierta, no una ventaja de compatibilidad.**

   - Hoy `SessionMessage` tiene exactamente cinco campos (`message`, `message_id`, `redact_message`, `created_at`, `updated_at`), confirmado con `uv run python` sobre `strands-agents 1.30.0`; por eso la comprensión de §2 produce hoy cinco rutas netas tras excluir dos y sobrescribir `updated_at`. Pero el dataclass no usa `slots`: `__dict__` admite atributos adicionales ajenos al contrato.
   - Un campo nuevo válido de Strands alteraría el esquema Mongo sin revisión ni migración. Si coincide con `event_loop_metrics` o `guardrail_event`, vuelve a pisar precisamente los campos que se quieren proteger; si contiene un valor no BSON, convierte una redacción en error de serialización; si se renombra un timestamp, deja de quedar cubierto por `_MESSAGE_IMMUTABLE_FIELDS` y el nombre anterior queda huérfano.
   - Un campo declarado por Python no puede llevar `.` o `$`, pero sí se puede colar una clave arbitraria en el `__dict__` mutable. La prueba real con la comprensión propuesta produjo estos resultados:

     ```text
     dot matched=1 ... 'x': {'y': 1}
     dollar matched=1 ... '$hidden': 1
     conflict WriteError 40 Updating the path
       'agents.a.messages.$.message.foo' would create a conflict at
       'agents.a.messages.$.message'
     ```

     MongoDB explica que el punto se interpreta como ruta y desaconseja ambos caracteres; algunos usos no se pueden consultar/indexar sin `$getField`/`$setField` ([documentación oficial](https://www.mongodb.com/docs/manual/core/dot-dollar-considerations/)).
   - `redact_message=None` no es un problema nuevo: hoy el reemplazo completo ya guarda `None`, la propuesta también lo haría y `SessionMessage.to_message()` devuelve entonces `message`. Es un *clear* explícito, no “campo sin cambio”.
   - **Corrección propuesta:** construir un allowlist explícito con `message`, `redact_message` y `updated_at`, que es además lo que proponía la issue original. Todo campo nuevo del SDK debe requerir una decisión consciente de persistencia, tipo y migración. Añadir un test que inyecte un atributo extra y compruebe que no se escribe.

4. **P1 — la secuencia “U1–U7 + I1–I5 (fallan)” no es TDD RED; varios tests pasan antes del fix y uno de los principales es inerte.**

   Evidencia por inspección del test propuesto contra `mongodb_session_repository.py:550-608` y mediante MongoDB real:

   | Test | Antes del cambio | Motivo |
   |---|---:|---|
   | U1 | FALLA | hoy hay un `find_one` (`:563-565`) |
   | U2 | FALLA | el update actual filtra solo por `_id` (`:588-590`) |
   | U3 | FALLA | escribe `messages.<índice>` (`:592`) |
   | U4 | **PASA** | tal como está redactado solo busca que no existan `messages.$.created_at` ni `messages.$.message_id`; hoy no existe ninguna ruta posicional |
   | U5 | FALLA | sin mock de `find_one`, el fixture devuelve `None` (`tests/conftest.py:19`) y aparece el error de agente, no el de mensaje |
   | U6 | FALLA | hoy `redact_message` está dentro de `messages.0`, no en `messages.$.redact_message` (`tests/unit/test_session_repository.py:695-728`) |
   | U7 | FALLA | sin documento leído, hoy se aborta antes de `update_one` |
   | I1 | FALLA | ejecución real dejó ausentes ambos campos inyectados: `{'event_loop_metrics' in raw, 'guardrail_event' in raw} == {False}` |
   | I2 | **PASA** | ejecución real: `before_type=datetime`, `after_type=datetime`, `equal=True`, `updated_greater=True` |
   | I3 | **PASA** | ejecución real: `ValueError Message 99 not found` |
   | I4 | **PASA** si solo exige `ValueError` | ejecución real: `ValueError Agent missing not found in session s`; solo sería RED si aserta el texto unificado exacto |
   | I5 | **PASA** | 50/50 ejecuciones correctas con el código actual |

   El test de coste sí sería RED: hoy hay un `find` y un `update`. No es obligatorio que todo test nuevo falle antes, pero §3 lo presenta como batería RED y §7.2 afirma expresamente que todos fallan.

   **Corrección propuesta:** reforzar U4 exigiendo también las rutas mutables posicionales, etiquetar I2/I3/I4 como tests de contrato que ya son GREEN y sustituir I5 por la barrera con desplazamiento real o, preferiblemente, por la colisión de IDs de dos managers. Mantener I1 y el contador de comandos como las regresiones RED sólidas.

5. **P2 — el matiz de `guardrail_event` es cierto, pero las conclusiones sobre historial y métricas están sobregeneralizadas.**

   - El orden está verificado: `MongoDBSessionManager.redact_latest_message()` llama primero a `super()` (`src/mongodb_session_manager/mongodb_session_manager.py:242-247`), el padre asigna `redact_message` y llama al repositorio (`.venv/.../repository_session_manager.py:96-100`), y solo después se ejecuta `_record_guardrail_event()` (`mongodb_session_manager.py:248-259`). Por tanto, **el evento de esa redacción sobrevive hoy**.
   - En el flujo normal tampoco es realista el caso “`_get_last_message_id()` devuelve `None`”: el padre ya exige que `_latest_agent_message[agent_id]` no sea `None`, y el override prefiere exactamente ese cache (`mongodb_session_manager.py:517-528`). Un update directo del repositorio sí carece, naturalmente, del evento posterior.
   - En una segunda intervención, el evento de mensaje anterior se borra transitoriamente con el código viejo, pero `_record_guardrail_event()` vuelve a hacer `$set` sobre el mismo campo y lo reemplaza con el evento nuevo (`:296-305`). El arreglo campo a campo tampoco conservará un historial en ese campo singular; el historial real está en `guardrail_events`, al que se hace `$push` (`:305`). I1 demuestra preservación a nivel repositorio, no preservación histórica en el flujo del manager.
   - “`event_loop_metrics` se pierde siempre” es falso. En el primer turno Strands reinicia la invocación antes de añadir el input (`.venv/.../agent.py:746-766`), el mensaje se añade en `:831`, y la redacción ocurre durante el stream en `:840-854`; las métricas del modelo se actualizan después de añadir la respuesta (`.venv/.../event_loop/event_loop.py:408-414`). `_build_metrics_update()` no escribe si la latencia acumulada es cero (`mongodb_session_manager.py:412-416`). En turnos posteriores las métricas son acumuladas y pueden haberse escrito sobre el nuevo input por los hooks `MessageAddedEvent -> append_message -> sync_agent` (`.venv/.../session_manager.py:45-52`), de modo que entonces sí pueden ser borradas por la redacción. Es condicional, no universal.
   - **Corrección propuesta:** redactar CHANGELOG y docs como “`update_message()` deja de borrar campos de extensión ya presentes”. Decir explícitamente que el evento de la misma redacción ya sobrevivía. Mantener I1 como test directo y, si se quiere afirmar impacto de turno real, añadir un fake model con guardrail para primer turno y turno posterior.

6. **P2 — dejar de escribir `created_at` es correcto para datos creados por el repositorio, pero elimina una reparación de facto de documentos antiguos o incompletos.**

   - No existe una ruta normal de `create_message()` sin timestamp: el método sobrescribe incondicionalmente `created_at` y `updated_at` con `datetime` (`mongodb_session_repository.py:496-499`). En ese contrato, omitir `created_at` del `$set` conserva valor y tipo, y no introduce conversión de ISO string a datetime.
   - Sí existe un cambio observable para datos preexistentes incompletos. Inserté un mensaje sin `created_at` y el `update_message()` actual lo rellenó:

     ```text
     legacy_missing_created_backfilled_by_current:
       {'has_created_at': True, 'type': 'datetime'}
     ```

     La propuesta lo dejaría ausente. Además, `list_messages()` ordena con `x.get("created_at", "")` (`mongodb_session_repository.py:628-631`); una mezcla real de datetime y campo ausente produjo `TypeError: '<' not supported between instances of 'str' and 'datetime.datetime'`.
   - I2 no detecta esta diferencia porque ya pasa con el código viejo.
   - **Corrección propuesta:** documentar expresamente que no se soporta/backfillea el dato legado, o endurecer lectura/ordenación y añadir un test de mensaje sin timestamp. No reinyectar el ISO del dataclass cacheado, porque eso sí cambiaría tipo y reabriría el read-before-write.

7. **P2 — la ruta bajo una clave dinámica funciona solo si `agent_id` es seguro para dot notation; Strands permite IDs que no lo son.**

   - Para `agent-1` el experimento real dio `matched_count=1`, y solo se atraviesa un array, por lo que no aplica la limitación de `$` sobre arrays anidados de MongoDB.
   - Pero Strands 1.30.0 solo rechaza separadores de ruta (`.venv/lib/python3.12/site-packages/strands/_identifier.py:14-30`); acepta `a.b` y `$...`. Una clave BSON literal `agents["a.b"]` no casó con `agents.a.b.messages...`, y escribir esa dot path creó `agents.a.b` como objetos anidados:

     ```text
     literal_dot_agent_id: {'matched': 0, ...}
     dot_path_constructs_nested: {'agents': {'a': {'b': {'messages': [...]}}}}
     ```

   - Es un defecto transversal ya existente en `create_agent`, `read_agent`, `create_message`, métricas y guardrails, no introducido por este cambio; aun así hace falsa cualquier afirmación incondicional sobre “clave dinámica”.
   - **Corrección propuesta:** validar/normalizar IDs Mongo-safe en la frontera del repositorio o codificar las claves; añadir tests con `.` y `$`. Si queda fuera de #64, abrir issue y acotar el plan a IDs seguros.

8. **P2 — la justificación de compatibilidad con DocumentDB está desactualizada y la forma exacta no fue verificada allí.**

   - AWS documenta que `$` actualiza el primer elemento coincidente ([operador `$`](https://docs.aws.amazon.com/documentdb/latest/devguide/dollar-update.html)) y marca `$`, `$[]` y `$[<identifier>]` como soportados en 3.6, 4.0, 5.0, 8.0 y Elastic ([matriz oficial](https://docs.aws.amazon.com/documentdb/latest/devguide/mongo-apis.html)). Por tanto, “`arrayFilters`: soporte desigual en DocumentDB” (`plan.md:171`) ya no es una razón válida.
   - El `$` simple sigue siendo suficiente y más pequeño aquí si existe una identidad única. No dispongo de un clúster DocumentDB para probar la combinación exacta de objeto dinámico + array de subdocumentos; que #54 use una forma parecida en el código no es evidencia de producción aportada por este repositorio.
   - **Corrección propuesta:** citar la matriz actual y marcar la semántica exacta como no verificada en DocumentDB, o ejecutar una smoke test allí. No usar compatibilidad antigua para decidir entre operadores.

9. **P3 — el contrato de errores interno no rompe consumidores encontrados, pero el plan describe de forma incompleta lo que colapsa.**

   - El código actual puede emitir tres estados: agente/sesión ausente durante el read (`mongodb_session_repository.py:567-568`), mensaje ausente (`:584-585`) y sesión borrada entre read y write (`:599-600`). La escritura única solo conoce “el filtro compuesto no casó”.
   - El barrido completo del repositorio encontró como única aserción textual `pytest.raises(..., match="Message 99 not found")` (`tests/unit/test_session_repository.py:492-503`); el texto nuevo seguiría casando porque `pytest` usa búsqueda regex. `docs/api-reference/mongodb-session-repository.md:507-510` ya documenta un único `ValueError` para sesión, agente o mensaje. Playground no existe en este checkout; examples y docs no distinguen el texto.
   - Strands no captura el error: devuelve directamente `session_repository.update_message(...)` (`.venv/.../repository_session_manager.py:96-100`). No puedo verificar consumidores externos, incluido el proyecto enlazado en la issue, desde este repositorio.
   - **Corrección propuesta:** aceptar un error compuesto pero documentar que pierde diagnóstico; hacer U5/I4 exactos si el texto pasa a ser contrato. No afirmar que se comprobó “nadie” fuera del repositorio.

10. **P3 — no hace falta un índice nuevo para este filtro, pero “cero lecturas” solo significa cero comandos `find`.**

    - El filtro conserva igualdad por `_id`. Un `explain()` real de `{"_id": "s", "agents.a.messages.message_id": 1}` mostró:

      ```text
      stage: FETCH
      inputStage: {stage: IXSCAN, indexName: '_id_', indexBounds: {'_id': ['["s", "s"]']}}
      ```

      No hay collection scan y un índice multikey adicional por rutas de agentes dinámicos no es necesario para localizar el único documento. MongoDB sí debe inspeccionar el array dentro de ese documento; se elimina el round-trip y la transferencia del historial, no todo trabajo de lectura en servidor.
    - `updateOne` es atómico a nivel de documento ([documentación oficial](https://www.mongodb.com/docs/manual/core/write-operations-atomicity/)), que es la ventaja real frente al read-modify-write. La durabilidad concreta sigue dependiendo del write concern heredado por la colección; el plan no lo fija.

## Afirmaciones del plan que he verificado

| Afirmación | Estado | Evidencia |
|---|---|---|
| El `$set` actual de `messages.<índice>` reemplaza el subdocumento y borra campos ajenos a `SessionMessage`. | CIERTA | `mongodb_session_repository.py:559,588-595`; prueba real I1 dejó ausentes métricas y evento. |
| El filtro propuesto y `messages.$.<campo>` actualizan el elemento coincidente. | CIERTA | MongoDB 8.2.7: `matched=1`; documentación oficial de `$`. Solo el primer coincidente. |
| Si el agente no existe, `messages` no existe o está vacío, el update no casa. | CIERTA | Prueba real: `matched=0, modified=0` en los tres casos. |
| El mismo `message_id` identifica inequívocamente un elemento. | FALSA | Dos elementos con ID 7: solo se modificó el primero; Strands genera el siguiente ID en memoria (`repository_session_manager.py:77-86`). |
| Cualquier append concurrente vuelve obsoleto el índice leído. | FALSA | `$push` final no desplaza índices; append forzado entre read/write dejó correcto el ID 2. |
| Un mensaje de otro agente de la sesión puede desplazar este array. | FALSA | Cada agente usa `agents.<otro_id>.messages`; son rutas distintas. |
| Una réplica atrasada con un prefijo más corto puede por sí sola apuntar a otra posición en este array append-only. | FALSA | En un prefijo, los elementos visibles conservan posición; el objetivo no visible produce “not found”. Reordenadores externos cambiarían la conclusión. |
| La escritura única elimina el TOCTOU entre lectura e update y es atómica sobre el documento. | CIERTA | Un solo `update_one`; atomicidad oficial de MongoDB. No resuelve identidades duplicadas ni reemplazo concurrente del agente. |
| El posicional se comporta igual bajo una clave dinámica. | FALSA | Funciona para `agent-1`; con ID literal `a.b` dio `matched=0` porque dot notation interpreta niveles. |
| Derivar de `__dict__` es más futuro-resistente que listar campos. | FALSA | Cambia esquema sin revisión, acepta extras y puede producir rutas conflictivas (`WriteError` 40). |
| Hoy el `__dict__` normal produce cinco rutas netas. | CIERTA | `SessionMessage` 1.30.0 tiene cinco campos; se excluyen dos y `updated_at` se reemplaza por `now`. No vale si hay atributos extra. |
| `redact_message=None` mantiene el comportamiento actual y no rompe `to_message()`. | CIERTA | Prueba real guardó `None`; `SessionMessage.to_message()` cae a `message`. |
| `create_message()` guarda timestamps Mongo como `datetime`. | CIERTA | `mongodb_session_repository.py:496-499`; prueba real confirmó tipo `datetime`. |
| No hay creación normal de mensajes sin `created_at`. | CIERTA | El método lo sobreescribe incondicionalmente. No cubre datos legados/manuales. |
| Omitir `created_at` conserva valor y tipo en documentos normales. | CIERTA | Semántica de `$set`; I2 ya pasa hoy con igualdad y tipo datetime. |
| Dejar de escribir `created_at` no cambia ningún comportamiento. | FALSA | El código actual rellena un `created_at` ausente; prueba real lo confirmó. |
| El `guardrail_event` de esa misma redacción sobrevive por escribirse después de `super()`. | CIERTA | `mongodb_session_manager.py:242-259,296-307`. |
| El fix conserva el evento anterior de mensaje en una segunda intervención. | FALSA | `_record_guardrail_event()` posterior vuelve a reemplazar el campo singular; el historial está en el array de sesión. |
| Las métricas del mensaje redactado se pierden siempre en un turno real. | FALSA | En el primer turno aún no existen en el objetivo; en turnos posteriores pueden existir por métricas acumuladas y entonces sí perderse. |
| No hay consumidores internos que distingan el texto de los `ValueError`. | CIERTA | `rg` completo: solo el test con prefijo; docs agrupan los tres casos; Strands no captura. |
| No hay consumidores externos que distingan el texto. | NO VERIFICABLE | No están en este checkout y no se inspeccionó el repositorio consumidor enlazado. |
| U1–U7 e I1–I5 forman todos una fase RED. | FALSA | U4, I2, I3, I4 (si solo tipo) e I5 pasan antes; I5 dio 50/50. |
| I1 captura una regresión real. | CIERTA | Los dos campos inyectados desaparecen con el código actual. |
| I5, tal como está descrito, captura la carrera. | FALSA | Dos redacciones de posiciones estables no desplazan el array y pasaron 50/50. |
| `$` está soportado por DocumentDB. | CIERTA | Documentación oficial de AWS y matriz por versiones. |
| `arrayFilters` tiene soporte desigual en DocumentDB. | FALSA | La matriz oficial actual marca `$[<identifier>]` en todas las versiones enumeradas y Elastic. |
| La forma exacta propuesta se ha validado en DocumentDB. | NO VERIFICABLE | No hubo acceso a DocumentDB; el uso existente en código no demuestra ejecución real. |
| El filtro nuevo provocará collection scan si no se añade un índice de mensajes. | FALSA | `explain()` usó `_id_` con `IXSCAN -> FETCH`; solo inspecciona el documento localizado. |

## Lo que el plan se deja

- **La asignación concurrente de IDs es el problema de identidad de fondo.** Dos managers pueden producir el mismo `message_id`; afecta también a métricas y guardrails. El plan solo cambia el selector que consume esa identidad.
- **`create_agent()` reemplaza el agente entero.** Hace `$set` de `agents.<id>` con `messages: []` (`mongodb_session_repository.py:359-375`). Dos inicializaciones concurrentes de un agente ausente pueden borrar mensajes/configuración creados por la otra.
- **`update_agent()` y `create_message()` no exigen que el agente exista.** Sus filtros solo contienen `_id` (`mongodb_session_repository.py:472-475,502-510`); sobre una sesión existente pueden materializar estructuras parciales bajo un ID ausente en vez de fallar con “agent not found”.
- **Los otros posicionamientos ya heredan la ambigüedad.** `_record_guardrail_event()` y `_apply_sync_update()` usan `message_id` + `$`; el segundo además descarta conjuntamente la actualización de configuración si no casa el mensaje (`mongodb_session_manager.py:482-497`).
- **Reemplazo concurrente del agente.** Aunque el update posicional sea atómico, puede casar con un agente recién reemplazado que contenga el mismo `message_id`. Sin identidad/versionado no se sabe que es el mismo elemento lógico.
- **IDs y claves Mongo.** Ni este plan ni el precedente de `update_agent()` protegen contra `agent_id` con `.`/`$`; Strands los admite. `update_metadata()` repite el patrón con claves de usuario (`mongodb_session_repository.py:665-675`).
- **Write concern.** `matched_count` y la garantía de persistencia dependen de una escritura reconocida; el repositorio hereda la configuración de la colección y el plan no declara el mínimo exigido para una redacción de seguridad.
- **No falta un índice de colección.** La igualdad por `_id` evita collection scan; añadir un índice dinámico/multikey de mensajes no arreglaría duplicados y probablemente añadiría coste de escritura. Sí queda el coste lineal de buscar dentro del array/documento.
- **Compatibilidad de datos legados.** Al dejar de reparar timestamps ausentes, `list_messages()` puede seguir fallando al ordenar tipos heterogéneos. Hace falta una política explícita de migración o lectura tolerante.
- **La suite base está verde, pero el comando del plan omite el extra dev en este worktree.** `uv run python -m pytest ...` falló inicialmente con `No module named pytest`; con `uv run --extra dev` pasaron `275` unit tests y `18` tests de integración de repositorio. Conviene documentar el bootstrap (`uv sync --extra dev` o `uv run --extra dev`) para que la secuencia sea reproducible.
