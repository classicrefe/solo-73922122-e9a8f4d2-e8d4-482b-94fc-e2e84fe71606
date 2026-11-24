"""Small local benchmark for the 24-batch / 12-hold / 2000-row limits."""

from __future__ import annotations

import random
import time

from app.domain import BatchData, RowData, evaluate_allocation
from app.solver import _expand_half, feasible_format_choices


def main() -> None:
    batches: list[BatchData] = []
    counts = [0] * 12
    line_no = 1

    for batch_index in range(24):
        row_count = 84 if batch_index < 8 else 83
        rows: list[RowData] = []
        for _ in range(row_count):
            hold_no = (line_no % 12) + 1
            counts[hold_no - 1] += 1
            rows.append(RowData(line_no=line_no, hold_no=hold_no, weight_text="1"))
            line_no += 1
        batches.append(BatchData(batch_no=f"B{batch_index + 1}", rows=rows))

    totals = {i + 1: counts[i] * 1000 for i in range(12)}
    start = time.perf_counter()
    result = evaluate_allocation(
        ship_code="BENCH", hold_totals=totals, batches=batches, revision=1
    )
    row_elapsed = time.perf_counter() - start

    rng = random.Random(20261124)
    options = []
    target = [0] * 12
    for _ in range(24):
        v0 = tuple(rng.randrange(0, 100_000) for _ in range(12))
        v1 = tuple(rng.randrange(0, 100_000) for _ in range(12))
        options.append({0: v0, 1: v1})
        vector = rng.choice((v0, v1))
        target = [a + b for a, b in zip(target, vector)]

    start = time.perf_counter()
    choices = feasible_format_choices(tuple(target), options)
    solver_elapsed = time.perf_counter() - start

    left = _expand_half(range(0, 12), options, 12)
    right = _expand_half(range(12, 24), options, 12)

    print(f"whole-ship Cartesian combinations avoided: 2**24 = {2**24:,}")
    print(f"dense half states: left={len(left):,}, right={len(right):,} (theoretical max 4,096 each)")
    print(f"max rows evaluation: {row_elapsed * 1000:.1f} ms, supplied={result['supplied_row_count']}")
    print(f"dense solver: {solver_elapsed * 1000:.1f} ms, batch_choice_sets={len(choices or [])}")


if __name__ == "__main__":
    main()
