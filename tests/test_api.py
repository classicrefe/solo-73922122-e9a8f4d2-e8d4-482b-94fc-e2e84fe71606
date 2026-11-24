import pytest
from fastapi.testclient import TestClient

from app.db import connect_db, init_db
from app.main import DEMO_CORRECTION, DEMO_REGISTRATION, app, get_db


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "api-test.db"
    monkeypatch.setenv("DB_PATH", str(path))
    init_db(path)
    return path


@pytest.fixture
def client(db_path):
    def override_get_db():
        conn = connect_db(db_path)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health_docs_and_full_register_correct_fetch_workflow(client):
    assert client.get("/health").status_code == 200
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "Swagger UI" in docs.text

    code = DEMO_REGISTRATION["ship_code"]
    created = client.post("/ships", json=DEMO_REGISTRATION)
    assert created.status_code == 201, created.text
    first = created.json()

    assert first["revision"] == 1
    assert first["pending_line_nos"] == [1, 3]
    assert [(row["line_no"], row["kg"]) for row in first["supplied_rows"]] == [(2, 5_000)]
    assert first["holds"] == [
        {
            "hold_no": 1,
            "certified_total_kg": 1_001_000,
            "supplied_kg": 0,
            "remaining_kg": 1_001_000,
        },
        {
            "hold_no": 2,
            "certified_total_kg": 5_000,
            "supplied_kg": 5_000,
            "remaining_kg": 0,
        },
    ]

    fetched = client.get(f"/ships/{code}")
    assert fetched.status_code == 200
    assert fetched.json()["pending_line_nos"] == [1, 3]

    impossible = client.patch(
        f"/ships/{code}/holds",
        json={
            "expected_revision": 1,
            "corrections": [{"hold_no": 1, "certified_total_kg": 999}],
        },
    )
    assert impossible.status_code == 422
    assert impossible.json()["detail"]["code"] == "no_feasible_interpretation"

    unchanged = client.get(f"/ships/{code}/supply").json()
    assert unchanged["revision"] == 1
    assert unchanged["pending_line_nos"] == [1, 3]
    assert unchanged["holds"][0]["certified_total_kg"] == 1_001_000
    assert unchanged["holds"][0]["remaining_kg"] == 1_001_000

    corrected = client.patch(
        f"/ships/{code}/holds",
        json=DEMO_CORRECTION,
    )
    assert corrected.status_code == 200, corrected.text
    second = corrected.json()
    assert second["revision"] == 2
    assert second["pending_line_nos"] == []
    kg_by_line = {row["line_no"]: row["kg"] for row in second["supplied_rows"]}
    assert kg_by_line == {1: 1_000, 2: 5_000, 3: 1_000}
    assert all(hold["remaining_kg"] == 0 for hold in second["holds"])

    stale = client.patch(
        f"/ships/{code}/holds",
        json={
            "expected_revision": 1,
            "corrections": [{"hold_no": 1, "certified_total_kg": 2_000}],
        },
    )
    assert stale.status_code == 409


def test_single_hold_path_correction(client):
    client.post("/ships", json=DEMO_REGISTRATION)
    response = client.patch(
        "/ships/DEMO-001/holds/1",
        json={"certified_total_kg": 2_000},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["revision"] == 2
    assert body["pending_line_nos"] == []
    assert {row["line_no"]: row["kg"] for row in body["supplied_rows"]} == {
        1: 1_000,
        2: 5_000,
        3: 1_000,
    }


def test_duplicate_registration_conflicts_and_preserves_ship(client):
    first = client.post("/ships", json=DEMO_REGISTRATION)
    assert first.status_code == 201

    duplicate = client.post("/ships", json=DEMO_REGISTRATION)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "ship_conflict"

    assert client.get("/ships/DEMO-001").status_code == 200


def test_tolerant_flat_aliases_and_hold_mapping(client):
    payload = {
        "ship_code": "FLAT-1",
        "hold_weights": {"1": 3_000},
        "rows": [{"line_number": "L-1", "hold": "1", "weight": "3"}],
    }
    response = client.post("/intakes", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["pending_line_nos"] == []
    assert body["supplied_rows"][0]["line_no"] == "L-1"
    assert body["supplied_rows"][0]["kg"] == 3_000


def test_unknown_ship_404(client):
    response = client.get("/ships/NOPE")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "ship_not_found"
