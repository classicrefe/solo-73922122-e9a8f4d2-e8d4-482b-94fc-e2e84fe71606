"""Exact parsing of localized tonnage strings into integer kilograms.

The API never uses binary floating point for weights.  A tonne has 1000 kg and
the source text allows at most three decimal places, so every legal value is an
exact integer number of kilograms.
"""

from __future__ import annotations

from typing import Final

DOT_DECIMAL: Final = "DOT_DECIMAL_COMMA_THOUSANDS"
COMMA_DECIMAL: Final = "COMMA_DECIMAL_DOT_THOUSANDS"
FORMATS: Final[tuple[str, str]] = (DOT_DECIMAL, COMMA_DECIMAL)

_FORMAT_LABELS: Final[dict[str, str]] = {
    DOT_DECIMAL: "dot decimal / comma thousands",
    COMMA_DECIMAL: "comma decimal / dot thousands",
}


class WeightFormatError(ValueError):
    """Raised when a raw weight is not legal under one locale format."""


def _split_decimal(text: str, decimal_sep: str) -> tuple[str, str | None]:
    if decimal_sep not in text:
        return text, None

    parts = text.split(decimal_sep)
    if len(parts) != 2:
        raise WeightFormatError("more than one decimal separator")

    integer_part, fraction = parts
    if not fraction or not fraction.isascii() or not fraction.isdigit():
        raise WeightFormatError("decimal part must contain 1-3 digits")
    if len(fraction) > 3:
        raise WeightFormatError("more than three decimal places")
    return integer_part, fraction


def _validate_grouped_integer(integer_part: str, thousands_sep: str) -> str:
    """Validate grouping and return digits without separator characters."""
    if integer_part == "":
        return "0"

    if thousands_sep in integer_part:
        groups = integer_part.split(thousands_sep)
        if any(group == "" or not group.isascii() or not group.isdigit() for group in groups):
            raise WeightFormatError("thousands groups must contain digits")
        if len(groups[0]) > 3:
            raise WeightFormatError("first thousands group has at most three digits")
        if any(len(group) != 3 for group in groups[1:]):
            raise WeightFormatError("thousands separator must group exactly three digits")
        return "".join(groups)

    if not integer_part.isascii() or not integer_part.isdigit():
        raise WeightFormatError("integer part must contain digits")
    return integer_part


def parse_weight_kg(weight_text: str, format_name: str) -> int:
    """Parse one nonnegative tonnage text as exact kilograms.

    Format ``DOT_DECIMAL_COMMA_THOUSANDS`` is the common en-US layout;
    ``COMMA_DECIMAL_DOT_THOUSANDS`` is the swapped layout.
    """
    if not isinstance(weight_text, str):
        raise WeightFormatError("weight text must be a string")

    text = weight_text.strip()
    if not text:
        raise WeightFormatError("weight text is empty")
    if text[0] in "+-":
        if text[0] == "-":
            raise WeightFormatError("weight must be nonnegative")
        text = text[1:].strip()
        if not text:
            raise WeightFormatError("weight text is empty")

    if format_name == DOT_DECIMAL:
        decimal_sep, thousands_sep = ".", ","
    elif format_name == COMMA_DECIMAL:
        decimal_sep, thousands_sep = ",", "."
    else:
        raise WeightFormatError(f"unknown format: {format_name}")

    allowed = set("0123456789" + decimal_sep + thousands_sep)
    if any(ch not in allowed for ch in text):
        raise WeightFormatError(f"invalid character for {_FORMAT_LABELS[format_name]}")

    integer_part, fraction = _split_decimal(text, decimal_sep)
    integer_digits = _validate_grouped_integer(integer_part, thousands_sep)

    tonnes = int(integer_digits or "0")
    kg = tonnes * 1000
    if fraction is not None:
        kg += int(fraction.ljust(3, "0"))

    # Keep SQLite binding and arithmetic safely inside signed 64-bit range.
    if kg > 9_223_372_036_854_775_807:
        raise WeightFormatError("weight is too large")
    return kg


def parse_both_formats(weight_text: str) -> dict[str, int]:
    """Return all legal format interpretations for one raw weight."""
    values: dict[str, int] = {}
    errors: dict[str, str] = {}
    for format_name in FORMATS:
        try:
            values[format_name] = parse_weight_kg(weight_text, format_name)
        except WeightFormatError as exc:
            errors[format_name] = str(exc)
    if not values:
        details = "; ".join(f"{name}: {msg}" for name, msg in errors.items())
        raise WeightFormatError(f"weight {weight_text!r} is not parseable ({details})")
    return values
