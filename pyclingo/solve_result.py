"""
Search results: the streaming handles (SolveResult, RefinementSteps) and
the typed atom containers (Model, Consequences) they produce.

Every search mode shares one lifecycle — _Search handles over one
_search_generator — because the skeleton is mode-independent clingo fact:
resume/wait/cancel/get ordering, the timed-out-vs-exhausted race, and
finalization on every exit path. The modes differ at exactly three
labeled points in the generator: what an emission is, whether costs are
legal, and what a timeout terminal does.

A note on object lifetimes, which shape this module's design. clingo's
Control frees its native object in __del__, and native calls on a freed
control crash rather than raise. That is fatal in a reference cycle: the
garbage collector finalizes a cycle's members in undefined order, so a
Control could be freed before a generator whose cleanup still calls into
it — observed as a segfault. This module therefore keeps the handles
cycle-free, so an abandoned one tears down by refcount in a deterministic
order: the generator closes first (its frame's `control` reference keeps
the native object alive through the cleanup calls and the statistics
copy), and the Control is freed last. Concretely:

- The search generator is a free function, not a handle method — a
  method generator's frame would hold self, closing the cycle
  (self -> iterator -> frame -> self).
- Generator and handle share a _SearchState holder for bookkeeping;
  both hold it strongly, it references neither.
- The native solver thread (async solving) exists only when a wall-clock
  timeout demands it; without one, solving is synchronous and there is no
  second thread to race during teardown.
"""

import time
from abc import ABC, abstractmethod
from collections.abc import Generator, Iterator
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Self, cast, overload

import clingo

from pyclingo.clingo_handler import ClingoMessage, ClingoMessageHandler
from pyclingo.core import DefinedConstant, Number, String
from pyclingo.predicate import Predicate
from pyclingo.statistics import format_statistics_clingo_style

# Solution reconstruction is keyed by (name, arity): p/1 and p/2 are distinct
# predicates in ASP
type PREDICATE_TYPES = dict[tuple[str, int], type[Predicate]]


class RefinementMode(StrEnum):
    """
    The two consequence refinements: BRAVE grows toward the union (atoms
    true in at least one answer set), CAUTIOUS shrinks toward the
    intersection (atoms true in every answer set). Values match clingo's
    enum_mode configuration spellings.
    """

    BRAVE = "brave"
    CAUTIOUS = "cautious"


class AtomCollection:
    """
    A set of atoms as typed Predicate instances: the claim-free reading
    surface shared by everything that hands atoms back. Subclasses say what
    their atoms MEAN — a Model's are one answer set, a Consequences' are a
    statement about every answer set — this class only provides the access.
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
        All atoms, or all of the given predicate class — BOTH signs:
        classically negated atoms (-p) are instances of the same class,
        so filter on .negated if your program uses classical negation.

        Lookup is by EXACT class, and in_namespace() clones are distinct
        classes: query with the clone you built the program with (atoms(Base)
        is empty if the collection holds only clone atoms). When in doubt,
        atoms() with no argument returns everything.
        """
        if predicate is None:
            return list(self._atoms)
        return list(self._by_class.get(predicate, []))

    def __len__(self) -> int:
        return len(self._atoms)

    def __repr__(self) -> str:
        counts = ", ".join(f"{cls.get_name()}: {len(atoms)}" for cls, atoms in self._by_class.items())
        return f"{type(self).__name__}({counts})"


class Model(AtomCollection):
    """
    One answer set: the atoms clingo found true, as typed Predicate instances.

    (Clingo calls this a model; the paradigm's own name for it is an answer set.)
    """

    def __init__(self, atoms: list[Predicate], messages: list[ClingoMessage] | None = None) -> None:
        super().__init__(atoms)
        # Diagnostics clingo emitted while searching for this model (usually empty)
        self.messages = messages if messages is not None else []


