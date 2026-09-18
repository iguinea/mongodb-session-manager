"""Los eventos de un turno, tal y como los dispara un `Agent` de Strands.

Un turno de referencia son cuatro mensajes -- la pregunta, un `toolUse`, su
`toolResult` y la respuesta -- entre un `BeforeInvocationEvent` y un
`AfterInvocationEvent`. Esa envoltura no es decorativa desde #53: fuera de una
invocación no hay nada que garantice un cierre, y un mensaje que llega ahí se
escribe al momento en vez de esperar al lote.

La forma de cada mensaje tampoco: un `toolResult` es un mensaje `user`, y lo que
distingue la pregunta del usuario de él es su contenido, no su papel.

Los ficheros que cuentan escrituras usan esto para no inventarse dos veces cómo
es un turno. El orden real de los eventos lo prueba `test_invocation_metrics.py`
con un `Agent` de verdad; aquí solo se reproduce.
"""

from __future__ import annotations

from typing import Any

from strands.hooks import (
    AfterInvocationEvent,
    BeforeInvocationEvent,
    HookRegistry,
    MessageAddedEvent,
)

PROMPT: dict[str, Any] = {"role": "user", "content": [{"text": "y el mes pasado?"}]}
TOOL_USE: dict[str, Any] = {
    "role": "assistant",
    "content": [{"toolUse": {"toolUseId": "t1", "name": "consulta", "input": {}}}],
}
TOOL_RESULT: dict[str, Any] = {
    "role": "user",
    "content": [{"toolResult": {"toolUseId": "t1", "content": [{"text": "42"}]}}],
}
ANSWER: dict[str, Any] = {"role": "assistant", "content": [{"text": "42"}]}

TURN = [PROMPT, TOOL_USE, TOOL_RESULT, ANSWER]


def invoking(mgr, agent) -> HookRegistry:
    """Registra los hooks del manager y abre una invocación para el agente."""
    registry = HookRegistry()
    mgr.register_hooks(registry)
    registry.invoke_callbacks(BeforeInvocationEvent(agent=agent))
    return registry


def run_turn(mgr, agent, messages=TURN, on_message_added=None) -> None:
    """Dispara un turno entero por el registry del manager.

    Args:
        on_message_added: Se llama tras cada mensaje, para mover lo que el
            propio agente movería entre ciclos (las métricas acumuladas).
    """
    registry = invoking(mgr, agent)
    for message in messages:
        registry.invoke_callbacks(MessageAddedEvent(agent=agent, message=message))
        if on_message_added:
            on_message_added()
    registry.invoke_callbacks(AfterInvocationEvent(agent=agent))
