"""Runnable synchronous and AsyncIO usage for n-log-forge.

Run from the repository root after installation:

    python -m example.sync_async
"""

from __future__ import annotations

import asyncio
import logging

from n_log_forge import configure, flush, getLogger, shutdown

log = getLogger("example.worker")


@log.timed("load_configuration")
def load_configuration() -> dict[str, bool]:
    log.debug("Loaded configuration", source="defaults")
    return {"ready": True}


@log.timed("fetch_user")
async def fetch_user(user_id: int) -> dict[str, int]:
    await asyncio.sleep(0)
    log.info("Fetched user %s", user_id, userId=user_id)
    return {"id": user_id}


async def main() -> None:
    configure(level="debug", packageName="Example Service")

    load_configuration()
    with log.timed("request"):
        await fetch_user(42)

    timer = log.startTimer("batch")
    try:
        log.warning("Processing batch", itemCount=3)
    finally:
        elapsed_seconds = timer.stop()
        log.info("Batch timer stopped", elapsedSeconds=elapsed_seconds)

    # Ordinary standard-library records use LogRecord.name as their source.
    logging.getLogger("dependency.client").error("Dependency example")

    flush()
    shutdown()


if __name__ == "__main__":
    asyncio.run(main())
