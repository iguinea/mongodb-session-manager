# Plan: reducir lecturas completas al restaurar sesiones

Issue: [#57](https://github.com/iguinea/mongodb-session-manager/issues/57)

## Objetivo

Evitar que las lecturas de cabecera y estado del agente transfieran el historial
embebido. La restauracion conserva sus tres lecturas de dominio y todos los datos
restaurados, pero `read_session()` proyecta solo la cabecera de `Session` y
`read_agent()` solo `agent_data`.

## Evidencia y decision

- MongoDB 8.2.7 local, 30 repeticiones con calentamiento: con 5.000 mensajes de
  918 bytes BSON, la restauracion paso de 13.570 KiB / 64,24 ms p50 a
  4.523 KiB / 23,96 ms p50.
- La proyeccion `agents.<id>.agent_data` conserva el estado del agente y los campos
  `model` / `system_prompt` que hidratan la cache de configuracion.
- Strands 1.30.0 ya pasa `removed_message_count` como `offset` a `list_messages()`.
  Esa lectura no cambia: ordena por `created_at` antes de paginar.
- `$slice` queda fuera. Aplicarlo sobre el orden fisico del array antes de la
  ordenacion cambia el resultado cuando ambos ordenes difieren.
- La preferencia de lectura queda fuera de este cambio. Las proyecciones respetan
  la configuracion que ya hereda la coleccion.

## TDD

### RED

1. Test unitario: `read_session()` envia exactamente la proyeccion de los cuatro
   campos de `Session`.
2. Test unitario: `read_agent()` envia exactamente la proyeccion de
   `agents.<id>.agent_data`.
3. Tests de integracion con `CommandListener`: un MongoDB real recibe ambas
   proyecciones y la configuracion del agente sigue disponible.

Los cuatro tests deben fallar contra v0.15.0 antes de tocar produccion.

### GREEN

1. Anadir la proyeccion de cabecera al `find_one()` de `read_session()`.
2. Estrechar la proyeccion de `read_agent()` hasta `agent_data`.
3. No cambiar contratos, modelos ni el numero de comandos.

### REFACTOR Y VERIFICACION

1. Ejecutar los tests nuevos y los tests de repositorio/manager relacionados.
2. Ejecutar integracion contra `localhost:8550`.
3. Ejecutar `ruff format`, `ruff check` y la suite completa.
4. Revisar manualmente que no se haya introducido `$slice`, otra lectura ni una
   dependencia del manager respecto a la coleccion.

## Criterios de aceptacion

- Los tests nuevos demuestran RED antes de la implementacion y GREEN despues.
- `read_session()` no solicita `agents`, metadata, feedbacks ni guardrails.
- `read_agent()` no solicita `messages` y conserva `model` / `system_prompt`.
- Restaurar una sesion sigue produciendo los mismos mensajes, estado y cache.
- Suite completa y Ruff pasan.
