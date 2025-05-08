# PyCLingo

PyCLingo is a Python library for building clingo ASP (Answer Set Programming) programs with a clean, object-oriented interface.

## Term Hierarchy

The library is built around a rich hierarchy of term types that represent different ASP constructs:

- `Term` (abstract base class)
  - `BasicTerm` (abstract, can be direct predicate arguments)
    - `Value` (abstract, for basic values)
      - `Variable` (e.g., `X`, `Y`)
      - `ConstantBase` (abstract)
        - `Constant` (numeric constants, e.g., `42`)
        - `StringConstant` (string literals, e.g., `"hello"`)
        - `SymbolicConstant` (symbolic constants, e.g., `max_size`)
    - `Predicate` (e.g., `person(john, 42)`)
    - `Pool` (abstract)
      - `RangePool` (e.g., `1..5`)
      - `ExplicitPool` (e.g., `(1;3;5)`)
  - `Expression` (arithmetic expressions, e.g., `X+Y*2`)
  - `Comparison` (comparisons, e.g., `X < Y`)
  - `NegatedLiteral` (abstract)
    - `DefaultNegation` (default negation, e.g., `not p(X)`)
    - `ClassicalNegation` (classical negation, e.g., `-p(X)`)
  - `ConditionalLiteral` (e.g., `p(X) : q(X)`)
  - `Aggregate` (abstract)
    - `Count`, `Sum`, `SumPlus`, `Min`, `Max`
  - `Choice` (e.g., `{ p(X) : q(X) }`)

## Core Concepts

### Values

Values represent basic elements in an ASP program:

```python
from pyclingo import Variable, Constant, StringConstant

X = Variable("X")
age = Constant(42)
name = StringConstant("john")
```

### Predicates

Create predicates for your domain:

```python
from pyclingo import Predicate

# Define with class
Person = Predicate.define("person", ["name", "age"])

# Create instances
john = Person(name="john", age=30)
mary = Person(name="mary", age=25)
```

### Rules

Build rules with clear syntax:

```python
from pyclingo import ASPProgram

program = ASPProgram()

# Facts
program.fact(john)
program.fact(mary)

# Rules
program.when(Person(name=X, age=Y), Older(person=X))

# Constraints
program.forbid(Person(name=X), Person(name=X, age=Y), Y < 0)
```

### Comparisons

Compare terms:

```python
X < Y  # Creates a comparison X < Y
```

### Aggregates

Use aggregates for advanced computations:

```python
from pyclingo import Count, Variable

X = Variable("X")
count = Count(X, Person(name=X)) > 5
```

### Solving

Solve your ASP program:

```python
# Generate ASP code
asp_code = program.render()
print(asp_code)

# Solve
for model in program.solve(models=0):  # 0 means find all models
    print("Solution found:")
    for pred_type, instances in model.items():
        for instance in instances:
            print(f"  {instance}")
```

## Requirements

- Python 3.11+
- clingo 5.8+

## License

MIT License
