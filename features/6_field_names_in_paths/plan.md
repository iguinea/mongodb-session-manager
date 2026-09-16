# #79 — Nombres que acaban dentro de una ruta dot-notation

## Contexto

El repositorio guarda cada agente en `agents.<agent_id>` y cada clave de metadata en
`metadata.<key>`, y llega a ellos con dot notation. MongoDB lee esos nombres como sintaxis, no como
datos. Strands solo rechaza separadores de ruta (`strands/_identifier.py`, `os.path.basename`).

### Lo verificado (MongoDB 8.2.7 local; los revisores lo repitieron también en mongo:7.0.41)

| Entrada | Resultado hoy |
|---|---|
| `agent_id="a.b"` | Escribe en `agents.a.b` anidado; `read_agent()` → `None`. **Con un manager real, cada petición borra el historial**: no encuentra el agente, llama a `create_agent()` y este reemplaza el subdocumento con `messages: []` (3 peticiones: restaurados 0/0/0; con `plain`, 0/1/2) |
| `agent_id="$x"` | Las escrituras pasan; las lecturas **por proyección** (`read_agent`, `list_messages`, `count_messages`…) revientan con 16410. Los filtros `$exists` sí funcionan |
| `agent_id=""`, `".a"`, `"a."`, `"a.$"` | Errores opacos del servidor (campo vacío, operador posicional) |
| `agent_id="a$b"` | **Funciona en todo**, positional y `$slice` incluidos |
| `"a\x00b"` (agente o metadata) | `bson.errors.InvalidDocument`, que no es `ValueError`; el doble lo acepta |
| metadata `"user.name"`, `"tags.0"` | Rutas. **Comportamiento publicado**: `test_delete_metadata_reaches_dotted_keys` y #47 («Caso 1 ✅») |
| metadata `"tags.$[]"` | Reescribe todos los elementos de un array existente (y `delete` los pone a `null`) |
| metadata `"$where"`, `"x.$y"` | Campo literal `$…`; se guarda y se borra, pero no se puede indexar |
| `metadata_fields=["$where"]` | Falla el índice, el error se absorbe y **tampoco se crea el de `application_name`** |

**Premisas de la issue que se corrigen:** el impacto de `.` es pérdida del historial en cada
petición, no «datos en el sitio equivocado»; `$` solo rompe al inicio de un segmento (`a$b` va
bien); en metadata `.` no se rechaza porque es una ruta por contrato.

**Resultado esperado:** ningún nombre recibido del exterior llega a una ruta de MongoDB sin
validar. Lo que MongoDB leería como sintaxis se rechaza con un `ValueError` claro **antes de
cualquier round-trip**, igual en el repositorio real y en el doble.

## Decisiones

| Decisión | Elegido |
|---|---|
| Rechazar o codificar | **Rechazar**. Codificar cambia las claves almacenadas (rompe `repo.collection` ad hoc, el session viewer y los ids con `%`). Un `agent_id` con `.` nunca persistió entre peticiones: no hay datos que preservar |
| Regla (confirmada por el usuario) | **Un segmento es no vacío, sin NUL y sin `$` inicial. Una ruta es una secuencia de segmentos separados por `.`. Un `agent_id` es un único segmento.** La misma regla para todo |
| Claves `$…` de metadata que hoy se guardan | Dejan de aceptarse. **Breaking**, versión **0.13.0** (confirmado) |
| Segmentos numéricos (`tags.0`) | Se aceptan: son semántica de ruta, como `user.name` |
| Límites de servidor no sintácticos (conflicto `{"a", "a.b"}` en un lote, profundidad > 100) | No se validan; siguen llegando como error del servidor, ruidoso. Se documenta |
| Tipo de error | `ValueError`, como ya hacen el repositorio y Strands |

## Compatibilidad

- **Los documentos no cambian**: ni campos nuevos, ni claves renombradas, ni migración. Es una
  comprobación en Python antes de hablar con la base de datos. Con un nombre válido se envían
  exactamente las mismas operaciones que hoy, con el mismo número de round-trips.
- **Versiones mezcladas** (managers viejos y nuevos sobre la misma colección): conviven, porque la
  forma del documento es la misma.
- **DocumentDB**: no se añade ningún operador ni consulta. Su única diferencia documentada sobre
  nombres de campo (no consulta campos con prefijo `$` dentro de `$in`/`$nin`/`$all` en objetos
  anidados) va en la misma dirección que la regla. No hay acceso aquí a un clúster DocumentDB: lo
  rechazado no llega al servidor, así que da igual cómo lo trataría.
