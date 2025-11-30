"""
Tests for the CLI parser module.

These tests verify the CLIParser functionality including:
- Basic long option parsing
- Short option parsing
- Combined short options
- Conflict detection
- Override mechanism
"""

from __future__ import annotations

import warnings

import pytest

from cot.config._cli_parser import CLIConflictError, CLIParser


class TestBasicParsing:
    """Test basic CLI argument parsing."""

    def test_long_option_with_value(self) -> None:
        """Parse --key value form."""
        parser = CLIParser()
        parser.add_field("config_file", str)

        result = parser.parse(["--config-file", "test.toml"])

        assert result.values == {"config_file": "test.toml"}
        assert result.unknown_args == []

    def test_long_option_equals_form(self) -> None:
        """Parse --key=value form."""
        parser = CLIParser()
        parser.add_field("log_level", str)

        result = parser.parse(["--log-level=DEBUG"])

        assert result.values == {"log_level": "DEBUG"}

    def test_boolean_flag(self) -> None:
        """Parse --flag (boolean, no value)."""
        parser = CLIParser()
        parser.add_field("verbose", bool)

        result = parser.parse(["--verbose"])

        assert result.values == {"verbose": True}

    def test_unknown_args_passed_through(self) -> None:
        """Unknown arguments are collected."""
        parser = CLIParser()
        parser.add_field("config_file", str)

        result = parser.parse(["--config-file", "test.toml", "--unknown", "value"])

        assert result.values == {"config_file": "test.toml"}
        assert "--unknown" in result.unknown_args
        assert "value" in result.unknown_args


class TestShortOptions:
    """Test short option parsing."""

    def test_short_boolean_flag(self) -> None:
        """Parse -v (boolean flag)."""
        parser = CLIParser()
        parser.add_field("verbose", bool, short="v")

        result = parser.parse(["-v"])

        assert result.values == {"verbose": True}

    def test_short_option_with_value(self) -> None:
        """Parse -c value form."""
        parser = CLIParser()
        parser.add_field("config_file", str, short="c")

        result = parser.parse(["-c", "test.toml"])

        assert result.values == {"config_file": "test.toml"}

    def test_combined_short_flags(self) -> None:
        """Parse -vq (combined boolean flags)."""
        parser = CLIParser()
        parser.add_field("verbose", bool, short="v")
        parser.add_field("quiet", bool, short="q")

        result = parser.parse(["-vq"])

        assert result.values == {"verbose": True, "quiet": True}

    def test_short_and_long_both_work(self) -> None:
        """Both -v and --verbose set the same field."""
        parser = CLIParser()
        parser.add_field("verbose", bool, short="v")

        result1 = parser.parse(["-v"])
        result2 = parser.parse(["--verbose"])

        assert result1.values == {"verbose": True}
        assert result2.values == {"verbose": True}

    def test_unknown_short_option(self) -> None:
        """Unknown short options are collected."""
        parser = CLIParser()
        parser.add_field("verbose", bool, short="v")

        result = parser.parse(["-x"])

        assert result.values == {}
        assert "-x" in result.unknown_args


class TestConflictDetection:
    """Test conflict detection when registering fields."""

    def test_duplicate_field_name_raises(self) -> None:
        """Registering same field name twice raises error."""
        parser = CLIParser(on_conflict="error")
        parser.add_field("verbose", bool)

        with pytest.raises(CLIConflictError, match="already registered"):
            parser.add_field("verbose", bool)

    def test_duplicate_long_option_raises(self) -> None:
        """Registering conflicting long options raises error."""
        parser = CLIParser(on_conflict="error")
        parser.add_field("log_level", str)

        # log_level -> --log-level, so log-level (with underscore) would conflict
        with pytest.raises(CLIConflictError, match="already registered"):
            parser.add_field("log_level", str)

    def test_duplicate_short_option_raises(self) -> None:
        """Registering conflicting short options raises error."""
        parser = CLIParser(on_conflict="error")
        parser.add_field("verbose", bool, short="v")

        with pytest.raises(CLIConflictError, match="conflicts"):
            parser.add_field("version", bool, short="v")

    def test_reserved_short_option_raises(self) -> None:
        """Reserved short options raise error."""
        parser = CLIParser(on_conflict="error")

        with pytest.raises(CLIConflictError, match="reserved"):
            parser.add_field("output", str, short="o")

    def test_conflict_warn_mode(self) -> None:
        """In warn mode, conflicts emit warnings but don't raise."""
        parser = CLIParser(on_conflict="warn")
        parser.add_field("verbose", bool, short="v")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            parser.add_field("version", bool, short="v")

            assert len(w) == 1
            assert "conflicts" in str(w[0].message)

        # First field still works
        result = parser.parse(["-v"])
        assert result.values == {"verbose": True}

    def test_conflict_ignore_mode(self) -> None:
        """In ignore mode, conflicts are silently skipped."""
        parser = CLIParser(on_conflict="ignore")
        parser.add_field("verbose", bool, short="v")
        parser.add_field("version", bool, short="v")  # silently ignored

        # First field still works
        result = parser.parse(["-v"])
        assert result.values == {"verbose": True}


class TestOverrides:
    """Test -o/--override mechanism."""

    def test_override_simple(self) -> None:
        """Parse -o key=value."""
        parser = CLIParser()

        result = parser.parse(["-o", "log.level=DEBUG"])

        assert result.overrides == {"log.level": "DEBUG"}

    def test_override_long_form(self) -> None:
        """Parse --override key=value."""
        parser = CLIParser()

        result = parser.parse(["--override", "log.level=DEBUG"])

        assert result.overrides == {"log.level": "DEBUG"}

    def test_multiple_overrides(self) -> None:
        """Multiple -o options accumulate."""
        parser = CLIParser()

        result = parser.parse(["-o", "a=1", "-o", "b=2"])

        assert result.overrides == {"a": "1", "b": "2"}


class TestParseString:
    """Test parsing from string (like addopts)."""

    def test_parse_string_basic(self) -> None:
        """Parse a string of arguments."""
        parser = CLIParser()
        parser.add_field("verbose", bool, short="v")
        parser.add_field("tb", str)

        result = parser.parse_string("-v --tb=short")

        assert result.values == {"verbose": True, "tb": "short"}

    def test_parse_string_with_quotes(self) -> None:
        """Parse string with quoted values."""
        parser = CLIParser()
        parser.add_field("message", str)

        result = parser.parse_string('--message "hello world"')

        assert result.values == {"message": "hello world"}
