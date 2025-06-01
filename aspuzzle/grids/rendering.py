from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pyclingo import Predicate


class Color(Enum):
    """
    ANSI terminal colors for use in visualization.
    Each enum value directly maps to its ANSI color code.
    """

    # Standard colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Bright colors
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    # Reset
    RESET = "\033[0m"


class BgColor(Enum):
    """
    ANSI terminal background colors for use in visualization.
    Each enum value directly maps to its ANSI color code.
    """

    # Standard background colors
    BLACK = "\033[40m"
    RED = "\033[41m"
    GREEN = "\033[42m"
    YELLOW = "\033[43m"
    BLUE = "\033[44m"
    MAGENTA = "\033[45m"
    CYAN = "\033[46m"
    WHITE = "\033[47m"

    # Bright background colors
    BRIGHT_BLACK = "\033[100m"
    BRIGHT_RED = "\033[101m"
    BRIGHT_GREEN = "\033[102m"
    BRIGHT_YELLOW = "\033[103m"
    BRIGHT_BLUE = "\033[104m"
    BRIGHT_MAGENTA = "\033[105m"
    BRIGHT_CYAN = "\033[106m"
    BRIGHT_WHITE = "\033[107m"


def colorize(text: str, color: Color | None = None, background: BgColor | None = None) -> str:
    """
    Wrap text in ANSI color codes.

    Args:
        text: Text to colorize
        color: Foreground color
        background: Background color

    Returns:
        Colorized text string
    """
    if color is None and background is None:
        return text

    color_codes = []

    # Process foreground color
    if color is not None:
        color_codes.append(color.value)

    # Process background color
    if background is not None:
        color_codes.append(background.value)

    # Apply colors
    return "".join(color_codes) + text + Color.RESET.value if color_codes else text


@dataclass
class RenderItem:
    """
    Represents a single item to render in a grid cell.

    Attributes:
        loc: The location predicate
        symbol: The symbol to display (or None to preserve existing)
        color: The foreground color
        background: The background color
    """

    loc: Predicate
    symbol: str | None = None
    color: Color | None = None
    background: BgColor | None = None


@dataclass
class RenderSymbol:
    symbol: str
    color: Color | None = None
    bgcolor: BgColor | None = None
