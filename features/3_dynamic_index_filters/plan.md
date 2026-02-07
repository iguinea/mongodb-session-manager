# Feature 3: Filtros Dinámicos Basados en Índices MongoDB

## Contexto
El Session Viewer actual usa el endpoint `/api/v1/metadata-fields` que extrae campos metadata mediante aggregation pipeline (`$objectToArray`). Esto funciona pero tiene limitaciones:
- No aprovecha índices existentes (búsquedas lentas en colecciones grandes)
- No diferencia tipos de datos (todo se renderiza como text input)
- No tiene soporte para enums configurables

## Objetivo
Transformar el sistema de filtrado para que sea completamente dinámico, basándose en:
1. **Índices MongoDB**: Solo mostrar campos que tienen índices (garantiza performance)
2. **Detección de Tipos**: Analizar automáticamente el tipo de dato (string, date, number, boolean, enum)
3. **Enums Configurables**: Permitir configurar campos enum via variables de entorno

## Casos de Uso
1. **Performance**: Solo filtrar por campos indexados evita full collection scans
2. **UX Mejorado**: Dropdowns para enums, date pickers para fechas, número inputs para números
3. **Mantenibilidad**: Añadir nuevo filtro = crear índice en MongoDB (no tocar código)
4. **Configuración**: Admins pueden definir qué campos son enum vía .env

---

## Arquitectura

### Flujo de Datos

```
[MongoDB Indexes]
      ↓
[Backend: list_indexes()]
      ↓
[Backend: detect_field_type()]
      ↓
[Backend: get_enum_values() if configured]
      ↓
[API Response: FieldInfo[]]
      ↓
[Frontend: renderDynamicFilter()]
      ↓
[UI: Appropriate Input Control]
```

### Estructura de Respuesta API

**Actual (v0.1.16-0.1.18):**
```json
{
  "fields": ["case_type", "customer_phone", "priority"],
  "sample_values": {
    "case_type": ["IP_REAPERTURA", "NEW_CASE"],
    "customer_phone": ["604518797"]
  }
}
```

**Nueva (v0.1.19):**
```json
{
  "fields": [
    {
      "field": "session_id",
      "type": "string"
    },
    {
      "field": "created_at",
      "type": "date"
    },
    {
      "field": "metadata.status",
      "type": "enum",
      "values": ["active", "completed", "failed"]
    },
    {
      "field": "metadata.priority",
      "type": "enum",
      "values": ["high", "medium", "low"]
    },
    {
      "field": "metadata.customer_phone",
      "type": "string"
    }
  ]
}
```

---

## Implementación Detallada

### 1. Backend Configuration

#### config.py (Añadir configuración)

```python
class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ... existing settings ...

    # Dynamic Filter Configuration
    enum_fields_str: str = ""
    enum_max_values: int = 50

    @property
    def enum_fields(self) -> List[str]:
        """Parse enum fields from comma-separated string.

        Example:
            ENUM_FIELDS_STR="metadata.status,metadata.priority"
            Returns: ["metadata.status", "metadata.priority"]
        """
        if not self.enum_fields_str:
            return []
        return [field.strip() for field in self.enum_fields_str.split(",")]
```

#### .env Configuration

```bash
# Dynamic Filter Configuration
# Campos que deben mostrarse como dropdowns con valores predefinidos
ENUM_FIELDS_STR=metadata.status,metadata.priority,metadata.case_type

# Número máximo de valores únicos para considerar un campo como enum
# Si un campo tiene más valores que este límite, se mostrará como text input
ENUM_MAX_VALUES=50
```

### 2. Backend Models

#### models.py (Nuevo modelo FieldInfo)

```python
class FieldInfo(BaseModel):
    """Information about an indexed field.

    Attributes:
        field: Full field name (e.g., "metadata.status", "created_at")
        type: Detected field type (string, date, number, boolean, enum)
        values: Possible values for enum fields (None for other types)
    """
    field: str = Field(..., description="Field name")
    type: Literal["string", "date", "number", "boolean", "enum"] = Field(
        ...,
        description="Detected field type"
    )
    values: Optional[List[Any]] = Field(
        None,
        description="Possible values for enum fields"
    )


class MetadataFieldsResponse(BaseModel):
    """Available indexed fields with type information.

    Replaces the old structure with fields: List[str].
    Now returns structured FieldInfo objects.
    """
    fields: List[FieldInfo] = Field(..., description="List of indexed fields with type info")
```

### 3. Backend Logic

