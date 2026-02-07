# Feature 2: Session Viewer - Visualizador de Sesiones MongoDB

## Contexto
Crear una aplicación web completa para visualizar y analizar sesiones almacenadas en MongoDB. La aplicación permitirá buscar sesiones mediante filtros dinámicos configurables y visualizar el historial completo de conversaciones en un timeline cronológico unificado.

## Objetivo
Proporcionar una herramienta de análisis y debugging para revisar conversaciones completas, identificar problemas, analizar el comportamiento de agentes y validar feedbacks de usuarios.

## Casos de Uso
1. **Debugging**: Revisar conversaciones problemáticas para identificar fallos
2. **Análisis de Feedback**: Correlacionar feedbacks negativos con mensajes específicos
3. **Auditoría**: Revisar qué se dijo en una conversación específica
4. **Analytics**: Analizar patrones en conversaciones por metadata
5. **Soporte al Cliente**: Ver el historial completo de interacción con un cliente

---

## Arquitectura

### Backend - FastAPI (Puerto 8882)
```
session_viewer/backend/
├── main.py              # FastAPI application con endpoints
├── config.py            # Configuración via .env
├── models.py            # Pydantic models para request/response
├── .env.example         # Template de configuración
├── Makefile             # Comandos para desarrollo
└── README.md            # Documentación del backend
```

### Frontend - Vanilla JavaScript (Puerto 8883)
```
session_viewer/frontend/
├── index.html           # Interfaz principal
├── viewer.js            # Lógica de búsqueda y visualización
├── components.js        # Componentes reutilizables
├── Makefile             # Comandos para desarrollo
└── README.md            # Documentación del frontend
```

---

## Implementación Detallada

### 1. Backend API

#### Endpoints

**`GET /api/v1/sessions/search`**
- **Descripción**: Buscar sesiones con filtros dinámicos y paginación
- **Query Parameters**:
  - `filters` (string, opcional): JSON con filtros dinámicos
    - Ejemplo: `{"metadata.case_type": "IP_REAPERTURA", "metadata.customer_phone": "604518797"}`
  - `session_id` (string, opcional): Búsqueda parcial por session_id
  - `created_at_start` (datetime, opcional): Fecha inicial
  - `created_at_end` (datetime, opcional): Fecha final
  - `limit` (int, default=20): Resultados por página
  - `offset` (int, default=0): Offset para paginación
- **Response**:
```json
{
  "sessions": [
    {
      "session_id": "68ee8a6e8ff935ffff0f7b85",
      "created_at": "2025-10-14T17:37:50.668Z",
      "updated_at": "2025-10-14T17:38:28.325Z",
      "metadata": {
        "case_type": "Analizando caso",
        "customer_phone": "604518797",
        "customer_cups": "ES0234150063456295RR",
        "customer_itaxnum": "Y5604106D"
      },
      "agents_count": 1,
      "messages_count": 4,
      "feedbacks_count": 1
    }
  ],
  "total": 100,
  "limit": 20,
  "offset": 0,
  "has_more": true
}
```

**`GET /api/v1/sessions/{session_id}`**
- **Descripción**: Obtener sesión completa con timeline unificado
- **Response**:
```json
{
  "session_id": "68ee8a6e8ff935ffff0f7b85",
  "created_at": "2025-10-14T17:37:50.668Z",
  "updated_at": "2025-10-14T17:38:28.325Z",
  "metadata": {...},
  "timeline": [
    {
      "type": "message",
      "timestamp": "2025-10-14T17:37:54.164Z",
      "agent_id": "case_dispatcher",
      "role": "user",
      "content": [{"text": "Analiza el caso..."}],
      "message_id": 0
    },
    {
      "type": "message",
      "timestamp": "2025-10-14T17:37:57.626Z",
      "agent_id": "case_dispatcher",
      "role": "assistant",
      "content": [{"text": "Voy a analizar..."}],
      "message_id": 1,
      "metrics": {
        "latency_ms": 3000,
        "input_tokens": 17859,
        "output_tokens": 74
      }
    },
    {
      "type": "feedback",
      "timestamp": "2025-10-14T17:38:02.006Z",
      "rating": "up",
      "comment": "Excelente análisis"
    }
  ],
  "agents_summary": {
    "case_dispatcher": {
      "messages_count": 4,
      "model": "eu.anthropic.claude-sonnet-4-20250514-v1:0",
      "system_prompt": "Eres un asistente..."
    }
  }
}
```

