# Arquitectura y Organizacion de Codigo

## Limites de tamano

- Ficheros: target 200-400 lineas, maximo 800.
- Funciones: bajo 50 lineas. Si crece, extraer.
- Maximo 4 niveles de nesting. Usar early returns para reducir complejidad.

## Organizacion

- Organizar por feature/dominio, no por tipo de fichero.
- Dependency injection para desacoplar componentes y facilitar testing.
- Constantes y config en lugar de valores hardcodeados (magic numbers/strings).

## Reglas de limpieza

- No dead code: eliminar variables, funciones e imports no usados INMEDIATAMENTE.
- No over-engineering: construir lo necesario ahora (YAGNI), no funcionalidades especulativas.
- Fix root causes, no bandaids: parches temporales crean deuda tecnica.

## Inmutabilidad

- Preferir inmutabilidad: crear nuevos objetos en vez de mutar existentes.
- En estado compartido: copiar antes de modificar.
- Value objects para domain primitives con validacion en construccion.

## Documentacion SIEMPRE actualizada (OBLIGATORIO)

Toda modificacion de codigo DEBE ir acompanada de la actualizacion de su documentacion asociada.

### Que actualizar con cada cambio

- README.md del proyecto/modulo afectado
- Docstrings de funciones/clases modificadas
- CLAUDE.md si cambia arquitectura, comandos o convenciones
- CHANGELOG.md o notas de release
- Diagramas si cambia el flujo o la estructura

### Regla de oro

Un PR que cambia comportamiento pero no actualiza documentacion esta INCOMPLETO.
