# PyClingo

PyClingo is a Python library for building clingo ASP (Answer Set Programming) programs with a clean, object-oriented interface.

## Term Hierarchy

The library is built around a rich hierarchy of term types that represent different ASP constructs:

- `Term` (abstract base class)
  - `ComparableTerm` (abstract: usable in comparisons; provides `==`, `!=`, `<`, `<=`, `>`, `>=`)
    - `Value` (abstract, for basic values — also a `BasicTerm`)
      - `Variable` (e.g., `X`, `Y`)
      - `ConstantBase` (abstract)
        - `Number` (numeric constants, e.g., `42`)
        - `String` (string literals, e.g., `"hello"`)
        - `DefinedConstant` (#const-defined constants, e.g., `max_size`)
    - `Expression` (arithmetic expressions, e.g., `X+Y*2`)
    - `Aggregate` (abstract)
      - `Count`, `Sum`, `SumPlus`, `Min`, `Max`
  - `BasicTerm` (abstract, can be direct predicate arguments: `Value`, `Predicate`, `Pool`)
    - `Predicate` (e.g., `person(john, 42)`)
    - `Pool` (abstract)
      - `RangePool` (e.g., `1..5`)
      - `ExplicitPool` (e.g., `(1;3;5)`)
  - `Comparison` (comparisons, e.g., `X < Y`)
  - `DefaultNegation` (default negation, e.g., `not p(X)`)
  - `ConditionalLiteral` (e.g., `p(X) : q(X)`)
  - `Choice` (e.g., `{ p(X) : q(X) }`)

## Core Concepts

### Values

Values represent basic elements in an ASP program. Plain Python literals coerce
automatically wherever terms are expected — an int becomes an ASP number, a str
becomes a quoted ASP string. Variables you construct by hand, and bare atoms
(the `n` in `direction(n)`) are zero-arity predicates:

```python
from pyclingo import Predicate, Variable

X = Variable("X")  # an ASP variable
n = Predicate.define("n", [], show=False)()  # a bare atom: n, distinct from the string "n"
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
from pyclingo import ASPProgram, Variable

program = ASPProgram()
X, Y = Variable("X"), Variable("Y")
Adult = Predicate.define("adult", ["name"])

# Facts
program.fact(john)
program.fact(mary)

# Rules
program.when([Person(name=X, age=Y), Y >= 18], let=Adult(name=X))

# Constraints
program.forbid(Person(name=X, age=Y), Y < 0)
```

### Comparisons

Compare terms:

```python
X < Y  # Creates a comparison X < Y
```

### Aggregates

Use aggregates for advanced computations:

```python
from pyclingo import ANY, Count, Variable

X = Variable("X")
count = Count(X, Person(name=X, age=ANY)) > 5
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

- Python 3.14+
- clingo 5.8+

## License

MIT License