**`GET /api/v1/metadata-fields`**
- **Descripción**: Listar campos metadata disponibles para filtros
- **Response**:
```json
{
  "fields": [
    "case_type",
    "customer_phone",
    "customer_cups",
    "customer_itaxnum",
    "actual_datetime"
  ],
  "sample_values": {
    "case_type": ["Analizando caso", "IP_REAPERTURA", "NEW_CASE"],
    "customer_phone": ["604518797", "612345678"]
  }
}
```

**`GET /health`**
- **Descripción**: Health check del servicio
- **Response**:
```json
{
  "status": "healthy",
  "mongodb": "connected",
  "connection_pool": {
    "active_connections": 5,
    "available_connections": 95
  }
}
```

#### Lógica de Timeline Unificado

```python
def build_unified_timeline(session_doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Construir timeline cronológico unificado de todos los agentes y feedbacks."""
    timeline = []

    # Agregar mensajes de todos los agentes
    for agent_id, agent_data in session_doc.get("agents", {}).items():
        for msg in agent_data.get("messages", []):
            timeline_item = {
                "type": "message",
                "timestamp": msg["created_at"],
                "agent_id": agent_id,
                "role": msg["message"]["role"],
                "content": msg["message"]["content"],
                "message_id": msg["message_id"]
            }

            # Incluir métricas si existen
            if "event_loop_metrics" in msg:
                timeline_item["metrics"] = msg["event_loop_metrics"]

            timeline.append(timeline_item)

    # Agregar feedbacks
    for feedback in session_doc.get("feedbacks", []):
        timeline.append({
            "type": "feedback",
            "timestamp": feedback["created_at"],
            "rating": feedback.get("rating"),
            "comment": feedback.get("comment")
        })

    # Ordenar cronológicamente
    timeline.sort(key=lambda x: x["timestamp"])

    return timeline
```

#### MongoDB Queries

**Búsqueda con filtros dinámicos:**
```python
def build_search_query(
    filters: Optional[Dict[str, str]],
    session_id: Optional[str],
    created_at_start: Optional[datetime],
    created_at_end: Optional[datetime]
) -> Dict[str, Any]:
    """Construir query MongoDB con filtros dinámicos."""
    query = {}

    # Filtros metadata dinámicos
    if filters:
        for key, value in filters.items():
            if key.startswith("metadata."):
                # Búsqueda parcial case-insensitive
                query[key] = {"$regex": value, "$options": "i"}
            else:
                query[key] = value

    # Búsqueda por session_id
    if session_id:
        query["session_id"] = {"$regex": session_id, "$options": "i"}

    # Rango de fechas
    if created_at_start or created_at_end:
        query["created_at"] = {}
        if created_at_start:
            query["created_at"]["$gte"] = created_at_start
        if created_at_end:
            query["created_at"]["$lte"] = created_at_end

    return query
```

**Obtener campos metadata disponibles:**
```python
def get_metadata_fields(collection: Collection) -> Dict[str, Any]:
    """Obtener todos los campos metadata disponibles."""
    pipeline = [
        {"$project": {"metadata": {"$objectToArray": "$metadata"}}},
        {"$unwind": "$metadata"},
        {"$group": {
            "_id": "$metadata.k",
            "sample_values": {"$addToSet": "$metadata.v"}
        }},
        {"$project": {
            "field": "$_id",
            "sample_values": {"$slice": ["$sample_values", 10]}
        }}
    ]

    results = list(collection.aggregate(pipeline))

    return {
        "fields": [r["field"] for r in results],
        "sample_values": {r["field"]: r["sample_values"] for r in results}
    }
```

