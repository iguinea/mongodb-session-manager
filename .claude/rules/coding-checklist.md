# Checklist de Programacion

## Transversal

- [ ] Queries parametrizadas (nunca concatenar strings)
- [ ] Connection pooling configurado
- [ ] Secrets en env vars o secret manager (nunca hardcodeados)
- [ ] Structured logging con contexto
- [ ] Input validation en boundaries del sistema
- [ ] Cache con TTL explicito y invalidacion en mutaciones
- [ ] Auth en todas las operaciones de escritura
- [ ] Dependency audit passing (sin vulnerabilidades conocidas)
- [ ] Error responses con estructura consistente
- [ ] Paginacion en endpoints de listado
- [ ] No dead code (imports, variables, funciones sin usar)
- [ ] Ficheros < 800 lineas, funciones < 50 lineas
- [ ] Documentacion actualizada con cada cambio de codigo
- [ ] Dependencias verificadas contra documentacion oficial
