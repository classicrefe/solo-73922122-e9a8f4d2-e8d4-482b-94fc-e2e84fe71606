import threading
from concurrent.futures import ThreadPoolExecutor

from app import service
from app.db import connect_db, init_db
from app.schemas import ShipRegistrationRequest


def _ship(code: str) -> dict:
    return {
        "ship_code": code,
        "holds": [{"hold_no": 1, "certified_total_kg": 3_000}],
        "rows": [
            {"line_no": 1, "hold_no": 1, "weight_text": "1"},
            {"line_no": 2, "hold_no": 1, "weight_text": "2"},
        ],
    }


def test_other_ship_can_complete_while_heavy_ship_is_checking(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "concurrency.db"
    init_db(db_path)

    entered_solver = threading.Event()
    release_heavy = threading.Event()
    original_evaluate = service.evaluate_allocation

    def gated_evaluate(**kwargs):
        if kwargs["ship_code"] == "HEAVY":
            entered_solver.set()
            assert release_heavy.wait(timeout=5)
        return original_evaluate(**kwargs)

    monkeypatch.setattr(service, "evaluate_allocation", gated_evaluate)

    def register_heavy():
        conn = connect_db(db_path)
        try:
            payload = ShipRegistrationRequest.model_validate(_ship("HEAVY"))
            return service.create_ship(conn, "HEAVY", payload)
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        heavy_future = pool.submit(register_heavy)
        assert entered_solver.wait(timeout=5)

        # HEAVY is inside format reconciliation and has not started its write
        # transaction. A different ship must still register successfully.
        small_conn = connect_db(db_path)
        try:
            small_payload = ShipRegistrationRequest.model_validate(_ship("SMALL"))
            small = service.create_ship(small_conn, "SMALL", small_payload)
            assert small["ship_code"] == "SMALL"
        finally:
            small_conn.close()

        release_heavy.set()
        heavy = heavy_future.result(timeout=5)
        assert heavy["ship_code"] == "HEAVY"

    verify = connect_db(db_path)
    try:
        assert service.get_allocation(verify, "SMALL")["revision"] == 1
        assert service.get_allocation(verify, "HEAVY")["revision"] == 1
    finally:
        verify.close()
