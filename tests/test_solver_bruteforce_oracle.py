import itertools
import random

from app.parsing import FORMATS
from app.solver import feasible_format_choices


def brute_force_choices(target, options):
    possible = [set() for _ in options]
    found = False
    available = [list(batch.keys()) for batch in options]

    for codes in itertools.product(*available):
        total = [0] * len(target)
        for batch_index, code in enumerate(codes):
            for hold_index, value in enumerate(options[batch_index][code]):
                total[hold_index] += value
        if tuple(total) == tuple(target):
            found = True
            for batch_index, code in enumerate(codes):
                possible[batch_index].add(FORMATS[code])

    return possible if found else None


def test_mitm_classification_matches_bruteforce_for_random_small_ships():
    rng = random.Random(918273)
    for _ in range(300):
        batch_count = rng.randrange(1, 9)
        hold_count = rng.randrange(1, 4)
        options = []
        planted_target = [0] * hold_count

        for _ in range(batch_count):
            batch = {}
            # Rarely make a format illegal; usually both are available.
            codes = [0, 1] if rng.random() > 0.12 else [rng.randrange(2)]
            for code in codes:
                batch[code] = tuple(
                    rng.randrange(0, 20) for _ in range(hold_count)
                )
            options.append(batch)
            chosen = rng.choice(codes)
            for i, value in enumerate(batch[chosen]):
                planted_target[i] += value

        # Most iterations use a guaranteed feasible planted target; sometimes
        # perturb it to exercise the no-solution path.
        target = tuple(planted_target)
        if rng.random() < 0.2:
            target = tuple(value + rng.randrange(1, 5) for value in target)

        expected = brute_force_choices(target, options)
        actual = feasible_format_choices(target, options)
        assert actual == expected
