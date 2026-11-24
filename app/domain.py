"""Pure registration/correction allocation logic."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import NoFeasibleInterpretation, ValidationFailed
from .parsing import FORMATS, parse_both_formats
from .solver import feasible_format_choices


@dataclass(frozen=True)
class RowData:
    line_no: int | str
    hold_no: int
    weight_text: str


@dataclass
class BatchData:
    batch_no: str
    rows: list[RowData] = field(default_factory=list)


def line_key(line_no: int | str) -> str:
    """Canonical uniqueness key; JSON ``1`` and text ``"1"`` are one line."""
    if isinstance(line_no, bool):
        raise ValidationFailed("line_no must be an integer or string")
    return str(line_no).strip()


def _row_is_invariant(kg_by_format: dict[str, int]) -> tuple[bool, int | None]:
    distinct_values = set(kg_by_format.values())
    if len(distinct_values) == 1:
        return True, next(iter(distinct_values))
    return False, None


def evaluate_allocation(
    *,
    ship_code: str,
    hold_totals: dict[int, int],
    batches: list[BatchData],
    revision: int,
) -> dict[str, Any]:
    """Parse, solve, and build the atomic supply/remainder representation."""
    if not hold_totals:
        raise ValidationFailed("at least one certified hold total is required")
    if len(hold_totals) > 12:
        raise ValidationFailed("at most 12 holds are allowed")
    if len(batches) > 24:
        raise ValidationFailed("at most 24 batches are allowed")
    if any(total > 9_223_372_036_854_775_807 for total in hold_totals.values()):
        raise ValidationFailed("certified_total_kg exceeds SQLite signed 64-bit range")

    hold_numbers = sorted(hold_totals)
    hold_index = {hold_no: index for index, hold_no in enumerate(hold_numbers)}
    target_vector = tuple(int(hold_totals[hold_no]) for hold_no in hold_numbers)

    seen_lines: set[str] = set()
    row_count = sum(len(batch.rows) for batch in batches)
    if row_count == 0:
        raise ValidationFailed("at least one weight row is required")
    if row_count > 2000:
        raise ValidationFailed("at most 2000 rows are allowed")

    # Parsed row information is retained in registration order.
    parsed_batches: list[list[dict[str, Any]]] = []
    solver_options: list[dict[int, tuple[int, ...]]] = []

    for batch_index, batch in enumerate(batches):
        if not batch.rows:
            raise ValidationFailed(
                f"batch {batch.batch_no!r} must contain at least one row"
            )

        options: dict[int, list[int]] = {
            code: [0] * len(hold_numbers) for code, _ in enumerate(FORMATS)
        }
        option_legal = {code: True for code, _ in enumerate(FORMATS)}
        parsed_rows: list[dict[str, Any]] = []

        for row in batch.rows:
            key = line_key(row.line_no)
            if key in seen_lines:
                raise ValidationFailed(
                    f"duplicate line number {row.line_no!r}",
                    details={"line_no": row.line_no},
                )
            seen_lines.add(key)

            if row.hold_no not in hold_index:
                raise ValidationFailed(
                    f"row {row.line_no!r} references unknown hold {row.hold_no}",
                    details={"line_no": row.line_no, "hold_no": row.hold_no},
                )

            try:
                kg_by_format = parse_both_formats(row.weight_text)
            except ValueError as exc:
                raise ValidationFailed(
                    str(exc),
                    details={
                        "line_no": row.line_no,
                        "hold_no": row.hold_no,
                        "weight_text": row.weight_text,
                    },
                ) from exc

            position = hold_index[row.hold_no]
            for code, format_name in enumerate(FORMATS):
                kg = kg_by_format.get(format_name)
                if kg is None:
                    # Do not solve against a partial vector that silently
                    # omits this row.
                    option_legal[code] = False
                else:
                    options[code][position] += kg

            parsed_rows.append(
                {
                    "line_no": row.line_no,
                    "hold_no": row.hold_no,
                    "weight_text": row.weight_text,
                    "kg_by_format": kg_by_format,
                }
            )

        parsed_batches.append(parsed_rows)
        solver_options.append(
            {
                code: tuple(vector)
                for code, vector in options.items()
                if option_legal[code]
            }
        )

    possible_formats = feasible_format_choices(target_vector, solver_options)
    if possible_formats is None:
        raise NoFeasibleInterpretation(
            "no batch-format interpretation matches every certified hold total",
            details={
                "ship_code": ship_code,
                "batch_count": len(batches),
                "row_count": row_count,
                "hold_totals": [
                    {"hold_no": hold_no, "certified_total_kg": hold_totals[hold_no]}
                    for hold_no in hold_numbers
                ],
            },
        )

    supplied_rows: list[dict[str, Any]] = []
    pending_line_nos: list[int | str] = []
    supplied_by_hold = {hold_no: 0 for hold_no in hold_numbers}
    batch_results: list[dict[str, Any]] = []

    for batch_index, batch in enumerate(batches):
        choices = possible_formats[batch_index]
        forced_format = next(iter(choices)) if len(choices) == 1 else None
        batch_results.append(
            {
                "batch_no": batch.batch_no,
                "possible_formats": sorted(choices),
                "forced_format": forced_format,
                "ambiguous": len(choices) > 1,
            }
        )

        for row in parsed_batches[batch_index]:
            kg_by_format = row["kg_by_format"]
            invariant, invariant_kg = _row_is_invariant(kg_by_format)

            if invariant:
                kg = invariant_kg
            elif forced_format is not None:
                kg = kg_by_format[forced_format]
            else:
                pending_line_nos.append(row["line_no"])
                continue

            supplied_rows.append(
                {
                    "line_no": row["line_no"],
                    "hold_no": row["hold_no"],
                    "batch_no": batch.batch_no,
                    "weight_text": row["weight_text"],
                    "kg": kg,
                    "reason": "same_under_all_interpretations"
                    if invariant
                    else "batch_format_forced_by_hold_totals",
                }
            )
            supplied_by_hold[row["hold_no"]] += kg

    hold_results: list[dict[str, Any]] = []
    for hold_no in hold_numbers:
        certified = hold_totals[hold_no]
        supplied = supplied_by_hold[hold_no]
        remaining = certified - supplied
        if remaining < 0:
            # Mathematically impossible if solver and aggregation agree.
            raise ValidationFailed(
                f"supplied rows exceed certified total for hold {hold_no}",
                details={"hold_no": hold_no},
            )
        hold_results.append(
            {
                "hold_no": hold_no,
                "certified_total_kg": certified,
                "supplied_kg": supplied,
                "remaining_kg": remaining,
            }
        )

    return {
        "ship_code": ship_code,
        "revision": revision,
        "feasible": True,
        "batch_count": len(batches),
        "row_count": row_count,
        "supplied_row_count": len(supplied_rows),
        "pending_line_count": len(pending_line_nos),
        "supplied_rows": supplied_rows,
        "pending_line_nos": pending_line_nos,
        "holds": hold_results,
        "batches": batch_results,
    }
