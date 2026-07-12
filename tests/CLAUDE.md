# tests/

This directory contains the testing strategy for the ASPAlchemy project.

## Test Architecture

### Unit Testing (`tests/aspalchemy/`)
**Purpose**: Tests the aspalchemy library at 100% line coverage

Files are organized by construct (e.g. `test_choice.py`, `test_aggregates.py`,
`test_arithmetic.py`, `test_values.py`) and by cross-cutting concern (e.g.
`test_scoping.py`, `test_reconstruction.py`, `test_source_location.py`,
`test_optimization.py` / `test_optimize_solve.py`). `test_end_to_end.py` holds
the paved-path smoke tests: small complete programs run construct → render →
solve → typed reconstruction. Location-sensitive tests capture expected line
numbers at runtime (via `inspect`), never as literals.

## Running Tests

```bash
# Run all tests (unit suite + module doctests)
pytest

# Run a single file
pytest tests/aspalchemy/test_choice.py
```

## Adding Test Coverage

Add unit tests in `tests/aspalchemy/`, organized by construct or
cross-cutting concern as above. The 100% line-coverage gate means every new
library line needs an exercising test (genuinely unexecutable lines are
excluded centrally in `pyproject.toml`, never with scattered pragmas).

## Quality Control via Pre-commit

The project uses pre-commit hooks to maintain high code quality. Every commit automatically runs:

### Code Quality Checks (`.pre-commit-config.yaml`)
1. **ruff (linter)**: Fast Python linting with auto-fix (`--fix`)
2. **ruff (formatter)**: Consistent code formatting
3. **mypy**: Static type checking for type safety
4. **pyright**: Additional static type checking
5. **pytest (100% coverage gate)**: Runs the suite + module doctests and
   fails under 100% line coverage of `aspalchemy`
6. **config validation**: Ensures pre-commit setup stays valid

### Benefits
- **Automatic quality**: No manual intervention needed
- **Fast feedback**: Catches issues before they enter the codebase
- **Consistent style**: All code follows same formatting standards
- **Type safety**: Static analysis prevents common errors
- **Regression prevention**: Tests run on every commit

### Developer Workflow
```bash
# Install pre-commit (one-time setup)
pre-commit install

# Manual run (optional - hooks run automatically on commit)
pre-commit run --all-files

# Commit triggers all hooks automatically
git commit -m "Add new feature"
```

**Note**: If any hook fails, the commit is blocked until issues are resolved. This ensures the main branch always maintains high quality standards.
