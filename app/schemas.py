"""FastAPI request/response schemas and tolerant field aliases."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.aliases import AliasChoices

from .domain import BatchData, RowData


def _as_int(value: Any) -> Any:
    if isinstance(value, bool):
        raise ValueError("boolean is not an integer")
    if isinstance(value, str):
        stripped = value.strip().replace(",", "")
        if not stripped:
            raise ValueError("expected an integer")
        return int(stripped)
    return value


class HoldWeightIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hold_no: int = Field(
        ge=1,
        le=12,
        validation_alias=AliasChoices(
            "hold_no",
            "holdNo",
            "hold_number",
            "holdNumber",
            "hold_id",
            "holdId",
            "hold",
            "no",
        ),
        description="舱号，1–12",
    )
    certified_total_kg: int = Field(
        ge=0,
        le=9_223_372_036_854_775_807,
        validation_alias=AliasChoices(
            "certified_total_kg",
            "certifiedTotalKg",
            "certified_total_weight_kg",
            "total_weight_kg",
            "totalWeightKg",
            "total_kg",
            "totalKg",
            "certified_weight_kg",
            "certifiedWeightKg",
            "certified_kg",
            "certifiedKg",
            "total",
        ),
        description="该舱核定总重，整数公斤",
    )

    @field_validator("hold_no", "certified_total_kg", mode="before")
    @classmethod
    def _coerce_integer_text(cls, value: Any) -> Any:
        return _as_int(value)


class RowIn(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    line_no: int | str = Field(
        validation_alias=AliasChoices(
            "line_no",
            "lineNo",
            "line_number",
            "lineNumber",
            "row_no",
            "rowNo",
            "line",
            "id",
        ),
        description="全船唯一行号；整数或字符串均可",
    )
    hold_no: int = Field(
        ge=1,
        le=12,
        validation_alias=AliasChoices(
            "hold_no",
            "holdNo",
            "hold_number",
            "holdNumber",
            "hold_id",
            "holdId",
            "hold",
        ),
    )
    weight_text: str = Field(
        min_length=1,
        max_length=64,
        validation_alias=AliasChoices(
            "weight_text",
            "weightText",
            "weight_original",
            "weightOriginal",
            "raw_weight",
            "rawWeight",
            "weight_tonnes",
            "weightTonnes",
            "original_weight",
            "originalWeight",
            "tonnage",
            "weight",
            "text",
            "value",
        ),
        description="以吨计的非负重量原文，例如 1,234.567",
    )
    batch_no: int | str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "batch_no", "batchNo", "batch_number", "batchNumber", "batch"
        ),
    )

    @field_validator("hold_no", mode="before")
    @classmethod
    def _coerce_hold(cls, value: Any) -> Any:
        return _as_int(value)

    @field_validator("line_no")
    @classmethod
    def _line_not_bool(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("line_no cannot be a boolean")
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("line_no cannot be empty")
        return value

    @field_validator("weight_text", mode="before")
    @classmethod
    def _weight_to_text(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("weight_text must be text or a number")
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return repr(value)
        return value

    @field_validator("weight_text")
    @classmethod
    def _strip_weight(cls, value: str) -> str:
        return value.strip()


class BatchIn(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    batch_no: int | str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "batch_no", "batchNo", "batch_number", "batchNumber", "code", "id"
        ),
    )
    rows: list[RowIn] = Field(
        min_length=1,
        max_length=2000,
        validation_alias=AliasChoices(
            "rows", "lines", "items", "records", "weights", "weighbills"
        ),
    )

    @field_validator("batch_no")
    @classmethod
    def _normalize_batch_no(cls, value: int | str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
        return str(value)


class ShipRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    ship_code: str | None = Field(
        default=None,
        max_length=64,
        validation_alias=AliasChoices("ship_code", "shipCode", "code", "ship_id"),
    )
    holds: list[HoldWeightIn] = Field(
        min_length=1,
        max_length=12,
        validation_alias=AliasChoices(
            "holds",
            "hold_weights",
            "holdWeights",
            "certified_holds",
            "hold_totals",
            "holdTotals",
            "totals",
        ),
    )
    batches: list[BatchIn] = Field(
        default_factory=list,
        max_length=24,
        validation_alias=AliasChoices("batches", "batch_list", "batchList"),
    )
    rows: list[RowIn] = Field(
        default_factory=list,
        max_length=2000,
        validation_alias=AliasChoices(
            "rows", "lines", "items", "records", "weights", "weighbills"
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_hold_mapping(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        for key in (
            "holds",
            "hold_weights",
            "holdWeights",
            "certified_holds",
            "hold_totals",
            "holdTotals",
            "totals",
        ):
            value = data.get(key)
            if isinstance(value, dict):
                data[key] = [
                    {"hold_no": hold_no, "certified_total_kg": total}
                    for hold_no, total in value.items()
                ]
                break
        return data

    @model_validator(mode="after")
    def _validate_shape(self) -> "ShipRegistrationRequest":
        if self.batches and self.rows:
            raise ValueError("use either batches or top-level rows, not both")
        if not self.batches and not self.rows:
            raise ValueError("at least one batch or row is required")
        if self.batches:
            total_rows = sum(len(batch.rows) for batch in self.batches)
            if total_rows > 2000:
                raise ValueError("at most 2000 rows are allowed across the ship")
        return self

    def hold_totals(self) -> dict[int, int]:
        totals: dict[int, int] = {}
        for hold in self.holds:
            if hold.hold_no in totals:
                raise ValueError(f"duplicate hold_no {hold.hold_no}")
            totals[hold.hold_no] = hold.certified_total_kg
        return totals

    def to_batches(self) -> list[BatchData]:
        if self.batches:
            result: list[BatchData] = []
            used_names: set[str] = set()
            for index, batch in enumerate(self.batches, start=1):
                name = batch.batch_no or f"B{index}"
                if name in used_names:
                    raise ValueError(f"duplicate batch_no {name}")
                used_names.add(name)
                result.append(
                    BatchData(
                        batch_no=name,
                        rows=[
                            RowData(
                                line_no=row.line_no,
                                hold_no=row.hold_no,
                                weight_text=row.weight_text,
                            )
                            for row in batch.rows
                        ],
                    )
                )
            return result

        # Flat payload: group by optional row.batch_no, preserving first use.
        grouped: dict[str, list[RowData]] = {}
        order: list[str] = []
        for row in self.rows:
            name = str(row.batch_no) if row.batch_no is not None else "B1"
            if name not in grouped:
                grouped[name] = []
                order.append(name)
            grouped[name].append(
                RowData(
                    line_no=row.line_no,
                    hold_no=row.hold_no,
                    weight_text=row.weight_text,
                )
            )

        return [BatchData(batch_no=name, rows=grouped[name]) for name in order]


class CorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    expected_revision: int | None = Field(
        default=None,
        ge=1,
        validation_alias=AliasChoices(
            "expected_revision", "expectedRevision", "revision"
        ),
    )
    corrections: list[HoldWeightIn] = Field(
        min_length=1,
        validation_alias=AliasChoices(
            "corrections",
            "holds",
            "hold_weights",
            "holdWeights",
            "updates",
            "hold_totals",
            "totals",
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _wrap_single_or_mapping(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        for key in (
            "corrections",
            "holds",
            "hold_weights",
            "holdWeights",
            "updates",
            "hold_totals",
            "totals",
        ):
            value = data.get(key)
            if isinstance(value, dict):
                data["corrections"] = [
                    {"hold_no": hold_no, "certified_total_kg": total}
                    for hold_no, total in value.items()
                ]
                return data
            if isinstance(value, list):
                data["corrections"] = value
                return data

        if "hold_no" in data or "hold" in data:
            data["corrections"] = [data]
        return data

    def corrected_totals(self) -> dict[int, int]:
        result: dict[int, int] = {}
        for item in self.corrections:
            if item.hold_no in result:
                raise ValueError(f"duplicate correction for hold {item.hold_no}")
            result[item.hold_no] = item.certified_total_kg
        return result


class SingleHoldCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    expected_revision: int | None = Field(
        default=None,
        ge=1,
        validation_alias=AliasChoices(
            "expected_revision", "expectedRevision", "revision"
        ),
    )
    certified_total_kg: int = Field(
        ge=0,
        le=9_223_372_036_854_775_807,
        validation_alias=AliasChoices(
            "certified_total_kg",
            "certifiedTotalKg",
            "certified_total_weight_kg",
            "total_weight_kg",
            "totalWeightKg",
            "total_kg",
            "totalKg",
            "certified_weight_kg",
            "certifiedWeightKg",
            "certified_kg",
            "certifiedKg",
            "total",
        ),
        description="该舱新的核定总重，整数公斤",
    )

    @field_validator("certified_total_kg", mode="before")
    @classmethod
    def _coerce_integer_text(cls, value: Any) -> Any:
        return _as_int(value)


class SuppliedRowOut(BaseModel):
    line_no: int | str
    hold_no: int
    batch_no: str
    weight_text: str
    kg: int
    reason: str


class HoldAllocationOut(BaseModel):
    hold_no: int
    certified_total_kg: int
    supplied_kg: int
    remaining_kg: int


class BatchResolutionOut(BaseModel):
    batch_no: str
    possible_formats: list[str]
    forced_format: str | None
    ambiguous: bool


class AllocationResponse(BaseModel):
    ship_code: str
    revision: int
    feasible: bool
    batch_count: int
    row_count: int
    supplied_row_count: int
    pending_line_count: int
    supplied_rows: list[SuppliedRowOut]
    pending_line_nos: list[int | str]
    holds: list[HoldAllocationOut]
    batches: list[BatchResolutionOut]
    created_at: str | None = None
    updated_at: str | None = None


class ShipSummary(BaseModel):
    ship_code: str
    revision: int
    batch_count: int
    row_count: int
    supplied_row_count: int
    pending_line_count: int
    updated_at: str
