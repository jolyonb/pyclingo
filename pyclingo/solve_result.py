"""
Solve results: the streaming SolveResult handle returned by ASPProgram.solve()
and the typed Model (answer set) objects it yields.

A note on object lifetimes, which shape this module's design. clingo's
Control frees its native object in __del__, and native calls on a freed
control crash rather than raise. That is fatal in a reference cycle: the
garbage collector finalizes a cycle's members in undefined order, so a
Control could be freed before a generator whose cleanup still calls into
it — observed as a segfault. This module therefore keeps SolveResult
cycle-free, so an abandoned result tears down by refcount in a
deterministic order: the generator closes first (its frame's `control`
reference keeps the native object alive through the cleanup calls and the
statistics copy), and the Control is freed last. Concretely:

- The solve generator is a free function, not a SolveResult method — a
  method generator's frame would hold self, closing the cycle
  (self -> iterator -> frame -> self).
- Generator and SolveResult share a _SolveState holder for bookkeeping;
  both hold it strongly, it references neither.
- The native solver thread (async solving) exists only when a wall-clock
  timeout demands it; without one, solving is synchronous and there is no
  second thread to race during teardown.
"""

import time
from collections.abc import Generator, Iterator
from dataclasses import dataclass, field
from typing import Any, Self, overload

import clingo

from pyclingo.clingo_handler import ClingoMessage, ClingoMessageHandler
from pyclingo.core import DefinedConstant, Number, String
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

    def __init__(self, atoms: list[Predicate], messages: list[ClingoMessage] | None = None) -> None:
        self._atoms = atoms
        # Diagnostics clingo emitted while searching for this model (usually empty)
        self.messages = messages if messages is not None else []
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


@dataclass
class _SolveState:
    """
    Mutable solve bookkeeping, shared by a SolveResult and its generator.

    Both hold it strongly and it references neither, keeping SolveResult
    cycle-free (see the module docstring for why that matters).
    """

    satisfiable: bool | None = None
    exhausted: bool = False
    solution_count: int = 0
    statistics: dict[str, Any] | None = None
    finished: bool = False
    messages: list[ClingoMessage] = field(default_factory=list)


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
        timeout: float,
        message_handler: ClingoMessageHandler,
        check_all_atoms: bool = False,
        assumptions: list[tuple[clingo.Symbol, bool]] | None = None,
    ) -> None:
        self._state = _SolveState()
        self._iterator = _solve_generator(
            control,
            predicate_types,
            timeout,
            time.perf_counter(),
            self._state,
            message_handler,
            check_all_atoms,
            assumptions or [],
        )

    @property
    def satisfiable(self) -> bool | None:
        """True/False once known; None if nothing has been learned yet."""
        return self._state.satisfiable

    @property
    def exhausted(self) -> bool:
        """Whether the search space was fully explored."""
        return self._state.exhausted

    @property
    def solution_count(self) -> int:
        """Models yielded so far."""
        return self._state.solution_count

    def __iter__(self) -> Iterator[Model]:
        # Iterating a finished stream would silently yield nothing, which reads
        # as "no models"; partial consumption may resume, but a finished result
        # fails loudly instead
        if self._state.finished:
            raise RuntimeError(
                "This SolveResult is already consumed (exhausted or closed); call solve() again for a fresh search"
            )
        return self._iterator

    def close(self) -> None:
        """Stop solving early; flags and statistics are finalized."""
        self._iterator.close()
        # Closing a never-started generator skips its finally, so mark
        # finished here as well
        self._state.finished = True

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @property
    def finished(self) -> bool:
        """Whether this result's stream has ended (exhausted or closed)."""
        return self._state.finished

    @property
    def messages(self) -> list[ClingoMessage]:
        """
        Diagnostics clingo emitted during the solve phase (after grounding).

        These never halt solving — the stop_on_log_level threshold applies to
        parsing and grounding only. Each Model also carries the slice that
        arrived while it was being found.
        """
        return list(self._state.messages)

    @property
    def statistics(self) -> dict[str, Any] | None:
        """
        Raw clingo statistics plus 'wall_time', or None if solving never ran.

        wall_time spans this result's creation (the solve() call) to the end
        of iteration — it includes any time the caller spends between models,
        and excludes rendering and grounding. clingo's own solving clocks
        live under summary.times.
        """
        return self._state.statistics

    def format_statistics(self) -> str:
        """The last solve's statistics in clingo's native output style."""
        if self._state.statistics is None:
            return "No statistics available"
        return format_statistics_clingo_style(self._state.statistics)


