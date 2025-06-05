# aspuzzle/

The aspuzzle module is a framework for building logic puzzle solvers using Answer Set Programming (ASP). It provides a high-level, modular architecture for defining puzzles and their constraints.

## Core Architecture

### puzzle.py
The central module containing the core framework classes:

- **`Puzzle`** - Main class that coordinates modules and manages the ASP program
  - Manages modules and their rules to create a complete ASP program
  - Provides methods like `fact()`, `when()`, `forbid()`, `solve()`, `render()`
  - Handles symbolic constants and constraint generation
  - Includes `count_constraint()` for complex counting constraints

- **`Module`** - Base class for puzzle components
  - Provides organization and domain-specific logic for puzzle components
  - Each module has its own namespace in the ASP program
  - Auto-registers with puzzle and provides scoped methods (`fact()`, `when()`, `forbid()`)
  - `finalize()` method called before rendering for any last-minute rule generation

- **`@cached_predicate`** - Decorator for caching predicate definitions
  - Ensures predicate initialization logic executes only on first access
  - Used extensively in grid and solver modules for performance

### regionconstructor.py
A specialized `Module` for constructing regions in grid-based puzzles:

- **`RegionConstructor`** - Handles both fixed-anchor and dynamic-anchor region construction
  - Fixed anchors: predefined cells anchor regions (e.g., Nurikabe numbered cells)
  - Dynamic anchors: flexible anchor placement (e.g., Fillomino)
  - Supports various constraints: contiguous regions, non-adjacent regions, size limits
  - Provides predicates: `Region`, `Anchor`, `Connected`, `RegionSize`, `Regionless`
  - Handles complex rules like rectangular regions and pool forbidding

### symbolset.py
A `Module` for managing symbols that can be placed in grid cells:

- **`SymbolSet`** - Manages placement of symbols into grid cells
  - Supports simple symbols and range symbols (from pools)
  - Choice rules with configurable cardinality (`fill_all_squares`)
  - Exclusion mechanism for cells where symbols cannot be placed
  - `make_contiguous()` method to enforce contiguity for specific symbols
  - Automatic integration with grid borders and excluded cells

## Key Features

1. **Modular Design**: Each puzzle component is a separate module with its own namespace
2. **Flexible Constraints**: Rich constraint language including counting, exclusions, and contiguity
3. **Grid Integration**: Seamless integration with various grid types through abstract interfaces
4. **Performance Optimized**: Cached predicates and efficient rule generation
5. **Extensible**: Easy to add new modules and extend existing functionality
