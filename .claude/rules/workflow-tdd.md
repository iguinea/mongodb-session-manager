# TDD Discipline

Nunca escribir codigo de produccion sin un test que falle primero.
Test-Driven Development es OBLIGATORIO en este proyecto.

## Ciclo Red-Green-Refactor

Seguir siempre el ciclo: RED (test que falla) -> GREEN (codigo minimo) -> REFACTOR (mejorar sin romper).

Para la guia detallada de TDD (Given-When-Then, niveles de tests, principios FIRST,
patrones por lenguaje), Claude activara automaticamente el skill `tdd` del plugin
`feature-dev` cuando detecte keywords como "TDD", "test first" o "red green refactor".

## Politica del proyecto

- **Obligatorio**: Todo codigo de produccion debe tener tests que fallen primero
- **Sin excepciones**: Si un test pasa sin codigo nuevo, el test es inutil -- reescribirlo
- **Refactor seguro**: Ejecutar tests despues de CADA cambio; si falla, deshacer
- **Orden**: Happy path -> Edge cases -> Error cases -> Integration

## Exigir elegancia

Para cambios no triviales, antes de dar por terminado preguntar:
"Hay una forma mas elegante de hacer esto?"

Si un fix se siente hacky: "Sabiendo todo lo que se ahora, descarta esto e implementa
la solucion elegante."

Para fixes simples y obvios, NO aplicar esto -- no sobre-ingenierar.
