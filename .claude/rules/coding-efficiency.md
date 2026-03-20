# Eficiencia y Memoria

## Reglas

- Pre-asignar listas y buffers con capacidad conocida. Evitar grows dinamicos.
- Usar generadores/iteradores en vez de materializar colecciones completas en memoria cuando el dataset puede ser grande.
- Disenar estructuras de datos cache-friendly: preferir arrays contiguos sobre listas enlazadas.
- Preferir zero-copy cuando sea posible: evitar copias innecesarias de datos.

## Profiling obligatorio

NUNCA optimizar sin medir primero:
- Python: `cProfile`, `memory_profiler`, `py-spy`

## Anti-patrones

- Optimizar sin datos de profiling
- Copiar objetos grandes en loops
- Materializar datasets completos cuando se puede iterar
- Ignorar memory leaks en long-running processes