- **SessionViewer** (Control Center, `prompt-manager-skill/backend/src/session_viewer/service.py`):
  lee los documentos en bruto y construye él mismo `agents.{aid}` y `metadata.{key}`. Como la forma
  no cambia, no le afecta. Los nombres que se rechazan le darían los mismos problemas.
- **Quién recibe ahora un `ValueError`**: `agent_id` con `.`, `$` inicial, vacío o NUL (nunca
  funcionaron); claves de metadata con un segmento `$…`, vacío o con NUL (**lo único que hoy
  funcionaba**: `$where` se guardaba); `metadata_fields` con esos nombres, al arrancar. Las claves
  `$…` ya almacenadas siguen en el documento y se siguen leyendo con `get_metadata()` y desde el
  visor.

## Diseño

### Nuevo: `src/mongodb_session_manager/field_names.py`

Un concepto de dominio, como `message_identity.py`: qué nombre puede acabar dentro de una ruta.

- `validate_field_path(path: str, what: str) -> str` — valida cada segmento de `path.split(".")`;
  el mensaje nombra qué era (`what`), la ruta y el segmento culpable, y dice por qué.
- `validate_agent_id(agent_id: str) -> str` — rechaza `.` y aplica la regla de segmento.

### `mongodb_session_repository.py` — cuatro familias de nombres

1. **`agent_id`**: nuevo `_agent_path(agent_id)` = `f"agents.{validate_agent_id(agent_id)}"`, **el
   único sitio que construye una ruta de agente** (como `_update_message_document()` lo es del
   selector posicional). Cada método lo calcula **en su primera sentencia**, antes de cualquier
   early return o I/O: `create_agent`, `read_agent`, `update_agent`, `create_message`,
   `read_message`, `list_messages`, `_update_message_document`, `update_agent_fields`,
   `get_agent_config`, `count_messages`, `get_last_message_ref`; `_missing_message_error` lo reutiliza.
2. **Claves de metadata**: `update_metadata()` / `delete_metadata()` validan **todas** las claves
   antes de construir la operación: un lote con una inválida no escribe nada.
3. **`metadata_fields`**: se validan en el constructor, antes de `_ensure_indexes()`: error de
   configuración ruidoso al arrancar en vez de índices que faltan en silencio.
4. **Claves relativas** de `update_message_fields()` / `update_agent_fields()` (`message_fields`,
   `agent_fields`, `set_operations`): se validan al entrar en `_update_message_document()` y en
   `update_agent_fields()`, también antes del early return por operaciones vacías.

### `tests/support/in_memory_session_repository.py`

Mismas validaciones y **mismo orden**: primera sentencia de `_update_message_document()` (antes de
su early return), `update_agent_fields()` (antes del suyo), `_agent()`, `create_agent()`,
`update_metadata()` y `delete_metadata()` (antes de mirar si existe la sesión). El párrafo «Known
divergence» de #79 se sustituye por la divergencia que sí queda: `_set_dotted()` no recorre
arrays, así que `tags.0` sobre una lista no se comporta como en MongoDB.

### `mongodb_session_manager.py`

- **`initialize()` y nuevo `initialize_bidi_agent()`** validan el `agent_id` **antes** de
  `super()`: Strands registra el id en `_latest_agent_message` antes de tocar el repositorio
  (`repository_session_manager.py:172-174`), y un reintento con el mismo manager daría un
  `SessionException("must be unique")` en lugar del `ValueError`.
- **Wrappers de `_apply_metadata_hook()`** validan las claves antes de invocar el hook: un hook
  propio no llega a ver (ni a propagar) una clave inválida. Los hooks SQS/WebSocket ya llaman a
  `original_func` primero, así que para ellos no cambia nada.
- `manage_metadata` ya captura la excepción y devuelve el texto al LLM: sin cambios.

## Tests (TDD: cada bloque en RED antes de su GREEN)

1. **`tests/unit/test_field_names.py`** (nuevo), parametrizado. Válidos: `plain`, `a$b`,
   `agent-1_x`, `agénte`, `con espacio`; rutas `status`, `user.name`, `tags.0`, `x.y$z`.
   Inválidos: `a.b`, `$x`, `""`, `.a`, `a.`, `a\x00b`; rutas `$where`, `x.$y`, `tags.$[]`, `a.$`,
   `""`, `a..b`, `.a`, `a.`, `a\x00b`. El mensaje nombra el segmento culpable.
