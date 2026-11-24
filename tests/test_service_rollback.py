import sqlite3

import pytest

from app import service
from app.db import connect_db, init_db
from app.errors import StorageUnavailable
from app.main import DEMO_REGISTRATION
from app.schemas import CorrectionRequest, ShipRegistrationRequest


class CommitFailingConnection:
    """Proxy that fails only when the service tries to commit a correction."""

    def __init__(self, real: sqlite3.Connection):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def commit(self):
        raise sqlite3.OperationalError("simulated commit failure")


def test_failed_commit_keeps_original_hold_weights_and_supply(tmp_path):
    db_path = tmp_path / "rollback.db"
    init_db(db_path)
    conn = connect_db(db_path)

    payload = ShipRegistrationRequest.model_validate(DEMO_REGISTRATION)
    original = service.create_ship(conn, "DEMO-001", payload)
    assert original["revision"] == 1

    correction = CorrectionRequest.model_validate(
        {"corrections": [{"hold_no": 1, "certified_total_kg": 2_000}]}
    )

    with pytest.raises(StorageUnavailable):
        service.correct_hold_weights(
            CommitFailingConnection(conn), "DEMO-001", correction
        )

    unchanged = service.get_allocation(conn, "DEMO-001")
    assert unchanged["revision"] == 1
    assert unchanged["pending_line_nos"] == [1, 3]
    assert unchanged["holds"][0]["certified_total_kg"] == 1_001_000
    assert unchanged["holds"][0]["remaining_kg"] == 1_001_000

    conn.close()
