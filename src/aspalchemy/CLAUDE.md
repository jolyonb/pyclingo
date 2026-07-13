# ASPAlchemy Library Reference

## Overview
ASPAlchemy is a Python library for building Answer Set Programming (ASP) programs with a clean, object-oriented interface. It provides a high-level API for constructing ASP programs that can then be solved using the Clingo solver.

## Core Architecture

### Term Hierarchy
The library is built around a rich hierarchy of term types representing different ASP constructs:

```
Term (abstract base class)
├── ComparableTerm (abstract: usable in comparisons; provides ==, !=, <, <=, >, >=)
│   ├── Value (abstract, for basic values — also a BasicTerm)
│   │   ├── Variable (e.g., X, Y)
│   │   └── ConstantBase (abstract)
│   │       ├── Number (numeric constants, e.g., 42)
│   │       ├── String (string literals, e.g., "hello")
│   │       └── DefinedConstant (#const-defined constants, e.g., max_size)
│   ├── Expression (arithmetic expressions, e.g., X+Y*2)
│   └── AggregateBase (abstract marker so core can recognize aggregates)
│       └── Aggregate (abstract)
│           └── Count, Sum, SumPlus, Min, Max
├── BasicTerm (abstract, can be direct predicate arguments: Value, Predicate, Pool)
│   ├── Predicate (e.g., person(john, 42))
│   └── Pool (abstract)
│       ├── RangePool (e.g., 1..5)
│       └── ExplicitPool (e.g., (1;3;5))
├── Negatable (abstract mixin: ~ builds "not term" on atoms/negations; on plain comparisons it builds the COMPLEMENT)
│   ├── Comparison (comparisons, e.g., X < Y)
│   └── DefaultNegation (default negation, e.g., not p(X))
├── ConditionalLiteral (e.g., p(X) : q(X))
└── Choice (e.g., { p(X) : q(X) })
```

## Module Layout

The mutually-recursive operator cluster (terms, values, pools, expressions,
comparisons) lives in a single module, `core.py` — construction and isinstance
checks need real classes, so this cluster cannot be split across modules without
deferred imports. Everything else imports downward from core; the import graph
is a DAG, enforced by tests/aspalchemy/test_architecture.py (which also bans
function-level intra-package imports).

## Key Modules

### 1. Values (`core.py`)
Fundamental data types for ASP programs:
- **Variable**: ASP variables (must start with uppercase or be '_')
- **Number**: Numeric integer constants
- **String**: String literals with quotes
- **DefinedConstant**: #const-defined names that must be declared via define_constant()

Bare atoms (the n in direction(n)) are zero-arity predicates — matching clingo's
own data model, where a symbolic constant IS a function of arity zero.

Key features:
- Variables support arithmetic operations (create Expression objects)
- Variables have `in_()` method for pool binding
- Constants are always grounded

### 2. Predicates (`predicate.py`)
Core building blocks for ASP facts and rules:
- **Predicate**: Base class using dataclass pattern
- Class-syntax declaration with statically checked fields; `Field[int]`,
  `Field[str]`, and `Field[SomePredicate]` annotations add per-field write
  validation and plain-Python typed reads (solution atoms return real
  ints/strs). Rule terms (Variables, Expressions) are always accepted on write.
- Dynamic predicate creation via `Predicate.define()`
- Support for namespacing
- Show directive management

Key methods:
- `get_name()`: Returns predicate name with namespace
- `get_arity()`: Returns number of arguments
- `collect_predicates()`: Gathers all predicate classes used

### 3. Expressions and Comparisons (`core.py`)
Arithmetic and comparison operations:
- **Expression**: Mathematical expressions with proper precedence
- **Comparison**: Relational and equality comparisons
- Support for Python operator overloading
- Automatic parentheses handling for complex expressions
- Type conversion for Python literals

