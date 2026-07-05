from typing import Sequence

from pyclingo.core import Term, Variable


def collect_variables(*terms: Term | Sequence[Term] | None) -> set[str]:
    """
    Collect all variable names used in the given terms.

    Accepts a mix of Terms, lists of Terms, and Nones (skipped).
    """
    used_variables: set[str] = set()

    for term in terms:
        if term is None:
            continue

        elif isinstance(term, (list, tuple)):
            for t in term:
                used_variables.update(t.collect_variables())

        elif isinstance(term, Term):
            used_variables.update(term.collect_variables())

        else:
            raise TypeError(f"Expected a Term, a sequence of Terms, or None, got {type(term).__name__}")

    return used_variables


def create_unique_variable_name(used_variables: set[str], preferred_names: list[str]) -> Variable:
    """
    Given a set of used variables and a list of preferred names, construct a unique variable name.
    Uses the first available name in the preferred names list, or starts appending numbers to the last one if needed.
    """
    for name in preferred_names:
        if name not in used_variables:
            return Variable(name)

    # If all preferred names are taken, use numeric suffix with the last preferred name
    base_name = preferred_names[-1]
    counter = 1
    while f"{base_name}{counter}" in used_variables:
        counter += 1
    return Variable(f"{base_name}{counter}")
