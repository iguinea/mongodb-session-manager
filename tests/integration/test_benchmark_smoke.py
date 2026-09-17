"""The benchmark harness against a real server (issue #60).

Runs a deliberately tiny matrix: what is under test is the harness, not the
library's performance. The important test here is the negative one — a workload
that does nothing must fail the run — because that is the failure #60 exists to
make impossible: `examples/example_performance.py` reported throughput for a
loop whose body was `pass`.
"""

from __future__ import annotations

import json

import pytest
from pymongo import MongoClient

from benchmarks import workload as workload_module
from benchmarks.__main__ import main

pytestmark = pytest.mark.integration

DATABASE = "test_benchmark_harness"
COLLECTION = "sessions"


def _argv(connection_string: str, *extra: str) -> list[str]:
    return [
        "--connection-string",
        connection_string,
        "--database-name",
        DATABASE,
        "--collection-name",
        COLLECTION,
        "--warmups",
        "1",
        "--repetitions",
        "2",
        "--volume-repetitions",
        "1",
        "--baseline-seconds",
        "0.05",
        *extra,
    ]


@pytest.fixture
def benchmark_collection(mongodb_connection):
    client = MongoClient(mongodb_connection)
    collection = client[DATABASE][COLLECTION]
    yield collection
    # Nothing of ours should be here; if the harness leaked, say so loudly
    # rather than hiding it by dropping the collection.
    client.close()


def _leftovers(collection) -> int:
    return collection.count_documents({"_id": {"$regex": "^bench-"}})


class TestRealRun:
    def test_smoke_profile_runs_real_turns_and_cleans_up(
        self, mongodb_connection, benchmark_collection, tmp_path, capsys
    ):
        results_file = tmp_path / "run.json"

        exit_code = main(
            _argv(
                mongodb_connection,
                "--operation",
                "turn.supervisor",
                "--history",
                "10",
                "--json-out",
                str(results_file),
            )
        )

        assert exit_code == 0, capsys.readouterr().out
        document = json.loads(results_file.read_text())
        result = document["results"][0]

        assert result["passed"] is True
        assert result["latency"]["p50_ms"] > 0
        assert result["commands"]["total"] > 0
        assert result["bytes"]["reply"] > 0
        assert document["cleanup"]["leftovers"] == 0
        assert _leftovers(benchmark_collection) == 0

    def test_a_turn_issues_the_writes_the_budget_describes(
        self, mongodb_connection, benchmark_collection, tmp_path
    ):
        """Not a ceiling — `test_write_amplification_integration.py` owns that.
        This only proves the harness sees the same commands that test counts."""
        results_file = tmp_path / "run.json"

        main(
            _argv(
                mongodb_connection,
                "--operation",
                "turn.supervisor",
                "--history",
                "10",
                "--json-out",
                str(results_file),
            )
        )

        by_name = json.loads(results_file.read_text())["results"][0]["commands"][
            "by_name"
        ]
        assert by_name.get("update", 0) > 0

    def test_the_measured_window_creates_no_indexes(
        self, mongodb_connection, benchmark_collection, tmp_path
    ):
        """Warmups exist so the reported sample runs on a warm connection."""
        results_file = tmp_path / "run.json"

        main(
            _argv(
                mongodb_connection,
                "--operation",
                "turn.simple",
                "--history",
                "10",
                "--json-out",
                str(results_file),
            )
        )

        by_name = json.loads(results_file.read_text())["results"][0]["commands"][
            "by_name"
        ]
        assert "createIndexes" not in by_name

    def test_the_environment_travels_with_the_results(
        self, mongodb_connection, benchmark_collection, tmp_path
    ):
        """Without this a results file cannot be compared with another one."""
        results_file = tmp_path / "run.json"

        main(
            _argv(
                mongodb_connection,
                "--operation",
                "restore",
                "--history",
                "10",
                "--json-out",
                str(results_file),
            )
        )

        environment = json.loads(results_file.read_text())["environment"]
        assert environment["server_version"]
        assert environment["engine_hint"] in {
            "mongodb",
            "documentdb-or-compatible",
            "unknown",
        }
        assert environment["topology"]
        assert environment["read_preference"]
        assert environment["notes"]

    def test_event_loop_lag_is_reported_or_explained(
        self, mongodb_connection, benchmark_collection, tmp_path
    ):
        """A window shorter than one heartbeat says so, instead of printing a
        zero that would read as "the loop was never blocked"."""
        results_file = tmp_path / "run.json"

        main(
            _argv(
                mongodb_connection,
                "--operation",
                "turn.supervisor",
                "--history",
                "10",
                "--json-out",
                str(results_file),
            )
        )

        lag = json.loads(results_file.read_text())["results"][0]["loop_lag"]
        assert lag["baseline"]["n"] > 0
        assert lag["lag"] is not None or lag["reason"]


class TestTheHarnessFailsWhenNothingHappens:
    def test_a_workload_that_does_no_work_fails_the_run(
        self, mongodb_connection, benchmark_collection, monkeypatch, capsys
    ):
        """The bug that motivated #60, turned into a guardrail.

        A repetition that touches nothing still produces timings — very good
        ones. The run must refuse to report them.
        """

        async def measures_nothing(self) -> list[float]:
            return [0.001]

        monkeypatch.setattr(
            workload_module.Workload, "run_repetition", measures_nothing
        )

        exit_code = main(
            _argv(mongodb_connection, "--operation", "turn.simple", "--history", "10")
        )

        assert exit_code == 1
        output = capsys.readouterr().out
        assert "did not prove it did the work" in output

    def test_the_synthetic_data_still_disappears(
        self, mongodb_connection, benchmark_collection, monkeypatch
    ):
        """Cleanup is not conditional on the run going well."""

        async def explodes(self) -> list[float]:
            raise RuntimeError("the workload broke")

        monkeypatch.setattr(workload_module.Workload, "run_repetition", explodes)

        with pytest.raises(RuntimeError, match="the workload broke"):
            main(
                _argv(
                    mongodb_connection, "--operation", "turn.simple", "--history", "10"
                )
            )

        assert _leftovers(benchmark_collection) == 0


class TestRefusals:
    def test_a_run_without_a_connection_string_is_refused(self, monkeypatch):
        monkeypatch.delenv("MONGODB_CONNECTION_STRING", raising=False)

        assert main(["--profile", "smoke"]) == 2

    def test_the_full_matrix_is_refused_without_permission(self):
        assert main(["--profile", "full", "--dry-run"]) == 2
