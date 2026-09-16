"""Stable identity of a stored message.

`message_id` is an *index*, not an identity: Strands derives it in memory
(`RepositorySessionManager.append_message`: `latest.message_id + 1`) and each
manager restores its counter from the last stored message. Two managers
restoring the same agent at once compute the same index, so the message array
can end up holding two messages numbered alike -- and MongoDB's positional
operator then updates the first one that matches, which is how a redaction
lands on the wrong message (issue #78).

`storage_id` is the identity: written once by `create_message()`, never derived
from anything, never rewritten. It travels attached to the `SessionMessage`
because Strands keeps the very same instance for the whole turn -- it appends
it, hands it to the repository, remembers it in `_latest_agent_message` and
gives it back for the redaction. Attaching the identity to that object is what
lets a write name the message this process appended instead of whatever shares
its index.

Messages written before #78 have no `storage_id`. They keep being located by
`message_id`, exactly as they always were, which is why this needs no migration.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from strands.types.session import SessionMessage

# Field holding the identity, both on the stored document and on the
# SessionMessage carrying it around.
STORAGE_ID_FIELD = "storage_id"


@dataclass(frozen=True)
class MessageRef:
    """Points at one stored message.

    Attributes:
        message_id: Index of the message in the conversation, as Strands sees
            it. Kept because it is what the session history is ordered and read
            by, and the only thing a pre-#78 message has.
        storage_id: Identity of the stored message, when it has one.
    """

    message_id: int
    storage_id: str | None = None

    @classmethod
    def from_document(cls, msg_data: Mapping[str, Any]) -> MessageRef:
        """Reference a message as it is stored."""
        return cls(
            message_id=msg_data["message_id"],
            storage_id=msg_data.get(STORAGE_ID_FIELD),
        )

    def locator(self) -> tuple[str, Any]:
        """Name the field that identifies this message, and the value to match.

        The identity whenever the message has one: no other message can answer
        to it. A message stored before #78 has none and falls back to its index,
        where a duplicate matches its first occurrence only.

        This is the whole rule, in one place: every implementation of the
        repository -- MongoDB's positional selector and the in-memory double's
        list scan -- asks here rather than deciding for itself.
        """
        if self.storage_id is not None:
            return STORAGE_ID_FIELD, self.storage_id
        return "message_id", self.message_id


def new_storage_id() -> str:
    """Mint an identity for a message about to be stored."""
    return uuid4().hex


def attach_storage_id(session_message: SessionMessage, storage_id: str | None) -> None:
    """Attach an identity to the SessionMessage that carries it around.

    Set outside the dataclass fields on purpose: `asdict()` and `to_dict()`
    ignore it, so nothing Strands serializes changes shape. That `SessionMessage`
    accepts the attribute at all is a contract with the SDK, pinned by
    `tests/unit/test_message_identity.py` so an upgrade that breaks it fails
    there instead of quietly turning #78 back on.
    """
    if storage_id is None:
        return

    setattr(session_message, STORAGE_ID_FIELD, storage_id)


def storage_id_of(session_message: SessionMessage) -> str | None:
    """Return the identity a SessionMessage carries, None when it has none."""
    return getattr(session_message, STORAGE_ID_FIELD, None)


def ref_of(session_message: SessionMessage) -> MessageRef:
    """Build the reference that points at a SessionMessage where it is stored."""
    return MessageRef(
        message_id=session_message.message_id,
        storage_id=storage_id_of(session_message),
    )
