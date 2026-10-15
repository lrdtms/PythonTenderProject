"""Worker entry point. Placeholder loop; the Postgres job queue arrives with M2-3."""

import logging
import signal
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")

_running = True


def _stop(*_: object) -> None:
    global _running
    _running = False


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("worker started (no job handlers registered yet)")
    while _running:
        time.sleep(1)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