### 2. Frontend UI

#### Componentes Principales

**1. Filter Panel (Panel de Filtros)**
- Input para `session_id` con búsqueda parcial
- Botón "+ Agregar Filtro" para filtros metadata dinámicos
- Cada filtro dinámico tiene:
  - Select con campos metadata disponibles (obtenidos del backend)
  - Input para valor del filtro
  - Botón "Eliminar" para remover el filtro
- Date range picker para `created_at`
- Botón "Buscar" para ejecutar búsqueda
- Botón "Limpiar Filtros" para resetear

**2. Results List (Lista de Resultados)**
- Cards con preview de cada sesión:
  - Session ID
  - Fecha de creación
  - Metadata relevante (primeras 3-4 keys)
  - Contadores: N agentes, M mensajes, F feedbacks
  - Botón "Ver Detalles"
- Paginación:
  - Botones Anterior/Siguiente
  - Indicador "Página X de Y"
  - Total de resultados encontrados
  - Select para cambiar tamaño de página (10, 20, 50, 100)

**3. Session Viewer (Visualizador de Sesión)**
- Header con información de sesión:
  - Session ID (copiable)
  - Fechas created_at / updated_at
  - Botón para expandir metadata completo
- Metadata Panel (colapsable):
  - Todos los campos metadata en formato legible
  - JSON colapsable para objetos anidados
- Agents Summary (resumen de agentes):
  - Lista de agentes con configuración (model, system_prompt)
  - Contadores de mensajes por agente
- Timeline Unificado:
  - Mensajes de usuario (alineados derecha, color azul)
  - Mensajes de asistente (alineados izquierda, color gris)
    - Badge con agent_id
    - Métricas (tokens, latency) si disponibles
  - Feedbacks (inline en su posición cronológica)
    - Badge de rating (👍/👎)
    - Comentario
    - Timestamp
- Botón "Volver a Resultados"

#### Estilos y UX

**Paleta de colores (Tailwind CSS):**
- User messages: `bg-blue-500 text-white`
- Assistant messages: `bg-gray-200 text-gray-900`
- Feedbacks positivos: `bg-green-100 border-green-500`
- Feedbacks negativos: `bg-red-100 border-red-500`
- Feedbacks neutrales: `bg-gray-100 border-gray-500`

**Animaciones:**
- Fade in para resultados de búsqueda
- Slide in para timeline
- Smooth scroll al seleccionar sesión

---

## Configuración

### Backend Configuration (.env)

```bash
# MongoDB Configuration
MONGODB_CONNECTION_STRING=mongodb://mongodb:mongodb@mongodb_session_manager-mongodb:27017/
DATABASE_NAME=examples
COLLECTION_NAME=sessions

# Backend Configuration
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8882

# Frontend Configuration (para CORS)
FRONTEND_URL=http://localhost:8883
ALLOWED_ORIGINS=http://localhost:8883,http://127.0.0.1:8883

# Pagination
DEFAULT_PAGE_SIZE=20
MAX_PAGE_SIZE=100

# Logging
LOG_LEVEL=INFO
```

### Frontend Configuration (viewer.js)

```javascript
const CONFIG = {
  API_BASE_URL: 'http://localhost:8882/api/v1',
  DEFAULT_PAGE_SIZE: 20,
  DATE_FORMAT: 'YYYY-MM-DD HH:mm:ss'
};
```

---

## Archivos a Crear

### Backend (7 archivos)
1. ✅ `session_viewer/backend/main.py` - FastAPI application
2. ✅ `session_viewer/backend/config.py` - Configuration management
3. ✅ `session_viewer/backend/models.py` - Pydantic models
4. ✅ `session_viewer/backend/.env.example` - Configuration template
5. ✅ `session_viewer/backend/Makefile` - Development commands
6. ✅ `session_viewer/backend/README.md` - Backend documentation