Operators supported (Python operator -> rendered ASP):
- Arithmetic: `+`, `-`, `*`, `//` (renders `/`), `%` (renders `\`), `**`, `-` (unary), `|x|` via abs()
- Bitwise: `&`, `|` (renders `?`), `^`, `Compl(x)` (renders `~`; the `~` operator itself is reserved for default negation)
- Comparison: `==`, `!=`, `<`, `<=`, `>`, `>=`
- Power and bitwise renderings are deliberately over-parenthesized; classic
  arithmetic keeps minimal parentheses. Pinned against clingo evaluation in
  tests/aspalchemy/test_arithmetic.py.
- A negative RIGHT operand of a binary ADD/SUBTRACT is folded into the
  operator at construction (`X + (-1)` becomes `X - 1`, `X - (-Y)` becomes
  `X + Y`, repeated to a fixpoint) — the same normalize-at-construction
  policy as Not() on a plain comparison (see "Negation" below), so it is
  visible: `.operator` reports the normalized operator. Cosmetic only: both
  spellings are valid ASP (gringo parses a bare negative literal as a unit in
  every operator slot). Never applied to *, /, \, **, bitwise, the unary ops,
  or the left operand. The one exception is Number(-2147483648), whose
  negation is not a legal int32: it does not fold. The fold runs before
  _depth is computed, so MAX_DEPTH counts the operators actually rendered.

### 4. Logic Constructs

#### Choice Rules (`choice.py`)
ASP choice constructs with cardinality constraints:
- Basic choices: `{ p(X) : q(X) }`
- Cardinality: `2 { p(X) : q(X) } 4`
- Exact cardinality: `{ p(X) : q(X) } = 3`

Methods:
- `add()`: Add elements with conditions
- `exactly()`, `at_least()`, `at_most()`: Set cardinality constraints

#### Aggregates (`aggregates.py`)
Aggregate functions for ASP:
- **Count**: `#count{ X : p(X) }`
- **Sum/SumPlus**: `#sum{ W,X : p(X,W) }`
- **Min/Max**: `#min{ W,X : p(X,W) }`

All support multiple elements and conditions via `add()` method.

#### Negation (`core.py`)
- **DefaultNegation**: `not p(X)` (negation as failure), via `Not()` or `~`
- On atoms, a double negation is PRESERVED (not not p is not p's equivalent
  under stable-model semantics) and a triple collapses to a single
- On a PLAIN comparison, Not()/~ return the complementary comparison
  instead of wrapping — gringo's own normalization ("not X != Y" is the
  binding "X = Y"), performed at construction where it is visible (the
  same policy as the negative-addend fold in Expression, above);
  comparisons over aggregates keep the "not" wrapper (not
  complement-flippable), and DefaultNegation refuses plain comparisons
- Classical negation (`-p`): unary minus on a Predicate instance flips its
  sign — the sign is part of the atom, as in clingo's own symbol model. A
  negated predicate is just a predicate (same class, both signs in atoms());
  deriving p and -p together is UNSAT

#### Conditional Literals (`conditional_literal.py`)
Conditional structures: `p(X) : q(X)`
- Used directly in rule bodies and in show_when() (aggregates and choices
  build their own elements via add(); see ConditionedElement)
- Intuition: the head is a "key", the condition a "lock" — the literal
  holds when every lock has a matching key

### 5. Collections (`core.py`)
Collections of terms for ASP expansion:
- **RangePool**: Continuous ranges like `1..5`
- **ExplicitPool**: Explicit sets like `(1;3;5)`
- Helper function `pool()` for automatic type selection
- Support for Python ranges, lists, and tuples

### 6. Program Management

#### ASP Program (`solver.py`)
Main class for building and solving ASP programs:
- **Fact creation**: `fact()` method
- **Bare choice rules**: `choose()` method
- **Rule creation**: `when()` method
- **Constraint creation**: `forbid()` method
- **Comments and formatting**: `comment()`, `section()`, `blank_line()`
- **Defined constants**: `define_constant()`
- **Solving**: `solve()` returns a SolveResult (see below)

Key features:
- Segment-based organization
- Automatic show directive generation
- Comprehensive error handling
- Ground-program inspection: GroundedProgram.ground_text() (gringo's
  --text rendering) and .aspif() (the exact statement stream clasp
  receives) — generated on demand by an in-process re-ground through
  clingo's own application, stored @-function context included

#### Solve Results (`solve_result.py`)
- **Search**: the shared lifecycle for one search on a Control
  (close()/with, finished/satisfiable/messages/statistics); SolveResult,
  RefinementSteps, and OptimizeSteps are its three handles, all driven by
  the single _search_generator (mode-parameterized at three points:
  emission type, cost legality, timeout terminal).
