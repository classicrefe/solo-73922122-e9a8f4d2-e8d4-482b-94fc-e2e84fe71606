import random
import time

from app.domain import BatchData, RowData, evaluate_allocation
from app.parsing import FORMATS
from app.solver import feasible_format_choices


def test_max_24_batches_12_holds_2000_rows_is_fast_and_exact():
    batches: list[BatchData] = []
    counts = [0] * 12
    line_no = 1

    # 8 batches with 84 rows and 16 with 83 rows = 2000.
    for batch_index in range(24):
        row_count = 84 if batch_index < 8 else 83
        rows: list[RowData] = []
        for _ in range(row_count):
            hold_no = (line_no % 12) + 1
            counts[hold_no - 1] += 1
            rows.append(RowData(line_no=line_no, hold_no=hold_no, weight_text="1"))
            line_no += 1
        batches.append(BatchData(batch_no=f"B{batch_index + 1}", rows=rows))

    totals = {hold_no: counts[hold_no - 1] * 1000 for hold_no in range(1, 13)}

    started = time.perf_counter()
    result = evaluate_allocation(
        ship_code="MAX",
        hold_totals=totals,
        batches=batches,
        revision=1,
    )
    elapsed = time.perf_counter() - started

    assert result["row_count"] == 2000
    assert result["batch_count"] == 24
    assert result["supplied_row_count"] == 2000
    assert result["pending_line_nos"] == []
    assert elapsed < 2.0, f"max registration took {elapsed:.3f}s"


def test_solver_half_enumeration_handles_dense_random_vectors_quickly():
    rng = random.Random(20261124)
    hold_count = 12
    options = []
    selected = []
    target = [0] * hold_count

    for _ in range(24):
        v0 = tuple(rng.randrange(0, 100_000) for _ in range(hold_count))
        v1 = tuple(rng.randrange(0, 100_000) for _ in range(hold_count))
        options.append({0: v0, 1: v1})
        code = rng.randrange(0, 2)
        selected.append(code)
        vector = v0 if code == 0 else v1
        for i, value in enumerate(vector):
            target[i] += value

    started = time.perf_counter()
    choices = feasible_format_choices(tuple(target), options)
    elapsed = time.perf_counter() - started

    assert choices is not None
    # The planted assignment proves each corresponding choice is possible.
    for batch_index, code in enumerate(selected):
        assert FORMATS[code] in choices[batch_index]
    assert elapsed < 2.0, f"dense solver took {elapsed:.3f}s"
