import pytest

from app.parsing import (
    COMMA_DECIMAL,
    DOT_DECIMAL,
    WeightFormatError,
    parse_both_formats,
    parse_weight_kg,
)


def test_dot_decimal_comma_thousands_exact_kg():
    assert parse_weight_kg("1,234.567", DOT_DECIMAL) == 1_234_567
    assert parse_weight_kg("12,345", DOT_DECIMAL) == 12_345_000
    assert parse_weight_kg("0.5", DOT_DECIMAL) == 500


def test_swapped_format_exact_kg():
    assert parse_weight_kg("1.234,567", COMMA_DECIMAL) == 1_234_567
    assert parse_weight_kg("1.234", COMMA_DECIMAL) == 1_234_000
    assert parse_weight_kg("12,34", COMMA_DECIMAL) == 12_340


def test_ambiguous_three_digit_separator_has_two_values():
    values = parse_both_formats("1.234")
    assert values[DOT_DECIMAL] == 1_234
    assert values[COMMA_DECIMAL] == 1_234_000

    values = parse_both_formats("1,234")
    assert values[DOT_DECIMAL] == 1_234_000
    assert values[COMMA_DECIMAL] == 1_234


def test_plain_integer_is_invariant():
    assert parse_both_formats("2000") == {
        DOT_DECIMAL: 2_000_000,
        COMMA_DECIMAL: 2_000_000,
    }


@pytest.mark.parametrize("text", ["1.2345", "1,2345", "abc", "", "1..2", "1,,2"])
def test_no_legal_format(text):
    with pytest.raises(WeightFormatError):
        parse_both_formats(text)


def test_negative_rejected():
    with pytest.raises(WeightFormatError):
        parse_weight_kg("-1.2", DOT_DECIMAL)
