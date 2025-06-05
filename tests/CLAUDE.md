# tests/

This directory contains the testing strategy for the PyClingo project, using a multi-layered approach to ensure correctness and prevent regressions.

## Test Architecture

### Integration Testing (`test_puzzles.py`)
**Purpose**: Validates that all puzzle solvers work correctly end-to-end

**How it works**:
- **Auto-discovery**: Finds all `.json` files in `puzzles/` directory using `get_puzzle_files()`
- **Parametrized testing**: Creates one test per puzzle file via `@pytest.mark.parametrize`
- **Complete pipeline**: For each puzzle, tests the full solving workflow:
  1. Load JSON configuration
  2. Create solver with `Solver.from_config()`
  3. Call `construct_puzzle()` and `solve()`
  4. Verify puzzle is satisfiable
  5. Test display/rendering code runs without errors
  6. If puzzle has `"solutions"` field, validate against expected results using `validate_solutions()`

**Key insight**: Any new puzzle added to `puzzles/` is automatically included in the test suite.

### Unit Testing (`pyclingo/`)
**Purpose**: Tests core PyClingo functionality in isolation

- `test_expression.py`: Tests arithmetic expression rendering, operator precedence, ASP syntax generation
- Future tests can be added for other PyClingo components (predicates, aggregates, etc.)

## Validation Strategy

The `puzzles/*.json` files serve dual purposes:
1. **Test cases** for automated regression testing
2. **Reference solutions** for development validation

Expected solution format in JSON:
```json
{
  "puzzle_type": "Sudoku",
  "grid": [...],
  "solutions": [
    {
      "predicate_name": ["predicate_instance_1", "predicate_instance_2", ...]
    }
  ]
}
```

## Running Tests

```bash
# Run all tests
pytest

# Run only puzzle integration tests
pytest tests/test_puzzles.py

# Run specific puzzle test
pytest tests/test_puzzles.py::test_puzzle_solves[minesweeper.json]

# Run with verbose output to see all puzzle names
pytest -v tests/test_puzzles.py

# Run PyClingo unit tests only
pytest tests/pyclingo/
```

## Adding Test Coverage

1. **New puzzle types**: Add `.json` file to `puzzles/` directory - automatically included in tests
2. **PyClingo components**: Add unit tests in `tests/pyclingo/`
3. **Framework validation**: Integration tests catch issues across the entire solver pipeline

## Quality Control via Pre-commit

The project uses pre-commit hooks to maintain high code quality. Every commit automatically runs:

### Code Quality Checks (`.pre-commit-config.yaml`)
1. **ruff (linter)**: Fast Python linting with auto-fix (`--fix`)
2. **ruff (formatter)**: Consistent code formatting
3. **mypy**: Static type checking for type safety
4. **pyright**: Additional static type checking (pinned to v1.1.400)
5. **pytest**: Runs full test suite (`tests/` directory)
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
git commit -m "Add new solver"
```

**Note**: If any hook fails, the commit is blocked until issues are resolved. This ensures the main branch always maintains high quality standards.

This comprehensive quality control system, combined with the testing strategy, ensures that framework changes don't break existing solvers while maintaining code quality and providing rapid feedback during development.