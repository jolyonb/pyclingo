def read_grid(data: list[str], map_to_integers: bool = False) -> list[tuple[int, int, int | str]]:
    """
    Extract dimensions and clues from the input data, using 1-based indexing.

    Args:
        data: The input grid as a list of strings
        map_to_integers: If True, map all symbols to unique integers (1-indexed)

    Returns:
        A list of tuples (row, col, value), where value is a string if it's a character,
        or an int if it's a number (or if map_to_integers is True).
    """
    symbol_to_id = {}
    if map_to_integers:
        # First, collect all unique symbols
        unique_symbols = set()
        for row in data:
            for char in row:
                if char != ".":
                    unique_symbols.add(char)

        # Create mapping from symbols to integer IDs
        # First map numbers to themselves (if they exist)
        used_ids = set()

        # Map numeric symbols first
        for symbol in unique_symbols:
            if symbol.isdigit():
                id_num = int(symbol)
                symbol_to_id[symbol] = id_num
                used_ids.add(id_num)

        # Map non-numeric symbols to unused integers
        next_id = 1
        for symbol in sorted(unique_symbols):  # Sort for consistency
            if symbol not in symbol_to_id:
                while next_id in used_ids:
                    next_id += 1
                symbol_to_id[symbol] = next_id
                used_ids.add(next_id)
                next_id += 1

    clues = []
    for r, line in enumerate(data):
        for c, char in enumerate(line):
            if char != ".":
                if map_to_integers:
                    value = symbol_to_id[char]
                else:
                    value = int(char) if char.isdigit() else char
                clues.append((r + 1, c + 1, value))

    return clues
