"""Files written before their row is committed (ADR-0007): delete them if the transaction fails."""

from __future__ import annotations

import logging

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.kernel import StoragePort

log = logging.getLogger(__name__)

_STORED_FILES = "documents.stored_files"


def delete_on_rollback(session: Session, storage: StoragePort, key: str) -> None:
    """ADR-0007: the file is written before its row is committed. If the surrounding transaction
    rolls back (a failed flush, enqueue or commit), delete the file so it is not orphaned.
    Best effort: a crash between the two still leaves a file for a sweep to find."""
    if _STORED_FILES not in session.info:
        session.info[_STORED_FILES] = []

        @event.listens_for(session, "after_commit")
        def _committed(sess: Session) -> None:
            sess.info[_STORED_FILES].clear()

        @event.listens_for(session, "after_rollback")
        def _rolled_back(sess: Session) -> None:
            keys, sess.info[_STORED_FILES] = sess.info[_STORED_FILES], []
            for stored in keys:
                try:
                    storage.delete(stored)
                except Exception as exc:  # noqa: BLE001 - cleanup must not mask the real error
                    log.warning("orphan file not deleted error_type=%s", type(exc).__name__)

    session.info[_STORED_FILES].append(key)