### Frontend (5 archivos)
1. ✅ `session_viewer/frontend/index.html` - Main UI
2. ✅ `session_viewer/frontend/viewer.js` - Application logic
3. ✅ `session_viewer/frontend/components.js` - Reusable components
4. ✅ `session_viewer/frontend/Makefile` - Development commands
5. ✅ `session_viewer/frontend/README.md` - Frontend documentation

### Documentation (4 archivos)
1. ✅ `features/2_session_viewer/plan.md` - Este archivo
2. ✅ `features/2_session_viewer/progress.md` - Progress tracking
3. ✅ `session_viewer/README.md` - General documentation

### Updates (3 archivos)
1. ✅ `README.md` - Add Session Viewer section
2. ✅ `CLAUDE.md` - Document new feature
3. ✅ `CHANGELOG.md` - Version 0.1.16 entry

**Total: 19 archivos (16 nuevos, 3 actualizaciones)**

---

## Comandos de Uso

```bash
# Setup (primera vez)
cd session_viewer/backend
cp .env.example .env
# Editar .env con tu configuración

# Terminal 1: Iniciar Backend
cd session_viewer/backend
make run
# Backend disponible en http://localhost:8882

# Terminal 2: Iniciar Frontend
cd session_viewer/frontend
make run
# Frontend disponible en http://localhost:8883

# Acceder a la aplicación
open http://localhost:8883
```

---

## Testing Plan

### Backend Testing

**1. Endpoint /api/v1/sessions/search**
- [ ] Búsqueda sin filtros (devuelve todas las sesiones)
- [ ] Búsqueda por session_id exacto
- [ ] Búsqueda por session_id parcial
- [ ] Búsqueda con un filtro metadata
- [ ] Búsqueda con múltiples filtros metadata
- [ ] Búsqueda con rango de fechas
- [ ] Búsqueda combinando session_id + metadata + fechas
- [ ] Paginación: primera página
- [ ] Paginación: páginas siguientes
- [ ] Paginación: última página
- [ ] Límite máximo de resultados
- [ ] Query sin resultados (devuelve lista vacía)

**2. Endpoint /api/v1/sessions/{session_id}**
- [ ] Recuperar sesión existente
- [ ] Recuperar sesión con múltiples agentes
- [ ] Recuperar sesión con feedbacks
- [ ] Timeline en orden cronológico correcto
- [ ] Métricas incluidas en mensajes de asistente
- [ ] Session no encontrada (404)

**3. Endpoint /api/v1/metadata-fields**
- [ ] Listar todos los campos metadata disponibles
- [ ] Sample values limitados correctamente
- [ ] Respuesta correcta cuando no hay sesiones

**4. Endpoint /health**
- [ ] Health check cuando MongoDB está conectado
- [ ] Health check cuando MongoDB está desconectado

### Frontend Testing

**1. Panel de Filtros**
- [ ] Agregar filtro dinámico
- [ ] Remover filtro dinámico
- [ ] Agregar múltiples filtros
- [ ] Select de campos metadata se actualiza correctamente
- [ ] Date range picker funciona
- [ ] Botón "Limpiar Filtros" resetea todo

**2. Búsqueda**
- [ ] Buscar con session_id
- [ ] Buscar con un filtro metadata
- [ ] Buscar con múltiples filtros
- [ ] Buscar con rango de fechas
- [ ] Búsqueda sin resultados muestra mensaje apropiado
- [ ] Loading state durante búsqueda

**3. Resultados**
- [ ] Lista de resultados se muestra correctamente
- [ ] Cards con información correcta
- [ ] Paginación: botón Anterior deshabilitado en primera página
- [ ] Paginación: botón Siguiente deshabilitado en última página
- [ ] Cambiar tamaño de página actualiza resultados
- [ ] Click en "Ver Detalles" carga sesión

