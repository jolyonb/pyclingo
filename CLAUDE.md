# ASPAlchemy: Python-to-ASP Translation Library

## Terminology

Do not call aspalchemy a "DSL" (in code, comments, docs, or conversation) — it
is a Python library that builds ASP programs. Describe it in those plain
terms.

## Mental Model

`aspalchemy` is an object-oriented Python interface for building and solving
clingo ASP (Answer Set Programming) programs:

```
High Level:  aspalchemy - Python-to-ASP translation layer (this repo)
Low Level:   clingo     - ASP solver engine
```

**Core Insight**: The library lets callers express logical constraints as
typed Python objects, renders them to ASP source, solves via the clingo API,
and reconstructs answer sets back into typed Python values.

The main consumer is `aspuzzle` (a logic puzzle solver framework in its own
repository, github.com/jolyonb/aspuzzle), which drives virtually every
construct in this library.

## Repo Layout

- `src/aspalchemy/` — the package. `src/aspalchemy/CLAUDE.md` documents the
  internals: the term hierarchy (Variable, Predicate, Expression, Choice,
  Aggregate, …), the program builder, and solver integration. The
  `ASPProgram` class coordinates everything.
- `tests/` — unit suite + module doctests; see `tests/CLAUDE.md`. Line
  coverage of `aspalchemy` is gated at 100%.
- `docs/` — user-facing documentation: `docs/README.md` (the PyPI readme)
  and `docs/MATH.md`. Their python code blocks are executed by
  `tests/aspalchemy/test_readme.py` to keep them runnable.
- `pyproject.toml` — packaging (uv_build, src layout), strict mypy/pyright,
  ruff.
- `.pre-commit-config.yaml` — the full quality gauntlet (see below).

## Tooling

```bash
uv sync                              # install environment
uv run pytest                        # unit suite + doctests
uv run pre-commit run --all-files    # ruff lint+format, mypy, pyright,
                                     # pytest with the 100% coverage gate
```

Every commit must pass the whole gauntlet. The coverage gate is a hard
policy: genuinely unexecutable lines are excluded centrally in
`[tool.coverage.report]` (never with scattered pragmas).

## Debugging & Performance Workflow

### Inspecting what the solver actually sees
- `program.render()` — the generated ASP source
- `grounded.ground_text()` — readable ground rules after gringo
- `grounded.aspif()` — the exact solver input; the honest size measure,
  since pretty-printed text repeats shared aggregate elements

### Grounding explosion
Complex conditions can create enormous ground programs. Perform scaling
analysis on the grounding size as the problem grows: O(N²) in the number of
domain elements is okay, O(N³) is not. Mitigations:
- Replace multi-variable rules with aggregates: `#count{X : condition}`
- Use intermediate predicates to break complex conditions
- Minimize variables in rule bodies

### Fast iteration
Render the program once, then test rule modifications directly with clingo
(`python -m clingo program.pl -n 0`) — much faster than round-tripping
through Python.
