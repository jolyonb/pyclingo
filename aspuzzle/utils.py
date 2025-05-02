def read_grid(data: list[str]) -> list[tuple[int, int, int | str]]:
    """
    Extract dimensions and clues from the input data, using 1-based indexing.

    Args:
        data: The input grid as a string

    Returns:
        A list of tuples (row, col, value), where value is a string if it's a character, or an int if it's a number.
    """
    clues = []
    for r, line in enumerate(data):
        for c, char in enumerate(line):
            if char != ".":
                value = int(char) if char.isdigit() else char
                clues.append((r + 1, c + 1, value))

    return clues