#### main.py - Nueva Función: get_indexed_fields()

```python
def get_indexed_fields(collection: Collection) -> List[str]:
    """Extract field names from MongoDB collection indexes.

    This function queries all indexes on the collection and extracts
    the field names, excluding system indexes (_id, _fts, etc.).

    Args:
        collection: MongoDB collection object

    Returns:
        List of unique indexed field names

    Example:
        >>> get_indexed_fields(my_collection)
        ['session_id', 'created_at', 'metadata.status', 'metadata.priority']
    """
    indexed_fields = []

    try:
        indexes = collection.list_indexes()

        for index in indexes:
            index_name = index.get("name", "")

            # Skip system indexes
            if index_name.startswith("_"):
                continue

            # Extract field names from index keys
            # index["key"] is like: {"metadata.status": 1, "created_at": -1}
            for field_name, _ in index.get("key", {}).items():
                # Skip internal fields
                if field_name not in ["_id", "_fts", "_ftsx"]:
                    indexed_fields.append(field_name)

        # Remove duplicates and return
        return list(set(indexed_fields))

    except Exception as e:
        logger.error(f"Error listing indexes: {e}")
        return []
```

#### main.py - Nueva Función: detect_field_type()

```python
def detect_field_type(collection: Collection, field_name: str) -> str:
    """Detect field data type by sampling documents.

    Analyzes up to 100 random documents to determine the most common
    data type for the field. Uses heuristics for type detection:
    - Convention-based: fields with "date" or "at" suffix → date
    - Sample-based: analyze actual values in documents

    Args:
        collection: MongoDB collection
        field_name: Full field name (e.g., "metadata.status")

    Returns:
        Type string: "string", "date", "number", "boolean"
        Priority order: boolean > number > date > string

    Example:
        >>> detect_field_type(collection, "metadata.priority")
        "string"
        >>> detect_field_type(collection, "created_at")
        "date"
    """
    # Convention-based detection for dates
    if "date" in field_name.lower() or field_name.endswith("_at"):
        return "date"

    # Sample documents to analyze actual values
    try:
        pipeline = [
            {"$match": {field_name: {"$exists": True, "$ne": None}}},
            {"$sample": {"size": 100}},
            {"$project": {field_name: 1}}
        ]

        samples = list(collection.aggregate(pipeline))

        if not samples:
            return "string"  # Default if no samples

        # Analyze types found in samples
        types_found = set()

        for doc in samples:
            # Navigate nested fields (e.g., "metadata.status")
            value = doc
            for part in field_name.split("."):
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = None
                    break

            if value is None:
                continue

            # Determine Python type
            if isinstance(value, bool):
                types_found.add("boolean")
            elif isinstance(value, (int, float)):
                types_found.add("number")
            elif isinstance(value, datetime):
                types_found.add("date")
            else:
                types_found.add("string")

        # Return most specific type (priority order)
        if "boolean" in types_found:
            return "boolean"
        elif "number" in types_found:
            return "number"
        elif "date" in types_found:
            return "date"
        else:
            return "string"

    except Exception as e:
        logger.warning(f"Error detecting type for {field_name}: {e}")
        return "string"  # Safe default
```

#### main.py - Nueva Función: get_enum_values()

```python
def get_enum_values(
    collection: Collection,
    field_name: str,
    max_values: int
) -> Optional[List[Any]]:
    """Get distinct values for a field to use as enum options.

    Retrieves all unique values for the field. If the count exceeds
    max_values, returns None (too many values, not suitable for enum).

    Args:
        collection: MongoDB collection
        field_name: Full field name (e.g., "metadata.status")
        max_values: Maximum number of values allowed for enum

    Returns:
        Sorted list of distinct values if count <= max_values
        None if too many values or error

    Example:
        >>> get_enum_values(collection, "metadata.status", 50)
        ["active", "completed", "failed", "pending"]

        >>> get_enum_values(collection, "metadata.customer_id", 50)
        None  # Too many unique customer IDs
    """
    try:
        # Get distinct values for the field
        distinct_values = collection.distinct(field_name)

        # Check if count is within limit
        if len(distinct_values) > max_values:
            logger.info(
                f"Field {field_name} has {len(distinct_values)} values "
                f"(exceeds limit of {max_values}), treating as regular field"
            )
            return None

        # Sort values for consistent display
        # Convert to string for sorting to handle mixed types
        sorted_values = sorted(distinct_values, key=lambda x: str(x))

        return sorted_values

    except Exception as e:
        logger.warning(f"Error getting enum values for {field_name}: {e}")
        return None
```

