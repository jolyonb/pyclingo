from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Self, cast

from aspuzzle.grids.base import Grid
from aspuzzle.puzzle import Module
from pyclingo import Choice, Not, Predicate, Variable, create_variables
from pyclingo.expression import Comparison
from pyclingo.negation import NegatedLiteral
from pyclingo.pool import Pool
from pyclingo.term import Term


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

            if symbol_info.value_field:
                # Range symbol, add condition that value is in the pool
                assert symbol_info.pool is not None
                choices.append(
                    (
                        pred(loc=cell, **{symbol_info.value_field: V}),
                        V.in_(symbol_info.pool),
                    )
                )
            else:
                # Simple symbol, no conditions
                choices.append((pred(loc=cell), None))

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
        if self.grid.has_outside_border:
            # This is safe to do because we're in the finalize method, which is
            # called after all rules that might create the outside border have been defined.
            conditions.append(Not(self.grid.outside_grid()))

        self.section("Place symbols in the grid")
        self.when(cast(list[Term], conditions), choice)

    def make_contiguous(self, symbol_name: str, anchor_cell: Predicate | None = None) -> Self:
        """
        Make the specified symbol form a contiguous region.
        For range symbols, each value in the range forms its own contiguous region.

        Args:
            symbol_name: The name of the symbol to make contiguous
            anchor_cell: Optional specific cell to use as the anchor (must have the same field structure as the symbol).
                         If None, anchors will be automatically determined.

        Returns:
            Self for method chaining
        """
        # Verify the symbol exists
        if symbol_name not in self._symbols:
            raise KeyError(f"No symbol named '{symbol_name}' in this set")

        symbol = self._symbols[symbol_name]
        symbol_pred = symbol.predicate
        fields = symbol_pred.field_names()
        value_field = {symbol.value_field: Variable("V")} if symbol.value_field else {}

        # Create Connected predicate with same fields as the symbol predicate
        Connected = Predicate.define(
            f"connected_{symbol_name}",
            fields,
            namespace=self.namespace,
            show=False,
        )

        # Determine anchor if needed
        if anchor_cell is None:
            # Create an anchor for the symbol, handling all values in a range as needed
            anchor_pred = self.grid.find_anchor_cell(
                condition_predicate=symbol_pred,
                cell_field="loc",
                anchor_name=f"{symbol_name}_anchor",
                fixed_fields=value_field,
                preserved_fields=[symbol.value_field] if symbol.value_field else None,
                segment=self._name,
            )
            anchor_cell = anchor_pred(loc=self.grid.cell(), **value_field)

        # Validate anchor cell fields
        if anchor_cell.field_names() != fields:
            raise ValueError(
                f"The anchor cell {anchor_cell} must have the same field structure as the symbol predicate {fields}."
            )

        self.section(f"Contiguity for {symbol_name}")

        # Mark each anchor as connected, using whatever was provided in the anchor
        self.when(anchor_cell, Connected(**{f: getattr(anchor_cell, f) for f in fields}))

        # Propagate connectivity
        C, C_adj = create_variables("C", "C_adj")
        self.when(
            [
                Connected(loc=C, **value_field),
                symbol_pred(loc=C_adj, **value_field),
                self.grid.Orthogonal(cell1=C, cell2=C_adj),
            ],
            Connected(loc=C_adj, **value_field),
        )

        # Forbid symbol cells that aren't connected
        self.forbid(symbol_pred(loc=C, **value_field), Not(Connected(loc=C, **value_field)))

        return self
