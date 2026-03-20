# Release & Operations

Checklist y reglas para releases, deployment y respuesta a incidentes.

## Checklist pre-release

Antes de crear un release, verificar:

- [ ] Tests pasan (unit + integration + e2e si aplica)
- [ ] Lint y formateo limpios
- [ ] Code review aprobado (workflow-review.md)
- [ ] CHANGELOG actualizado (o auto-generado)
- [ ] Version bumpeada (semver)
- [ ] No hay TODOs criticos pendientes (`grep -r "TODO.*CRITICAL\|FIXME\|HACK" src/`)
- [ ] Secretos y credenciales NO estan hardcodeados

## Gates de deployment

```
feature branch -> PR -> main -> staging -> produccion
                  |           |           |
                  v           v           v
              code review   smoke tests  monitoring
              CI green      QA manual     alertas
                            (si aplica)
```

## Estrategia de rollback

- **Siempre tener plan de rollback** antes de deployar
- **Migraciones reversibles**: Disenar migraciones de BD que se puedan revertir
- **Feature flags**: Para features de alto riesgo, deployar detras de un flag
- **No arreglar en produccion**: Revertir primero, investigar despues

## Monitoring post-deploy

Despues de cada deploy, revisar durante 15-30 minutos:

- **Logs**: Errores nuevos, warnings, excepciones no capturadas
- **Metricas**: Latencia, tasa de errores (4xx/5xx), throughput
- **Alertas**: Verificar que las alertas configuradas no estan disparandose

## Incident response basico

```
1. DETECTAR   Alerta, reporte de usuario, monitoring
2. COMUNICAR  Informar al equipo
3. MITIGAR    Rollback o workaround rapido
4. INVESTIGAR Root cause analysis (solo DESPUES de mitigar)
5. DOCUMENTAR Post-mortem: que paso, por que, como prevenirlo
```