#### main.py - Refactor: get_metadata_fields()

```python
def get_metadata_fields(collection: Collection, settings: Settings) -> MetadataFieldsResponse:
    """Get indexed fields with type information and enum values.

    This function replaces the old aggregation-based approach with
    an index-based approach that:
    1. Lists all indexes on the collection
    2. Extracts field names from indexes
    3. Detects data type for each field
    4. Retrieves enum values for configured enum fields

    Args:
        collection: MongoDB collection
        settings: Application settings (includes enum_fields config)

    Returns:
        MetadataFieldsResponse with FieldInfo objects

    Raises:
        HTTPException: If unable to retrieve field information

    Example Response:
        {
          "fields": [
            {"field": "session_id", "type": "string"},
            {"field": "created_at", "type": "date"},
            {
              "field": "metadata.status",
              "type": "enum",
              "values": ["active", "completed"]
            }
          ]
        }
    """
    try:
        # Step 1: Get indexed fields
        indexed_fields = get_indexed_fields(collection)

        logger.info(f"Found {len(indexed_fields)} indexed fields")

        # Step 2: Build FieldInfo for each indexed field
        field_infos = []

        for field_name in indexed_fields:
            # Detect base type
            field_type = detect_field_type(collection, field_name)

            # Check if field should be treated as enum
            values = None
            if field_name in settings.enum_fields:
                logger.info(f"Checking enum values for configured field: {field_name}")
                values = get_enum_values(
                    collection,
                    field_name,
                    settings.enum_max_values
                )

                # Only set type to enum if values were successfully retrieved
                if values:
                    field_type = "enum"
                    logger.info(
                        f"Field {field_name} configured as enum with "
                        f"{len(values)} values"
                    )
                else:
                    logger.warning(
                        f"Field {field_name} configured as enum but has too "
                        f"many values or error, treating as {field_type}"
                    )

            # Create FieldInfo object
            field_info = FieldInfo(
                field=field_name,
                type=field_type,
                values=values
            )
            field_infos.append(field_info)

        logger.info(f"Returning {len(field_infos)} fields with type information")

        return MetadataFieldsResponse(fields=field_infos)

    except Exception as e:
        logger.error(f"Error getting metadata fields: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve metadata fields: {str(e)}"
        )
```

#### main.py - Actualizar Endpoint

```python
@app.get("/api/v1/metadata-fields", response_model=MetadataFieldsResponse)
async def list_metadata_fields():
    """Get indexed fields with type information.

    Returns all fields that have MongoDB indexes, along with their
    detected data types and enum values (if configured).

    This endpoint now returns structured FieldInfo objects instead of
    plain field names. Frontend uses this to render appropriate input
    controls (text, date, number, enum dropdown).

    Configuration:
    - ENUM_FIELDS_STR: Comma-separated list of fields to treat as enums
    - ENUM_MAX_VALUES: Maximum distinct values for enum detection

    Example Response:
        {
          "fields": [
            {"field": "session_id", "type": "string"},
            {"field": "metadata.status", "type": "enum", "values": ["active"]}
          ]
        }
    """
    try:
        collection = app.state.collection
        return get_metadata_fields(collection, settings)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing metadata fields: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

### 4. Frontend Changes

#### viewer.js - Modificar FilterPanel.loadMetadataFields()

```javascript
/**
 * Load available indexed fields from backend
 * Now receives FieldInfo objects with type information
 */
async loadMetadataFields(apiClient) {
  try {
    const data = await apiClient.getMetadataFields();

    // Store FieldInfo objects (array of {field, type, values?})
    this.fieldInfos = data.fields || [];

    console.log(`Loaded ${this.fieldInfos.length} indexed fields with types:`,
      this.fieldInfos.map(f => `${f.field} (${f.type})`).join(', ')
    );
  } catch (error) {
    console.error('Error loading metadata fields:', error);
    this.fieldInfos = [];
  }
}
```

#### viewer.js - Modificar FilterPanel.addFilter()

```javascript
/**
 * Add a new dynamic filter
 * Now passes fieldInfos instead of simple field names
 */
