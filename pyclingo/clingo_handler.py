from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum

import clingo


class LogLevel(IntEnum):
    """Log levels for Clingo messages."""

    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50

    @classmethod
    def from_string(cls, level_str: str) -> LogLevel:
        """Convert Clingo's string levels to our enum."""
        mapping = {
            "debug": cls.DEBUG,
            "info": cls.INFO,
            "warning": cls.WARNING,
            "error": cls.ERROR,
            "critical": cls.CRITICAL,
        }
        return mapping.get(level_str.lower(), cls.INFO)


@dataclass
class ClingoMessage:
    """Represents a parsed Clingo warning/error message."""

    filename: str
    line: int
    code: clingo.MessageCode
    column_start: int
    column_end: int
    severity: str  # 'info', 'warning', 'error'
    message: str
    raw_message: str


class ClingoMessageHandler:
    """Handles capturing and formatting of Clingo messages."""

    def __init__(self, asp_source: str, stop_on_level: LogLevel = LogLevel.INFO):
        self.messages: list[ClingoMessage] = []
        self._asp_lines: list[str] = asp_source.splitlines()
        self.stop_on_level = stop_on_level
        self._highest_level: LogLevel | None = None

    def on_message(self, code: clingo.MessageCode, message: str) -> None:
        """Callback for Clingo messages."""
        if location_match := re.match(r"<(.+?)>:(\d+):(\d+)-(\d+):\s*(.+?):\s*(.+)", message):
            level = location_match[5]
            parsed_msg = ClingoMessage(
                filename=location_match[1],
                line=int(location_match[2]),
                code=code,
                column_start=int(location_match[3]),
                column_end=int(location_match[4]),
                severity=level,
                message=location_match[6],
                raw_message=message,
            )
            self.messages.append(parsed_msg)
        else:
            if level_match := re.match(r"^(\w+):\s*(.+)", message):
                level = level_match[1]
                message_text = level_match[2]
            else:
                level = "info"
                message_text = message

            self.messages.append(
                ClingoMessage(
                    filename="<unknown>",
                    line=0,
                    code=code,
                    column_start=0,
                    column_end=0,
                    severity=level,
                    message=message_text,
                    raw_message=message,
                )
            )

        # Update highest log level
        current_level = LogLevel.from_string(level)
        if self._highest_level is None or current_level > self._highest_level:
            self._highest_level = current_level

    @property
    def highest_level(self) -> LogLevel | None:
        """Get the highest log level encountered."""
        return self._highest_level

    @property
    def should_halt(self) -> bool:
        """Determine if execution should halt based on log levels."""
        if self._highest_level is None:
            return False
        return self._highest_level >= self.stop_on_level

    def format_message(self, msg: ClingoMessage) -> str:
        """Format a single message with context."""
        output = [
            f"{msg.severity.upper()}: {msg.message}",
            f"  at line {msg.line}, columns {msg.column_start}-{msg.column_end}",
            "",
            f"  in {msg.filename}",
        ]

        # Show the problematic line with context
        if 0 < msg.line <= len(self._asp_lines):
            # Show line before (if exists)
            if msg.line > 1:
                output.append(f"{msg.line - 1:4d} | {self._asp_lines[msg.line - 2]}")

            # Show the problematic line
            problem_line = self._asp_lines[msg.line - 1]
            output.append(f"{msg.line:4d} | {problem_line}")

            # Add the error pointer - single caret at the start position
            if msg.column_start > 0:
                # The column_start is 1-based, but we need 0-based for the string
                pointer_pos = msg.column_start - 1
                pointer = " " * pointer_pos + "^" * (msg.column_end - msg.column_start)
                output.append(f"       {pointer}")

        output.append("")
        return "\n".join(output)

    def format_all_messages(self, verb: str) -> str | None:
        """Format all captured messages."""
        if not self.messages:
            return None

        output = [
            "-" * 60,
            f"Found {len(self.messages)} message{'s' if len(self.messages) > 1 else ''} during {verb}:\n",
        ]
        for msg in self.messages:
            output.extend(
                [
                    self.format_message(msg),
                    "-" * 60,
                    "",
                ]
            )
        return "\n".join(output)
