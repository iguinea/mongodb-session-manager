"""Reproducible benchmark harness for MongoDB and Amazon DocumentDB (issue #60).

Run it with ``uv run python -m benchmarks`` from the repository root. The package
is deliberately not installable: it imports the scripted model the integration
tests already use, so that a benchmark turn and a tested turn are the same turn.
"""
