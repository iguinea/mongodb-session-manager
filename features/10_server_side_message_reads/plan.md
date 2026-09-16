# Plan: mover paginacion, busqueda y conteo al servidor

Issue: [#58](https://github.com/iguinea/mongodb-session-manager/issues/58)

## Contrato observado

- `list_messages()` ordena por `created_at` ascendente antes de paginar. El sort de
  Python es estable: los empates conservan la posicion del array y los mensajes
  sin timestamp quedan al final, tambien en posicion de insercion.
- `offset` es el numero de mensajes ya retirados por Strands y `limit` acota la
  pagina. En produccion ambos son enteros no negativos.
- `read_message()` devuelve el primer elemento fisico que tenga el `message_id`.
  El id puede estar duplicado; la identidad estable para escrituras sigue siendo
  `storage_id` y se resuelve en #78.
- Una sesion, un agente o un array ausentes producen `None`, `[]` o `0` segun el
  metodo actual. Un campo `messages` presente y no-array sigue siendo dato
  corrupto y debe producir un error del servidor al aplicar `$size`/`$unwind`.

## Decision

1. `list_messages()` usara un pipeline `$match` por `_id`, `$unwind` con indice
   fisico, `$sort`, `$skip` y `$limit`. Un indicador explicito coloca los
   `created_at` nulos o ausentes al final; el indice fisico desempata. En
   DocumentDB se repite `$sort` como ultima etapa porque el motor solo garantiza
   el orden de salida cuando `$sort` cierra el pipeline.
2. No se usa una proyeccion `$slice`: pagina el orden fisico antes de ordenar y
   cambia el resultado cuando ambos ordenes divergen. Tampoco se usa
   `$sortArray`, que no esta disponible en DocumentDB 3.6/4.0/5.0 ni Elastic.
3. `read_message()` usara `$filter` + `$arrayElemAt`, que conserva la semantica
   de primer duplicado sin transferir el resto del array. La opcion inicialmente
   propuesta, una proyeccion `$elemMatch`, se probo contra MongoDB 8 y el servidor
   la rechazo sobre `agents.<id>.messages` con codigo 31275 (`Cannot use
   $elemMatch projection on a nested field`). Que el operador figure como
   soportado no hace valida esa composicion sobre una ruta anidada.
4. `count_messages()` proyectara `$size($ifNull(..., []))` en un pipeline.
5. `list_agent_configs()` convertira el mapa dinamico con `$objectToArray` y
   `$map`, proyectando solo `agent_id`, `model`, `system_prompt` y
   `prompt_metadata`.

La matriz oficial de Amazon DocumentDB marca `aggregate`, `$filter`,
`$arrayElemAt`, `$size`, `$slice`, `$objectToArray`, `$map`, `$ifNull`, `$unwind`,
`$sort`, `$skip` y `$limit` como compatibles con las versiones objetivo. No se
introduce un fallback silencioso: ocultaria errores de compatibilidad y podria
volver a transferir historiales completos. El doble in-memory sigue siendo el
fallback explicito para consumidores sin MongoDB.

## TDD

### RED

1. Pruebas unitarias fijan los cuatro pipelines.
2. El contrato compartido fija que una lectura con `message_id` duplicado
   devuelve el primer elemento.
3. Una prueba de integracion altera timestamps para que el orden fisico difiera
   del cronologico y comprueba que se ordena antes de paginar.
4. El listener de comandos verifica que las cuatro rutas usan una unica consulta
   acotada y que sus pipelines no proyectan el historial fuera de la pagina.

### GREEN

1. Sustituir las lecturas amplias por las operaciones descritas.
2. Mantener filtrado de campos de extension, `storage_id`, diagnosticos y
   validacion temprana de `agent_id`.
3. Mantener las mismas preferencias de lectura: `find_one()` y `aggregate()` se
   ejecutan sobre la misma `Collection`, incluida `secondaryPreferred`.

### Verificacion

1. Suite unitaria, Ruff y build.
2. Suite de integracion y `explain("executionStats")` contra MongoDB 8.2.7.
3. Ejecutar la misma matriz contra DocumentDB de desarrollo, incluyendo lectura
   inmediata despues de escritura con `secondaryPreferred`.
4. Repetir el benchmark de 10, 100, 1.000 y 5.000 mensajes y guardar bytes,
   comandos y p50/p95/p99.

Los cuatro puntos se completaron contra MongoDB 8.2.7 y Amazon DocumentDB 5.0
DEV; resultados en `artifacts/issue-58-server-side-reads.md`. La suite completa
de integracion dio 129 casos correctos en DocumentDB. El driver acepto
`secondaryPreferred`; una sonda con `replicaSet=rs0` comprobo que las cuatro
lecturas inmediatas enviaron esa preferencia y cayeron correctamente en la unica
instancia primaria. Queda fuera de esta validacion medir retraso real de replica
o demostrar una lectura servida por una secundaria.

## Criterios de aceptacion

- La respuesta de una pagina contiene como maximo `limit` mensajes.
- Buscar y contar no transfieren el array completo.
- Listar configuraciones no transfiere mensajes ni estado del agente.
- Orden cronologico, estabilidad, datos sin timestamp y primer id duplicado se
  conservan.
- Las implementaciones MongoDB e in-memory satisfacen el mismo contrato.
