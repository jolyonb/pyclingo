from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Self

from aspuzzle.grid import Grid
from aspuzzle.puzzle import Module
from pyclingo import (
    Choice,
    Count,
    Equals,
    Not,
    NotEquals,
    Predicate,
    Variable,
)
from pyclingo.expression import Comparison
from pyclingo.negation import NegatedLiteral
from pyclingo.pool import Pool
from pyclingo.term import Term

if TYPE_CHECKING:
    from pyclingo.aggregates import AGGREGATE_CONDITION_TYPE
    from pyclingo.types import CONSTANT_NUMBER


@dataclass
class SymbolInfo:
    """Information about a symbol in the symbol set."""

    predicate: type[Predicate]
    is_range: bool = False
    pool: Optional[Pool] = None
    value_field: Optional[str] = None  # For range symbols, the name of the value field


class SymbolSet(Module):
    """
    A module for representing a set of symbols to be placed into a grid.
    """

    def __init__(
        self,
        grid: Grid,
        name: str = "symbols",
        primary_namespace: bool = True,
        fill_all_squares: bool = False,
    ):
        super().__init__(grid.puzzle, name, primary_namespace)

        self.grid = grid
        self._symbols: dict[str, SymbolInfo] = {}
        self._excluded_cells: list[Predicate] = []
        self.fill_all_squares = fill_all_squares

    def add_symbol(self, name: str, show: bool = True) -> Self:
        """
        Add a new symbol to the set.

        Args:
            name: The name of the symbol
            show: Whether to include this symbol in the show directive

        Returns:
            Self for method chaining
        """
        if name in self._symbols:
            raise ValueError(f"Symbol '{name}' already exists in this set")

        # Define the predicate for this symbol
        symbol_pred = Predicate.define(name, ["loc"], namespace=self.namespace, show=show)

        self._symbols[name] = SymbolInfo(predicate=symbol_pred, is_range=False)

        return self

    def add_range_symbol(
        self,
        pool: Pool,
        name: str = "number",
        type_name: str = "num",
        show: bool = True,
    ) -> Self:
        """
        Add a new symbol to the set that comes from a set of related objects.

        Args:
            pool: Pool of values to use as symbols
            name: Base name for the predicate
            type_name: Name of the value parameter in the predicate
            show: Whether to include this symbol in the show directive

        Returns:
            Self for method chaining
        """
        if name in self._symbols:
            raise ValueError(f"Symbol '{name}' already exists in this set")

        # Define the predicate for this symbol type
        symbol_pred = Predicate.define(name, ["loc", type_name], namespace=self.namespace, show=show)

        self._symbols[name] = SymbolInfo(
            predicate=symbol_pred,
            is_range=True,
            pool=pool,
            value_field=type_name,
        )

        return self

    def __getitem__(self, predicate_name: str) -> type[Predicate]:
        """
        Returns the predicate class associated with the given symbol name.

        Args:
            predicate_name: The name of the symbol predicate

        Returns:
            The predicate class for the symbol

        Raises:
            KeyError: If the predicate doesn't exist
        """
        if predicate_name not in self._symbols:
            raise KeyError(f"No symbol named '{predicate_name}' in this set")

        return self._symbols[predicate_name].predicate

    def excluded_symbol(self, cell: Predicate) -> Self:
        """
        Add a cell where symbols cannot be placed.

        Args:
            cell: The cell predicate where symbols can't be placed

        Returns:
            Self for method chaining
        """
        self._excluded_cells.append(cell)
        return self

    def finalize(self) -> None:
        """Render the rules associated with the symbol set."""
        # Early exit if no symbols defined
        if not self._symbols:
            return

        # Get all cells in the grid
        cell = self.grid.cell()

        # Add all symbols to the choice rule
        V = Variable("V")
        choices: list[tuple[Predicate, Comparison | None]] = []
        for name, symbol_info in self._symbols.items():
            pred = symbol_info.predicate

            if not symbol_info.is_range:
                # Simple symbol, no conditions
                choices.append((pred(loc=cell), None))
            else:
                # Range symbol, add condition that value is in the pool
                choices.append(
                    (
                        pred(loc=cell, **{symbol_info.value_field: V}),
                        V.in_(symbol_info.pool),
                    )
                )

        # Create the choice rule
        first_choice, first_condition = choices[0]
        choice = Choice(first_choice, first_condition)
        for choice_pred, condition in choices[1:]:
            choice.add(choice_pred, condition)

        # Set cardinality constraints
        if self.fill_all_squares:
            choice.exactly(1)
        else:
            choice.at_least(0).at_most(1)

        # Add the condition that the cell is not excluded
        conditions: list[Predicate | NegatedLiteral] = [cell]
        conditions.extend(Not(excl) for excl in self._excluded_cells)
        # Add grid outside border to exclusions if it exists
        if self.grid.include_outside_border:
            conditions.append(Not(self.grid.outside()))

        self.section("Place symbols in the grid")
        self.when(conditions, choice)


