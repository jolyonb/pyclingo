"""
Solve results: the streaming SolveResult handle returned by ASPProgram.solve()
and the typed Model (answer set) objects it yields.
"""

import time
from collections.abc import Generator, Iterator
from typing import Any, Self, overload

import clingo

from pyclingo.predicate import Predicate
from pyclingo.statistics import format_statistics_clingo_style

# Solution reconstruction is keyed by (name, arity): p/1 and p/2 are distinct
# predicates in ASP
type PREDICATE_TYPES = dict[tuple[str, int], type[Predicate]]


class Model:
    """
    One answer set: the atoms clingo found true, as typed Predicate instances.

    (Clingo calls this a model; the paradigm's own name for it is an answer set.)
    """

    def __init__(self, atoms: list[Predicate]) -> None:
        self._atoms = atoms
        self._by_class: dict[type[Predicate], list[Predicate]] = {}
        for atom in atoms:
            self._by_class.setdefault(type(atom), []).append(atom)

    @overload
    def atoms(self) -> list[Predicate]: ...

    @overload
    def atoms[P: Predicate](self, predicate: type[P]) -> list[P]: ...

    def atoms(self, predicate: type[Predicate] | None = None) -> list[Any]:
        """
        All atoms in the model, or all of the given predicate class — BOTH
        signs: classically negated atoms (-p) are instances of the same class,
        so filter on .negated if your program uses classical negation.
        """
        if predicate is None:
            return list(self._atoms)
        return list(self._by_class.get(predicate, []))

    def __len__(self) -> int:
        return len(self._atoms)

    def __repr__(self) -> str:
        counts = ", ".join(f"{cls.get_name()}: {len(atoms)}" for cls, atoms in self._by_class.items())
        return f"Model({counts})"


class SolveResult:
    """
    The handle for one solve: iterate it to receive Models lazily.

    'satisfiable', 'exhausted', and 'solution_count' update as models arrive
    and are finalized when iteration ends on any path — exhaustion, close(),
    or leaving a with-block. Statistics are available after solving finishes.
    Each call to ASPProgram.solve() returns an independent SolveResult, so
    repeated solves never interfere.
    """

    def __init__(
        self,
        control: clingo.Control,
        predicate_types: PREDICATE_TYPES,
        timeout: int,
        tic: float,
    ) -> None:
        self.satisfiable: bool | None = None
        self.exhausted: bool = False
        self.solution_count: int = 0
        self._statistics: dict[str, Any] | None = None
        self._control = control
        self._predicate_types = predicate_types
        self._timeout = timeout
        self._tic = tic
        self._finished = False
        self._iterator = self._solve_generator()

    def __iter__(self) -> Iterator[Model]:
        # Iterating a finished stream would silently yield nothing, which reads
        # as "no models"; partial consumption may resume, but a finished result
        # fails loudly instead
        if self._finished:
            raise RuntimeError(
                "This SolveResult is already consumed (exhausted or closed); call solve() again for a fresh search"
            )
        return self._iterator

    def close(self) -> None:
        """Stop solving early; flags and statistics are finalized."""
        self._iterator.close()
        # Closing a never-started generator skips its finally, so mark
        # finished here as well
        self._finished = True

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @property
    def statistics(self) -> dict[str, Any] | None:
        """Raw clingo statistics plus 'total_time', or None if solving never ran."""
        return self._statistics

    def format_statistics(self) -> str:
        """The last solve's statistics in clingo's native output style."""
        if self._statistics is None:
            return "No statistics available"
        return format_statistics_clingo_style(self._statistics)

    def _solve_generator(self) -> Generator[Model]:
        """Yields models and finalizes bookkeeping on every exit path."""
        # The timeout clock starts here — at first iteration — not at solve():
        # time between constructing the result and consuming it belongs to the
        # caller, and clingo does no work until we resume the handle
        deadline = time.monotonic() + self._timeout if self._timeout > 0 else None
        timed_out = False
        final: clingo.SolveResult | None = None
        try:
            # Wall-clock timeouts require async solving: clingo has no timeout
            # configuration key; instead we wait on the handle and cancel at the deadline.
            with self._control.solve(yield_=True, async_=True) as handle:
                try:
                    while True:
                        handle.resume()
                        # Clamp to zero: wait() treats a negative timeout as "block forever",
                        # but a passed deadline should poll and cancel instead
                        remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
                        if not handle.wait(remaining):
                            # The deadline passed before the next model was found
                            timed_out = True
                            break
                        model = handle.model()
                        if model is None:
                            break
                        self.solution_count += 1
                        self.satisfiable = True
                        yield Model(
                            [
                                convert_symbol_to_predicate(symbol, self._predicate_types)
                                for symbol in model.symbols(shown=True)
                            ]
                        )
                finally:
                    # Also reached when the caller close()s mid-iteration. Cancelling a
                    # finished search is a no-op, so this is safe on every path.
                    handle.cancel()
                    # After a cancelled solve, satisfiability may be unknown (None);
                    # keep what we learned from any yielded models.
                    outcome: clingo.SolveResult = handle.get()
                    if outcome.satisfiable is not None:
                        self.satisfiable = outcome.satisfiable
                    # A fast search can finish between resume() and the deadline
                    # check; a timed-out solve must never claim exhaustion
                    self.exhausted = False if timed_out else outcome.exhausted
                    final = outcome
        finally:
            self._finished = True
            if final is not None:
                # Skipped if the result was closed before solving began. clingo
                # raises if statistics aren't ready (e.g. finalized during garbage
                # collection mid-search); reporting none is better than raising there.
                try:
                    self._statistics = dict(self._control.statistics)
                    self._statistics["total_time"] = time.perf_counter() - self._tic
                except RuntimeError:
                    self._statistics = None


def convert_symbol_to_predicate(symbol: clingo.Symbol, predicate_types: PREDICATE_TYPES) -> Predicate:
    """
    Convert a clingo model symbol back into a typed Predicate instance, recursively.

    Raises:
        ValueError: If the symbol's name/arity doesn't match any known predicate.
    """
    pred_name = symbol.name
    key = (pred_name, len(symbol.arguments))

    if key not in predicate_types:
        raise ValueError(f"Unknown predicate type: {pred_name}/{len(symbol.arguments)}")

    pred_class = predicate_types[key]
    field_names = [f.name for f in pred_class.argument_fields()]

    kwargs: dict[str, Predicate | int | str] = {}
    for i, (arg, field_name) in enumerate(zip(symbol.arguments, field_names, strict=True)):
        if arg.type == clingo.SymbolType.Number:
            kwargs[field_name] = arg.number
        elif arg.type == clingo.SymbolType.String:
            kwargs[field_name] = arg.string
        elif arg.type == clingo.SymbolType.Function:
            # Recursively convert nested predicates; bare atoms are nullary predicates
            kwargs[field_name] = convert_symbol_to_predicate(arg, predicate_types)
        else:
            raise ValueError(f"Unsupported symbol type in argument {i} of {pred_name}: {arg.type}")

    instance = pred_class(**kwargs)
    return -instance if symbol.negative else instance
