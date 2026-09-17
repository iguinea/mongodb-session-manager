"""Command line of the benchmark harness.

    uv run python -m benchmarks --help

Configuration comes from the environment: `MONGODB_CONNECTION_STRING` points at
whatever should be measured — a local MongoDB, or a DocumentDB cluster through
the tunnel described in `docs/development/testing.md`. No credential is ever
read, printed or stored by this package.

Exit codes: 0 the run proved its work, 1 a scenario did not, 2 the run was
refused before it started.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from benchmarks.environment import capture, ping_probe
from benchmarks.report import build_document, compare_runs, human_summary
from benchmarks.run_context import RunContext
from benchmarks.runner import Probes, build_client, run_matrix
from benchmarks.scenarios import LoadTooLarge, build_matrix, plan_run

DEFAULT_DATABASE = "benchmark_mongodb_session_manager"
DEFAULT_COLLECTION = "sessions"


def _add_target_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--connection-string",
        default=os.environ.get("MONGODB_CONNECTION_STRING"),
        help="defaults to $MONGODB_CONNECTION_STRING",
    )
    parser.add_argument("--database-name", default=DEFAULT_DATABASE)
    parser.add_argument("--collection-name", default=DEFAULT_COLLECTION)


def _add_matrix_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        default="smoke",
        choices=("smoke", "full"),
        help="smoke runs in minutes; full is the matrix of the issue",
    )
    parser.add_argument("--history", type=int, action="append", dest="histories")
    parser.add_argument("--operation", action="append", dest="operations")
    parser.add_argument(
        "--concurrency", type=int, action="append", dest="concurrencies"
    )
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--repetitions", type=int, default=30)
    parser.add_argument("--volume-repetitions", type=int, default=3)
    parser.add_argument(
        "--baseline-seconds",
        type=float,
        default=1.0,
        help="idle-loop calibration taken before each scenario",
    )


def _add_safety_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--allow-large",
        action="store_true",
        help="required for runs above the size guardrails",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the matrix and its cost without connecting",
    )
    parser.add_argument(
        "--keep-data",
        action="store_true",
        help="leave the synthetic sessions behind, and say which ones",
    )


def _add_output_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--label", default="", help="free text: region, tunnel, host")
    parser.add_argument("--note", action="append", dest="notes")
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("BASE.json", "HEAD.json"),
        type=Path,
        help="compare two result files and exit",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks",
        description=(
            "Reproducible benchmark of MongoDB Session Manager, against MongoDB "
            "or Amazon DocumentDB (issue #60)."
        ),
    )
    _add_target_arguments(parser)
    _add_matrix_arguments(parser)
    _add_safety_arguments(parser)
    _add_output_arguments(parser)
    return parser


def _compare(paths: list[Path]) -> int:
    base, head = (json.loads(path.read_text()) for path in paths)
    print(compare_runs(base, head).describe())
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.compare:
        return _compare(args.compare)

    try:
        scenarios = build_matrix(
            args.profile,
            histories=args.histories,
            operations=args.operations,
            concurrencies=args.concurrencies,
        )
        plan = plan_run(
            scenarios,
            warmups=args.warmups,
            repetitions=args.repetitions,
            volume_repetitions=args.volume_repetitions,
            allow_large=args.allow_large,
        )
    except (ValueError, LoadTooLarge) as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 2

    print(plan.describe())
    if args.dry_run:
        print("\ndry run: nothing was written")
        return 0

    if not args.connection_string:
        print(
            "refused: no connection string. Set MONGODB_CONNECTION_STRING or "
            "pass --connection-string.",
            file=sys.stderr,
        )
        return 2

    return _execute(args, plan)


def _configuration(args: argparse.Namespace, plan: Any) -> dict[str, Any]:
    return {
        "profile": args.profile,
        "warmups": args.warmups,
        "repetitions": args.repetitions,
        "volume_repetitions": args.volume_repetitions,
        "baseline_seconds": args.baseline_seconds,
        "database_name": args.database_name,
        "collection_name": args.collection_name,
        "synthetic_messages_planned": plan.synthetic_messages,
    }


def _measure(args: argparse.Namespace, plan: Any) -> dict[str, Any]:
    """Runs the matrix and returns the results document."""
    probes = Probes.new()
    client = build_client(args.connection_string, probes)
    try:
        environment = capture(
            client,
            connection_string=args.connection_string,
            label=args.label,
            notes=args.notes or [],
        )
        ping_before = ping_probe(client)
        collection = client[args.database_name][args.collection_name]

        with RunContext(collection, keep_data=args.keep_data) as run:
            results = run_matrix(
                database_name=args.database_name,
                collection_name=args.collection_name,
                run=run,
                plan=plan,
                probes=probes,
                client=client,
                baseline_seconds=args.baseline_seconds,
                on_progress=lambda message: print(f"  · {message}", flush=True),
            )
            ping_after = ping_probe(client)

        cleanup = run.cleanup_report
        return build_document(
            run_id=run.run_id,
            environment=environment.as_dict(),
            config=_configuration(args, plan),
            results=results,
            cleanup={**cleanup.as_dict(), "describe": cleanup.describe()},
            ping_before=ping_before.as_dict(),
            ping_after=ping_after.as_dict(),
        )
    finally:
        client.close()


def _execute(args: argparse.Namespace, plan: Any) -> int:
    document = _measure(args, plan)
    print(human_summary(document))

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(document, indent=2, default=str))
        print(f"\nresults written to {args.json_out}")

    cleanup = document["cleanup"]
    if document["failed_checks"]:
        return 1
    if cleanup["leftovers"] and not cleanup["kept"]:
        print(
            f"\n{cleanup['leftovers']} synthetic sessions were left behind",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
