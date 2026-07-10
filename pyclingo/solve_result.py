"""
Search results: the streaming handles (SolveResult, RefinementSteps,
OptimizeSteps) and the typed atom containers (Model, Consequences) they
produce.

Every search mode shares one lifecycle — Search handles over one
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

One nuance: a GroundedProgram keeps a strong reference to its most recent
handle (the sequential guard's _active), so an abandoned mid-flight handle
tears down by refcount only once the GroundedProgram itself is dropped or
abandon() is called — until then the suspended native search stays alive,
and the next solve attempt raises the loud still-open error.
"""

import copy
import time
from abc import ABC, abstractmethod
from collections.abc import Generator, Iterator, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Self, cast, overload

import clingo

from pyclingo.clingo_handler import ClingoMessage, ClingoMessageHandler
from pyclingo.core import INF, SUP, DefaultNegation, DefinedConstant, ExtremeConstant, Infimum, Number, String, Supremum
from pyclingo.exceptions import UnsatisfiableError
from pyclingo.predicate import Predicate
from pyclingo.statistics import format_statistics_clingo_style

# Solution reconstruction is keyed by (name, arity): p/1 and p/2 are distinct
# predicates in ASP
type PredicateTypes = dict[tuple[str, int], type[Predicate]]


# The search generator's full mode range: None enumerates models, a
# RefinementMode refines consequences, OPTIMIZE descends a cost
type SearchMode = RefinementMode | Literal["optimize"] | None
OPTIMIZE: Literal["optimize"] = "optimize"


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

    def __init__(self, atoms: list[Predicate], hidden_classes: frozenset[type[Predicate]] = frozenset()) -> None:
        self._atoms = atoms
        # Classes whose atoms are never shown: asking for them teaches
        # instead of returning a silent [] (see _reject_hidden)
        self._hidden_classes = hidden_classes
        self._by_class: dict[type[Predicate], list[Predicate]] = {}
        for atom in atoms:
            self._by_class.setdefault(type(atom), []).append(atom)

    def _reject_hidden(self, predicate: type[Predicate]) -> None:
        """
        A hidden class's atoms are never read back into results — the shown
        set is what keeps model reads fast at scale (hundreds of thousands
        of helper atoms never get touched) — so asking for one is answered
        loudly, never with an [] that reads as "none were derived".
        """
        if predicate in self._hidden_classes:
            raise ValueError(
                f"{predicate.get_name()}/{predicate.get_arity()} is hidden "
                f"(show=False and never shown): hidden atoms are not read back "
                f"into results — skipping them is what keeps model reads fast. "
                f"show() the class, or define it with show=True, to read it."
            )

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
        atoms() with no argument returns everything. Asking for a HIDDEN
        class raises with the remedy: hidden atoms are never read back into
        results, so an empty answer would be a lie (see _reject_hidden).
        A class shown only through a show_when CONDITION returns just the
        condition-filtered atoms — a partial extension, by that directive's
        explicit intent.
        """
        if predicate is None:
            return list(self._atoms)
        if isinstance(predicate, Predicate):
            raise TypeError(
                f"atoms() takes a predicate class, got the atom {predicate.render()} — "
                f"pass the class {type(predicate).__name__} (a silent [] here would read "
                f"as an empty result)"
            )
        if not (isinstance(predicate, type) and issubclass(predicate, Predicate)):
            described = predicate.__name__ if isinstance(predicate, type) else type(predicate).__name__
            raise TypeError(f"atoms() takes a Predicate class, got {described}")
        self._reject_hidden(predicate)
        return list(self._by_class.get(predicate, []))

    def __iter__(self) -> Iterator[Predicate]:
        """Iterate all atoms — the same list atoms() returns."""
        return iter(self._atoms)

    def __contains__(self, atom: object) -> bool:
        """
        Whether this exact grounded atom is present: value equality, sign
        included. Anything that could never be present is rejected rather
        than quietly False.
        """
        if isinstance(atom, type) and issubclass(atom, Predicate):
            raise TypeError(
                f"Membership takes a grounded atom, got the class {atom.__name__} — "
                f"ask atoms({atom.__name__}) for its instances"
            )
        if not isinstance(atom, Predicate):
            raise TypeError(f"Membership takes a grounded atom, got {type(atom).__name__}")
        if not atom.is_grounded:
            raise ValueError(f"Membership takes a grounded atom, but {atom.render()} contains variables")
        self._reject_hidden(type(atom))
        return atom in self._by_class.get(type(atom), [])

    def __len__(self) -> int:
        return len(self._atoms)

    def _counts_str(self) -> str:
        return ", ".join(f"{cls.get_name()}: {len(atoms)}" for cls, atoms in self._by_class.items())

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._counts_str()})"


class Model(AtomCollection):
    """
    One answer set: the atoms clingo found true, as typed Predicate instances.

    (Clingo calls this a model; the paradigm's own name for it is an answer set.)
    """

    def __init__(
        self,
        atoms: list[Predicate],
        messages: Sequence[ClingoMessage] | None = None,
        hidden_classes: frozenset[type[Predicate]] = frozenset(),
    ) -> None:
        super().__init__(atoms, hidden_classes)
        # Diagnostics clingo emitted while searching for this model (usually empty).
        self.messages = tuple(messages) if messages is not None else ()


class CostedModel(Model):
    """
    An answer set found during an optimization search, carrying its cost
    and its certificate.

    cost has one entry per SURVIVING ground priority level, highest
    first (priorities are ordinal keys — gaps do not pad the tuple, and
    a declared tier whose elements ground empty is absent). A
    maximization's cost is reported negated: clasp minimizes the negated
    weights, so maximizing a total of 9 reads cost=(-9,). Lower is better
    at every level, in every sense.

    proven is the per-model certificate: True means clasp has PROVED this
    model optimal (only the all_optima re-enumeration emits such models —
    a plain descent's emissions are all unproven, even the one that turns
    out to be the optimum: the proof lands after the last emission).
    """

    def __init__(
        self,
        atoms: list[Predicate],
        cost: tuple[int, ...],
        proven: bool = False,
        messages: Sequence[ClingoMessage] | None = None,
        hidden_classes: frozenset[type[Predicate]] = frozenset(),
    ) -> None:
        super().__init__(atoms, messages, hidden_classes)
        self.cost = cost
        self.proven = proven

    def __repr__(self) -> str:
        return f"{type(self).__name__}(cost={list(self.cost)}, proven={self.proven}, {self._counts_str()})"


class Optimum(CostedModel):
    """
    The product of one optimization search: the best answer set found,
    its cost, and how it was reached.

    .path holds every emission in order — genuine answer sets, unlike
    consequence approximations, so an interrupted search's best is still
    a real solution. .proven means the search PROVED this model optimal;
    a timeout or iteration cap cutting the search short leaves
    proven=False, the anytime reading: "best found so far".

    .optima is every proven-optimal model when the search was asked for
    them (optimize(all_optima=True)), or None when it was not — the path
    is still available either way; a capped all_optima run cut before
    the proof holds optima=() (nothing certified yet — check .complete
    before reading uniqueness off len(optimum.optima) == 1). .complete means the search ran to full exhaustion: the
    optimality proof finished and, with all_optima, every optimum was
    enumerated (a timeout mid-enumeration leaves genuine certified
    optima with complete=False).
    """

    def __init__(
        self,
        atoms: list[Predicate],
        cost: tuple[int, ...],
        path: tuple[CostedModel, ...],
        proven: bool,
        messages: Sequence[ClingoMessage] | None = None,
        optima: tuple[CostedModel, ...] | None = None,
        complete: bool = False,
        levels: dict[int, int] | None = None,
        timed_out: bool = False,
        statistics: dict[str, Any] | None = None,
        hidden_classes: frozenset[type[Predicate]] = frozenset(),
    ) -> None:
        super().__init__(atoms, cost, proven, messages, hidden_classes)
        self.path = path
        self.optima = optima
        self.complete = complete
        # The search's statistics snapshot (see Search.statistics), carried
        # so the eager verb loses nothing its _iter twin exposes
        self.statistics = statistics
        # The cost keyed by its declared priorities: {priority: cost} over
        # the SURVIVING levels, so multi-tier costs read by name instead of
        # by position
        self.levels = levels if levels is not None else {}
        # Whether a wall-clock deadline cut the search short (one cause of
        # proven=False; an iteration cap is the other)
        self.timed_out = timed_out


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
        messages: Sequence[ClingoMessage],
        timed_out: bool = False,
        statistics: dict[str, Any] | None = None,
        hidden_classes: frozenset[type[Predicate]] = frozenset(),
    ) -> None:
        super().__init__(atoms, hidden_classes)
        self.path = path
        self.complete = complete
        self.messages = tuple(messages)
        # The search's statistics snapshot (see Search.statistics), carried
        # so the eager verb loses nothing its _iter twin exposes
        self.statistics = statistics
        # Whether a wall-clock deadline cut the refinement short (one cause
        # of complete=False; an iteration cap is the other)
        self.timed_out = timed_out


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
    timed_out: bool = False
    unsat_core: tuple[Predicate | DefaultNegation, ...] | None = None
    emission_count: int = 0
    statistics: dict[str, Any] | None = None
    finished: bool = False
    closed: bool = False
    messages: list[ClingoMessage] = field(default_factory=list)


class _ClosedCheckingIterator:
    """
    The iterator handed out by every search handle. A generator closed
    early can only raise StopIteration on resume — Python's protocol —
    which would make a PRE-HELD iterator read as "no more results", the
    exact silent-empty failure the consumed guard exists to prevent.
    This thin wrapper distinguishes natural exhaustion (StopIteration
    forever after, as iterators must) from early close (loud
    RuntimeError). Holds the generator and state only, never the handle:
    cycle-free.
    """

    __slots__ = ("_ended", "_generator", "_state")

    def __init__(self, generator: Generator[Any], state: _SearchState) -> None:
        self._generator = generator
        self._state = state
        self._ended = False

    def __iter__(self) -> _ClosedCheckingIterator:
        return self

    def __next__(self) -> Any:
        if self._state.closed and not self._ended:
            raise RuntimeError(
                "This search was closed; a held iterator does not quietly end (it would "
                "read as exhaustion). Start a fresh search."
            )
        try:
            return next(self._generator)
        except StopIteration:
            self._ended = True
            raise

    def close(self) -> None:
        self._generator.close()
        self._state.closed = True


class Search(ABC):
    """
    Shared lifecycle for one search on a Control: the iterate-once guard,
    close()/with teardown, and the flags the generator finalizes on every
    exit path. Subclasses say what the emissions MEAN — a SolveResult's
    are answer sets, a RefinementSteps' are approximations — by declaring
    their own __iter__ element type and exhausted semantics, and name the
    counters in their mode's vocabulary.
    """

    def __init__(
        self,
        control: clingo.Control,
        predicate_types: PredicateTypes,
        timeout: float,
        message_handler: ClingoMessageHandler,
        assumptions: list[tuple[clingo.Symbol, bool]] | None,
        mode: SearchMode,
        hidden_classes: frozenset[type[Predicate]] = frozenset(),
    ) -> None:
        """
        One constructor for every handle: builds the shared state and the
        mode's generator, clocking wall time from here. Subclasses fix the
        mode that defines them and add nothing else.
        """
        state = _SearchState()
        self._state = state
        self._iterator = _ClosedCheckingIterator(
            _search_generator(
                control,
                predicate_types,
                timeout,
                time.perf_counter(),
                state,
                message_handler,
                assumptions or [],
                mode=mode,
                hidden_classes=hidden_classes,
            ),
            state,
        )

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
        """
        Stop the search early; flags and statistics are finalized.

        Only a SUSPENDED search can be closed: if this handle is being
        iterated right now (in another thread), this raises with the
        remedies instead of leaking the raw generator error.
        """
        try:
            self._iterator.close()
        except ValueError as e:
            # generator.close() on an executing generator
            raise RuntimeError(
                f"Only a suspended search can be stopped, but this "
                f"{type(self).__name__} is executing right now (in another "
                f"thread). Interrupt it with .control.interrupt(), or give "
                f"the solve a timeout."
            ) from e
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
    def timed_out(self) -> bool:
        """
        Whether the wall-clock deadline ended this search early. Complements
        exhausted: a quietly-stopped stream (models in hand) reads False /
        False on exhausted/timed_out when closed early by the CALLER, and
        False / True when the deadline did it.
        """
        return self._state.timed_out

    @property
    def unsat_core(self) -> tuple[Predicate | DefaultNegation, ...] | None:
        """
        The assumptions clasp reports as jointly unsatisfiable, in the
        shapes they were given (an atom assumed true, ~atom assumed
        false) — available once this search has PROVEN unsatisfiability.
        None before then and for satisfiable programs; () when UNSAT
        needed no assumptions at all. This is A core, not necessarily a
        minimal one: clasp promises it contains a conflict, nothing more.
        """
        return self._state.unsat_core

    @property
    def satisfiable(self) -> bool | None:
        """True/False once known; None if nothing has been learned yet."""
        return self._state.satisfiable

    @property
    def messages(self) -> tuple[ClingoMessage, ...]:
        """
        Diagnostics clingo emitted during the solve phase (after grounding),
        as an immutable snapshot — the records (Model, Consequences,
        Optimum) carry the same shape.

        These never halt solving — the stop_on_log_level threshold applies
        to parsing and grounding only.
        """
        return tuple(self._state.messages)

    @property
    def statistics(self) -> dict[str, Any] | None:
        """
        Raw clingo statistics plus 'wall_time' (a copy — mutate freely), or
        None if solving never ran.

        wall_time spans this handle's creation to the end of iteration — it
        includes any time the caller spends between emissions, and excludes
        rendering and grounding. clingo's own solving clocks live under
        summary.times.
        """
        return None if self._state.statistics is None else copy.deepcopy(self._state.statistics)

    def format_statistics(self) -> str:
        """The search's statistics in clingo's native output style."""
        if self._state.statistics is None:
            return "No statistics available"
        return format_statistics_clingo_style(self._state.statistics)


class SolveResult(Search):
    """
    The handle for one solve: iterate it to receive Models lazily.

    'satisfiable', 'exhausted', and 'models_yielded' update as models arrive
    and are finalized when iteration ends on any path — exhaustion, close(),
    or leaving a with-block. Statistics are available after solving finishes.
    Each call to ASPProgram.solve() returns an independent SolveResult, so
    repeated solves never interfere. Each Model carries the message slice
    that arrived while it was being found.

    A timeout with models in hand quietly ends iteration (exhausted stays
    False; every yielded model was a true answer); a timeout before ANY
    model raises TimeoutError — a silent empty stream would read as
    unsatisfiable.
    """

    def __init__(
        self,
        control: clingo.Control,
        predicate_types: PredicateTypes,
        timeout: float,
        message_handler: ClingoMessageHandler,
        assumptions: list[tuple[clingo.Symbol, bool]] | None = None,
        hidden_classes: frozenset[type[Predicate]] = frozenset(),
    ) -> None:
        super().__init__(
            control, predicate_types, timeout, message_handler, assumptions, mode=None, hidden_classes=hidden_classes
        )

    @property
    def exhausted(self) -> bool:
        """Whether the search space was fully explored."""
        return self._state.exhausted

    @property
    def models_yielded(self) -> int:
        """Models yielded so far."""
        return self._state.emission_count

    def __iter__(self) -> Iterator[Model]:
        self._guard_consumed("call solve() again for a fresh search")
        # mode=None (enumeration) makes every emission a Model; the generator
        # is typed by the shared element type, so this cast is the one honest seam
        return cast(Iterator[Model], self._iterator)

    def first(self) -> Model:
        """
        The first model, closing the search: the one-answer sugar for
        programs expected to be satisfiable. Raises UnsatisfiableError
        when there is no model; if UNSAT is an expected outcome for your
        program, use next(iter(result), None), which gives None instead
        of raising. A stream that has already yielded models refuses —
        first() is not a cursor.
        """
        if self._state.emission_count:
            raise RuntimeError(
                f"first() refuses a stream that has already yielded "
                f"{self._state.emission_count} model(s): the next model is not 'the "
                f"first'. Keep the iterator you are holding, or call solve() again "
                f"for a fresh search."
            )
        for model in self:
            self.close()
            return model
        raise UnsatisfiableError(
            "first() found no model: the program is unsatisfiable. If UNSAT is "
            "an expected outcome here, use next(iter(result), None), which "
            "returns None when there is no model instead of raising."
        )


class RefinementSteps(Search):
    """
    The handle for one brave/cautious refinement, consumed step by step:
    iterate it to receive each successive approximation as a claim-free
    AtomCollection, and stop whenever your question is answered — each
    step is a full solver search, so control between steps is control
    over real work. Returned by cautious_iter()/
    brave_iter(); cautious() and brave() are the eager forms.

    Iteration ending naturally means the refinement completed: the last
    yielded approximation is the true intersection/union (zero yields
    means unsatisfiable), and .exhausted reports True. Breaking early
    leaves a partial approximation whose one-sided reading is described
    on the Consequences subclasses. A timeout raises TimeoutError from
    within iteration — a timed-out refinement must never impersonate a
    completed one by merely stopping.
    """

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


class OptimizeSteps(Search):
    """
    The handle for one optimization descent, consumed step by step:
    iterate it to receive each strictly-better answer set as a
    CostedModel. Every emission is a genuine solution — stopping early
    keeps the best found so far (the anytime workflow); .exhausted
    reports whether the optimum was PROVEN. Returned by optimize_iter();
    optimize() is the eager form.

    Each emission carries its certificate: a plain search's emissions are
    all proven=False (the optimality proof lands after the last one);
    under optimize_iter(all_optima=True) the stream continues past the
    proof and re-emits every optimal model with proven=True — including
    the descent's own final model, which therefore appears twice (once
    uncertified, once certified). Filter on .proven to consume each
    optimum exactly once.

    A timeout with models in hand quietly ends iteration with .exhausted
    False: unlike a refinement approximation, the last emission is a real
    solution, so no exception is needed to disown it. A timeout BEFORE
    any model raises TimeoutError — with nothing usable in hand, a quiet
    stop would read as unsatisfiable. Zero emissions ending naturally
    mean genuinely unsatisfiable.
    """

    def __init__(
        self,
        control: clingo.Control,
        predicate_types: PredicateTypes,
        timeout: float,
        message_handler: ClingoMessageHandler,
        assumptions: list[tuple[clingo.Symbol, bool]] | None = None,
        hidden_classes: frozenset[type[Predicate]] = frozenset(),
    ) -> None:
        super().__init__(
            control,
            predicate_types,
            timeout,
            message_handler,
            assumptions,
            mode=OPTIMIZE,
            hidden_classes=hidden_classes,
        )

    @property
    def exhausted(self) -> bool:
        """Whether the search PROVED the last emission optimal."""
        return self._state.exhausted

    @property
    def models_yielded(self) -> int:
        """Models yielded so far, each strictly better than the one before."""
        return self._state.emission_count

    def __iter__(self) -> Iterator[CostedModel]:
        self._guard_consumed("call optimize_iter() again to restart")
        return cast(Iterator[CostedModel], self._iterator)


def _search_generator(
    control: clingo.Control,
    predicate_types: PredicateTypes,
    timeout: float,
    tic: float,
    state: _SearchState,
    message_handler: ClingoMessageHandler,
    assumptions: list[tuple[clingo.Symbol, bool]],
    mode: SearchMode,
    hidden_classes: frozenset[type[Predicate]] = frozenset(),
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
    refining = isinstance(mode, RefinementMode)
    optimizing = mode == OPTIMIZE
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
                    if optimizing and not model.cost:
                        # Only reachable by constructing OptimizeSteps by hand
                        # around a non-optimizing control: there is no cost
                        # to descend
                        raise ValueError(
                            "optimize_iter() needs an optimizing program (the model carries no cost); "
                            "add minimize()/maximize() to the program."
                        )
                    if model.cost and not optimizing:
                        # Variation point: costs are illegal outside optimize
                        # mode. Refinement would aggregate the cost-descent
                        # path, not the optima; enumeration would stream one
                        # improving chain as if it were distinct solutions.
                        # Unreachable through the API (detection is observer
                        # ground truth); guards hand-constructed handles.
                        if refining:
                            raise ValueError(
                                f"{mode} consequences over an optimizing program (#minimize/#maximize "
                                f"present) are computed against the solver's cost-descent path, not "
                                f"the set of optimal models — the result would be wrong. Remove the "
                                f"optimization directive to ask about all answer sets."
                            )
                        raise ValueError("This program optimizes (the model carries a cost). Solve it with optimize().")
                    state.emission_count += 1
                    state.satisfiable = True
                    new_messages = message_handler.messages[messages_seen:]
                    messages_seen = len(message_handler.messages)
                    state.messages.extend(new_messages)
                    atoms = [
                        convert_symbol_to_predicate(symbol, predicate_types) for symbol in model.symbols(shown=True)
                    ]
                    # Variation point: an enumeration emission is an answer
                    # set, a refinement emission a claim-free approximation,
                    # a descent emission an answer set carrying its cost
                    if refining:
                        yield AtomCollection(atoms, hidden_classes)
                    elif optimizing:
                        yield CostedModel(
                            atoms,
                            cost=tuple(model.cost),
                            proven=model.optimality_proven,
                            messages=new_messages,
                            hidden_classes=hidden_classes,
                        )
                    else:
                        yield Model(atoms, messages=new_messages, hidden_classes=hidden_classes)
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
                state.timed_out = timed_out
                if outcome.satisfiable is False:
                    # The culprits, in the shapes the caller gave: clasp's
                    # core is solver literals, mapped back through the
                    # assumption list (a core, not necessarily minimal)
                    core = set(handle.core())
                    conflicting: list[Predicate | DefaultNegation] = []
                    for symbol, truth in assumptions:
                        symbolic = control.symbolic_atoms[symbol]
                        assert symbolic is not None  # existence-checked at conversion
                        if (symbolic.literal if truth else -symbolic.literal) in core:
                            atom = convert_symbol_to_predicate(symbol, predicate_types)
                            conflicting.append(atom if truth else DefaultNegation(atom))
                    state.unsat_core = tuple(conflicting)
                final = outcome
    except BaseException:
        # A generator dead from an exception can only StopIteration on
        # resume, which a retained iterator would read as clean exhaustion —
        # the silent-empty misread the closed flag exists to make loud (the
        # timeout terminals below do the same). GeneratorExit lands here
        # too, harmlessly: close() already sets the flag it re-sets.
        state.closed = True
        raise
    finally:
        # Finalize FIRST, publish LAST: the sequential guard reads
        # `finished` as "fully finalized", so flipping it before the
        # message tail and the statistics snapshot would admit a racing
        # second solve mid-finalization — concurrent native statistics
        # access, and the tail messages lost to (or stolen from) the new
        # solve's message-window reset. The inner finally guarantees the
        # flag still publishes if the snapshot itself raises.
        try:
            # Messages after the last emission (exhaustion proof, cancellation)
            state.messages.extend(message_handler.messages[messages_seen:])
            if final is not None:
                # Skipped if the handle was closed before solving began. clingo
                # raises if statistics are not ready; none is better than raising.
                with suppress(RuntimeError):
                    statistics = dict(control.statistics)
                    statistics["wall_time"] = time.perf_counter() - tic
                    state.statistics = statistics
        finally:
            state.finished = True
    if timed_out and refining:
        # Variation point: a timed-out enumeration flags and stops (each
        # yielded model was already a true answer), but a timed-out
        # refinement must raise — merely stopping would impersonate a
        # completed one. Closing first keeps a retained iterator loud: a
        # generator dead from an exception can only StopIteration on
        # resume, which would read as clean exhaustion.
        state.closed = True
        if state.emission_count == 0:
            raise TimeoutError(
                f"{mode} refinement did not finish within {timeout}s, before its first "
                f"approximation — nothing usable is in hand."
            )
        raise TimeoutError(
            f"{mode} refinement did not finish within {timeout}s; approximations yielded "
            f"so far form a {'superset' if mode is RefinementMode.CAUTIOUS else 'subset'} "
            f"bound on the true answer, not the answer."
        )
    if timed_out and state.emission_count == 0:
        # One principle for every mode: a timeout is quiet while real
        # answers are in hand, loud when empty-handed — a silent empty
        # stream would read as unsatisfiable. Closed first, as above.
        state.closed = True
        raise TimeoutError(
            f"the search found no model within {timeout}s; an empty result would "
            f"read as unsatisfiable, and there is nothing usable to return. "
            f"Raise the timeout."
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
        elif isinstance(value, Supremum):
            arguments.append(clingo.Supremum)
        elif isinstance(value, Infimum):
            arguments.append(clingo.Infimum)
        elif isinstance(value, Predicate):
            arguments.append(convert_predicate_to_symbol(value, defined_constants))
        else:
            raise ValueError(
                f"Cannot convert {predicate.render()} to a symbol: field '{field_name}' holds "
                f"{type(value).__name__}. clingo evaluates arithmetic at grounding (with its own "
                f"semantics), so pass the computed value instead."
            )
    return clingo.Function(predicate.get_name(), arguments, positive=not predicate.negated)


def convert_symbol_to_predicate(symbol: clingo.Symbol, predicate_types: PredicateTypes) -> Predicate:
    """
    Convert a clingo model symbol back into a typed Predicate instance, recursively.

    Raises:
        ValueError: If the symbol's name/arity doesn't match any known predicate.
    """
    if symbol.type != clingo.SymbolType.Function or symbol.name == "":
        raise ValueError(
            f"Model contains non-predicate output {symbol}: raw #show term forms "
            f"(#show expr : condition) emit arbitrary terms, which pyclingo does not "
            f"model — show atoms instead."
        )
    pred_name = symbol.name
    key = (pred_name, len(symbol.arguments))

    if key not in predicate_types:
        raise ValueError(
            f"Unknown predicate type: {pred_name}/{len(symbol.arguments)}. If this atom is "
            f"produced by a raw_asp() block, declare its class via raw_asp(..., predicates=[...])."
        )

    pred_class = predicate_types[key]
    field_names = [f.name for f in pred_class.argument_fields()]

    kwargs: dict[str, Predicate | int | str | ExtremeConstant] = {}
    for i, (arg, field_name) in enumerate(zip(symbol.arguments, field_names, strict=True)):
        if arg.type == clingo.SymbolType.Number:
            kwargs[field_name] = arg.number
        elif arg.type == clingo.SymbolType.String:
            kwargs[field_name] = arg.string
        elif arg.type == clingo.SymbolType.Supremum:
            # #sup/#inf are clingo's greatest/least terms — usually the value
            # of a #min/#max over an EMPTY set (the min of nothing is #sup)
            kwargs[field_name] = SUP
        elif arg.type == clingo.SymbolType.Infimum:
            kwargs[field_name] = INF
        else:
            # Function is the last symbol type; tuples are its nameless form
            if arg.name == "":
                # A clingo tuple argument, not a #show term form: diagnose the
                # actual limitation instead of blaming the (real) atom around it
                raise ValueError(
                    f"Argument {i} of {pred_name} is the clingo tuple {arg}, which pyclingo "
                    f"does not model — wrap it in a named predicate (pair{arg} instead of {arg})."
                )
            # Recursively convert nested predicates; bare atoms are nullary predicates
            kwargs[field_name] = convert_symbol_to_predicate(arg, predicate_types)

    try:
        instance = pred_class(**kwargs)
    except (TypeError, ValueError) as e:
        # The solver produced a value pyclingo never validated on the way in
        # (raw_asp text or an @-function): name the atom and its class, not
        # just the failing field's construction rule. The original class is
        # kept — a type mismatch stays a TypeError.
        raise type(e)(
            f"Model atom {symbol} cannot be read back as {pred_class.__name__} "
            f"({pred_name}/{len(symbol.arguments)}): {e}"
        ) from e
    return -instance if symbol.negative else instance
