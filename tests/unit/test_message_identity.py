"""The stable identity of a message, and the SDK contract it rests on.

`storage_id` rides on the `SessionMessage` instance Strands keeps for the whole
turn, as an attribute outside the dataclass fields. That is a contract with an
SDK this project does not own, so it is pinned here: an upgrade that breaks it
fails in this file, loudly, instead of silently turning issue #78 back on in
production.
"""

from __future__ import annotations

from dataclasses import asdict

from strands.types.session import SessionMessage

from mongodb_session_manager.message_identity import (
    STORAGE_ID_FIELD,
    MessageRef,
    attach_storage_id,
    new_storage_id,
    ref_of,
    storage_id_of,
)


def a_message(message_id: int = 1) -> SessionMessage:
    """Build a SessionMessage the way Strands does."""
    return SessionMessage(
        message_id=message_id, message={"role": "user", "content": [{"text": "hi"}]}
    )


class TestSDKContract:
    """What `attach_storage_id()` assumes about Strands' SessionMessage."""

    def test_accepts_an_attribute_outside_its_fields(self):
        message = a_message()

        attach_storage_id(message, "9f1c")

        assert storage_id_of(message) == "9f1c"

    def test_the_identity_stays_out_of_what_strands_serializes(self):
        """It must not reach `to_dict()`: that is the SDK's own wire format."""
        message = a_message()

        attach_storage_id(message, "9f1c")

        assert STORAGE_ID_FIELD not in asdict(message)
        assert STORAGE_ID_FIELD not in message.to_dict()


class TestStorageId:
    def test_a_message_without_one_reports_none(self):
        assert storage_id_of(a_message()) is None

    def test_attaching_none_leaves_the_message_alone(self):
        """A pre-#78 message read back has nothing to attach."""
        message = a_message()

        attach_storage_id(message, None)

        assert storage_id_of(message) is None

    def test_minted_identities_do_not_repeat(self):
        assert len({new_storage_id() for _ in range(100)}) == 100


class TestMessageRef:
    def test_locates_by_identity_when_there_is_one(self):
        assert MessageRef(7, "9f1c").locator() == (STORAGE_ID_FIELD, "9f1c")

    def test_falls_back_to_the_index_without_one(self):
        """The pre-#78 rule, kept so stored messages need no migration."""
        assert MessageRef(7).locator() == ("message_id", 7)

    def test_from_a_stored_document(self):
        ref = MessageRef.from_document({"message_id": 7, STORAGE_ID_FIELD: "9f1c"})

        assert ref == MessageRef(7, "9f1c")

    def test_from_a_document_stored_before_the_identity(self):
        assert MessageRef.from_document({"message_id": 7}) == MessageRef(7)

    def test_from_the_message_that_carries_it(self):
        message = a_message(7)
        attach_storage_id(message, "9f1c")

        assert ref_of(message) == MessageRef(7, "9f1c")
