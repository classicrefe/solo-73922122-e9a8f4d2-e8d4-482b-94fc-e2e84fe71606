"""Meet-in-the-middle consistency solver for batch locale choices.

A ship has at most 24 binary batch-format choices, so testing every whole-ship
Cartesian combination could reach 2**24.  Instead, split the batches into two
halves of at most 12 batches, enumerate at most 2**12 = 4096 contribution
vectors per half, and join vectors whose hold sums equal the certified totals.

The join also records which format choices occur in *any* matching assignment.
That is exactly the information needed to decide whether a row is invariant
across every feasible interpretation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .parsing import FORMATS

FormatCode = int
HoldVector = tuple[int, ...]
BatchOptions = Mapping[FormatCode, HoldVector]


class SolverInputError(ValueError):
    pass


def _expand_half(
    batch_indices: Sequence[int],
    options: Sequence[BatchOptions],
    hold_count: int,
) -> dict[HoldVector, int]:
    """Return vector -> bit mask of choices occurring in this half.

    Bit ``2*b + code`` records that global batch ``b`` used format ``code``.
    Alternative assignments producing the same vector safely OR their bits:
    when that vector joins, every represented half assignment joins.
    """
    states: dict[HoldVector, int] = {(0,) * hold_count: 0}

    for batch_index in batch_indices:
        batch_options = options[batch_index]
        if not batch_options:
            return {}

        next_states: dict[HoldVector, int] = {}
        for current_vector, current_bits in states.items():
            for format_code, option_vector in batch_options.items():
                if len(option_vector) != hold_count:
                    raise SolverInputError("option vector length does not match holds")
                new_vector = tuple(
                    current_value + option_value
                    for current_value, option_value in zip(current_vector, option_vector)
                )
                bit = 1 << (2 * batch_index + format_code)
                new_bits = current_bits | bit
                old_bits = next_states.get(new_vector)
                if old_bits is None:
                    next_states[new_vector] = new_bits
                else:
                    next_states[new_vector] = old_bits | new_bits
        states = next_states

    return states


def feasible_format_choices(
    targets: Sequence[int],
    batch_options: Sequence[BatchOptions],
) -> list[set[str]] | None:
    """Find format choices participating in at least one feasible solution.

    Returns ``None`` when no assignment matches all hold totals.  Otherwise
    returns, for each batch, the set of format names that can appear in a
    feasible whole-ship interpretation.
    """
    hold_count = len(targets)
    if hold_count == 0:
        raise SolverInputError("at least one hold target is required")

    batch_count = len(batch_options)
    middle = batch_count // 2
    left_indices = range(0, middle)
    right_indices = range(middle, batch_count)

    left_states = _expand_half(left_indices, batch_options, hold_count)
    right_states = _expand_half(right_indices, batch_options, hold_count)
    if not left_states or not right_states:
        return None

    possible_bits = 0
    feasible = False
    target_tuple = tuple(targets)

    for left_vector, left_bits in left_states.items():
        needed_right_vector = tuple(
            target_value - left_value
            for target_value, left_value in zip(target_tuple, left_vector)
        )
        right_bits = right_states.get(needed_right_vector)
        if right_bits is not None:
            feasible = True
            possible_bits |= left_bits | right_bits

    if not feasible:
        return None

    result: list[set[str]] = []
    for batch_index in range(batch_count):
        choices: set[str] = set()
        for format_code, format_name in enumerate(FORMATS):
            if possible_bits & (1 << (2 * batch_index + format_code)):
                choices.add(format_name)
        result.append(choices)

    return result
