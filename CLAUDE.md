# PyClingo Project: Logic Puzzle Solver Framework

## Mental Model

This project implements a **layered architecture** for solving logic puzzles using Answer Set Programming (ASP):

```
High Level:  aspuzzle/     - Puzzle-specific solvers and framework
Middle Layer: pyclingo/    - Python-to-ASP translation layer  
Low Level:    clingo       - ASP solver engine
```

**Core Insight**: The project transforms high-level puzzle constraints (Python) into low-level logical constraints (ASP) that can be efficiently solved.

## Architecture Layers

### 1. PyClingo (`pyclingo/`)
**Purpose**: Object-oriented Python interface to ASP programming

- **Term System**: Rich hierarchy (Variable, Predicate, Expression, Choice, Aggregate)
- **Program Builder**: Constructs ASP programs with validation and type safety
- **Solver Integration**: Direct interface to clingo with error handling
- **Key Abstraction**: `ASPProgram` class coordinates everything

### 2. ASPuzzle Framework (`aspuzzle/`)
**Purpose**: Modular framework for puzzle-specific logic

- **Puzzle Class**: Orchestrates modules and manages ASP program lifecycle
- **Module System**: Composable components (Grid, RegionConstructor, SymbolSet)
- **Grid Abstraction**: Handles coordinate systems, adjacency, rendering
- **Key Insight**: Each puzzle type composes different modules differently

### 3. Solver Implementations (`aspuzzle/solvers/`)
**Purpose**: Concrete puzzle implementations

- **Base Solver**: Common patterns (config loading, validation, rendering)
- **Dynamic Loading**: Solvers discovered by name from configuration
- **Rendering System**: ASCII visualization with customizable symbols/colors
- **Key Pattern**: `construct_puzzle()` method defines puzzle-specific constraints

## Main Interface

### CLI Tool (`solver.py`)
**Purpose**: Command-line interface that orchestrates the entire solving pipeline

- **Configuration Loading**: Reads JSON puzzle files from `puzzles/` directory
- **Dynamic Solver Creation**: Uses `Solver.from_config()` to instantiate appropriate solver
- **ASP Generation**: Calls `construct_puzzle()` and renders complete ASP program
- **File Management**: Automatically saves generated ASP to `solver_scripts/[puzzle].pl`
- **Solving Pipeline**: Manages clingo execution with timeout/solution limits
- **Rich Output**: Provides puzzle preview, ASCII visualization, statistics, and validation

**Key Usage Patterns**:
```bash
# Basic solving with statistics
python solveit.py minesweeper --stats

# Render ASP program only (for debugging)
python solveit.py sudoku --render-only

# Performance testing with limits
python solveit.py fillomino --max-solutions 10 --timeout 30

# Quiet mode for automation
python solveit.py nurikabe --quiet --no-viz
```

**Optimization Workflow**: Use `solver.py` repeatedly with different rule implementations to compare performance:
1. Modify constraint logic in solver class
2. Run `python solver.py puzzle --stats` to get timing/grounding metrics
3. Compare statistics to identify optimal rule formulations
4. Check generated `.pl` files to verify rule efficiency

## Critical Design Patterns

### 1. Module Composition
```python
# Typical puzzle construction
puzzle = Puzzle()
grid = RectangularGrid(puzzle, rows=9, cols=9)
regions = RegionConstructor(puzzle, grid, ...)
symbols = SymbolSet(grid, ...)
# Each module adds its own constraints to the puzzle
```

### 2. Cached Predicates
```python
@property
@cached_predicate  # Only execute initialization once
def SomePredicate(self) -> type[Predicate]:
    # Heavy computation here
    return Predicate.define(...)
```

### 3. Constraint Patterns
```python
# Counting constraints
puzzle.count_constraint(count_over=X, condition=Y, exactly=N)

# Choice rules with cardinality
Choice(element=P(x), condition=Q(x)).exactly(1)

# Region connectivity via RegionConstructor
regions = RegionConstructor(..., contiguous_regionless=True)
```

## Extension Points

### Adding New Puzzle Types
1. **Create solver**: `aspuzzle/solvers/newpuzzle.py`
2. **Inherit from Solver**: Implement `construct_puzzle()` and `get_render_config()`
3. **Add rules**: `rules/newpuzzle.md`
4. **Add test cases**: `puzzles/newpuzzle.json`

### Adding New Grid Types
1. **Inherit from Grid**: Implement abstract methods in `aspuzzle/grids/`
2. **Define coordinate system**: `cell_fields`, `direction_vectors`
3. **Implement adjacency**: `add_vector_to_cell()`, `render_ascii()`