**4. Visualización de Sesión**
- [ ] Header con session info correcta
- [ ] Metadata panel expandible
- [ ] Agents summary muestra todos los agentes
- [ ] Timeline en orden cronológico
- [ ] Mensajes de usuario alineados derecha
- [ ] Mensajes de asistente alineados izquierda
- [ ] Badge de agent_id visible
- [ ] Feedbacks en posición cronológica correcta
- [ ] Métricas visibles en mensajes que las tienen
- [ ] Botón "Volver" regresa a resultados

**5. Responsive Design**
- [ ] UI funciona en desktop (1920x1080)
- [ ] UI funciona en laptop (1366x768)
- [ ] UI funciona en tablet (768px)
- [ ] UI funciona en mobile (375px)

### Integration Testing
- [ ] Backend → Frontend: búsqueda completa
- [ ] Backend → Frontend: visualización de sesión
- [ ] Multiple búsquedas consecutivas
- [ ] Navegación entre resultados y detalle
- [ ] Sesiones con mucho contenido (100+ mensajes)
- [ ] Sesiones con múltiples agentes
- [ ] CORS configurado correctamente

---

## Beneficios

1. **Debugging Mejorado**: Visualizar conversaciones completas para identificar problemas
2. **Análisis de Feedback**: Correlacionar feedbacks con mensajes específicos
3. **Auditoría**: Revisar interacciones históricas para compliance
4. **Analytics**: Identificar patrones en conversaciones por metadata
5. **Soporte**: Ayudar a clientes revisando su historial completo
6. **Desarrollo**: Validar comportamiento de agentes durante desarrollo

---

## Extensiones Futuras (Post-MVP)

1. **Export**: Exportar sesión a JSON, PDF o markdown
2. **Search Within Session**: Buscar texto dentro de mensajes
3. **Comparison**: Comparar dos sesiones lado a lado
4. **Analytics Dashboard**: Métricas agregadas de sesiones
5. **Real-time Monitoring**: Ver sesiones activas en tiempo real
6. **Agent Performance**: Métricas de performance por agente
7. **Feedback Analytics**: Dashboard de feedbacks agregados
8. **Bulk Operations**: Exportar múltiples sesiones
9. **Advanced Filters**: Regex, operadores complejos
10. **Saved Searches**: Guardar búsquedas frecuentes

---

## Versión

**Target Version:** 0.1.16

**CHANGELOG Entry:**
```markdown
## [0.1.16] - 2025-10-15

### Added
- **Session Viewer**: Web application for MongoDB session visualization and analysis
  - Backend FastAPI API (port 8882) with dynamic filtering and pagination
  - Frontend vanilla JavaScript interface (port 8883) with Tailwind CSS
  - Dynamic metadata field filtering (user-configurable at runtime)
  - Multiple simultaneous filters support with AND logic
  - Unified chronological timeline for multi-agent sessions
  - Feedback integration in timeline at correct temporal position
  - Pagination for search results (configurable page size)
  - Health check endpoint with MongoDB connection status
  - Configurable MongoDB connection via .env file
  - Comprehensive documentation and usage examples
  - Located in `session_viewer/` directory with backend and frontend subdirectories
```

---

## Compatibilidad

- ✅ Funciona con documentos MongoDB existentes
- ✅ No requiere migración de datos
- ✅ No modifica el schema de MongoDB
- ✅ Compatible con versión 0.1.15 del session manager
- ✅ Soporta sesiones creadas con versiones anteriores

---

## Estado

- **Fecha inicio**: 2025-10-15
- **Fecha fin estimada**: 2025-10-15
- **Estado**: Planificación completa ✅
- **Siguiente paso**: Implementación backend
- **Versión target**: 0.1.16
- **Esfuerzo estimado**: 5-7 horas
