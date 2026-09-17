"""How long a hook notification may spend talking to AWS.

botocore's defaults — 60 s to connect, 60 s to read, the legacy retry mode —
suit a request somebody is waiting for. A hook notification is not that: it
runs in the background, after the write it accompanies already succeeded, and
the thread it holds is the resource the limit on work in flight protects. One
notification against an unreachable endpoint would otherwise keep a thread for
minutes.

The budget here is deliberately smaller than the grace an orchestrator gives a
task on shutdown (30 s on ECS by default), so a notification in flight resolves
one way or the other before the process is killed.
"""

from botocore.config import Config

CONNECT_TIMEOUT_SECONDS = 3
READ_TIMEOUT_SECONDS = 5
# Attempts in total, first one included. botocore's `max_attempts` counts
# retries instead, so it gets one less. Two is what fits: a retry covers the
# transient reset that most notification failures are, and a third attempt
# would push the worst case past the shutdown grace once the backoff below is
# counted honestly.
TOTAL_ATTEMPTS = 2

# What botocore can wait before a retry, taken from its own
# `retries.standard.ExponentialBackoff`: `rand(0,1) * 2**(retry-1)` seconds for
# a throttled response, capped at `_MAX_BACKOFF`, plus up to
# `_RETRY_AFTER_MAX_ADDITIONAL` more when the response carries an
# `x-amz-retry-after` header. That header is only honoured on the retry path
# `AWS_NEW_RETRIES_2026` turns on, which any deployment may set — so the budget
# assumes it. A test asks botocore for these numbers and fails if they move.
MAX_BACKOFF_SECONDS = 20
RETRY_AFTER_ALLOWANCE_SECONDS = 5


def backoff_seconds(retry: int) -> int:
    """The longest botocore waits before retry number `retry` (1-based)."""
    return min(2 ** (retry - 1), MAX_BACKOFF_SECONDS) + RETRY_AFTER_ALLOWANCE_SECONDS


def worst_case_seconds() -> int:
    """The longest a single notification can hold its thread."""
    talking = TOTAL_ATTEMPTS * (CONNECT_TIMEOUT_SECONDS + READ_TIMEOUT_SECONDS)
    waiting = sum(backoff_seconds(retry) for retry in range(1, TOTAL_ATTEMPTS))
    return talking + waiting


def notification_config() -> Config:
    """Return the botocore config the bundled hooks build their clients with."""
    return Config(
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
        read_timeout=READ_TIMEOUT_SECONDS,
        retries={"mode": "standard", "max_attempts": TOTAL_ATTEMPTS - 1},
    )
