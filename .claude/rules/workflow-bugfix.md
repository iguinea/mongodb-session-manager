# Autonomous Bug Fixing

Cuando recibas un bug report: corrigelo directamente. No pidas que te guien paso a paso.
(Boris Cherny, 10 Team Tips, Feb 2026, tip #5)

> Si el proyecto usa TDD (ver workflow-tdd.md), SIEMPRE escribir un test de
> reproduccion antes de corregir el bug. El test debe fallar antes del fix
> y pasar despues.

## Reglas

- **Cero cambio de contexto**: El usuario reporta el bug, tu lo resuelves. Sin preguntas
  innecesarias sobre como hacerlo.
- **Apuntar a evidencia**: Senala logs, errores, tests que fallan -- luego resuelve.
- **CI fallando**: "Ve a corregir los tests de CI que estan fallando." No microgestiones el como.
- **Logs de Docker**: Apunta Claude a los logs de contenedores para diagnosticar sistemas
  distribuidos.

## Flujo

1. Localizar el error (logs, stack trace, test fallido)
2. Reproducir si es posible (escribir test que falla)
3. Identificar root cause (no parches superficiales)
4. Corregir con cambio minimo
5. Verificar: test pasa, CI verde, comportamiento correcto
6. Si el fix es no trivial: pasar por code review

## Herramientas disponibles

- `dev-tools:qlty-auditor` -- Escaneo de seguridad y calidad
- `dev-tools:chrome-auditor` -- Debugging de performance web
- `dev-tools:web-tester` -- Verificacion en browser con Playwright
