"""Comparing two runs, and refusing to when they are not comparable (#60).

The issue asks to document how to compare a branch before and after. The trap it
does not mention is the comparison that looks fine and is meaningless: a local
MongoDB against a tunnelled DocumentDB, or two runs with different compressors.
Those are reported side by side, never as a delta — the same rule the #58
evidence followed by hand.
"""

from __future__ import annotations

import pytest

from benchmarks.report import compare_runs, human_summary

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
        assert row.base_p50 == pytest.approx(10.0)
        assert row.head_p50 == pytest.approx(5.0)
        assert row.p50_change_pct == pytest.approx(-50.0)

    def test_scenarios_are_paired_by_their_key(self):
        base = _run(**{"a": 10.0, "b": 20.0})
        head = _run(**{"b": 10.0, "a": 5.0})

        report = compare_runs(base, head)

        by_key = {row.scenario: row for row in report.rows}
        assert by_key["a"].head_p50 == pytest.approx(5.0)
        assert by_key["b"].head_p50 == pytest.approx(10.0)

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

    def test_the_text_compares_throughput_and_event_loop_lag(self):
        base = _run(**{"turn_simple": 10.0})
        head = _run(**{"turn_simple": 5.0})
        base["results"][0]["throughput"] = {"operations_per_second": 100.0}
        head["results"][0]["throughput"] = {"operations_per_second": 180.0}
        base["results"][0]["loop_lag"] = {"lag": {"p99_ms": 90.0}}
        head["results"][0]["loop_lag"] = {"lag": {"p99_ms": 4.0}}

        text = compare_runs(base, head).describe()

        assert "base op/s" in text
        assert "head op/s" in text
        assert "100.0" in text and "180.0" in text
        assert "90.0" in text and "4.0" in text


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


class TestSaturationIsVisible:
    """The table has to say it, or the reader quotes the p99 as a tail."""

    def _document(self, n: int) -> dict:
        return {
            "schema_version": 1,
            "run": {"run_id": "r1"},
            "environment": {
                "engine_hint": "mongodb",
                "server_version": "8.2.7",
                "topology": "Single",
                "read_preference": "Primary()",
            },
            "cleanup": {"describe": "ok"},
            "failed_checks": [],
            "results": [
                {
                    "scenario": "turn.tool/h5000/c1",
                    "latency": {
                        "p50_ms": 1314.9,
                        "p95_ms": 1976.8,
                        "p99_ms": 1976.8,
                        "n": n,
                        "saturated": ["p95", "p99"] if n < 20 else [],
                    },
                    "commands": {"per_operation": 9.0},
                    "bytes": {"reply": 33356},
                    "pool": {},
                    "loop_lag": None,
                }
            ],
        }

    def test_a_saturated_percentile_is_marked(self):
        text = human_summary(self._document(n=15))

        assert "1976.800*" in text or "1976.800 *" in text.replace("  ", " ")

    def test_the_mark_is_explained_once(self):
        text = human_summary(self._document(n=15))

        assert "--repetitions" in text
        assert text.count("--repetitions") == 1

    def test_a_healthy_sample_is_not_marked(self):
        text = human_summary(self._document(n=100))

        assert "*" not in text
