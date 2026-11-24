"""SQLite-backed registration, fetch, and correction use cases."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .domain import BatchData, RowData, evaluate_allocation, line_key
from .errors import (
    RevisionConflict,
    ShipConflict,
    ShipNotFound,
    StorageUnavailable,
    ValidationFailed,
)
from .schemas import CorrectionRequest, ShipRegistrationRequest


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str) -> Any:
    return json.loads(value)


def _request_domain(
    payload: ShipRegistrationRequest,
) -> tuple[dict[int, int], list[BatchData]]:
    try:
        return payload.hold_totals(), payload.to_batches()
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc


def create_ship(
    conn: sqlite3.Connection,
    ship_code: str,
    payload: ShipRegistrationRequest,
) -> dict[str, Any]:
    code = ship_code.strip()
    if payload.ship_code and payload.ship_code.strip() != code:
        raise ValidationFailed("path ship_code does not match body ship_code")

    hold_totals, batches = _request_domain(payload)
    allocation = evaluate_allocation(
        ship_code=code,
        hold_totals=hold_totals,
        batches=batches,
        revision=1,
    )

    now = _now()
    allocation["created_at"] = now
    allocation["updated_at"] = now
    allocation_json = _dumps(allocation)

    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO ships
                (ship_code, revision, allocation_json, created_at, updated_at)
            VALUES (?, 1, ?, ?, ?)
            """,
            (code, allocation_json, now, now),
        )

        conn.executemany(
            """
            INSERT INTO holds (ship_code, hold_no, certified_total_kg)
            VALUES (?, ?, ?)
            """,
            [(code, hold_no, total) for hold_no, total in hold_totals.items()],
        )

        for batch_index, batch in enumerate(batches):
            conn.execute(
                """
                INSERT INTO batches (ship_code, batch_index, batch_no)
                VALUES (?, ?, ?)
                """,
                (code, batch_index, batch.batch_no),
            )
            for row_order, row in enumerate(batch.rows):
                conn.execute(
                    """
                    INSERT INTO weight_rows
                        (ship_code, line_key, line_no_json, batch_index,
                         row_order, hold_no, weight_text)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        code,
                        line_key(row.line_no),
                        _dumps(row.line_no),
                        batch_index,
                        row_order,
                        row.hold_no,
                        row.weight_text,
                    ),
                )

        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        existing = conn.execute(
            "SELECT 1 FROM ships WHERE ship_code = ?", (code,)
        ).fetchone()
        if existing:
            raise ShipConflict(
                f"ship {code!r} is already registered; correct its hold weights instead"
            ) from exc
        raise ValidationFailed(
            "registration violates a uniqueness or foreign-key constraint"
        ) from exc
    except sqlite3.Error as exc:
        conn.rollback()
        raise StorageUnavailable("ship registration was not written") from exc

    return allocation


def get_allocation(conn: sqlite3.Connection, ship_code: str) -> dict[str, Any]:
    code = ship_code.strip()
    row = conn.execute(
        """
        SELECT allocation_json, created_at, updated_at
        FROM ships WHERE ship_code = ?
        """,
        (code,),
    ).fetchone()
    if row is None:
        raise ShipNotFound(f"ship {code!r} was not found")

    allocation = _loads(row["allocation_json"])
    allocation["created_at"] = row["created_at"]
    allocation["updated_at"] = row["updated_at"]
    return allocation


def list_ships(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT ship_code, revision, allocation_json, updated_at
        FROM ships ORDER BY created_at, ship_code
        """
    ).fetchall()

    result: list[dict[str, Any]] = []
    for row in rows:
        allocation = _loads(row["allocation_json"])
        result.append(
            {
                "ship_code": row["ship_code"],
                "revision": row["revision"],
                "batch_count": allocation.get("batch_count", 0),
                "row_count": allocation.get("row_count", 0),
                "supplied_row_count": allocation.get("supplied_row_count", 0),
                "pending_line_count": allocation.get("pending_line_count", 0),
                "updated_at": row["updated_at"],
            }
        )
    return result


