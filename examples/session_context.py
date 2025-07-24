from typing import Optional
from contextvars import ContextVar
from builtins import str

_session_context: ContextVar[Optional[str]] = ContextVar("session_id", default=None)


def get_session_context_id():
    return _session_context.get()


def set_session_context_id(session_id: str):
    _session_context.set(session_id)
