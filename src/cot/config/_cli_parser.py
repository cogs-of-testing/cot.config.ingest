"""Custom CLI argument parser tailored for configuration loading.

This module provides a simple, predictable CLI parser that:
- Supports dynamic field registration (add fields at any time)
- Re-parses cleanly when new fields are added or addopts prepended
- Handles --key=value and --key value forms
- Supports -v short options for fields
- Supports --flag for booleans (store_true style)
- Tracks unknown args for passthrough
- Supports -o key=value overrides for any config path
- Detects and reports conflicts when registering fields
"""

from __future__ import annotations

import shlex
import warnings
from dataclasses import dataclass, field
from typing import Any, get_origin


class CLIConflictError(Exception):
    """Raised when a CLI option conflicts with an existing registration."""

    pass


@dataclass
class FieldSpec:
    """Specification for a CLI field."""

    name: str  # Identity key (e.g., "log_cli_level")
    long_option: str  # Long CLI arg name (e.g., "log-cli-level")
    short_option: str | None  # Short option (e.g., "c"), without dash
    field_type: type[Any]  # The field's type annotation
    is_boolean: bool = False  # If True, --flag sets to True (no value needed)
    help: str | None = None  # Help text, rendered by format_help()
    repeatable: bool = False  # If True, every occurrence appends to a list


@dataclass
class ParseResult:
    """Result of parsing CLI arguments."""

    values: dict[str, Any] = field(default_factory=dict)
    overrides: dict[str, str] = field(default_factory=dict)  # -o key=value
    unknown_args: list[str] = field(default_factory=list)
    help_requested: bool = False  # -h / --help seen


