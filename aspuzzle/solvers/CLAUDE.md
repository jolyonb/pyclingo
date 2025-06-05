# aspuzzle/solvers/

This module contains concrete puzzle solver implementations built on the aspuzzle framework. Each solver implements a specific logic puzzle type and demonstrates different usage patterns of the framework.

## Core Solver Framework

### base.py
Abstract base class for all puzzle solvers:

- **`Solver`** - Abstract base class for puzzle implementations
  - **Factory Method**: `from_config()` - Dynamically loads solver classes based on puzzle_type
  - **Lifecycle**: `__init__()` → `create_grid()` → `validate()` → `construct_puzzle()` → `solve()`
  - **Grid Integration**: Automatically creates appropriate grid type from config
  - **Validation**: Symbol validation, config validation, solution validation
  - **Rendering**: ASCII visualization with customizable symbols and colors
  - **Solution Processing**: JSON output, statistics, and multiple solution handling

- **Key Methods:**
  - `construct_puzzle()` - Abstract method where puzzle rules are defined
  - `get_render_config()` - Returns rendering configuration for ASCII output
  - `validate_config()` - Custom validation logic per solver
  - `solve()` - Executes the ASP solver and returns results
  - `display_results()` - Formatted output with optional visualization

## Solver Categories

### Number Placement Puzzles
Logic puzzles focused on placing numbers in grids:

- **Sudoku** - Classic number placement with row, column, and block constraints
- **Minesweeper** - Mine placement based on adjacent count clues

### Region-Based Puzzles
Puzzles involving area division and region construction:

- **Fillomino** - Dynamic regions where region size determines cell numbers
- **Nurikabe** - Fixed islands in a continuous stream
- **Galaxies** - Point-symmetric regions around galaxy centers
- **Starbattle** - Star placement within irregular regions
- **Cave** - Connected cave area with line-of-sight counting

### Path and Connection Puzzles
Puzzles involving connections and paths:

- **Numberlink** - Connect numbered endpoints with non-crossing paths
- **Slitherlink** - Inside/outside regions based on boundary constraints
- **Stitches** - Connect adjacent regions with limited stitches

### Logic Grid Puzzles
Binary logic puzzles with additional constraints:

- **Hitori** - Shade cells to eliminate duplicates while maintaining connectivity
- **Tents** - Place tents next to trees with adjacency and counting constraints

## Common Patterns

### Configuration-Based Construction
All solvers follow consistent patterns:
```python
class MySolver(Solver):
    solver_name = "My Puzzle Type"
    supported_symbols = [1, 2, 3, ".", "X"]  # Valid input symbols
    default_config = {"param": default_value}
    
    def construct_puzzle(self):
        puzzle, grid, config, grid_data = self.unpack_data()
        # Define puzzle rules here
```

### Module Integration
Solvers extensively use framework modules:
- `SymbolSet` for symbol placement with choices and exclusions
- `RegionConstructor` for area-based puzzles
- Grid predicates for adjacency and geometric constraints

### Rendering Customization
Each solver provides puzzle-specific visualization:
- Symbol mapping for input clues
- Color schemes for different elements
- Custom renderers for complex visualizations
- Priority-based layered rendering

## Framework Features Demonstrated

1. **Dynamic Loading**: Solvers are loaded by name from configuration
2. **Modular Architecture**: Each solver composes framework modules differently
3. **Flexible Constraints**: Rich constraint language (counting, exclusions, contiguity)
4. **Grid Abstraction**: Works with different grid types transparently
5. **Validation Pipeline**: Input validation, solution validation, statistics
6. **Extensible Rendering**: Customizable ASCII output with colors and symbols

## Adding New Solvers

This directory is under active development. To add a new solver:

1. Create `newsolver.py` implementing the `Solver` abstract class
2. Define `construct_puzzle()` with puzzle-specific rules
3. Set appropriate `solver_name`, `supported_symbols`, and `default_config`
4. Implement `get_render_config()` for visualization
5. The solver will be automatically discoverable via `Solver.from_config()`

The framework handles all common functionality (parsing, validation, solving, rendering), allowing solver implementations to focus purely on puzzle logic and constraints.