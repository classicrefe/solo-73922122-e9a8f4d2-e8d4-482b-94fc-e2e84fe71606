from app.parsing import COMMA_DECIMAL, DOT_DECIMAL
from app.solver import feasible_format_choices


def test_solver_finds_both_matching_global_assignments_without_cartesian_whole_ship():
    options = [
        {0: (1_000,), 1: (1_000_000,)},
        {0: (1_000_000,), 1: (1_000,)},
    ]

    choices = feasible_format_choices((1_001_000,), options)
    assert choices == [
        {DOT_DECIMAL, COMMA_DECIMAL},
        {DOT_DECIMAL, COMMA_DECIMAL},
    ]


def test_solver_detects_forced_format_combination():
    options = [
        {0: (1_000,), 1: (1_000_000,)},
        {0: (1_000_000,), 1: (1_000,)},
    ]

    choices = feasible_format_choices((2_000,), options)
    assert choices == [{DOT_DECIMAL}, {COMMA_DECIMAL}]


def test_solver_rejects_no_solution():
    options = [{0: (1,), 1: (2,)}, {0: (4,), 1: (8,)}]
    assert feasible_format_choices((3,), options) is None


def test_solver_enforces_every_hold():
    # First hold can match via either batch; second hold eliminates one pairing.
    options = [
        {0: (10, 0), 1: (20, 5)},
        {0: (20, 7), 1: (10, 0)},
    ]

    choices = feasible_format_choices((30, 7), options)
    assert choices == [{DOT_DECIMAL}, {DOT_DECIMAL}]

    # First-hold sum 30 exists in another pairing, but second hold does not.
    assert feasible_format_choices((30, 0), options) is None
