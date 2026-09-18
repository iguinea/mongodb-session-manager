"""Names that end up inside a MongoDB dot-notation path.

The repository stores each agent under `agents.<agent_id>` and each metadata key
under `metadata.<key>`, and reaches both with dot notation. MongoDB reads those
names as syntax, not as data (issue #79):

- A dot is a path separator. `agent_id="a.b"` writes to `agents.a.b`, nested,
  while every read looks for the literal key; the agent is never found, so each
  request creates it again and wipes its history.
- A leading `$` is an operator: `tags.$[]` rewrites every element of an array,
  `$x` breaks every projection, and neither can be indexed.
- An empty segment is rejected by the server with an opaque error, and a NUL
  byte cannot be encoded as BSON at all.

A `$` anywhere else is plain data: `a$b` works in every operation, so it stays.

The rule lives here, in one place, so the MongoDB repository, the in-memory
double and the session manager all reject the same names -- before any
round-trip, with an error that says why.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _segment_problem(segment: str) -> str | None:
    """Say why a single field name cannot go into a path, None when it can."""
    if not segment:
        return "cannot be empty"
    if segment.startswith("$"):
        return "cannot start with '$': MongoDB reads it as an operator"
    if "\x00" in segment:
        return "contains a NUL byte, which BSON cannot encode"
    return None


def validate_field_paths(paths: Iterable[str], what: str) -> None:
    """Check dot-notation paths whose segments come from outside the repository.

    A dot separates segments on purpose here: `user.name` is a nested field and
    `tags.0` an array element, as documented for metadata (#47). Every path is
    checked before the caller uses any of them, so a batch is all or nothing.

    Args:
        paths: The paths, relative to wherever the repository will prefix them.
        what: What the paths are, to name them in the error ("metadata key").

    Raises:
        ValueError: When a segment is empty, starts with `$` or holds a NUL.
    """
    for path in paths:
        # A path is checked as the text it becomes: keys have always been joined
        # with an f-string, so `{1: "x"}` writes `metadata.1`.
        for segment in str(path).split("."):
            problem = _segment_problem(segment)
            if problem is not None:
                raise ValueError(
                    f"{what} {path!r} is invalid: segment {segment!r} {problem}"
                )


def nested_document(paths: Iterable[str], value: Any = "") -> dict[str, Any]:
    """Build the document a set of dot-notation paths describes.

    A dot is a path separator everywhere else in this library, so a document
    seeded with the literal key `user.name` is not the field that
    `metadata.user.name` indexes and that `update_metadata()` writes: the seed
    never matched its own index, and nothing touched that key again (#59).

    Args:
        paths: The paths to create, relative to the document being built.
        value: What to store at the end of each path.

    Returns:
        The document, nested as deep as each path goes.

    Raises:
        ValueError: When a path is not valid, under the same rule as
            validate_field_paths(); or when two paths cannot coexist because
            one would have to be both a value and a subdocument (`user` and
            `user.name`). MongoDB rejects that same pair in a single `$set`,
            and building it here would silently drop one of the two.
    """
    # Walked twice below, and the signature promises to take any iterable: a
    # generator was exhausted by the validation and built nothing, so the seed
    # disappeared without an error.
    paths = list(paths)
    validate_field_paths(paths, "metadata field")

    document: dict[str, Any] = {}
    for path in paths:
        segments = str(path).split(".")
        here = document
        for segment in segments[:-1]:
            branch = here.setdefault(segment, {})
            if not isinstance(branch, dict):
                raise ValueError(
                    f"metadata field {path!r} conflicts with {segment!r}, which is "
                    f"already a value: a field cannot hold a value and a subdocument"
                )
            here = branch
        leaf = segments[-1]
        if isinstance(here.get(leaf), dict):
            raise ValueError(
                f"metadata field {path!r} conflicts with a longer path already "
                f"nested under {leaf!r}: a field cannot hold a value and a subdocument"
            )
        here[leaf] = value
    return document


def resolve_path(document: dict[str, Any], path: str) -> tuple[bool, Any]:
    """Read the value a dot-notation path names, the mirror of writing one.

    `update_metadata({"user.name": "Ana"})` writes a nested field, so asking for
    `user.name` has to find it there and not as a literal key. The metadata tool
    filtered the top-level keys instead, and told an agent that had just written
    `user.name` that no such metadata existed (#47).

    Args:
        document: The decoded document to walk, as MongoDB returned it.
        path: The path, relative to that document.

    Returns:
        Whether the path is there, and the value stored at it. The two are
        separate because `None` and `False` are values a document can hold,
        and neither means the field is missing.
    """
    here: Any = document
    for segment in str(path).split("."):
        if isinstance(here, dict):
            if segment not in here:
                return False, None
            here = here[segment]
        elif isinstance(here, list):
            # MongoDB reads a numeric segment as the index of an array element.
            # `-1` is not one: it reads it as a field name, and an array has none.
            if not segment.isdigit() or int(segment) >= len(here):
                return False, None
            here = here[int(segment)]
        else:
            # The path goes on past a value: `priority.high` over a string.
            return False, None
    return True, here


def validate_agent_id(agent_id: str) -> None:
    """Check that an agent_id is a single field name, usable as `agents.<agent_id>`.

    Raises:
        ValueError: When it contains a dot, is empty, starts with `$` or holds a NUL.
    """
    if "." in agent_id:
        raise ValueError(
            f"agent_id {agent_id!r} cannot contain '.': MongoDB reads it as a path "
            f"separator, so the agent would be stored where no read can find it"
        )

    problem = _segment_problem(agent_id)
    if problem is not None:
        raise ValueError(f"agent_id {agent_id!r} {problem}")
