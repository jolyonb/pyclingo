"""
Seeded differential fuzz of expression rendering: random expression trees,
rendered by pyclingo and evaluated by clingo, must match Python's evaluation
of the same tree.

The generator avoids clingo/Python semantic divergences
so any mismatch is a RENDERING bug: division and modulo are
excluded (truncation vs floor on negatives), ** keeps small non-negative
exponents on positive bases (no negative-exponent or overflow cases), and
operand magnitudes are bounded well inside 32 bits.
"""

import random
from typing import Any

from pyclingo import ASPProgram, Compl, Number, Predicate

# Binary operators safe from semantic divergence; weights favor the
# precedence-sensitive mixes
BINARY_OPS = [
    ("+", lambda a, b: a + b),
    ("-", lambda a, b: a - b),
    ("*", lambda a, b: a * b),
    ("&", lambda a, b: a & b),
    ("|", lambda a, b: a | b),
    ("^", lambda a, b: a ^ b),
]


def _leaf(rng: random.Random) -> tuple[Any, Any]:
    value = rng.randint(-50, 50)
    return Number(value), value


def build_tree(rng: random.Random, depth: int) -> tuple[Any, Any]:
    """
    Returns (pyclingo expression or Number, python int) for the same tree.

    EVERY node's value is kept inside clingo's 32-bit range, intermediates
    included: Python evaluates the reference in bignum while clingo wraps,
    so a tree like (big*big) - (big*big) with an in-range RESULT would
    diverge for no rendering reason. An overflowing subtree collapses to a
    fresh leaf.
    """
    if depth == 0 or rng.random() < 0.3:
        return _leaf(rng)
    shape = rng.random()
    if shape < 0.08:
        term, value = build_tree(rng, depth - 1)
        return (-term, -value) if -(2**31) <= -value < 2**31 else _leaf(rng)
    if shape < 0.16:
        term, value = build_tree(rng, depth - 1)
        return Compl(term), ~value  # ~ maps the 32-bit range onto itself
    if shape < 0.24:
        # ** with a small non-negative literal exponent on a positive base
        base = rng.randint(1, 6)
        exponent = rng.randint(0, 3)
        return Number(base) ** Number(exponent), base**exponent
    _name, op = BINARY_OPS[rng.randrange(len(BINARY_OPS))]
    left_term, left_value = build_tree(rng, depth - 1)
    right_term, right_value = build_tree(rng, depth - 1)
    value = op(left_value, right_value)
    if not -(2**31) <= value < 2**31:
        return _leaf(rng)
    return op(left_term, right_term), value


def test_rendered_trees_evaluate_identically_seeded_fuzz() -> None:
    rng = random.Random(0x5EED)
    Result = Predicate.define("result", ["case", "value"])
    program = ASPProgram()
    expected: dict[int, int] = {}
    case = 0
    while case < 1000:
        term, value = build_tree(rng, depth=5)
        if isinstance(term, Number):
            continue  # a bare leaf pins nothing (build_tree bounds every node's value)
        program.fact(Result(case=case, value=term))
        expected[case] = value
        case += 1

    model = next(iter(program.solve()))
    actual = {atom["case"].value: atom["value"].value for atom in model.atoms(Result)}
    mismatches = {c: (expected[c], actual.get(c)) for c in expected if actual.get(c) != expected[c]}
    assert not mismatches, f"renderer/clingo disagreement on {len(mismatches)} trees: {mismatches}"
