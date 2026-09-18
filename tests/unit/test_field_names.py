"""Which names can end up inside a MongoDB dot-notation path (issue #79).

The rule is checked here on its own, without a repository: the contract suite
then proves that both repository implementations apply it before any I/O.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from mongodb_session_manager.field_names import (
    apply_fields,
    nested_document,
    resolve_path,
    validate_agent_id,
    validate_field_paths,
)


class TestApplyFields:
    """Escribir por ruta, lo que `$set` hace con notación de punto (#53).

    Es lo que mete los campos en un documento que todavía no está ahí para
    hacerle `$set`: un mensaje que se está creando con un `$push`, o la semilla
    de metadata que nace con la sesión.
    """

    def test_writes_each_path_where_it_points(self):
        assert apply_fields({}, {"a": 1, "b.c": 2}) == {"a": 1, "b": {"c": 2}}

    def test_keeps_what_the_document_already_had(self):
        document = {"message": {"role": "user"}, "message_id": 3}

        apply_fields(document, {"event_loop_metrics.accumulated_usage": {"t": 7}})

        assert document == {
            "message": {"role": "user"},
            "message_id": 3,
            "event_loop_metrics": {"accumulated_usage": {"t": 7}},
        }

    def test_a_path_into_an_existing_subdocument_keeps_its_siblings(self):
        document = {"message": {"role": "user", "content": []}}

        apply_fields(document, {"message.tracking_id": "t-1"})

        assert document["message"] == {
            "role": "user",
            "content": [],
            "tracking_id": "t-1",
        }

    def test_the_last_value_of_a_path_wins(self):
        assert apply_fields({"a": 1}, {"a": 2}) == {"a": 2}

    def test_it_validates_before_it_writes(self):
        document = {"a": 1}

        with pytest.raises(ValueError, match="message field"):
            apply_fields(document, {"b": 2, "$where": 3}, "message field")

        assert document == {"a": 1}

    def test_a_path_that_collides_with_a_value_is_refused(self):
        with pytest.raises(ValueError, match="conflicts"):
            apply_fields({"a": 1}, {"a.b": 2})


class TestAgentId:
    """An agent_id is a single field name: `agents.<agent_id>`."""

    @pytest.mark.parametrize(
        "agent_id", ["plain", "a$b", "agent-1_x", "agénte", "con espacio", "0"]
    )
    def test_accepts_a_single_field_name(self, agent_id):
        """`a$b` included: a `$` that does not start the name is plain data."""
        validate_agent_id(agent_id)

    @pytest.mark.parametrize("agent_id", ["a.b", ".a", "a.", "."])
    def test_rejects_a_dot(self, agent_id):
        """A dot turns `agents.a.b` into a nested path: the history is lost."""
        with pytest.raises(ValueError, match=r"agent_id .* cannot contain '\.'"):
            validate_agent_id(agent_id)

    @pytest.mark.parametrize("agent_id", ["$x", "$", "$[]"])
    def test_rejects_a_leading_dollar(self, agent_id):
        with pytest.raises(ValueError, match=r"cannot start with '\$'"):
            validate_agent_id(agent_id)

    def test_rejects_an_empty_name(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_agent_id("")

    def test_rejects_a_nul_byte(self):
        """BSON cannot encode it: pymongo would fail with InvalidDocument instead."""
        with pytest.raises(ValueError, match="NUL"):
            validate_agent_id("a\x00b")


class TestNestedDocument:
    """The document a set of paths describes, for seeding it in one insert (#59).

    `create_session()` used to seed `metadata_fields` as literal keys, so
    `user.name` landed as a flat key while its index and `update_metadata()`
    both went to the nested `metadata.user.name`. The seeded value did not match
    its own index, and nothing ever touched that key again.
    """

    def test_a_plain_name_is_a_plain_key(self):
        assert nested_document(["status", "priority"]) == {
            "status": "",
            "priority": "",
        }

    def test_a_dotted_path_nests(self):
        assert nested_document(["user.name"]) == {"user": {"name": ""}}

    def test_paths_that_share_a_prefix_share_the_subdocument(self):
        assert nested_document(["user.name", "user.role"]) == {
            "user": {"name": "", "role": ""}
        }

    def test_nests_as_deep_as_the_path_goes(self):
        assert nested_document(["a.b.c.d"]) == {"a": {"b": {"c": {"d": ""}}}}

    def test_nothing_in_nothing_out(self):
        assert nested_document([]) == {}

    def test_the_seeded_value_can_be_chosen(self):
        assert nested_document(["n"], value=0) == {"n": 0}

    def test_a_path_that_would_bury_another_is_rejected(self):
        """`user` and `user.name` cannot both be a value: one overwrites the other."""
        with pytest.raises(ValueError, match="conflict"):
            nested_document(["user", "user.name"])

    def test_the_conflict_is_caught_whichever_way_round_it_comes(self):
        with pytest.raises(ValueError, match="conflict"):
            nested_document(["user.name", "user"])

    def test_it_validates_before_it_builds(self):
        with pytest.raises(ValueError, match=r"cannot start with '\$'"):
            nested_document(["ok", "$where"])

    def test_a_one_shot_iterable_is_not_consumed_by_the_validation(self):
        """The signature says Iterable, so a generator has to work.

        Validating and then building walked `paths` twice: a generator was
        exhausted by the first pass and the second built nothing, so the seed
        vanished without an error and `create_session()` wrote empty metadata.
        """
        assert nested_document(path for path in ["user.name", "status"]) == {
            "user": {"name": ""},
            "status": "",
        }


class TestFieldPath:
    """A path is dot-separated segments, each of them a field name."""

    @pytest.mark.parametrize(
        "path", ["status", "user.name", "tags.0", "x.y$z", "a$b", "deep.er.path"]
    )
    def test_accepts_a_path_of_field_names(self, path):
        validate_field_paths([path], "metadata key")

    @pytest.mark.parametrize(
        ("path", "segment"),
        [("$where", "$where"), ("x.$y", "$y"), ("tags.$[]", "$[]"), ("a.$", "$")],
    )
    def test_rejects_a_segment_with_a_leading_dollar(self, path, segment):
        """MongoDB reads it as an operator, or cannot index it."""
        with pytest.raises(ValueError, match=r"cannot start with '\$'") as raised:
            validate_field_paths([path], "metadata key")

        assert repr(segment) in str(raised.value)

    @pytest.mark.parametrize("path", ["", "a..b", ".a", "a."])
    def test_rejects_an_empty_segment(self, path):
        with pytest.raises(ValueError, match="segment '' cannot be empty"):
            validate_field_paths([path], "metadata key")

    def test_rejects_a_nul_byte(self):
        with pytest.raises(ValueError, match="NUL"):
            validate_field_paths(["user.a\x00b"], "metadata key")

    def test_a_batch_fails_on_its_first_invalid_path(self):
        with pytest.raises(ValueError, match=r"'\$where'"):
            validate_field_paths(["status", "user.name", "$where"], "metadata key")

    def test_the_message_says_what_was_being_validated(self):
        with pytest.raises(ValueError, match=r"^metadata field 'a\.\.b'"):
            validate_field_paths(["a..b"], "metadata field")

    def test_a_non_string_key_is_checked_as_its_text(self):
        """Keys were joined with an f-string, so `{1: "x"}` wrote `metadata.1`."""
        validate_field_paths([1, "user.name"], "metadata key")


class TestResolvePath:
    """Reading a path out of a document, the mirror of writing one (#47).

    `update_metadata({"user.name": "Ana"})` writes a nested field, so asking for
    `user.name` has to find it. Resolving it here, on the document the read
    already returned, costs no extra round-trip.
    """

    DOCUMENT: ClassVar[dict[str, Any]] = {
        "user": {"name": "Ana", "address": {"city": "Madrid"}},
        "priority": "high",
        "tags": ["urgent", "vip"],
        "cleared": None,
        "open": False,
    }

    @pytest.mark.parametrize(
        ("path", "value"),
        [
            ("priority", "high"),
            ("user.name", "Ana"),
            ("user.address.city", "Madrid"),
            ("user.address", {"city": "Madrid"}),
            ("tags.0", "urgent"),
            ("tags.1", "vip"),
        ],
    )
    def test_finds_what_the_path_names(self, path, value):
        assert resolve_path(self.DOCUMENT, path) == (True, value)

    @pytest.mark.parametrize("path", ["cleared", "open"])
    def test_a_falsy_value_is_found(self, path):
        """`None` and `False` are stored values, not absences."""
        found, _ = resolve_path(self.DOCUMENT, path)
        assert found is True

    @pytest.mark.parametrize(
        "path",
        [
            "missing",
            "user.surname",
            "user.address.zip",
            "tags.2",
            "tags.last",
            "priority.high",
            "cleared.anything",
        ],
    )
    def test_says_nothing_is_there(self, path):
        """A path that stops short, runs past an array or walks into a value."""
        assert resolve_path(self.DOCUMENT, path) == (False, None)

    def test_does_not_read_a_literal_dotted_key(self):
        """A dot is a path separator, the same as it is for every write."""
        assert resolve_path({"user.name": "Ana"}, "user.name") == (False, None)

    def test_a_negative_index_is_not_an_index(self):
        """MongoDB has no `tags.-1`: it is a field name, and there is none."""
        assert resolve_path({"tags": ["a", "b"]}, "tags.-1") == (False, None)