addFilter() {
  // Render filter with type information
  const filterElement = Components.renderDynamicFilter(this.fieldInfos);

  // Bind remove button
  const removeBtn = filterElement.querySelector('.remove-filter-btn');
  removeBtn.addEventListener('click', () => {
    filterElement.remove();
    const index = this.dynamicFilters.indexOf(filterElement);
    if (index > -1) {
      this.dynamicFilters.splice(index, 1);
    }
  });

  this.dynamicFilters.push(filterElement);
  this.filtersContainer.appendChild(filterElement);
}
```

#### components.js - Refactor Completo: renderDynamicFilter()

```javascript
/**
 * Dynamic Filter Component
 * Renders a filter row with field selector and type-appropriate value input
 *
 * @param {Array} fieldInfos - Array of FieldInfo objects from backend
 * @returns {HTMLElement} Filter row element
 *
 * FieldInfo structure:
 * {
 *   field: "metadata.status",
 *   type: "enum",
 *   values: ["active", "completed"]
 * }
 */
function renderDynamicFilter(fieldInfos = []) {
  const container = document.createElement('div');
  container.className = 'flex items-center space-x-2 p-2 bg-gray-50 rounded-md';

  // Field selector
  const fieldSelect = document.createElement('select');
  fieldSelect.className = 'filter-field flex-1 px-2 py-1 text-sm border border-gray-300 rounded-md focus:ring-1 focus:ring-primary-500 focus:border-transparent';

  // Default option
  const defaultOption = document.createElement('option');
  defaultOption.value = '';
  defaultOption.textContent = 'Seleccionar campo...';
  fieldSelect.appendChild(defaultOption);

  // Add field options with type information stored in dataset
  fieldInfos.forEach(fieldInfo => {
    const option = document.createElement('option');
    option.value = fieldInfo.field;
    option.textContent = fieldInfo.field;
    option.dataset.type = fieldInfo.type;

    // Store enum values as JSON if present
    if (fieldInfo.type === 'enum' && fieldInfo.values) {
      option.dataset.values = JSON.stringify(fieldInfo.values);
    }

    fieldSelect.appendChild(option);
  });

  // Value input container (will be replaced when field changes)
  const valueContainer = document.createElement('div');
  valueContainer.className = 'filter-value-container flex-1';

  // Initial value input (generic text)
  const initialInput = document.createElement('input');
  initialInput.type = 'text';
  initialInput.className = 'filter-value w-full px-2 py-1 text-sm border border-gray-300 rounded-md focus:ring-1 focus:ring-primary-500 focus:border-transparent';
  initialInput.placeholder = 'Valor...';
  valueContainer.appendChild(initialInput);

  // Remove button
  const removeBtn = document.createElement('button');
  removeBtn.className = 'remove-filter-btn p-1 text-gray-400 hover:text-red-600 transition-colors';
  removeBtn.innerHTML = `
    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
    </svg>
  `;

  /**
   * Event handler: When field is selected, render appropriate value input
   */
  fieldSelect.addEventListener('change', () => {
    const selectedOption = fieldSelect.options[fieldSelect.selectedIndex];
    const fieldType = selectedOption.dataset.type;
    const enumValues = selectedOption.dataset.values;

    // Clear current value input
    valueContainer.innerHTML = '';

    // Render type-appropriate input control
    let newInput;

    switch (fieldType) {
      case 'enum':
        // Dropdown with predefined values
        newInput = document.createElement('select');
        newInput.className = 'filter-value w-full px-2 py-1 text-sm border border-gray-300 rounded-md focus:ring-1 focus:ring-primary-500 focus:border-transparent';

        // Default option
        const defaultOpt = document.createElement('option');
        defaultOpt.value = '';
        defaultOpt.textContent = 'Seleccionar valor...';
        newInput.appendChild(defaultOpt);

        // Enum values from backend
        if (enumValues) {
          const values = JSON.parse(enumValues);
          values.forEach(value => {
            const opt = document.createElement('option');
            opt.value = value;
            opt.textContent = value;
            newInput.appendChild(opt);
          });
        }
        break;

      case 'date':
        // Date picker
        newInput = document.createElement('input');
        newInput.type = 'date';
        newInput.className = 'filter-value w-full px-2 py-1 text-sm border border-gray-300 rounded-md focus:ring-1 focus:ring-primary-500 focus:border-transparent';
        break;

      case 'number':
        // Number input
        newInput = document.createElement('input');
        newInput.type = 'number';
        newInput.className = 'filter-value w-full px-2 py-1 text-sm border border-gray-300 rounded-md focus:ring-1 focus:ring-primary-500 focus:border-transparent';
        newInput.placeholder = 'Valor numérico...';
        break;

      case 'boolean':
        // True/False dropdown
        newInput = document.createElement('select');
        newInput.className = 'filter-value w-full px-2 py-1 text-sm border border-gray-300 rounded-md focus:ring-1 focus:ring-primary-500 focus:border-transparent';

        ['', 'true', 'false'].forEach(val => {
          const opt = document.createElement('option');
          opt.value = val;
          opt.textContent = val === '' ? 'Seleccionar...' : val;
          newInput.appendChild(opt);
        });
        break;

      case 'string':
      default:
        // Text input (default fallback)
        newInput = document.createElement('input');
        newInput.type = 'text';
        newInput.className = 'filter-value w-full px-2 py-1 text-sm border border-gray-300 rounded-md focus:ring-1 focus:ring-primary-500 focus:border-transparent';
        newInput.placeholder = 'Valor...';
        break;
    }

    // Add new input to container
    valueContainer.appendChild(newInput);
  });

  // Assemble filter row
  container.appendChild(fieldSelect);
  container.appendChild(valueContainer);
  container.appendChild(removeBtn);

  return container;
}
```

---

## Configuración

### Variables de Entorno (.env)

```bash
# Dynamic Filter Configuration