class CostedModel(Model):
    """
    An answer set found during an optimization descent, carrying its cost.

    cost has one entry per declared priority level, highest priority
    first (priorities are ordinal keys — gaps do not pad the tuple). A
    maximization's cost is reported negated: clasp minimizes the negated
    weights, so maximizing a total of 9 reads cost=(-9,). Lower is better
    at every level, in every sense.
    """

    def __init__(
        self,
        atoms: list[Predicate],
        cost: tuple[int, ...],
        messages: list[ClingoMessage] | None = None,
    ) -> None:
        super().__init__(atoms, messages)
        self.cost = cost

    def __repr__(self) -> str:
        counts = ", ".join(f"{cls.get_name()}: {len(atoms)}" for cls, atoms in self._by_class.items())
        return f"{type(self).__name__}(cost={list(self.cost)}, {counts})"


class Consequences(AtomCollection):
    """
    The product of one brave/cautious refinement: a statement about the
    whole answer-set space, NOT an answer set itself.

    clasp computes consequences by refinement — successive approximations
    where brave grows toward the union and cautious shrinks toward the
    intersection. The full approximation sequence is kept as .path (the
    receipts). Consecutive differences are certified by a single witness
    model each — brave's additions are jointly true somewhere, cautious's
    removals jointly absent somewhere.

    .complete means the refinement PROVED it finished. An incomplete
    result still carries one-sided knowledge, and the trustworthy side
    differs by mode — see each subclass. A bound landing exactly on the
    final approximation reports complete=False: completeness is a proof,
    not a coincidence.
    """

    def __init__(
        self,
        atoms: list[Predicate],
        path: tuple[AtomCollection, ...],
        complete: bool,
        messages: list[ClingoMessage],
    ) -> None:
        super().__init__(atoms)
        self.path = path
        self.complete = complete
        self.messages = messages


class BraveConsequences(Consequences):
    """
    The atoms true in AT LEAST ONE answer set (the union) — "which cells
    are possible" is this question.

    Every atom present is certified (each arrived with a witness model),
    complete or not. When incomplete, ABSENCE proves nothing: an atom not
    yet added may still be possible.
    """


class CautiousConsequences(Consequences):
    """
    The atoms true in EVERY answer set (the intersection) — "which cells
    are forced" is this question.

    Every atom ABSENT is certified not-forced (some model lacks it),
    complete or not. When incomplete, PRESENCE proves nothing: an atom
    not yet removed may still fall out of the intersection.
    """


@dataclass
class _SearchState:
    """
    Mutable search bookkeeping, shared by a handle and its generator.

    Both hold it strongly and it references neither, keeping the handle
    cycle-free (see the module docstring for why that matters).
    emission_count counts whatever the mode emits — models or refinement
    approximations; the handles rename it in their own vocabulary.
    """

    satisfiable: bool | None = None
    exhausted: bool = False
    emission_count: int = 0
    statistics: dict[str, Any] | None = None
    finished: bool = False
    messages: list[ClingoMessage] = field(default_factory=list)


