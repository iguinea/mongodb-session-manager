# Feature 1: Almacenar model y system_prompt del agente

## Contexto
Actualmente, `SessionAgent` (de Strands SDK) solo persiste:
- `agent_id`
- `state`
- `conversation_manager_state`
- `created_at`, `updated_at`

Los campos `model` y `system_prompt` del objeto `Agent` NO se guardan automáticamente.

## Objetivo
Capturar y persistir `model` y `system_prompt` en MongoDB para:
1. **Auditoría**: Saber qué modelo y prompt se usó en cada conversación
2. **Debugging**: Reproducir comportamiento del agente
3. **Analytics**: Analizar uso de modelos y prompts
4. **Recuperación**: Poder recrear el agente con la misma configuración

## Implementación

### 1. Modificar `mongodb_session_manager.py`

#### En `sync_agent()` (línea 216-254):
- Capturar `agent.model` y `agent.system_prompt` después de llamar a `super().sync_agent()`
- Guardar como campos adicionales en `agent_data` usando update de MongoDB
- Preservar compatibilidad con documentos existentes

#### Nuevos métodos:
```python
def get_agent_config(self, agent_id: str) -> Optional[Dict[str, Any]]:
    """Obtener model y system_prompt de un agente.

    Args:
        agent_id: ID del agente

    Returns:
        Dict con model, system_prompt, agent_id o None si no existe
    """

def update_agent_config(self, agent_id: str, model: str = None, system_prompt: str = None) -> None:
    """Actualizar model o system_prompt de un agente.

    Args:
        agent_id: ID del agente
        model: Nuevo modelo (opcional)
        system_prompt: Nuevo system prompt (opcional)
    """

def list_agents(self) -> List[Dict[str, Any]]:
    """Listar todos los agentes de la sesión con su configuración.

    Returns:
        Lista de dicts con agent_id, model, system_prompt
    """
```

### 2. Schema de MongoDB actualizado

**Estructura resultante en `agents.{agent_id}.agent_data`:**
```json
{
  "agent_id": "case_dispatcher",
  "state": {},
  "conversation_manager_state": {...},
  "model": "eu.anthropic.claude-sonnet-4-20250514-v1:0",  // NUEVO
  "system_prompt": "You are a helpful assistant",         // NUEVO
  "created_at": "...",
  "updated_at": "..."
}
```

### 3. Documentación a actualizar

- **CLAUDE.md**: Agregar descripción de los nuevos campos y métodos
- **README.md**: Actualizar sección de MongoDB Schema y ejemplos
- **docs/api-reference/mongodb-session-manager.md**: Documentar nuevos métodos
- **docs/architecture/data-model.md**: Actualizar estructura del documento

### 4. Ejemplos

**`examples/example_agent_config.py`:**
- Demostrar cómo se guarda automáticamente
- Mostrar recuperación de configuración
- Ejemplo de auditoría de modelos usados

### 5. Versión

**Nueva versión:** 0.1.14

**CHANGELOG:**
```markdown
## [0.1.14] - 2025-10-15

### Added
- **Agent Configuration Persistence**: Automatic capture and storage of `model` and `system_prompt` fields
  - `sync_agent()` now captures agent configuration during synchronization
  - New `get_agent_config(agent_id)` method to retrieve agent configuration
  - New `update_agent_config(agent_id, model, system_prompt)` method to modify configuration
  - New `list_agents()` method to list all agents with their configurations
  - Agent configuration stored in `agents.{agent_id}.agent_data.model` and `.system_prompt`
  - Backward compatible: existing documents work without changes
```

## Beneficios

1. **Auditoría completa**: Se puede rastrear qué modelo y prompt se usó en cada conversación
2. **Debugging mejorado**: Reproducir exactamente el comportamiento del agente
3. **Analytics**: Analizar uso de modelos, costos, etc.
4. **Compatibilidad**: No rompe documentos existentes
5. **Flexibilidad**: Los métodos permiten consultar y modificar la configuración

## Compatibilidad hacia atrás

- Documentos existentes sin `model` y `system_prompt` seguirán funcionando
- Los nuevos campos se agregan solo cuando se sincroniza un agente
- Los métodos `get_agent_config()` retornan `None` o valores vacíos para agentes antiguos

## Testing Manual

1. Crear sesión con agente configurado con model y system_prompt
2. Verificar que se guardan en MongoDB tras `sync_agent()`
3. Recuperar configuración con `get_agent_config()`
4. Modificar con `update_agent_config()`
5. Listar agentes con `list_agents()`
6. Verificar compatibilidad con documentos existentes (sin los nuevos campos)

## Archivos afectados

### Crear:
1. `features/1_agent_config_persistence/plan.md` ✓
2. `features/1_agent_config_persistence/progress.md`
3. `examples/example_agent_config.py`

### Modificar:
1. `src/mongodb_session_manager/mongodb_session_manager.py`
2. `CLAUDE.md`
3. `README.md`
4. `CHANGELOG.md`
5. `pyproject.toml`
6. `src/mongodb_session_manager/__init__.py`
7. `docs/api-reference/mongodb-session-manager.md`
8. `docs/architecture/data-model.md` (si existe)

## Estado

- **Fecha inicio**: 2025-10-15
- **Fecha fin estimada**: 2025-10-15
- **Estado**: En desarrollo
- **Versión target**: 0.1.14