2. **Contrato** (`tests/support/repository_contract.py`, contra el doble y contra MongoDB real):
   - Cada método con `agent_id` lanza `ValueError` para `a.b`, `$x`, `""` y `a\x00b`, **sin
     escribir nada** (documento de sesión idéntico antes y después). Parametrizado por método,
     **incluidas las variantes con operaciones vacías** de `update_message_fields` y
     `update_agent_fields`.
   - `agent_id="a$b"` hace el ciclo completo: crear, mensaje, leer, listar, escribir por ref,
     último ref.
   - `update_metadata` / `delete_metadata` rechazan `$where`, `tags.$[]`, `a..b`, `a\x00b`; un lote
     mixto no escribe la clave válida; `tags.$[]` no toca el array existente.
   - `update_message_fields` / `update_agent_fields` rechazan claves relativas inválidas.
   - Se conserva `test_delete_metadata_reaches_dotted_keys`.
   - Nuevo helper abstracto `_raw_session(store, session_id)` en las dos subclases.
3. **Unit con mock** (`tests/unit/test_session_repository.py`): un `agent_id` inválido no produce
   ninguna llamada a la colección (`method_calls == []`); `metadata_fields=["$where"]` lanza en el
   constructor sin llamar a `create_index`.
4. **Unit del manager con el doble** (`tests/unit/test_session_manager.py`): `initialize()` con id
   inválido lanza `ValueError` **dos veces seguidas** con el mismo manager y no deja la clave en
   `_latest_agent_message`; ídem bidi; un `metadata_hook` no es invocado con una clave inválida;
   `manage_metadata` devuelve el error como texto.
5. **Regresión de integración** (`tests/integration/`, MongoDB real, `ScriptedModel` de
   `test_write_amplification_integration.py`): un `Agent` con `agent_id="a.b"` lanza `ValueError`
   y la sesión queda sin agentes; con `a$b`, tres peticiones restauran 0/1/2 mensajes. Sustituye al
   probe de `/tmp`.

## Documentación

- `CLAUDE.md` §2: la regla, `_agent_path()` como único constructor de rutas de agente y la
  garantía «ningún nombre externo llega a una ruta sin validar».
- `docs/api-reference/mongodb-session-repository.md`: `Raises: ValueError` en los métodos con
  `agent_id`, metadata, claves relativas y constructor; qué es un nombre válido; límites de
  servidor que se siguen propagando.
- `docs/user-guide/metadata-management.md`: las claves con `.` son rutas (arrays incluidos);
  segmentos vacíos, con NUL o que empiezan por `$` se rechazan.
- `docs/development/testing.md`: fuera el aviso «Not evidence about `agent_id` with `.` or `$`»,
  dentro la divergencia real (arrays en `_set_dotted`).
- **0.13.0** en `__init__.py`, `pyproject.toml`, `CHANGELOG.md`, badge de `README.md`,
  `docs/README.md` y `CLAUDE.md`. CHANGELOG con sección **Breaking** (claves `$…` de metadata y
  `metadata_fields`) y notas de lo que **no** arregla: documentos ya corruptos con `agents.a.b`
  anidado no se limpian; las claves `$…` ya almacenadas dejan de poder borrarse con
  `delete_metadata()` como efecto de esta regla, y hay que hacerlo con `repo.collection`. El texto
  del CHANGELOG se te enseña antes de escribirlo.
- Plan aceptado → `features/6_field_names_in_paths/plan.md`.

## Fuera de alcance (con destino)

- **Siembra de `metadata_fields` con punto**: `create_session()` inserta `{"user.name": ""}` como
  clave literal mientras el índice va sobre la ruta anidada. Preexistente; propongo volcarlo en el
  checklist de #59 (índices) en vez de abrir issue, previa confirmación.
- Deep merge de dicts en metadata (#47). Limpiar documentos ya corruptos.

## Cierre

1. Comentario en #79 corrigiendo las premisas con la evidencia (previa confirmación).
2. Gate: `uv run ruff format . && uv run ruff check .` → suite completa → `/simplify` → suite →
   `/code-review`. Commit, push y PR con `Closes #79` cuando lo confirmes.

## Verificación

```bash
uv run python -m pytest tests/unit/ -v
export MONGODB_CONNECTION_STRING="mongodb://<user>:<pass>@localhost:8550/"
uv run python -m pytest tests/ -v
```

Criterios: los casos inválidos del contrato pasan contra **las dos** implementaciones; la
regresión de integración demuestra que `a.b` falla al construir el `Agent` sin tocar la sesión y
que `a$b` restaura el historial; `test_delete_metadata_reaches_dotted_keys` sigue verde; el
presupuesto de escrituras de `test_write_amplification*` no se mueve.