class SearchABC(ABC):
    """
    Shared lifecycle for one search on a Control: the iterate-once guard,
    close()/with teardown, and the flags the generator finalizes on every
    exit path. Subclasses say what the emissions MEAN — a SolveResult's
    are answer sets, a RefinementSteps' are approximations — by declaring
    their own __iter__ element type and exhausted semantics, and name the
    counters in their mode's vocabulary.
    """

    def __init__(self, iterator: Generator[Any], state: _SearchState) -> None:
        self._state = state
        self._iterator = iterator

    @abstractmethod
    def __iter__(self) -> Iterator[AtomCollection]:
        """Iterate the search's emissions; subclasses narrow the element type."""

    @property
    @abstractmethod
    def exhausted(self) -> bool:
        """Whether the search proved there is nothing further to find."""

    def _guard_consumed(self, remedy: str) -> None:
        # Iterating a finished stream would silently yield nothing, which
        # reads as "no results"; partial consumption may resume, but a
        # finished handle fails loudly instead
        if self._state.finished:
            raise RuntimeError(f"This {type(self).__name__} is already consumed (exhausted or closed); {remedy}")

    def close(self) -> None:
        """Stop the search early; flags and statistics are finalized."""
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
        """Whether this handle's stream has ended (exhausted or closed)."""
        return self._state.finished

    @property
    def satisfiable(self) -> bool | None:
        """True/False once known; None if nothing has been learned yet."""
        return self._state.satisfiable

    @property
    def messages(self) -> list[ClingoMessage]:
        """
        Diagnostics clingo emitted during the solve phase (after grounding).

        These never halt solving — the stop_on_log_level threshold applies
        to parsing and grounding only.
        """
        return list(self._state.messages)

    @property
    def statistics(self) -> dict[str, Any] | None:
        """
        Raw clingo statistics plus 'wall_time', or None if solving never ran.

        wall_time spans this handle's creation to the end of iteration — it
        includes any time the caller spends between emissions, and excludes
        rendering and grounding. clingo's own solving clocks live under
        summary.times.
        """
        return self._state.statistics

    def format_statistics(self) -> str:
        """The search's statistics in clingo's native output style."""
        if self._state.statistics is None:
            return "No statistics available"
        return format_statistics_clingo_style(self._state.statistics)