def _solve_generator(
    control: clingo.Control,
    predicate_types: PREDICATE_TYPES,
    timeout: float,
    tic: float,
    state: _SolveState,
    message_handler: ClingoMessageHandler,
    check_all_atoms: bool,
    assumptions: list[tuple[clingo.Symbol, bool]],
) -> Generator[Model]:
    """
    Yields models and finalizes bookkeeping on every exit path.

    A free function rather than a SolveResult method so that its frame never
    references the result (see the module docstring).
    """
    # The timeout clock starts here — at first iteration — not at solve():
    # time between constructing the result and consuming it belongs to the
    # caller, and clingo does no work until we resume the handle
    deadline = time.monotonic() + timeout if timeout > 0 else None
    timed_out = False
    final: clingo.SolveResult | None = None
    # Messages before this index belong to parsing/grounding, already policed
    # by the stop threshold; everything after is solve-phase, captured and
    # attached rather than halting
    messages_seen = len(message_handler.messages)
    try:
        # Async only when a wall-clock timeout demands it (see module
        # docstring): clingo has no timeout configuration key, so we wait on
        # the handle and cancel at the deadline.
        with control.solve(assumptions=assumptions, yield_=True, async_=deadline is not None) as handle:
            try:
                while True:
                    handle.resume()
                    if deadline is not None:
                        # Clamp to zero: wait() treats a negative timeout as
                        # "block forever", but a passed deadline should poll
                        # and cancel instead
                        remaining = max(0.0, deadline - time.monotonic())
                        if not handle.wait(remaining):
                            # The deadline passed before the next model was found
                            timed_out = True
                            break
                    model = handle.model()
                    if model is None:
                        break
                    if check_all_atoms:
                        # raw_asp text is invisible to the walkers, so its
                        # contract is exhaustive declaration: an atom with an
                        # unknown signature is a forgotten predicates= entry
                        # (show directives would silently hide it otherwise)
                        for symbol in model.symbols(atoms=True):
                            if (symbol.name, len(symbol.arguments)) not in predicate_types:
                                raise ValueError(
                                    f"Model contains {symbol}, whose signature "
                                    f"{symbol.name}/{len(symbol.arguments)} was never declared. "
                                    f"raw_asp blocks must declare every predicate they produce "
                                    f"via predicates=[...]; control visibility with show= on the "
                                    f"class, not by omitting it."
                                )
                    state.solution_count += 1
                    state.satisfiable = True
                    new_messages = message_handler.messages[messages_seen:]
                    messages_seen = len(message_handler.messages)
                    state.messages.extend(new_messages)
                    yield Model(
                        [convert_symbol_to_predicate(symbol, predicate_types) for symbol in model.symbols(shown=True)],
                        messages=new_messages,
                    )
            finally:
                # Also reached when the caller close()s mid-iteration and when
                # an abandoned result is torn down by refcount. Cancelling a
                # finished search is a no-op.
                handle.cancel()
                # After a cancelled solve, satisfiability may be unknown (None);
                # keep what we learned from any yielded models.
                outcome: clingo.SolveResult = handle.get()
                if outcome.satisfiable is not None:
                    state.satisfiable = outcome.satisfiable
                # A fast search can finish between resume() and the deadline
                # check; a timed-out solve must never claim exhaustion
                state.exhausted = False if timed_out else outcome.exhausted
                final = outcome
    finally:
        state.finished = True
        # Messages after the last model (exhaustion proof, cancellation)
        state.messages.extend(message_handler.messages[messages_seen:])
        if final is not None:
            # Skipped if the result was closed before solving began. clingo
            # raises if statistics are not ready; none is better than raising.
            try:
                statistics = dict(control.statistics)
                statistics["wall_time"] = time.perf_counter() - tic
                state.statistics = statistics
            except RuntimeError:
                pass


def convert_predicate_to_symbol(
    predicate: Predicate, defined_constants: dict[str, int | str] | None = None
) -> clingo.Symbol:
    """
    Convert a grounded Predicate instance into a clingo Symbol, recursively —
    the mirror of convert_symbol_to_predicate. The classical-negation sign
    maps to the symbol's sign; #const references resolve through
    defined_constants (gringo substitutes them at grounding, so the ground
    atom carries the value, not the name).
    """
    arguments: list[clingo.Symbol] = []
    for field_name in predicate.field_names():
        value = predicate.read_as_term(field_name)
        if isinstance(value, DefinedConstant):
            resolved = (defined_constants or {}).get(value.value)
            if resolved is None:
                raise ValueError(
                    f"Cannot convert {predicate.render()} to a symbol: '{value.value}' is a "
                    f"#const reference and no value for it is available here"
                )
            arguments.append(clingo.Number(resolved) if isinstance(resolved, int) else clingo.String(resolved))
        elif isinstance(value, Number):
            arguments.append(clingo.Number(value.value))
        elif isinstance(value, String):
            arguments.append(clingo.String(value.value))
        elif isinstance(value, Predicate):
            arguments.append(convert_predicate_to_symbol(value, defined_constants))
        else:
            raise ValueError(
                f"Cannot convert {predicate.render()} to a symbol: field '{field_name}' holds "
                f"{type(value).__name__}. clingo evaluates arithmetic at grounding (with its own "
                f"semantics — see MATH.md), so pass the computed value instead."
            )
    return clingo.Function(predicate.get_name(), arguments, positive=not predicate.negated)


def convert_symbol_to_predicate(symbol: clingo.Symbol, predicate_types: PREDICATE_TYPES) -> Predicate:
    """
    Convert a clingo model symbol back into a typed Predicate instance, recursively.

    Raises:
        ValueError: If the symbol's name/arity doesn't match any known predicate.
    """
    pred_name = symbol.name
    key = (pred_name, len(symbol.arguments))

    if key not in predicate_types:
        raise ValueError(
            f"Unknown predicate type: {pred_name}/{len(symbol.arguments)}. If this atom is "
            f"produced by a raw_asp() block, declare its class via raw_asp(..., predicates=[...])."
        )

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
