from typing import Union, TypeVar, overload

T = TypeVar("T", int, str)


@overload
def read_grid(
    data: str, convert_to_int: bool = True
) -> tuple[int, int, list[tuple[int, int, int]]]: ...


@overload
def read_grid(
    data: str, convert_to_int: bool = False
) -> tuple[int, int, list[tuple[int, int, str]]]: ...


def read_grid(
    data: str, convert_to_int: bool = True
) -> Union[
    tuple[int, int, list[tuple[int, int, int]]],
    tuple[int, int, list[tuple[int, int, str]]],
]:
    """
    Extract dimensions and clues from the input data.

    Args:
        data: The input grid as a string
        convert_to_int: Whether to convert characters to integers (default: True)

    Returns:
        A tuple containing (rows, cols, clues), where clues is a list of tuples (row, col, value).
        If convert_to_int is True, value will be an int; otherwise, it will be a str.
    """
    data = data.strip()
    lines = data.splitlines()
    rows = len(lines)
    cols = len(lines[0])
    clues = []

    for r, line in enumerate(lines):
        for c, char in enumerate(line):
            if char != ".":
                value = int(char) if convert_to_int else char
                clues.append((r, c, value))

    return rows, cols, clues
