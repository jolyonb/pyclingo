# PyClingo Library Reference

## Overview
PyClingo is a Python library for building Answer Set Programming (ASP) programs with a clean, object-oriented interface. It provides a high-level API for constructing ASP programs that can then be solved using the Clingo solver.

## Core Architecture

### Term Hierarchy
The library is built around a rich hierarchy of term types representing different ASP constructs:

```
Term (abstract base class)
├── BasicTerm (abstract, can be direct predicate arguments)
│   ├── Value (abstract, for basic values)
│   │   ├── Variable (e.g., X, Y)
│   │   └── ConstantBase (abstract)
│   │       ├── Constant (numeric constants, e.g., 42)
│   │       ├── StringConstant (string literals, e.g., "hello")
│   │       └── SymbolicConstant (symbolic constants, e.g., max_size)
│   ├── Predicate (e.g., person(john, 42))
│   └── Pool (abstract)
│       ├── RangePool (e.g., 1..5)
│       └── ExplicitPool (e.g., (1;3;5))
├── Expression (arithmetic expressions, e.g., X+Y*2)
├── Comparison (comparisons, e.g., X < Y)
├── NegatedLiteral (abstract)
│   ├── DefaultNegation (default negation, e.g., not p(X))
│   └── ClassicalNegation (classical negation, e.g., -p(X))
├── ConditionalLiteral (e.g., p(X) : q(X))
├── Aggregate (abstract)
│   ├── Count, Sum, SumPlus, Min, Max
└── Choice (e.g., { p(X) : q(X) })
```

## Key Modules

### 1. Values (`value.py`)
Fundamental data types for ASP programs:
- **Variable**: ASP variables (must start with uppercase or be '_')
- **Constant**: Numeric integer constants
- **StringConstant**: String literals with quotes
- **SymbolicConstant**: Named constants that must be registered with the program

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
- Classical negation support via `-predicate` syntax

Key methods:
- `get_name()`: Returns predicate name with namespace
- `get_arity()`: Returns number of arguments
- `with_namespace()`: Creates namespaced version
- `collect_predicates()`: Gathers all predicate classes used

### 3. Expressions (`expression.py`)
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

#### Negation (`negation.py`)
Two types of negation:
- **DefaultNegation**: `not p(X)` (negation as failure)
- **ClassicalNegation**: `-p(X)` (explicit falsity)
- Helper function `Not()` for default negation
- Automatic simplification of nested negations

#### Conditional Literals (`conditional_literal.py`)
Conditional structures: `p(X) : q(X)`
- Used in aggregates and choice rules
- Helper function `key_for_each_lock()` for intuitive construction

### 5. Collections (`pool.py`)
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
- **Symbolic constants**: `register_symbolic_constant()`
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

#### Comparison Mixin (`comparison_mixin.py`)
Provides comparison operators for Value, Expression, and Aggregate classes:
- Python operator overloading for comparisons
- Automatic Comparison object creation

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