class SolveResult(SearchABC):
    """
    The handle for one solve: iterate it to receive Models lazily.

    'satisfiable', 'exhausted', and 'solution_count' update as models arrive
    and are finalized when iteration ends on any path — exhaustion, close(),
    or leaving a with-block. Statistics are available after solving finishes.
    Each call to ASPProgram.solve() returns an independent SolveResult, so
    repeated solves never interfere. Each Model carries the message slice
    that arrived while it was being found.
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
        state = _SearchState()
        super().__init__(
            _search_generator(
                control,
                predicate_types,
                timeout,
                time.perf_counter(),
                state,
                message_handler,
                check_all_atoms,
                assumptions or [],
                mode=None,
            ),
            state,
        )

    @property
    def exhausted(self) -> bool:
        """Whether the search space was fully explored."""
        return self._state.exhausted

    @property
    def solution_count(self) -> int:
        """Models yielded so far."""
        return self._state.emission_count

    def __iter__(self) -> Iterator[Model]:
        self._guard_consumed("call solve() again for a fresh search")
        # mode="models" makes every emission a Model; the generator is typed
        # by the shared element type, so this cast is the one honest seam
        return cast(Iterator[Model], self._iterator)


class RefinementSteps(SearchABC):
    """
    The handle for one brave/cautious refinement, consumed step by step:
    iterate it to receive each successive approximation as a claim-free
    AtomCollection, and stop whenever your question is answered — each
    step is a full solver search, so control between steps is control
    over real work. This is the consequences PRIMITIVE; cautious()/brave()
    are eager sugar over it.

    Iteration ending naturally means the refinement completed: the last
    yielded approximation is the true intersection/union (zero yields
    means unsatisfiable), and .exhausted reports True. Breaking early
    leaves a partial approximation whose one-sided reading is described
    on the Consequences subclasses. A timeout raises TimeoutError from
    within iteration — a timed-out refinement must never impersonate a
    completed one by merely stopping.
    """

    def __init__(
        self,
        control: clingo.Control,
        predicate_types: PREDICATE_TYPES,
        timeout: float,
        message_handler: ClingoMessageHandler,
        assumptions: list[tuple[clingo.Symbol, bool]],
        mode: RefinementMode,
        check_all_atoms: bool = False,
    ) -> None:
        state = _SearchState()
        super().__init__(
            _search_generator(
                control,
                predicate_types,
                timeout,
                time.perf_counter(),
                state,
                message_handler,
                check_all_atoms,
                assumptions,
                mode=mode,
            ),
            state,
        )

    @property
    def exhausted(self) -> bool:
        """Whether the refinement PROVED it reached the true answer."""
        return self._state.exhausted

    @property
    def steps_taken(self) -> int:
        """Approximations yielded so far."""
        return self._state.emission_count

    def __iter__(self) -> Iterator[AtomCollection]:
        self._guard_consumed("call the steps method again to restart")
        return self._iterator


def _search_generator(
    control: clingo.Control,
    predicate_types: PREDICATE_TYPES,
    timeout: float,
    tic: float,
    state: _SearchState,
    message_handler: ClingoMessageHandler,
    check_all_atoms: bool,
    assumptions: list[tuple[clingo.Symbol, bool]],
    mode: RefinementMode | None,
) -> Generator[AtomCollection]:
    """
    One loop for every search mode, finalizing bookkeeping on every exit
    path. The skeleton — resume/wait/cancel/get ordering, the
    timed-out-vs-exhausted race, finalization — is mode-independent clingo
    fact; the modes differ only at the three marked points: what an
    emission is, whether costs are legal, and what a timeout terminal does.

    A free function rather than a handle method so that its frame never
    references the handle (see the module docstring).
    """
    refining = mode is not None
    # The timeout clock starts here — at first iteration — not at the
    # originating call: time between constructing the handle and consuming
    # it belongs to the caller, and clingo does no work until we resume
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
                            # The deadline passed before the next emission
                            timed_out = True
                            break
                    model = handle.model()
                    if model is None:
                        break
                    if model.cost:
                        # Variation point: costs are illegal outside optimize
                        # mode. Refinement would aggregate the cost-descent
                        # path, not the optima; enumeration would stream one
                        # improving chain as if it were distinct solutions.
                        # This backstops the static detection for any
                        # optimization spelling the raw-text scan cannot see.
                        if refining:
                            raise ValueError(
                                f"{mode} consequences over an optimizing program (#minimize/#maximize "
                                f"present) are computed against the solver's cost-descent path, not "
                                f"the set of optimal models — the result would be wrong. Remove the "
                                f"optimization directive to ask about all answer sets."
                            )
                        raise ValueError("This program optimizes (the model carries a cost). Solve it with optimize().")
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
                    state.emission_count += 1
                    state.satisfiable = True
                    new_messages = message_handler.messages[messages_seen:]
                    messages_seen = len(message_handler.messages)
                    state.messages.extend(new_messages)
                    atoms = [
                        convert_symbol_to_predicate(symbol, predicate_types) for symbol in model.symbols(shown=True)
                    ]
                    # Variation point: an enumeration emission is an answer
                    # set; a refinement emission is a claim-free approximation
                    yield AtomCollection(atoms) if refining else Model(atoms, messages=new_messages)
            finally:
                # Also reached when the caller close()s mid-iteration and when
                # an abandoned handle is torn down by refcount. Cancelling a
                # finished search is a no-op.
                handle.cancel()
                # After a cancelled solve, satisfiability may be unknown (None);
                # keep what we learned from any yielded emissions.
                outcome: clingo.SolveResult = handle.get()
                if outcome.satisfiable is not None:
                    state.satisfiable = outcome.satisfiable
                # A fast search can finish between resume() and the deadline
                # check; a timed-out search must never claim exhaustion
                state.exhausted = False if timed_out else outcome.exhausted
                final = outcome
    finally:
        state.finished = True
        # Messages after the last emission (exhaustion proof, cancellation)
        state.messages.extend(message_handler.messages[messages_seen:])
        if final is not None:
            # Skipped if the handle was closed before solving began. clingo
            # raises if statistics are not ready; none is better than raising.
            with suppress(RuntimeError):
                statistics = dict(control.statistics)
                statistics["wall_time"] = time.perf_counter() - tic
                state.statistics = statistics
    if timed_out and refining:
        # Variation point: a timed-out enumeration flags and stops (each
        # yielded model was already a true answer), but a timed-out
        # refinement must raise — merely stopping would impersonate a
        # completed one
        raise TimeoutError(
            f"{mode} refinement did not finish within {timeout}s; approximations yielded "
            f"so far form a {'superset' if mode is RefinementMode.CAUTIOUS else 'subset'} "
            f"bound on the true answer, not the answer."
        )


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
