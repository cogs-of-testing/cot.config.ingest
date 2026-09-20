"""Tests for the reading-protocol sources in `cot.config._reading`.

Each source is driven directly: an index over some roots, the source's own
input, and the readings that come back. No manager, because the point of the
protocol is that a source needs one index and nothing else.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Annotated

import pytest

from cot.config import ConfigPart, ConfigUsageError, from_env, named, no_cli, short
from cot.config._annotations import counted, form, injected_args
from cot.config._index import SpellingIndex
from cot.config._precedence import Precedence
from cot.config._reading import (
    CLISource,
    ConfigFileDiscoverySource,
    EnvSource,
    IniSource,
    InjectedArgsSource,
    OverrideSource,
    TomlEnvSource,
    TomlSource,
    source_for_file,
)
from cot.config._store import Reading, Unmatched


class Cli(ConfigPart):
    level: str | None = None
    enabled: Annotated[bool, no_cli] = False


class Logging(ConfigPart, prefix="pytest", name_prefix="log"):
    level: str = "WARNING"
    retries: int = 0
    disable: Annotated[list[str], named("log_disable")] = []
    verbosity: Annotated[int, short("v"), counted] = 0
    maxfail: Annotated[int, form("--exitfirst", short="x", contributes=1)] = 0
    exposed: Annotated[str, from_env] = ""
    addopts: Annotated[str, injected_args] = ""
    cli: Cli


class Pool(ConfigPart):
    size: int = 5


class Bare(ConfigPart):
    """No prefix: its keys sit at the top level of a file."""

    host: str = "localhost"
    pool: Pool


@pytest.fixture
def index() -> SpellingIndex:
    built = SpellingIndex()
    built.add(Logging)
    built.add(Bare)
    return built


def values(readings: list[Reading | Unmatched]) -> dict[str, object]:
    return {".".join(r.path): r.raw for r in readings if isinstance(r, Reading)}


def unmatched(readings: list[Reading | Unmatched]) -> list[str]:
    return [r.spelling for r in readings if isinstance(r, Unmatched)]


def write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(dedent(body))
    return path


class TestTomlSource:
    def test_a_flat_key_in_the_section(
        self, tmp_path: Path, index: SpellingIndex
    ) -> None:
        path = write(
            tmp_path,
            "app.toml",
            """
            [pytest]
            log_level = "DEBUG"
        """,
        )
        assert values(list(TomlSource(path).read(index))) == {"level": "DEBUG"}

    def test_a_nested_table(self, tmp_path: Path, index: SpellingIndex) -> None:
        path = write(
            tmp_path,
            "app.toml",
            """
            [pytest.log.cli]
            level = "DEBUG"
        """,
        )
        assert values(list(TomlSource(path).read(index))) == {"cli.level": "DEBUG"}

    def test_both_spellings_in_one_file(
        self, tmp_path: Path, index: SpellingIndex
    ) -> None:
        path = write(
            tmp_path,
            "app.toml",
            """
            [pytest]
            log_level = "WARNING"
            [pytest.log.cli]
            level = "DEBUG"
        """,
        )
        assert values(list(TomlSource(path).read(index))) == {
            "level": "WARNING",
            "cli.level": "DEBUG",
        }

    def test_a_root_with_no_prefix_sits_at_the_top_level(
        self, tmp_path: Path, index: SpellingIndex
    ) -> None:
        path = write(
            tmp_path,
            "app.toml",
            """
            host = "db.internal"

            [pool]
            size = 9
        """,
        )
        assert values(list(TomlSource(path).read(index))) == {
            "host": "db.internal",
            "pool.size": 9,
        }

    def test_a_key_nobody_claims_comes_back_unmatched(
        self, tmp_path: Path, index: SpellingIndex
    ) -> None:
        path = write(
            tmp_path,
            "app.toml",
            """
            [pytest]
            log_levle = "DEBUG"
        """,
        )
        assert unmatched(list(TomlSource(path).read(index))) == ["pytest.log_levle"]

    def test_an_intermediate_depth_is_not_a_spelling(
        self, tmp_path: Path, index: SpellingIndex
    ) -> None:
        # [pytest.log] cli_level would mean both a table and a renamed leaf.
        path = write(
            tmp_path,
            "app.toml",
            """
            [pytest.log]
            cli_level = "DEBUG"
        """,
        )
        assert unmatched(list(TomlSource(path).read(index)))

    def test_values_keep_their_types(
        self, tmp_path: Path, index: SpellingIndex
    ) -> None:
        path = write(
            tmp_path,
            "app.toml",
            """
            [pytest]
            log_retries = 3
        """,
        )
        assert values(list(TomlSource(path).read(index))) == {"retries": 3}

    def test_a_file_that_is_not_there_says_nothing(
        self, tmp_path: Path, index: SpellingIndex
    ) -> None:
        assert list(TomlSource(tmp_path / "absent.toml").read(index)) == []

    def test_it_says_what_paths_are_relative_to(self, tmp_path: Path) -> None:
        assert TomlSource(tmp_path / "app.toml").base_dir == tmp_path


class TestIniSource:
    def test_it_reads_a_section(self, tmp_path: Path, index: SpellingIndex) -> None:
        path = write(
            tmp_path,
            "pytest.ini",
            """
            [pytest]
            log_level = DEBUG
        """,
        )
        readings = list(IniSource(path).read(index))
        assert values(readings) == {"level": "DEBUG"}

    def test_every_value_is_text(self, tmp_path: Path, index: SpellingIndex) -> None:
        path = write(
            tmp_path,
            "pytest.ini",
            """
            [pytest]
            log_retries = 3
        """,
        )
        assert values(list(IniSource(path).read(index))) == {"retries": "3"}
        assert IniSource(path).dialect == "string"


class TestTheSuffixTable:
    def test_each_known_suffix_has_a_reader(self, tmp_path: Path) -> None:
        assert isinstance(source_for_file(tmp_path / "a.toml"), TomlSource)
        assert isinstance(source_for_file(tmp_path / "a.ini"), IniSource)
        assert isinstance(source_for_file(tmp_path / "a.cfg"), IniSource)

    def test_an_unknown_suffix_names_the_path_and_what_is_known(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(ConfigUsageError, match="a.yaml"):
            source_for_file(tmp_path / "a.yaml")


class TestDiscovery:
    def test_the_nearest_file_is_read_last(
        self, tmp_path: Path, index: SpellingIndex
    ) -> None:
        far = tmp_path
        near = tmp_path / "project"
        near.mkdir()
        write(far, "pyproject.toml", '[pytest]\nlog_level = "FAR"\n')
        write(near, "pyproject.toml", '[pytest]\nlog_level = "NEAR"\n')

        source = ConfigFileDiscoverySource(invocation_dir=near)
        readings = [r for r in source.read(index) if isinstance(r, Reading)]
        assert [r.raw for r in readings] == ["FAR", "NEAR"]

    def test_discovery_is_one_source_at_one_rung(self, tmp_path: Path) -> None:
        # A chain of files needs no rung of its own; order is by depth instead.
        assert ConfigFileDiscoverySource(invocation_dir=tmp_path).precedence == (
            Precedence.FILE
        )


class TestEnvSource:
    def test_only_a_field_that_opted_in_is_read(self, index: SpellingIndex) -> None:
        environ = {"PYTEST_LOG_EXPOSED": "yes", "PYTEST_LOG_LEVEL": "DEBUG"}
        assert values(list(EnvSource(environ=environ).read(index))) == {
            "exposed": "yes"
        }

    def test_the_sources_prefix_goes_in_front(self, index: SpellingIndex) -> None:
        environ = {"APP_PYTEST_LOG_EXPOSED": "yes"}
        assert values(list(EnvSource("app", environ=environ).read(index))) == {
            "exposed": "yes"
        }

    def test_the_environment_is_never_judged_unknown(
        self, index: SpellingIndex
    ) -> None:
        # Every process inherits variables it did not choose; warning about
        # PATH would fire on correct configuration.
        environ = {"PATH": "/usr/bin", "HOME": "/home/x"}
        assert unmatched(list(EnvSource(environ=environ).read(index))) == []

    def test_values_are_text(self, index: SpellingIndex) -> None:
        assert EnvSource().dialect == "string"


class TestTomlEnvSource:
    def test_a_variable_can_carry_a_scalar(self, index: SpellingIndex) -> None:
        environ = {"PYTEST_LOG_EXPOSED": '"quoted"'}
        assert values(list(TomlEnvSource(environ=environ).read(index))) == {
            "exposed": "quoted"
        }

    def test_it_is_a_separate_source_rather_than_a_flag(self) -> None:
        # A source that delivers strings or native values depending on a
        # constructor argument leaves the dialect unanswerable.
        assert EnvSource().dialect == "string"
        assert TomlEnvSource().dialect == "typed"


class TestCLISource:
    def test_a_long_option(self, index: SpellingIndex) -> None:
        source = CLISource(args=["--log-level", "DEBUG"])
        assert values(list(source.read(index))) == {"level": "DEBUG"}

    def test_the_equals_form(self, index: SpellingIndex) -> None:
        source = CLISource(args=["--log-level=DEBUG"])
        assert values(list(source.read(index))) == {"level": "DEBUG"}

    def test_a_nested_option(self, index: SpellingIndex) -> None:
        source = CLISource(args=["--log-cli-level", "DEBUG"])
        assert values(list(source.read(index))) == {"cli.level": "DEBUG"}

    def test_a_no_cli_field_has_no_option(self, index: SpellingIndex) -> None:
        source = CLISource(args=["--log-cli-enabled"])
        readings = list(source.read(index))
        assert values(readings) == {}
        assert source.unknown == ["--log-cli-enabled"]

    def test_a_repeated_option_accumulates(self, index: SpellingIndex) -> None:
        source = CLISource(args=["--log-disable", "a", "--log-disable", "b"])
        assert values(list(source.read(index))) == {"disable": ["a", "b"]}

    def test_a_counted_option_is_summed(self, index: SpellingIndex) -> None:
        source = CLISource(args=["-v", "-v", "-v"])
        assert values(list(source.read(index))) == {"verbosity": "3"}

    def test_a_second_form_supplies_its_constant(self, index: SpellingIndex) -> None:
        assert values(list(CLISource(args=["-x"]).read(index))) == {"maxfail": 1}

    def test_a_value_may_look_like_an_option(self, index: SpellingIndex) -> None:
        # Unconditional consumption: without it, --log-level -5 is unreachable.
        source = CLISource(args=["--log-level", "-5"])
        assert values(list(source.read(index))) == {"level": "-5"}

    def test_a_missing_value_names_the_option(self, index: SpellingIndex) -> None:
        with pytest.raises(ConfigUsageError, match="--log-level"):
            list(CLISource(args=["--log-level"]).read(index))

    def test_unknown_tokens_are_left_for_the_host(self, index: SpellingIndex) -> None:
        source = CLISource(args=["tests/", "--log-level", "DEBUG", "-k", "x"])
        readings = list(source.read(index))
        assert values(readings) == {"level": "DEBUG"}
        assert unmatched(readings) == []
        assert "tests/" in source.unknown

    def test_help_is_reported_not_acted_on(self, index: SpellingIndex) -> None:
        source = CLISource(args=["--help"])
        list(source.read(index))
        assert source.help_requested is True

    def test_paths_are_relative_to_where_they_were_typed(self, tmp_path: Path) -> None:
        assert CLISource(args=[], invocation_dir=tmp_path).base_dir == tmp_path


class TestInjectedArgs:
    def test_contributions_are_parsed_as_tokens(self, index: SpellingIndex) -> None:
        source = InjectedArgsSource()
        source.contribute("pytest.ini[addopts]", ["--log-level", "DEBUG"])
        assert values(list(source.read(index))) == {"level": "DEBUG"}

    def test_a_reading_names_its_contributor(self, index: SpellingIndex) -> None:
        source = InjectedArgsSource()
        source.contribute("pytest.ini[addopts]", ["--log-level", "DEBUG"])
        reading = next(r for r in source.read(index) if isinstance(r, Reading))
        assert "pytest.ini[addopts]" in reading.location

    def test_it_sits_between_files_and_the_environment(self) -> None:
        assert Precedence.FILE < Precedence.INJECTED < Precedence.ENV
        assert InjectedArgsSource().precedence == Precedence.INJECTED

    def test_it_reports_as_injected_rather_than_as_typed(self) -> None:
        assert InjectedArgsSource().kind == "injected"


class TestOverrides:
    def test_a_pair_reaches_the_field_by_its_flat_name(
        self, index: SpellingIndex
    ) -> None:
        cli = CLISource(args=["-o", "log_cli_level=DEBUG"])
        list(cli.read(index))
        overrides = OverrideSource(sources=[cli])
        assert values(list(overrides.read(index))) == {"cli.level": "DEBUG"}

    def test_it_outranks_the_option_it_competes_with(
        self, index: SpellingIndex
    ) -> None:
        assert Precedence.CLI < Precedence.OVERRIDE
        assert OverrideSource().precedence == Precedence.OVERRIDE

    def test_one_carried_by_injected_arguments_lands_at_the_same_rung(
        self, index: SpellingIndex
    ) -> None:
        injected = InjectedArgsSource()
        injected.contribute("pytest.ini[addopts]", ["-o", "log_level=DEBUG"])
        list(injected.read(index))
        overrides = OverrideSource(sources=[injected])
        assert values(list(overrides.read(index))) == {"level": "DEBUG"}

    def test_a_key_addressing_nothing_comes_back_unmatched(
        self, index: SpellingIndex
    ) -> None:
        cli = CLISource(args=["-o", "nonsense=1"])
        list(cli.read(index))
        assert unmatched(list(OverrideSource(sources=[cli]).read(index))) == [
            "nonsense"
        ]

    def test_it_reports_as_an_override(self, index: SpellingIndex) -> None:
        cli = CLISource(args=["-o", "log_level=DEBUG"])
        list(cli.read(index))
        reading = next(
            r
            for r in OverrideSource(sources=[cli]).read(index)
            if isinstance(r, Reading)
        )
        assert reading.location == "-o log_level"
        assert OverrideSource().kind == "override"


class TestTheLadder:
    def test_the_rungs_are_in_the_documented_order(self) -> None:
        assert (
            Precedence.DEFAULTS
            < Precedence.FILE
            < Precedence.INJECTED
            < Precedence.ENV
            < Precedence.CLI
            < Precedence.OVERRIDE
            < Precedence.RUNTIME
        )

    def test_defaults_lose_to_a_source_declared_at_zero(self) -> None:
        assert Precedence.DEFAULTS < 0


class TestBooleansAreReachableFromBothSides:
    def test_a_flag_sets_it(self, index: SpellingIndex) -> None:
        source = CLISource(args=["--log-cli-enabled"])
        list(source.read(index))
        # no_cli, so there is nothing to set: the option does not exist.
        assert source.unknown == ["--log-cli-enabled"]

    def test_every_boolean_has_a_no_form(self) -> None:
        class Switchable(ConfigPart, name_prefix="run"):
            verbose: bool = False

        built = SpellingIndex()
        built.add(Switchable)
        source = CLISource(args=["--no-run-verbose"])
        readings = [r for r in source.read(built) if isinstance(r, Reading)]
        assert readings[0].raw is False

    def test_which_is_what_makes_a_file_value_overridable(self) -> None:
        # The ladder puts files below the command line so an argument can
        # override one. Without --no-, a file's `verbose = true` is unreachable.
        class Switchable(ConfigPart, name_prefix="run"):
            verbose: bool = False

        built = SpellingIndex()
        built.add(Switchable)
        assert built.cli("--no-run-verbose")
