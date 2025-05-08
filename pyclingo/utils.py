from typing import Sequence

from pyclingo import Variable
from pyclingo.term import Term


def collect_variables(*terms: Term | Sequence[Term] | None) -> set[str]:
    """
    Given a list of terms, collect all variables used in them.

    Accepts terms of the following types:
    * Term
    * List[Term]
    * None

    Returns:
        set[str]: Set of variable names
    """
    used_variables: set[str] = set()

    for term in terms:
        if term is None:
            continue

        elif isinstance(term, list):
            for t in term:
                used_variables.update(t.collect_variables())

        elif isinstance(term, Term):
            used_variables.update(term.collect_variables())

        else:
            raise ValueError(f"Bad term type: {term}")

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