# Campos que deben mostrarse como dropdowns (enum)
# Ejemplo: "metadata.status,metadata.priority,metadata.case_type"
ENUM_FIELDS_STR=

# Número máximo de valores únicos para considerar un campo como enum
# Si un campo tiene más valores que este límite, se mostrará como text input
# Valor por defecto: 50
ENUM_MAX_VALUES=50
```

### Ejemplo de Uso

**1. Crear índices en MongoDB:**
```javascript
db.sessions.createIndex({"metadata.status": 1});
db.sessions.createIndex({"metadata.priority": 1});
db.sessions.createIndex({"created_at": -1});
```

**2. Configurar enums en .env:**
```bash
ENUM_FIELDS_STR=metadata.status,metadata.priority
```

**3. Reiniciar backend:**
```bash
cd session_viewer/backend && make dev
```

**4. Frontend automáticamente mostrará:**
- `metadata.status` → Dropdown con valores únicos
- `metadata.priority` → Dropdown con valores únicos
- `created_at` → Date picker

---

## Testing Plan

### Backend Testing

#### Test 1: Index Extraction
```python
def test_get_indexed_fields():
    """Verify indexed fields are correctly extracted."""
    fields = get_indexed_fields(collection)

    assert "session_id" in fields
    assert "created_at" in fields
    assert "_id" not in fields  # System field excluded
```

#### Test 2: Type Detection
```python
def test_detect_field_type():
    """Verify type detection works correctly."""
    assert detect_field_type(collection, "created_at") == "date"
    assert detect_field_type(collection, "metadata.priority") == "string"
```

#### Test 3: Enum Values
```python
def test_get_enum_values():
    """Verify enum values extraction."""
    values = get_enum_values(collection, "metadata.status", 50)

    assert values is not None
    assert isinstance(values, list)
    assert len(values) <= 50
```

#### Test 4: Configuration Parsing
```python
def test_enum_fields_config():
    """Verify enum fields configuration is parsed correctly."""
    settings.enum_fields_str = "metadata.status,metadata.priority"

    assert len(settings.enum_fields) == 2
    assert "metadata.status" in settings.enum_fields
