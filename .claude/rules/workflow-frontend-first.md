# Frontend First -- Mock Before Backend

Maquetar el frontend con datos mock ANTES de desarrollar el backend.
Esto descubre campos, DTOs y flujos reales que de otro modo se definen en abstracto.

## Por que

1. **Descubre DTOs**: Al maquetar con datos reales, identificas exactamente que campos
   necesita cada vista -- sin adivinar desde el backend.
2. **Define contratos**: Los datos mock se convierten en el contrato API (request/response)
   que el backend debe implementar.
3. **Reduce confusion**: Cuando editas comportamientos en el frontend, los cambios
   necesarios en el backend son evidentes inmediatamente.
4. **Feedback visual**: Ver la UI con datos reales permite validar con stakeholders
   antes de invertir en backend.

## Flujo

```
1. MOCK     Maquetar pantallas con datos hardcodeados (JSON/fixtures)
2. EXTRACT  Extraer los datos mock como tipos/interfaces
3. CONTRACT Definir el contrato API (OpenAPI, GraphQL schema, tRPC router)
4. BACKEND  Implementar backend contra los contratos definidos
5. CONNECT  Reemplazar datos mock por llamadas reales al backend
```

## Cuando usar este patron

| Situacion | Usar Frontend First? |
|-----------|---------------------|
| Feature nueva con UI | SI -- descubre DTOs antes de backend |
| API-only / sin UI | NO -- definir contratos directamente |
| Refactor de UI existente | SI -- maquetar cambios con datos reales |
| Bug fix en backend | NO -- el contrato ya existe |
| Prototipo rapido para validar idea | SI -- ideal para feedback temprano |