def _load_hold_totals(
    conn: sqlite3.Connection, code: str
) -> dict[int, int]:
    rows = conn.execute(
        "SELECT hold_no, certified_total_kg FROM holds WHERE ship_code = ?",
        (code,),
    ).fetchall()
    return {int(row["hold_no"]): int(row["certified_total_kg"]) for row in rows}


def _load_batches(conn: sqlite3.Connection, code: str) -> list[BatchData]:
    batch_rows = conn.execute(
        """
        SELECT batch_index, batch_no
        FROM batches WHERE ship_code = ? ORDER BY batch_index
        """,
        (code,),
    ).fetchall()

    batches: list[BatchData] = []
    for batch_row in batch_rows:
        row_rows = conn.execute(
            """
            SELECT line_no_json, hold_no, weight_text
            FROM weight_rows
            WHERE ship_code = ? AND batch_index = ?
            ORDER BY row_order
            """,
            (code, batch_row["batch_index"]),
        ).fetchall()
        batches.append(
            BatchData(
                batch_no=batch_row["batch_no"],
                rows=[
                    RowData(
                        line_no=_loads(row_row["line_no_json"]),
                        hold_no=int(row_row["hold_no"]),
                        weight_text=row_row["weight_text"],
                    )
                    for row_row in row_rows
                ],
            )
        )
    return batches


def correct_hold_weights(
    conn: sqlite3.Connection,
    ship_code: str,
    payload: CorrectionRequest,
) -> dict[str, Any]:
    code = ship_code.strip()
    ship = conn.execute(
        "SELECT revision FROM ships WHERE ship_code = ?", (code,)
    ).fetchone()
    if ship is None:
        raise ShipNotFound(f"ship {code!r} was not found")

    current_revision = int(ship["revision"])
    if (
        payload.expected_revision is not None
        and payload.expected_revision != current_revision
    ):
        raise RevisionConflict(
            f"expected revision {payload.expected_revision}, "
            f"but current revision is {current_revision}",
            details={"current_revision": current_revision},
        )

    try:
        corrections = payload.corrected_totals()
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc

    hold_totals = _load_hold_totals(conn, code)
    for hold_no, total in corrections.items():
        if hold_no not in hold_totals:
            raise ValidationFailed(
                f"hold {hold_no} is not registered for ship {code!r}",
                details={"unknown_hold_no": hold_no},
            )
        hold_totals[hold_no] = total

    batches = _load_batches(conn, code)

    # Solve before taking a write lock.  A failed solve raises and leaves the
    # previous allocation_json/hold rows untouched.
    new_revision = current_revision + 1
    allocation = evaluate_allocation(
        ship_code=code,
        hold_totals=hold_totals,
        batches=batches,
        revision=new_revision,
    )
    now = _now()
    allocation["updated_at"] = now

    try:
        conn.execute("BEGIN IMMEDIATE")
        locked = conn.execute(
            "SELECT revision FROM ships WHERE ship_code = ?", (code,)
        ).fetchone()
        if locked is None:
            conn.rollback()
            raise ShipNotFound(f"ship {code!r} was not found")
        if int(locked["revision"]) != current_revision:
            conn.rollback()
            raise RevisionConflict(
                "ship was corrected by another request; reload and retry",
                details={"current_revision": int(locked["revision"])},
            )

        conn.executemany(
            """
            UPDATE holds
            SET certified_total_kg = ?
            WHERE ship_code = ? AND hold_no = ?
            """,
            [
                (total, code, hold_no)
                for hold_no, total in corrections.items()
            ],
        )
        # created_at is retained by reading the old snapshot first.
        old = conn.execute(
            "SELECT created_at FROM ships WHERE ship_code = ?", (code,)
        ).fetchone()
        allocation["created_at"] = old["created_at"] if old else now

        conn.execute(
            """
            UPDATE ships
            SET revision = ?, allocation_json = ?, updated_at = ?
            WHERE ship_code = ?
            """,
            (new_revision, _dumps(allocation), now, code),
        )
        conn.commit()
    except (RevisionConflict, ShipNotFound):
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        raise StorageUnavailable("hold correction was not written") from exc

    return allocation