```

### Frontend Testing

#### Test 1: Field Info Loading
- [ ] Frontend fetches `/api/v1/metadata-fields`
- [ ] Response contains `fields` array of FieldInfo objects
- [ ] Each FieldInfo has `field`, `type`, and optional `values`

#### Test 2: Dynamic Filter Rendering
- [ ] Field selector shows only indexed fields
- [ ] Selecting field updates value input
- [ ] Enum fields show dropdown with values
- [ ] Date fields show date picker
- [ ] Number fields show number input
- [ ] String fields show text input

#### Test 3: Filter Submission
- [ ] Filter values are correctly extracted
- [ ] Date values are formatted correctly
- [ ] Enum selections are sent as exact values
- [ ] Search works with new filter structure

### Integration Testing

- [ ] Create MongoDB indexes
- [ ] Configure ENUM_FIELDS_STR
- [ ] Restart backend
- [ ] Frontend loads indexed fields
- [ ] Appropriate controls render for each type
- [ ] Search works with typed filters

---

## Archivos a Modificar

### Backend (4 archivos)
1. **session_viewer/backend/config.py** (+10 líneas)
   - Añadir `enum_fields_str` setting
   - Añadir `enum_max_values` setting
   - Añadir property `enum_fields`

2. **session_viewer/backend/models.py** (+25 líneas)
   - Añadir clase `FieldInfo`
   - Modificar `MetadataFieldsResponse`

3. **session_viewer/backend/main.py** (+150 líneas)
   - Nueva función `get_indexed_fields()`
   - Nueva función `detect_field_type()`
   - Nueva función `get_enum_values()`
   - Refactor función `get_metadata_fields()`
   - Actualizar endpoint docstring

4. **session_viewer/backend/.env.example** (+5 líneas)
   - Añadir sección Dynamic Filter Configuration

### Frontend (2 archivos)
5. **session_viewer/frontend/viewer.js** (~15 líneas modificadas)
   - Modificar `loadMetadataFields()` para manejar FieldInfo
   - Modificar `addFilter()` para pasar fieldInfos

6. **session_viewer/frontend/components.js** (+120 líneas, refactor)
   - Refactor completo de `renderDynamicFilter()`
   - Añadir lógica de cambio de input según tipo

### Documentación (3 archivos)
7. **CHANGELOG.md** (nueva entrada)
8. **CLAUDE.md** (actualizar Session Viewer section)
9. **session_viewer/backend/README.md** (documentar configuración)

**Total: 9 archivos modificados**

---

## Beneficios

### Para Performance
✅ **Búsquedas Rápidas**: Solo filtrar por campos indexados evita full scans
✅ **Escalabilidad**: Funciona con colecciones grandes (millones de documentos)

### Para UX
✅ **Controles Apropiados**: Dropdowns para enums, date pickers para fechas
✅ **Menos Errores**: Validación automática por tipo de input
✅ **Mejor Experiencia**: Usuarios seleccionan valores en lugar de escribir

### Para Mantenibilidad
✅ **Sin Hardcoding**: Filtros se definen mediante índices MongoDB
✅ **Configuración Simple**: Enums vía variables de entorno
✅ **Extensible**: Añadir filtro = crear índice + restart

### Para Operaciones
✅ **Monitoreable**: Logs claros de campos detectados
✅ **Configurable**: Admins controlan enums sin cambiar código
✅ **Documentado**: Configuración clara en README

---

## Compatibilidad

- ✅ **Backward Compatible**: Frontend sigue funcionando con respuesta antigua
- ✅ **Incremental Rollout**: Se puede activar campo por campo
- ✅ **No Breaking Changes**: API mantiene mismo endpoint
- ✅ **Rollback Safe**: Quitar configuración vuelve a comportamiento anterior

---

## Extensiones Futuras (Post-MVP)

1. **Type Inference Mejorado**: Usar schema validation de MongoDB si existe
2. **Operadores Avanzados**: Soportar $gt, $lt, $gte, $lte para números y fechas
3. **Fuzzy Search**: Para campos string con búsqueda aproximada
4. **Index Health**: Mostrar warning si campo sin índice es usado frecuentemente
5. **Query Performance**: Mostrar explain() para queries complejas
6. **Custom Renderers**: Permitir custom UI components por tipo de campo

---

## Versión

**Target Version:** 0.1.19

**CHANGELOG Entry:**
```markdown
## [0.1.19] - 2025-10-16

### Added
- **Dynamic Index-Based Filters**: Session Viewer filters now automatically based on MongoDB indexes
  - Backend queries collection indexes to determine available filters
  - Automatic type detection (string, date, number, boolean, enum)
  - Configurable enum fields via ENUM_FIELDS_STR environment variable
  - Type-appropriate UI controls (dropdowns for enums, date pickers for dates, etc.)
  - Performance guarantee: only indexed fields can be filtered

### Changed
- **API Response Structure**: `/api/v1/metadata-fields` now returns FieldInfo objects with type information
  - Old: `{fields: ["status"], sample_values: {...}}`
  - New: `{fields: [{field: "status", type: "enum", values: ["active"]}]}`
- **Frontend Filter Rendering**: Dynamic filter inputs adapt to field type

### Configuration
- `ENUM_FIELDS_STR`: Comma-separated list of fields to treat as enum dropdowns
- `ENUM_MAX_VALUES`: Maximum distinct values for enum detection (default: 50)
```

---

## Estado

- **Fecha inicio**: 2025-10-16
- **Fecha fin estimada**: 2025-10-16
- **Estado**: Planificación completa ✅
- **Siguiente paso**: Implementación backend
- **Versión target**: 0.1.19
- **Esfuerzo estimado**: 3-4 horas
