from app.domain import BatchData, RowData, evaluate_allocation
from app.parsing import DOT_DECIMAL


def test_format_illegal_for_any_row_is_not_offered_to_solver(monkeypatch):
    captured = {}

    def capture_options(targets, options):
        captured["targets"] = targets
        captured["options"] = options
        return [{DOT_DECIMAL}]

    monkeypatch.setattr("app.domain.feasible_format_choices", capture_options)

    result = evaluate_allocation(
        ship_code="LEGAL",
        hold_totals={1: 1_235_560},
        batches=[
            BatchData(
                batch_no="B1",
                rows=[
                    RowData(line_no=1, hold_no=1, weight_text="1,234.56"),
                    RowData(line_no=2, hold_no=1, weight_text="1"),
                ],
            )
        ],
        revision=1,
    )

    assert set(captured["options"][0].keys()) == {0}
    assert result["batches"][0]["forced_format"] == DOT_DECIMAL
    assert [(row["line_no"], row["kg"]) for row in result["supplied_rows"]] == [
        (1, 1_234_560),
        (2, 1_000),
    ]