def set_count_constraint(
    grid: Grid,
    predicate: Predicate,
    exactly: CONSTANT_NUMBER | None = None,
    not_equal: CONSTANT_NUMBER | None = None,
    at_least: CONSTANT_NUMBER | None = None,
    at_most: CONSTANT_NUMBER | None = None,
    greater_than: CONSTANT_NUMBER | None = None,
    less_than: CONSTANT_NUMBER | None = None,
    count_conditions: AGGREGATE_CONDITION_TYPE | list[AGGREGATE_CONDITION_TYPE] | None = None,
    rule_terms: Term | list[Term] | None = None,
) -> None:
    """
    Set a count constraint on cells matching a specific predicate pattern.

    Args:
        grid: The grid object
        predicate: The predicate instance to count. IMPORTANT: This predicate must be
                  instantiated with grid.cell() as one of its fields (typically the 'loc' field)
        exactly: The exact count (==)
        not_equal: The count must not equal this value (!=)
        at_least: The minimum count, inclusive (>=)
        at_most: The maximum count, inclusive (<=)
        greater_than: The count must be greater than this value (>)
        less_than: The count must be less than this value (<)
        count_conditions: Optional list of additional conditions for the count
        rule_terms: Optional list of additional terms to add to the rule

    TODO: Option for the count to be in an ExplicitPool
    """
    # Get the puzzle from the grid
    puzzle = grid.puzzle

    # Check that at least one comparison is set
    comparisons = [exactly, not_equal, at_least, at_most, greater_than, less_than]
    if all(comp is None for comp in comparisons):
        raise ValueError("Must specify at least one comparison constraint")

    # Build the condition list
    conditions: list[AGGREGATE_CONDITION_TYPE] = [predicate]
    if count_conditions:
        if not isinstance(count_conditions, list):
            count_conditions = [count_conditions]
        conditions.extend(count_conditions)

    # Create a variable for the count
    N = Variable("N_cnt")  # TODO: Need something that doesn't clash! Autodetect clashes?

    # Create the constraint terms list
    count_term = Equals(N, Count(grid.cell(), condition=conditions))
    if isinstance(rule_terms, list):
        rule_body = [*rule_terms, count_term]
    elif rule_terms is not None:
        rule_body = [rule_terms, count_term]
    else:
        rule_body = count_term

    # Create rules for each constraint
    if exactly is not None:
        puzzle.when(rule_body, Equals(N, exactly))

    if not_equal is not None:
        puzzle.when(rule_body, NotEquals(N, not_equal))

    if at_least is not None:
        puzzle.when(rule_body, N >= at_least)

    if at_most is not None:
        puzzle.when(rule_body, N <= at_most)

    if greater_than is not None:
        puzzle.when(rule_body, N > greater_than)

    if less_than is not None:
        puzzle.when(rule_body, N < less_than)


# TODO: Helper conditions for contiguous symbols