- **SolveResult**: the handle returned by solve() — iterate it for Models;
  the stream is unbounded (consume what you need; islice/break are the
  limits). satisfiable/exhausted/models_yielded/statistics finalize when
  iteration ends on any path (exhaustion, close(), or a with-block).
- **RefinementSteps**: the handle returned by cautious_iter()/
  brave_iter() — iterate for successive approximations (claim-free
  AtomCollections); only the last is the true union/intersection; break
  whenever your question is answered. TimeoutError raised mid-iteration
  on deadline; zero yields = UNSAT.
- **AtomCollection**: the claim-free typed-atom reading surface —
  `atoms(Cls)` returns typed instances, `atoms()` returns everything.
  Subclasses say what their atoms mean:
- **Model**: one answer set (+ per-model .messages).
- **Consequences -> BraveConsequences/CautiousConsequences**: the eager
  answers from brave()/cautious(); carry .path (every approximation, the
  receipts) and .complete (a PROOF of exhaustion). Partials are one-sided:
  brave presence certified, cautious absence certified. None = UNSAT.

#### Program Elements (`program_elements.py`)
Building blocks for ASP programs:
- **Rule**: Complete ASP rules (facts, rules, constraints)
- **Comment**: Single-line and multi-line comments
- **BlankLine**: Formatting elements

### 7. Support Modules

#### Operators (`operators.py`)
Operator definitions and precedence rules:
- Mathematical operations with proper precedence
- Comparison operators
- Support for parentheses optimization in expressions

#### ComparableTerm (`core.py`)
Abstract base for Value, Expression, and Aggregate — the terms that may appear
in comparisons. Provides the comparison operators (which build Comparison terms)
and serves as the isinstance marker for comparison operands.

#### Statistics (`statistics.py`)
Formats a solve's raw statistics dict in clingo's native output style;
SolveResult.format_statistics() delegates here.

