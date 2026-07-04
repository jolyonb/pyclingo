# PyClingo Library Reference

## Overview
PyClingo is a Python library for building Answer Set Programming (ASP) programs with a clean, object-oriented interface. It provides a high-level API for constructing ASP programs that can then be solved using the Clingo solver.

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
│   │       ├── Symbol (plain symbolic terms, e.g., the n in direction(n))
│   │       └── DefinedConstant (#const-defined constants, e.g., max_size)
│   ├── Expression (arithmetic expressions, e.g., X+Y*2)
│   └── Aggregate (abstract)
│       └── Count, Sum, SumPlus, Min, Max
├── BasicTerm (abstract, can be direct predicate arguments: Value, Predicate, Pool)
│   ├── Predicate (e.g., person(john, 42))
│   └── Pool (abstract)
│       ├── RangePool (e.g., 1..5)
│       └── ExplicitPool (e.g., (1;3;5))
├── Comparison (comparisons, e.g., X < Y)
├── DefaultNegation (default negation, e.g., not p(X))
├── ConditionalLiteral (e.g., p(X) : q(X))
└── Choice (e.g., { p(X) : q(X) })
```

## Module Layout

The mutually-recursive operator cluster (terms, values, pools, expressions,
comparisons) lives in a single module, `core.py` — construction and isinstance
checks need real classes, so this cluster cannot be split across modules without
deferred imports. Everything else imports downward from core; the import graph
is a DAG, enforced by tests/pyclingo/test_architecture.py (which also bans
function-level intra-package imports).

## Key Modules

### 1. Values (`core.py`)
Fundamental data types for ASP programs:
- **Variable**: ASP variables (must start with uppercase or be '_')
- **Number**: Numeric integer constants
- **String**: String literals with quotes
- **Symbol**: Plain symbolic terms, unquoted (the n in direction(n))
- **DefinedConstant**: #const-defined names that must be declared via define_constant()

Key features:
- Variables support arithmetic operations (create Expression objects)
- Variables have `in_()` method for pool binding
- Constants are always grounded

### 2. Predicates (`predicate.py`)
Core building blocks for ASP facts and rules:
- **Predicate**: Base class using dataclass pattern
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

Operators supported:
- Arithmetic: `+`, `-`, `*`, `//` (integer division), `-` (unary), `|x|` (absolute)
- Comparison: `==`, `!=`, `<`, `<=`, `>`, `>=`

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
- **Count**: `#count{X : p(X)}`
- **Sum/SumPlus**: `#sum{W,X : p(X,W)}`
- **Min/Max**: `#min{W,X : p(X,W)}`

All support multiple elements and conditions via `add()` method.

#### Negation (`predicate.py`)
- **DefaultNegation**: `not p(X)` (negation as failure), via `Not()` or `~predicate`
- Automatic simplification of nested negations
- Classical negation (`-p`) is deliberately unsupported: model explicit falsity
  as a complementary predicate

#### Conditional Literals (`conditional_literal.py`)
Conditional structures: `p(X) : q(X)`
- Used in aggregates and choice rules
- Helper function `key_for_each_lock()` for intuitive construction

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
- **Rule creation**: `when()` method
- **Constraint creation**: `forbid()` method
- **Comments and formatting**: `comment()`, `section()`, `blank_line()`
- **Defined constants**: `define_constant()`
- **Solving**: `solve()` method with clingo integration

Key features:
- Segment-based organization
- Automatic show directive generation
- Comprehensive error handling
- Statistics formatting in clingo style

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

#### Error Handling (`clingo_handler.py`)
Comprehensive error message processing:
- **ClingoMessageHandler**: Captures and formats clingo messages
- **LogLevel**: Error severity levels
- Source code highlighting for errors
- Configurable stopping thresholds

#### Types (`types.py`)
Type aliases for better code clarity and type checking:
- Input type unions for predicates and expressions
- Field type definitions
- Conditional and choice type specifications

#### Utilities (`utils.py`)
Helper functions:
- `collect_variables()`: Gather variables from terms
- `create_unique_variable_name()`: Generate unique variable names

## Key Design Principles

1. **Type Safety**: Extensive use of type hints and runtime validation
2. **Immutability**: Most objects are frozen dataclasses or immutable
3. **Composability**: Rich operator overloading for natural expression building
4. **Validation**: Context-aware validation for rule construction
5. **Error Reporting**: Detailed error messages with source context
6. **Performance**: Efficient rendering and minimal object creation

## Integration Points

- **Clingo Integration**: Native clingo solver integration via `clingo` library
- **Python Interop**: Automatic conversion between Python literals and ASP values
- **Extensibility**: Easy predicate definition and namespace management
- **Debugging**: Comprehensive statistics and error reporting

This library abstracts the complexity of ASP syntax while maintaining support for the most commonly used features of the language.