class CLIParser:
    """
    Simple CLI argument parser for configuration.

    Unlike argparse, this parser:
    - Can have fields added dynamically at any time
    - Re-parses from scratch each time parse() is called
    - Has predictable, simple behavior
    - Detects conflicts when registering fields

    Supported argument forms:
    - --field-name value (two tokens)
    - --field-name=value (single token)
    - -f value (short option with value)
    - -f (short option for boolean, sets to True)
    - --boolean-flag (sets to True)
    - -o key=value or --override key=value (generic overrides)

    Example:
        parser = CLIParser()
        parser.add_field("verbose", bool, short="v")
        parser.add_field("config_file", str, short="c")

        result = parser.parse(["-v", "-c", "foo.toml"])
        # result.values = {"verbose": True, "config_file": "foo.toml"}
    """

    # Reserved short options that cannot be used by fields
    RESERVED_SHORT = frozenset({"o", "h"})  # -o for override, -h for help

    def __init__(self, *, on_conflict: str = "error") -> None:
        """
        Create a CLI parser.

        Args:
            on_conflict: What to do on field conflicts.
                "error" - raise CLIConflictError (default)
                "warn" - emit warning and skip the conflicting field
                "ignore" - silently skip the conflicting field
        """
        if on_conflict not in ("error", "warn", "ignore"):
            raise ValueError("on_conflict must be 'error', 'warn', or 'ignore'")
        self._on_conflict = on_conflict
        self._fields: dict[str, FieldSpec] = {}
        self._long_to_field: dict[str, str] = {}  # long-option -> field_name
        self._short_to_field: dict[str, str] = {}  # short (single char) -> field_name

    def add_field(
        self,
        name: str,
        field_type: type[Any],
        *,
        long_option: str | None = None,
        short: str | None = None,
        is_boolean: bool | None = None,
        help: str | None = None,
        repeatable: bool | None = None,
    ) -> None:
        """
        Register a field for CLI parsing.

        Args:
            name: Identity key for the field, used to key ParseResult.values
                (e.g., "log_cli_level")
            field_type: Type annotation for the field
            long_option: Long option spelling without dashes. Defaults to
                ``name`` with underscores turned into dashes.
            short: Short option character (e.g., "v" for -v). Optional.
            is_boolean: If True, treat as flag (--name sets True).
                       If None, auto-detect from field_type.
            help: Help text shown by format_help().
            repeatable: If True, each occurrence appends to a list.
                If None, auto-detect from field_type (list fields repeat).

        Raises:
            CLIConflictError: If field name or options conflict with existing
                registration (when on_conflict="error")
        """
        if long_option is None:
            long_option = name.replace("_", "-")

        # Check for conflicts
        conflict = self._check_conflicts(name, long_option, short)
        if conflict:
            if self._on_conflict == "error":
                raise CLIConflictError(conflict)
            elif self._on_conflict == "warn":
                warnings.warn(conflict, stacklevel=2)
            # In all non-error cases, skip registration
            return

        if is_boolean is None:
            is_boolean = field_type is bool
        if repeatable is None:
            repeatable = field_type is list or get_origin(field_type) is list

        spec = FieldSpec(
            name=name,
            long_option=long_option,
            short_option=short,
            field_type=field_type,
            is_boolean=is_boolean,
            help=help,
            repeatable=repeatable,
        )
        self._fields[name] = spec
        self._long_to_field[long_option] = name
        if short:
            self._short_to_field[short] = name

    def _check_conflicts(
        self, name: str, long_option: str, short: str | None
    ) -> str | None:
        """
        Check for conflicts with existing registrations.

        Returns conflict message if there's a conflict, None otherwise.
        """
        # Check field name
        if name in self._fields:
            return f"Field '{name}' is already registered"

        # Check long option
        if long_option in self._long_to_field:
            existing = self._long_to_field[long_option]
            return (
                f"Long option '--{long_option}' conflicts with "
                f"existing field '{existing}'"
            )

        # Check short option
        if short:
            if short in self.RESERVED_SHORT:
                return f"Short option '-{short}' is reserved"
            if short in self._short_to_field:
                existing = self._short_to_field[short]
                return (
                    f"Short option '-{short}' conflicts with "
                    f"existing field '{existing}'"
                )

        return None

    def parse(self, args: list[str]) -> ParseResult:
        """
        Parse CLI arguments.

        Args:
            args: List of CLI arguments

        Returns:
            ParseResult with values, overrides, and unknown args
        """
        result = ParseResult()
        i = 0

        while i < len(args):
            arg = args[i]

            # Handle -h / --help. This is a library: record the request and let
            # the application decide what to do with it. Never exit here.
            if arg in ("-h", "--help"):
                result.help_requested = True
                i += 1
                continue

            # Handle -o / --override
            if arg in ("-o", "--override"):
                if i + 1 < len(args):
                    override_value = args[i + 1]
                    if "=" in override_value:
                        key, value = override_value.split("=", 1)
                        result.overrides[key] = value
                    i += 2
                    continue
                else:
                    # -o without value, treat as unknown
                    result.unknown_args.append(arg)
                    i += 1
                    continue

            # Handle --key=value or --key value or --flag
            if arg.startswith("--"):
                i = self._parse_long_option(arg, args, i, result)

            # Handle short options like -v or -c value
            elif arg.startswith("-") and len(arg) == 2:
                i = self._parse_short_option(arg, args, i, result)

            # Handle combined short options like -vx (multiple flags)
            elif arg.startswith("-") and len(arg) > 2 and not arg[1].isdigit():
                i = self._parse_combined_short_options(arg, args, i, result)

            else:
                # Positional argument (unknown)
                result.unknown_args.append(arg)
                i += 1

        return result

    def _record(self, result: ParseResult, field_name: str, value: Any) -> None:
        """Store a parsed value, appending when the field is repeatable."""
        spec = self._fields[field_name]
        if spec.repeatable:
            existing = result.values.get(field_name)
            if isinstance(existing, list):
                existing.append(value)
            else:
                result.values[field_name] = [value]
        else:
            result.values[field_name] = value

    def _parse_long_option(
        self, arg: str, args: list[str], i: int, result: ParseResult
    ) -> int:
        """Parse a long option (--key or --key=value). Returns new index."""
        if "=" in arg:
            # --key=value form
            key_part, value = arg[2:].split("=", 1)
            field_name = self._long_to_field.get(key_part)
            if field_name is not None:
                self._record(result, field_name, value)
            else:
                result.unknown_args.append(arg)
            return i + 1
        else:
            # --key or --key value form
            key_part = arg[2:]
            field_name = self._long_to_field.get(key_part)

            if field_name is not None:
                spec = self._fields[field_name]
                if spec.is_boolean:
                    # Boolean flag - just presence sets True
                    result.values[field_name] = True
                    return i + 1
                else:
                    # Non-boolean - next arg is value
                    if i + 1 < len(args) and not args[i + 1].startswith("-"):
                        self._record(result, field_name, args[i + 1])
                        return i + 2
                    else:
                        # No value provided, skip
                        result.unknown_args.append(arg)
                        return i + 1
            else:
                # Unknown option
                result.unknown_args.append(arg)
                i += 1
                # If next arg doesn't start with -, it might be a value
                if i < len(args) and not args[i].startswith("-"):
                    result.unknown_args.append(args[i])
                    i += 1
                return i

    def _parse_short_option(
        self, arg: str, args: list[str], i: int, result: ParseResult
    ) -> int:
        """Parse a single short option (-v or -c value). Returns new index."""
        short_char = arg[1]
        field_name = self._short_to_field.get(short_char)

        if field_name is not None:
            spec = self._fields[field_name]
            if spec.is_boolean:
                # Boolean flag
                result.values[field_name] = True
                return i + 1
            else:
                # Non-boolean - next arg is value
                if i + 1 < len(args) and not args[i + 1].startswith("-"):
                    self._record(result, field_name, args[i + 1])
                    return i + 2
                else:
                    # No value provided
                    result.unknown_args.append(arg)
                    return i + 1
        else:
            # Unknown short option
            result.unknown_args.append(arg)
            return i + 1

    def format_help(self, *, prog: str | None = None) -> str:
        """Render the registered options as help text.

        Returns the text rather than printing or exiting -- this is a library,
        and the calling application owns the process.
        """
        lines: list[str] = []
        if prog:
            lines.append(f"usage: {prog} [options]")
            lines.append("")
        lines.append("options:")

        entries: list[tuple[str, str]] = [("-h, --help", "show this help")]
        for spec in sorted(self._fields.values(), key=lambda s: s.long_option):
            invocation = f"--{spec.long_option}"
            if spec.short_option:
                invocation = f"-{spec.short_option}, {invocation}"
            if not spec.is_boolean:
                invocation += " VALUE"
            entries.append((invocation, spec.help or ""))
        entries.append(("-o, --override KEY=VALUE", "set any config option"))

        width = max(len(invocation) for invocation, _ in entries)
        for invocation, text in entries:
            lines.append(f"  {invocation.ljust(width)}  {text}".rstrip())
        return "\n".join(lines) + "\n"

    def _parse_combined_short_options(
        self,
        arg: str,
        args: list[str],
        i: int,
        result: ParseResult,  # noqa: ARG002
    ) -> int:
        """Parse combined short options like -vx. Returns new index."""
        # Each character after - is a separate flag
        chars = arg[1:]
        all_known = True

        for char in chars:
            field_name = self._short_to_field.get(char)
            if field_name is not None:
                spec = self._fields[field_name]
                if spec.is_boolean:
                    result.values[field_name] = True
                else:
                    # Non-boolean in combined form is unusual
                    # Treat as unknown for safety
                    all_known = False
                    break
            else:
                all_known = False
                break

        if not all_known:
            result.unknown_args.append(arg)

        return i + 1

    def parse_string(self, args_string: str) -> ParseResult:
        """
        Parse a string of CLI arguments (like addopts).

        Args:
            args_string: String containing CLI args (e.g., "-v --tb=short")

        Returns:
            ParseResult
        """
        try:
            args = shlex.split(args_string)
        except ValueError:
            # Fallback to simple split if shlex fails
            args = args_string.split()
        return self.parse(args)

    @property
    def registered_fields(self) -> dict[str, FieldSpec]:
        """Get all registered field specifications."""
        return dict(self._fields)

    def get_field_by_short(self, short: str) -> FieldSpec | None:
        """Get field spec by short option character."""
        field_name = self._short_to_field.get(short)
        if field_name:
            return self._fields.get(field_name)
        return None

    def get_field_by_long(self, long_option: str) -> FieldSpec | None:
        """Get field spec by long option name."""
        field_name = self._long_to_field.get(long_option)
        if field_name:
            return self._fields.get(field_name)
        return None


__all__ = [
    "CLIParser",
    "CLIConflictError",
    "FieldSpec",
    "ParseResult",
]