#### Error Handling (`clingo_handler.py`)
Comprehensive error message processing:
- **ClingoMessageHandler**: Captures and formats clingo messages
- **LogLevel**: Error severity levels
- Source code highlighting for errors
- Configurable stopping thresholds
- With a line-origins map (built by `ground()`), each diagnostic also names
  the Python line that authored the offending ASP line ("generated by
  file:line")

#### Source Locations (`source_location.py`)
Each statement is stamped with the user Python line that authored it
(`ASPProgram(source_locations=True)`, the default; the setting reaches
segments the program creates, while a Segment attached as-is keeps its own):
- **capture_location()** (public) walks the call stack outward and returns
  the first frame that is not plumbing. Frozen interpreter frames are never
  user code; a frame with a non-string `__name__` always is. Capture reads
  a few frame attributes and never touches source files; formatting waits
  until a diagnostic needs it.
- Plumbing is declared two ways: **register_skip_package(name)** takes a
  dotted module prefix — a framework registers itself wholesale ("myfw"), or
  just its plumbing modules ("myfw.core", "myfw.solvers.base") when its
  package also contains authored code that must keep its lines (e.g.
  framework core vs. per-puzzle solvers); helpers, lambdas, and
  comprehensions inside a registered prefix are all covered. Registration is
  process-wide and permanent ("__main__" is rejected — it is the user's own
  script). **@attribute_to_caller** marks one function — a user-level helper
  emitting rules on the caller's behalf; per code object (by identity), so
  lambdas defined inside are not covered.
- **location_override(loc)** attributes everything created in the block to a
  location captured earlier — for code emitting rules where no stack frame is
  the honest answer (e.g. a framework's finalize pass).
- `when()` captures its open site so a dangling when() reports where it was
  opened; a closer on a different line is recorded as `closed_at`.
- Consumers: the dangling-when() report; `render(annotate=True)` (a trailing
  "% file:line" comment on each statement line; line numbering matches the
  plain render, so the annotated text doubles as the reverse map — off by
  default so rendered output stays stable); the "generated by" note on
  grounding diagnostics, which lands even errors only gringo can catch
  (including inside raw_asp text) back on Python source; and freeze receipts
  on Choice/Aggregate (the mutation-after-capture error names the capturing
  rule's line — recorded unconditionally at freeze, independent of the
  program's source_locations switch).

## Copying, Pickling, and Identity

The identity story has three layers that must be understood TOGETHER —
each hook exists because of the others.

**The guarantee.** Values intern (a weak cache keyed by the CONVERTED
plain value; constructors are positional-only so keywords never reach the
cache), and Values hash by identity — so "equal live values are the same
object" is what makes sets and dicts of Values work at all, given that
`==` builds Comparison terms instead of comparing.

**Replace.** `copy.replace(atom, field=...)` preserves the classical-
negation sign: `Predicate.__replace__` re-applies it (the sign is not a
dataclass field, and dataclass() generates a shadowing fields-based
`__replace__` on every subclass, which `__init_subclass__` overwrites
back). `dataclasses.replace()` CANNOT be hooked — its reconstruction is
fields-based with no stdlib hook — and silently drops the sign: never
use it on atoms. Both behaviors are pinned, the wrong one as a canary
for a future stdlib change.

**Copy.** `__copy__`/`__deepcopy__` on Value AND Predicate return `self`:
both are immutable data, and a distinct copy would be equal-but-not-
identical to the cache resident, silently breaking set membership.
Because these hooks exist, `copy.copy`/`copy.deepcopy` NEVER consult the
pickle hooks below — copy and pickle are entirely separate paths. Two
knock-on effects, both deliberate:
- `Predicate.__neg__` hand-builds its field-sharing duplicate (it cannot
  use `copy.copy`, which now returns the original it must not mutate).
- `copy.deepcopy` works on atoms whose classes CANNOT pickle (see below):
  deepcopy of a program containing define()-built atoms is fine.

**Pickle, Values.** `Value.__reduce__` returns `(type(self),
tuple(self.__dict__.values()))` — "call the class with the stored value".
Unpickling therefore routes through the interning metaclass and lands on
the canonical cache resident: identity survives the round trip
(`pickle.loads(pickle.dumps(v)) is v` while v lives). Every concrete
Value stores exactly its one constructor argument, and Supremum/Infimum
store nothing (their `__new__` returns the singleton), so the same hook
covers all of them.

**Pickle, Predicates.** `Predicate.__reduce_ex__` gates on whether the
CLASS can be found by name on import (walk `sys.modules[cls.__module__]`
through `cls.__qualname__`):
- Findable (class-syntax predicates at module level): pickle proceeds by
  the default machinery. The instance `__dict__` carries the `_negated`
  sign and the field values; any Values inside re-intern through their
  own hook on load, so the loaded atom is sound.
- Not findable (classes built by `define()`/`in_namespace()` — their
  `__module__` names the caller, but no module attribute holds them):
  refuse with a teaching error (transport atoms as text via render()).
  The gate applies recursively: a findable atom holding a runtime-built
  atom in a field refuses too, when pickle reaches the nested atom.

All of this is pinned: `test_values.py` (interning, copy identity, pickle
re-interning), `test_predicate.py` (copy identity, negation-vs-copy, the
findability gate both ways, nested refusal, re-interned field values).

## Key Design Principles

1. **Type Safety**: Extensive use of type hints and runtime validation
2. **Immutability**: Values and Predicates are immutable (cached/frozen); Choice and Aggregate are mutable builders that freeze when a rule captures them — mutating one afterwards raises (naming the capturing rule's file:line) instead of silently rewriting the recorded rule. A frozen builder is a value: further rules may capture and share it. The Value cache interns weakly (dead values are evicted, racing constructors agree on one object under a lock, copy/deepcopy return the interned object), so equal-live-values-are-the-same-object holds under threads, copying, and long-running generation
3. **Composability**: Rich operator overloading for natural expression building
4. **Validation**: Context-aware validation for rule construction, at the
   line that built the rule. Unsafe-variable rejection is an
   over-approximating binding analysis (scoping.py) whose rejections are
   certain gringo rejections; singleton-variable rejection is a deliberate
   aspalchemy-only lint (gringo itself is silent about singletons)
5. **Error Reporting**: Detailed error messages with source context
6. **Performance**: Efficient rendering and minimal object creation

## Integration Points

- **Clingo Integration**: Native clingo solver integration via `clingo` library
- **Python Interop**: Automatic conversion between Python literals and ASP values
- **Extensibility**: Easy predicate definition and namespace management
- **Debugging**: Comprehensive statistics and error reporting

This library abstracts the complexity of ASP syntax while maintaining support for the most commonly used features of the language.
