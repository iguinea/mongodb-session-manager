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
# retries instead, so it gets one less.
TOTAL_ATTEMPTS = 3
# Room for the exponential backoff the standard retry mode adds between
# attempts (about a second, then two).
BACKOFF_ALLOWANCE_SECONDS = 4


def worst_case_seconds() -> int:
    """The longest a single notification can hold its thread."""
    return (
        TOTAL_ATTEMPTS * (CONNECT_TIMEOUT_SECONDS + READ_TIMEOUT_SECONDS)
        + BACKOFF_ALLOWANCE_SECONDS
    )


def notification_config() -> Config:
    """Return the botocore config the bundled hooks build their clients with."""
    return Config(
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
        read_timeout=READ_TIMEOUT_SECONDS,
        retries={"mode": "standard", "max_attempts": TOTAL_ATTEMPTS - 1},
    )
