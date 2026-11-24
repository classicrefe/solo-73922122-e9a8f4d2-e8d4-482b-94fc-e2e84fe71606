"""FastAPI application for ambiguous ship weighbill intake."""

from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, Depends, FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import service
from .concurrency import ship_locks
from .db import connect_db, init_db
from .errors import AppError, ValidationFailed
from .schemas import (
    AllocationResponse,
    CorrectionRequest,
    ShipRegistrationRequest,
    ShipSummary,
    SingleHoldCorrectionRequest,
)

DEMO_REGISTRATION: dict[str, Any] = {
    "ship_code": "DEMO-001",
    "holds": [
        {"hold_no": 1, "certified_total_kg": 1_001_000},
        {"hold_no": 2, "certified_total_kg": 5_000},
    ],
    "batches": [
        {
            "batch_no": "WB-A",
            "rows": [
                {"line_no": 1, "hold_no": 1, "weight_text": "1.000"},
                {"line_no": 2, "hold_no": 2, "weight_text": "5"},
            ],
        },
        {
            "batch_no": "WB-B",
            "rows": [
                {"line_no": 3, "hold_no": 1, "weight_text": "1,000"},
            ],
        },
    ],
}

DEMO_CORRECTION: dict[str, Any] = {
    "expected_revision": 1,
    "corrections": [{"hold_no": 1, "certified_total_kg": 2_000}],
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="旧装船磅单入仓 API",
    description=(
        "按批解决逗号/点号格式歧义，用整船各舱核定总重筛选可行解释，"
        "并输出所有可行解释中重量固定的明细和舱重余量。\n\n"
        "核对使用分批 meet-in-the-middle：每半最多 12 批、4096 个向量，"
        "不穷举最多 2^24 个整船组合。"
    ),
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.to_detail()})


def get_db():
    conn = connect_db()
    try:
        yield conn
    finally:
        conn.close()


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["系统"], summary="健康检查")
def health(conn: sqlite3.Connection = Depends(get_db)) -> dict[str, str]:
    conn.execute("SELECT 1").fetchone()
    return {"status": "ok"}


@app.get(
    "/ships",
    response_model=list[ShipSummary],
    tags=["船舶磅单"],
    summary="列出已登记船舶",
)
def list_ships(conn: sqlite3.Connection = Depends(get_db)) -> list[dict[str, Any]]:
    return service.list_ships(conn)


@app.post(
    "/ships",
    response_model=AllocationResponse,
    status_code=201,
    tags=["船舶磅单"],
    summary="报送整船磅单和各舱核定总重",
)
@app.post(
    "/intakes",
    response_model=AllocationResponse,
    status_code=201,
    tags=["船舶磅单"],
    summary="报送整船磅单（/ships 的别名）",
    include_in_schema=False,
)
def register_ship_from_body(
    payload: ShipRegistrationRequest = Body(
        ...,
        examples={
            "demo": {
                "summary": "两批、两舱、三行的可复算示例",
                "value": DEMO_REGISTRATION,
            }
        },
    ),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    if not payload.ship_code or not payload.ship_code.strip():
        raise ValidationFailed("ship_code is required in the request body or path")
    ship_code = payload.ship_code.strip()
    with ship_locks.acquire(ship_code):
        return service.create_ship(conn, ship_code, payload)


@app.post(
    "/ships/{ship_code}/intake",
    response_model=AllocationResponse,
    status_code=201,
    tags=["船舶磅单"],
    summary="按船名路径报送整船磅单",
)
@app.put(
    "/ships/{ship_code}",
    response_model=AllocationResponse,
    status_code=201,
    tags=["船舶磅单"],
    summary="按船名路径登记整船磅单（POST intake 的 PUT 别名）",
)
def register_ship_by_path(
    ship_code: str,
    payload: ShipRegistrationRequest = Body(
        ...,
        examples={
            "demo": {
                "summary": "路径已指定 DEMO-001，body 中 ship_code 可省略",
                "value": {k: v for k, v in DEMO_REGISTRATION.items() if k != "ship_code"},
            }
        },
    ),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    ship_code = ship_code.strip()
    with ship_locks.acquire(ship_code):
        return service.create_ship(conn, ship_code, payload)


@app.get(
    "/ships/{ship_code}",
    response_model=AllocationResponse,
    tags=["船舶磅单"],
    summary="按船取数：固定明细、待查行号和舱重余量",
)
@app.get(
    "/ships/{ship_code}/allocation",
    response_model=AllocationResponse,
    tags=["船舶磅单"],
    summary="取数别名：/ships/{ship_code}/allocation",
)
@app.get(
    "/ships/{ship_code}/supply",
    response_model=AllocationResponse,
    tags=["船舶磅单"],
    summary="取数别名：/ships/{ship_code}/supply",
    include_in_schema=False,
)
def get_ship(
    ship_code: str, conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    return service.get_allocation(conn, ship_code)


@app.patch(
    "/ships/{ship_code}/holds/{hold_no}",
    response_model=AllocationResponse,
    tags=["船舶磅单"],
    summary="更正单个舱的核定总重",
)
@app.put(
    "/ships/{ship_code}/holds/{hold_no}",
    response_model=AllocationResponse,
    tags=["船舶磅单"],
    summary="更正单个舱（PUT 别名）",
    include_in_schema=False,
)
def correct_single_hold(
    ship_code: str,
    hold_no: int,
    payload: SingleHoldCorrectionRequest = Body(
        ...,
        examples={
            "force_unique": {
                "summary": "把 1 舱改为 2000 kg",
                "value": {"expected_revision": 1, "certified_total_kg": 2000},
            }
        },
    ),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    correction = CorrectionRequest.model_validate(
        {
            "expected_revision": payload.expected_revision,
            "corrections": [
                {
                    "hold_no": hold_no,
                    "certified_total_kg": payload.certified_total_kg,
                }
            ],
        }
    )
    ship_code = ship_code.strip()
    with ship_locks.acquire(ship_code):
        return service.correct_hold_weights(conn, ship_code, correction)


@app.patch(
    "/ships/{ship_code}/holds",
    response_model=AllocationResponse,
    tags=["船舶磅单"],
    summary="更正一个或多个舱的核定总重并重新判定",
)
@app.put(
    "/ships/{ship_code}/hold-weights",
    response_model=AllocationResponse,
    tags=["船舶磅单"],
    summary="更正舱重（PUT 别名）",
)
@app.post(
    "/ships/{ship_code}/corrections",
    response_model=AllocationResponse,
    tags=["船舶磅单"],
    summary="更正舱重（POST corrections 别名）",
)
def correct_ship_holds(
    ship_code: str,
    payload: CorrectionRequest = Body(
        ...,
        examples={
            "force_unique": {
                "summary": "把 1 舱改为 2000 kg，格式组合变为唯一",
                "value": DEMO_CORRECTION,
            },
            "impossible": {
                "summary": "无解更正：接口返回 422，原供数不变",
                "value": {
                    "corrections": [{"hold_no": 1, "certified_total_kg": 999}]
                },
            },
        },
    ),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    ship_code = ship_code.strip()
    with ship_locks.acquire(ship_code):
        return service.correct_hold_weights(conn, ship_code, payload)
