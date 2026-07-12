# ASPAlchemy

Copyright Jolyon Bloomfield 2025-2026

`aspalchemy` is a Python library for building and solving clingo ASP (Answer Set Programming) programs with a clean, 
object-oriented interface: constraints are expressed as typed Python objects, rendered to ASP, solved via the clingo 
API, and reconstructed back into typed Python values.

The package documentation (term hierarchy, usage examples) lives in [`docs/README.md`](docs/README.md), which is also 
the PyPI readme.

For examples leveraging ASPAlchemy to solve logic puzzles, see the [`aspuzzle`](https://github.com/jolyonb/aspuzzle) 
repository, a framework built on top of this library.

## Development

```bash
uv sync
uv run pytest                        # unit suite + doctests
uv run pre-commit run --all-files    # lint, typecheck, tests with 100% coverage gate
```
