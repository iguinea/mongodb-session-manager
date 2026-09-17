"""Which names can end up inside a MongoDB dot-notation path (issue #79).

The rule is checked here on its own, without a repository: the contract suite
then proves that both repository implementations apply it before any I/O.
"""

from __future__ import annotations

import pytest

from mongodb_session_manager.field_names import (
    nested_document,
    validate_agent_id,
    validate_field_paths,
)


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
