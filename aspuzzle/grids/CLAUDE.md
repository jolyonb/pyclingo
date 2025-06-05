# aspuzzle/grids/

This module provides grid abstractions and utilities for grid-based puzzles. It defines the interface for different grid types and provides concrete implementations along with rendering utilities.

## Core Grid Framework

### base.py
Abstract base class and utilities for all grid types:

- **`Grid`** - Abstract base class defining the grid interface
  - Inherits from `Module`, so grids are puzzle modules with their own segments
  - Defines abstract properties: `cell_fields`, `direction_vectors`, `line_direction_names`
  - Provides cached predicates: `Cell`, `Direction`, `Orthogonal`, `VertexSharing`, `Line`
  - Abstract methods: `parse_grid()`, `add_vector_to_cell()`, `render_ascii()`
  - `find_anchor_cell()` utility for finding lexicographically minimum cells

- **Key Predicates Generated:**
  - `Cell` - Defines valid cells in the grid
  - `Direction` - Maps direction names to vector coordinates  
  - `Orthogonal` - Cells sharing an edge
  - `VertexSharing` - Cells sharing any vertex
  - `Line` - Major lines in the grid (rows, columns, etc.)
  - `OrderedLine` - Lines with position indexing

- **`do_not_show_outside()`** - Utility to hide predicates for outside border cells

### rectangulargrid.py
Concrete implementation for rectangular grids with rows and columns:

- **`RectangularGrid`** - Standard rectangular grid implementation
  - Uses 1-based indexing for rows and columns
  - Supports configurable dimensions via `from_config()`
  - 8-directional support (N, NE, E, SE, S, SW, W, NW)
  - Orthogonal directions: N, E, S, W
  - Line directions: E (rows), S (columns)

- **Grid Parsing:**
  - `parse_grid()` - Converts string/list grid data to structured format
  - Ignores "." characters as empty cells
  - Optional integer mapping for region-based puzzles
  - Validates grid dimensions

- **Constraint Utilities:**
  - `forbid_2x2_blocks()` - Prevents 2x2 blocks of a symbol
  - `forbid_checkerboard()` - Prevents disconnecting checkerboard patterns
  - Outside border support with `OutsideGrid` predicate

- **ASCII Rendering:**
  - `render_ascii()` - Converts grid to ASCII with colors and symbols
  - Priority-based rendering with multiple layers
  - Configurable cell joining and color support

## Rendering System

### rendering.py
Color and rendering utilities:

- **Color Enums:**
  - `Color` - ANSI foreground colors (standard + bright variants)
  - `BgColor` - ANSI background colors (standard + bright variants)
  - `colorize()` - Applies color codes to text

- **Rendering Data Classes:**
  - `RenderItem` - Single item to render (location, symbol, colors)
  - `RenderSymbol` - Symbol with color information

### region_coloring.py
Advanced region coloring using ASP and the Four Color Theorem:

- **`RegionColoring`** - Utility for coloring adjacent regions with different colors
  - Uses ASP to solve graph coloring problem
  - Ensures no adjacent regions share colors
  - Requires minimum 4 colors (Four Color Theorem)
  - Handles both region dictionaries and predicate instances

- **Convenience Functions:**
  - `assign_region_colors()` - Color regions from location lists
  - `assign_region_colors_from_predicates()` - Color from predicate instances
  - `DEFAULT_PALETTE` - Standard 5-color palette

## Key Features

1. **Extensible Architecture**: Abstract Grid class allows new grid types
2. **Rich Adjacency Support**: Orthogonal, vertex-sharing, and directional adjacency
3. **Flexible Parsing**: Handles various input formats with validation
4. **Advanced Rendering**: Multi-layer ASCII rendering with colors
5. **Constraint Helpers**: Common pattern prevention (pools, checkerboards)
6. **Automatic Coloring**: ASP-based region coloring for visualization
