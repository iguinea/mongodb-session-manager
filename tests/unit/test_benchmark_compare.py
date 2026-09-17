"""Comparing two runs, and refusing to when they are not comparable (#60).

The issue asks to document how to compare a branch before and after. The trap it
does not mention is the comparison that looks fine and is meaningless: a local
MongoDB against a tunnelled DocumentDB, or two runs with different compressors.
Those are reported side by side, never as a delta — the same rule the #58
evidence followed by hand.
"""

from __future__ import annotations

from benchmarks.report import compare_runs

BASE_ENVIRONMENT = {
    "engine_hint": "mongodb",
    "server_version": "8.2.7",
    "topology": "Single",
    "read_preference": "Primary()",
    "uri_options": {},
}


def _run(environment=None, **latencies) -> dict:
    return {
        "schema_version": 1,
        "run": {"run_id": "test"},
        "environment": environment or dict(BASE_ENVIRONMENT),
        "results": [
            {
                "scenario": key,
                "latency": {"p50_ms": p50, "p95_ms": p50 * 2, "p99_ms": p50 * 3},
                "bytes": {"reply": 1000},
                "commands": {"total": 14},
            }
            for key, p50 in latencies.items()
        ],
    }


class TestComparable:
    def test_a_faster_run_shows_a_negative_delta(self):
        base = _run(**{"turn_simple": 10.0})
        head = _run(**{"turn_simple": 5.0})

        report = compare_runs(base, head)

        assert report.comparable is True
        row = report.rows[0]
        assert row.base_p50 == 10.0
        assert row.head_p50 == 5.0
        assert row.p50_change_pct == -50.0

    def test_scenarios_are_paired_by_their_key(self):
        base = _run(**{"a": 10.0, "b": 20.0})
        head = _run(**{"b": 10.0, "a": 5.0})

        report = compare_runs(base, head)

        by_key = {row.scenario: row for row in report.rows}
        assert by_key["a"].head_p50 == 5.0
        assert by_key["b"].head_p50 == 10.0

    def test_a_scenario_missing_from_one_side_is_reported_not_dropped(self):
        base = _run(**{"a": 10.0, "b": 20.0})
        head = _run(**{"a": 10.0})

        report = compare_runs(base, head)

        missing = [row for row in report.rows if row.scenario == "b"]
        assert missing and missing[0].head_p50 is None

    def test_the_text_says_what_changed(self):
        base = _run(**{"turn_simple": 10.0})
        head = _run(**{"turn_simple": 5.0})

        text = compare_runs(base, head).describe()

        assert "turn_simple" in text
        assert "-50" in text


class TestNotComparable:
    def test_differing_engines_are_reported_as_not_comparable(self):
        base = _run(**{"turn_simple": 10.0})
        documentdb = dict(BASE_ENVIRONMENT)
        documentdb["engine_hint"] = "documentdb-or-compatible"
        documentdb["server_version"] = "5.0.0"
        head = _run(environment=documentdb, **{"turn_simple": 60.0})

        report = compare_runs(base, head)

        assert report.comparable is False
        assert "engine_hint" in report.differences
        assert report.rows[0].p50_change_pct is None

    def test_a_different_compressor_stops_the_byte_comparison(self):
        base = _run(**{"turn_simple": 10.0})
        compressed = dict(BASE_ENVIRONMENT)
        compressed["uri_options"] = {"compressors": ["zlib"]}
        head = _run(environment=compressed, **{"turn_simple": 10.0})

        report = compare_runs(base, head)

        assert report.comparable is False
        assert "compressors" in report.differences

    def test_both_columns_are_still_shown(self):
        """Side by side is the useful answer for MongoDB versus DocumentDB."""
        base = _run(**{"turn_simple": 10.0})
        other = dict(BASE_ENVIRONMENT)
        other["topology"] = "ReplicaSetWithPrimary"
        head = _run(environment=other, **{"turn_simple": 60.0})

        text = compare_runs(base, head).describe()

        assert "10" in text and "60" in text
        assert "not comparable" in text.lower()

    def test_the_difference_is_named(self):
        base = _run(**{"turn_simple": 10.0})
        other = dict(BASE_ENVIRONMENT)
        other["read_preference"] = "SecondaryPreferred()"
        head = _run(environment=other, **{"turn_simple": 10.0})

        report = compare_runs(base, head)

        assert report.differences["read_preference"] == (
            "Primary()",
            "SecondaryPreferred()",
        )
