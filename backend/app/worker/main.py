"""Worker entry point: poll the Postgres queue and run jobs one at a time."""

import logging
import signal
import time

from app.worker.handlers import HANDLERS
from app.worker.runner import process_one

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")

POLL_SECONDS = 2.0
_running = True


def _stop(*_: object) -> None:
    global _running
    _running = False


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("worker started: %s", ", ".join(sorted(HANDLERS)))
    while _running:
        try:
            worked = process_one(HANDLERS)
        except Exception:  # noqa: BLE001 - e.g. database briefly unavailable; keep the loop alive
            log.exception("worker loop error")
            worked = False
        if not worked:
            time.sleep(POLL_SECONDS)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
