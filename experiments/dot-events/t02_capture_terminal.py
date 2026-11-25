"""Durable terminal owner for only the admitted capture operation."""

from t02_event_capture import CaptureStore


class CaptureTerminalOwner:
    """Seal and finalize the same one-use SQLite store from the watchdog host."""

    def __init__(self, store: CaptureStore) -> None:
        self._store = store

    def seal(self) -> bool:
        self._store.stop()
        return self._store.status()[0] == "sealed"

    def finish(self, confirmed: bool) -> bool:
        self._store.finish_cleanup(confirmed=confirmed)
        expected = "stopped" if confirmed else "cleanup-unknown"
        return self._store.status()[0] == expected
