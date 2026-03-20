# Dependencias Externas y Documentacion Oficial

## Regla fundamental

SIEMPRE consultar la documentacion oficial de una libreria antes de:
- Usar metodos o funciones de su API
- Implementar integraciones o configuraciones
- Resolver errores o problemas
- Asumir signatures, parametros o comportamientos

## Como verificar

1. Identificar la version exacta en `pyproject.toml` o `uv.lock`
2. Consultar la documentacion de ESA version (no la latest si difiere)
3. Usar WebFetch/WebSearch para acceder a docs oficiales

## Fuentes autorizadas (por orden de prioridad)

1. Documentacion oficial del proyecto/libreria
2. Repository README y ejemplos del repo
3. Changelogs y migration guides (para upgrades)
4. Issues/discussions del repo oficial

## Gestion de dependencias

- Lock files SIEMPRE commiteados (`uv.lock`)
- Actualizar dependencias con breaking changes solo tras leer migration guide
- Pinear versiones en produccion
- Auditoria regular: `pip audit`

## Anti-patrones

- Asumir method signatures de memoria sin verificar
- Usar patrones de una version antigua sin comprobar compatibilidad
- Copiar ejemplos sin validar contra docs oficiales de la version en uso
