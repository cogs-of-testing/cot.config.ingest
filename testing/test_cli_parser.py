"""The native parser, driven by the CLI forms the specs derive.

Rewritten for the rebuild: the parser no longer takes field names and types,
it registers ``CliForm``s (``docs/design/specs.md#cli-forms``). Conflicts
between two fields are judged by the spelling index at ``declare()``
(``testing/test_index.py``), not by the parser, so the warn and ignore modes
are gone with it. ``-o`` is the only override spelling (D1), and a string of
injected tokens is split by the manager, not the parser.
"""

from __future__ import annotations

from typing import Annotated

import pytest

from cot.config import (
    ConfigDeclarationError,
    ConfigManager,
    ConfigPart,
    ConfigUsageError,
    short,
)
from cot.config._parser import ArgumentParser, ParseResult
from cot.config._specs import field_specs


class App(ConfigPart):
    config_file: str | None = None
    log_level: str = "WARNING"
    verbose: Annotated[bool, short("v")] = False
    exitfirst: Annotated[bool, short("x")] = False
    jobs: Annotated[int, short("j")] = 1


def parse(*tokens: str) -> ParseResult:
    parser = ArgumentParser()
    parser.register(field_specs(App))
    return parser.parse(tokens)


def values(result: ParseResult) -> dict[str, object]:
    return {o.spec.flat: o.raw for o in result.occurrences}


class TestBasicParsing:
    def test_long_option_with_value(self) -> None:
        result = parse("--config-file", "test.toml")

        assert values(result) == {"config_file": "test.toml"}
        assert result.unknown == []

    def test_long_option_equals_form(self) -> None:
        assert values(parse("--log-level=DEBUG")) == {"log_level": "DEBUG"}

    def test_boolean_flag(self) -> None:
        assert values(parse("--verbose")) == {"verbose": True}

    def test_boolean_negative_form(self) -> None:
        """Every boolean has a --no- form, so a file's true is reachable (D2)."""
        assert values(parse("--no-verbose")) == {"verbose": False}

    def test_boolean_with_explicit_value_keeps_the_value(self) -> None:
        """``--flag=false`` is a value to convert, never mere presence (I8)."""
        assert values(parse("--verbose=false")) == {"verbose": "false"}

    def test_unknown_args_passed_through(self) -> None:
        result = parse("--log-level", "DEBUG", "--unknown", "file.py")

        assert values(result) == {"log_level": "DEBUG"}
        assert result.unknown == ["--unknown", "file.py"]

    def test_value_is_consumed_unconditionally(self) -> None:
        """``--jobs -5`` works, which a startswith("-") guard made impossible."""
        assert values(parse("--jobs", "-5")) == {"jobs": "-5"}

    def test_missing_value_names_the_option(self) -> None:
        with pytest.raises(ConfigUsageError, match="--log-level"):
            parse("--log-level")


class TestShortOptions:
    def test_short_boolean_flag(self) -> None:
        assert values(parse("-v")) == {"verbose": True}

    def test_short_option_with_value(self) -> None:
        assert values(parse("-j", "4")) == {"jobs": "4"}

    def test_short_option_with_attached_value(self) -> None:
        assert values(parse("-j4")) == {"jobs": "4"}

    def test_combined_short_flags(self) -> None:
        assert values(parse("-vx")) == {"verbose": True, "exitfirst": True}

    def test_unknown_short_option(self) -> None:
        result = parse("-z")

        assert values(result) == {}
        assert result.unknown == ["-z"]


class TestReservedShorts:
    def test_reserved_short_option_is_a_declaration_error(self) -> None:
        """``-o`` belongs to overrides; claiming it is caught at declare()."""

        class Clash(ConfigPart):
            output: Annotated[str, short("o")] = ""

        with pytest.raises(ConfigDeclarationError, match="-o"):
            ConfigManager().declare(Clash)


class TestOverrides:
    def test_override_simple(self) -> None:
        assert parse("-o", "log_level=DEBUG").overrides == [("log_level", "DEBUG")]

    def test_multiple_overrides(self) -> None:
        result = parse("-o", "log_level=DEBUG", "-o", "verbose=true")

        assert result.overrides == [("log_level", "DEBUG"), ("verbose", "true")]

    def test_override_without_equals_raises(self) -> None:
        with pytest.raises(ConfigUsageError, match="key=value"):
            parse("-o", "log_level")


class TestHelp:
    def test_help_is_reported_not_acted_on(self) -> None:
        assert parse("--help").help_requested is True
        assert parse("-h").help_requested is True
        assert parse().help_requested is False