### Adding New Modules
1. **Inherit from Module**: Add to `aspuzzle/`
2. **Use cached predicates**: Define predicates with `@cached_predicate`
3. **Implement finalize()**: Add rules in `finalize()` method

### Complex Framework Extensions
For advanced modifications (new ASP constructs, non-rectangular grids, novel module types):

**Recommended Approach**: Work in partnership with the project author, using existing implementations as templates:
- **New ASP constructs**: Follow patterns in `pyclingo/` (e.g., `Choice`, `Aggregate` classes)
- **Alternative grid geometries**: Extend `Grid` base class, copy `RectangularGrid` structure
- **Novel module types**: Follow `RegionConstructor`/`SymbolSet` patterns for module organization

Given the project's maturity, these extensions are best accomplished by adapting proven templates rather than designing from scratch.

## Performance Considerations

### ASP Program Size
- **Grounding explosion**: Complex conditions can create enormous ground programs
- **Mitigation**: Look at the clingo output and perform scaling analysis on the grounding size; O(N^2) is okay (N number of cells), but O(N^3) is not
- **Debug**: Check generated `.pl` files in `solver_scripts/` for size

### Module Dependencies
- **Predicate access triggers rule generation**: First access to cached predicate defines all rules
- **Pattern**: Call `finalize()` to ensure all rules are generated

## Debugging Strategy

### 1. Validation Errors
- **Check input symbols**: `supported_symbols` in solver
- **Verify grid dimensions**: Config validation in solver
- **Examine constraints**: Look for overconstrained rules

### 2. No Solutions Found
- **Check generated ASP**: Look at `.pl` files in `solver_scripts/`
- **Remove constraints**: Comment out rules to find conflicting constraints
- **Use smaller instances**: Test with minimal puzzle size first

### 3. Performance Issues - Step-by-Step Debugging
When a puzzle solver is too slow, follow this systematic workflow:

**Step 1: Baseline Performance Check**
```bash
# Get timing statistics for your puzzle
python solveit.py puzzle --stats
```
- **Target**: 10×10 puzzle should solve in < 0.1s in most cases
- If significantly slower, investigate scaling issues

**Step 2: Scaling Analysis by Grid Size**
Test the same puzzle type with different grid sizes:
```bash
# Test different sizes if possible
python solveit.py small_puzzle --stats    # e.g., 5×5
python solveit.py medium_puzzle --stats   # e.g., 10×10  
python solveit.py large_puzzle --stats    # e.g., 15×15
```
- Compare solve times: should scale roughly O(N²) where N = number of cells
- If scaling > O(N²), you have grounding explosion

**Step 3: Analyze Predicate Scaling**
Look at the generated .pl file and analyze each predicate:
- Count variables per rule for each predicate type
- Rules with many variables create expensive grounding
- Example: `rule(X,Y,Z,W,V)` with 5 variables is much more expensive than `rule(X,Y)`

**Step 4: Direct ASP Testing (Rapid Iteration)**
For fast debugging without Python overhead:
```bash
# Generate ASP file once
python solveit.py puzzle --render-only
# Test modifications directly with clingo
python -m clingo solver_scripts/puzzle.pl -n 0
```
- Edit the .pl file directly to test rule modifications
- Much faster iteration cycle for constraint optimization

**Step 5: Constraint Optimization**
Focus on rules with poor scaling:
- Replace multi-variable rules with aggregates: `#count{X : condition}`
- Use intermediate predicates to break complex conditions
- Minimize variables in rule bodies
- Consider problem-specific optimizations

**Step 6: Verify Improvement**
```bash
python solveit.py puzzle --stats
```
- Confirm improved scaling with larger grid sizes
- Ensure solution correctness is maintained

### 4. Rendering Problems
- **Check render config**: Verify predicate names match solver output
- **Priority conflicts**: Higher priority items render on top
- **Color issues**: Ensure ANSI codes work in terminal

## File Organization Strategy

- **Generated files**: `solver_scripts/` - Never edit manually
- **Test data**: `puzzles/` - JSON configs with expected solutions
- **Documentation**: `rules/` - Human-readable puzzle rules
- **Core library**: `pyclingo/` - Stable, low-level ASP interface
- **Framework**: `aspuzzle/` - High-level, extensible puzzle framework
- **Implementations**: `aspuzzle/solvers/` - Growing collection of puzzle types

This architecture enables rapid development of new puzzle types while maintaining performance and correctness through the strong typing and validation provided by the PyClingo foundation.