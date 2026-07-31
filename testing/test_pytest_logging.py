"""Acceptance test: pytest's logging plugin, declared once.

This is the project's reason for existing. In pytest, every logging option is
declared twice -- once as an ini option and once as a CLI option -- and the
two are reconciled by hand at read time with `get_option_ini(config, "log_cli_format",
"log_format")`. See `docs/pytest-logging-options.txt` for the full inventory
extracted from `_pytest/logging.py`.

Here the same 13 options are declared once, as a nested structure, and reached
from ini, TOML, env and CLI by their real pytest names:

    log_cli_level   ->  cli.level
    log_file        ->  file.path
    log_cli         ->  cli.enabled

The fallbacks pytest hand-rolls (`log_cli_level` falling back to `log_level`)
are the `from_parent` cascade.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Annotated

import pytest

from cot.config import (
    CLISource,
    ConfigManager,
    ConfigPart,
    EnvSource,
    IniSource,
    SubConfig,
    TomlSource,
    from_parent,
    help,
    named,
    no_cli,
)

DEFAULT_LOG_FORMAT = "%(levelname)-8s %(name)s:%(filename)s:%(lineno)d %(message)s"
DEFAULT_LOG_DATE_FORMAT = "%H:%M:%S"


# --- The declaration under test -------------------------------------------
# One structure. Compare with pytest_addoption in _pytest/logging.py, which
# needs ~90 lines and a local add_option_ini helper for the same options.


class LogOutputConfig(SubConfig):
    """Settings shared by every log output.

    `from_parent` is what makes `log_cli_level` fall back to `log_level`.
    """

    level: Annotated[str | None, from_parent, help("level of messages to catch")] = None
    format: Annotated[str, from_parent, help("log format")] = DEFAULT_LOG_FORMAT
    date_format: Annotated[str, from_parent, help("log date format")] = (
        DEFAULT_LOG_DATE_FORMAT
    )


class LogCliConfig(LogOutputConfig):
    """Live logging to the terminal."""

    # pytest calls this `log_cli`, and it is ini-only: live logging is switched
    # on from the command line with --log-cli-level instead.
    enabled: Annotated[bool, named("log_cli"), no_cli, help("enable live logs")] = False


class LogFileConfig(LogOutputConfig):
    """Logging to a file."""

    # Structurally `file.path`, but pytest calls it `log_file`.
    path: Annotated[str | None, named("log_file"), help("path to log file")] = None
    mode: Annotated[str, named("log_file_mode"), help("log file open mode")] = "w"


class LoggingConfig(LogOutputConfig, ConfigPart, prefix="pytest", name_prefix="log"):
    """pytest's logging configuration.

    `prefix="pytest"` puts the options in the `[pytest]` section; `name_prefix="log"`
    makes each option `log_*`. The two are separate on purpose -- pytest's
    options live in the pytest section but are named after their plugin.
    """

    auto_indent: Annotated[str | None, help("auto-indent multiline messages")] = None
    # CLI-only, repeatable, no ini equivalent.
    logger_disable: Annotated[
        list[str], named("log_disable"), help("disable a logger by name")
    ] = []

    cli: LogCliConfig
    file: LogFileConfig


ALL_INI_OPTIONS = [
    "log_level",
    "log_format",
    "log_date_format",
    "log_auto_indent",
    "log_cli",
    "log_cli_level",
    "log_cli_format",
    "log_cli_date_format",
    "log_file",
    "log_file_mode",
    "log_file_level",
    "log_file_format",
    "log_file_date_format",
]


def make_manager(*sources: object) -> ConfigManager:
    """A manager with LoggingConfig declared but not yet resolved."""
    manager = ConfigManager(sources=list(sources))  # type: ignore[arg-type]
    manager.declare(LoggingConfig)
    return manager


def load_config(*sources: object) -> LoggingConfig:
    """Declare, resolve and fetch in one step, for the single-fragment cases."""
    return make_manager(*sources).get(LoggingConfig)


class TestOptionInventory:
    """Every option in the reference file is reachable, by its pytest name."""

    def test_all_thirteen_ini_options_are_declared(self) -> None:
        from cot.config._names import flat_index

        declared = set(flat_index(LoggingConfig))
        assert set(ALL_INI_OPTIONS) <= declared

    def test_cli_only_option_is_declared(self) -> None:
        from cot.config._names import flat_index

        assert "log_disable" in flat_index(LoggingConfig)

    @pytest.mark.parametrize("option", ALL_INI_OPTIONS)
    def test_every_ini_option_reaches_a_field(
        self, option: str, tmp_path: Path
    ) -> None:
        ini = tmp_path / "pytest.ini"
        # `log_cli` is a bool, the rest take strings; both parse from "1".
        ini.write_text(f"[pytest]\n{option} = 1\n")

        manager = make_manager(IniSource(ini))
        manager.get(LoggingConfig)

        # No UnknownConfigKeyWarning means the key found a home.
        assert manager.origins(LoggingConfig)


class TestIniFlatNames:
    """pytest.ini uses flat keys; they must reach the nested structure.

    Before the name mapping existed, this needed a second, flat ConfigPart
    declared alongside the real one.
    """

    def test_flat_keys_reach_nested_fields(self, tmp_path: Path) -> None:
        ini = tmp_path / "pytest.ini"
        ini.write_text(
            dedent("""
            [pytest]
            log_level = WARNING
            log_cli = true
            log_cli_level = DEBUG
            log_file = pytest.log
            log_file_level = INFO
            log_file_mode = a
        """)
        )

        manager = make_manager(IniSource(ini))
        config = manager.get(LoggingConfig)

        assert config.level == "WARNING"
        assert config.cli.enabled is True
        assert config.cli.level == "DEBUG"
        assert config.file.path == "pytest.log"
        assert config.file.level == "INFO"
        assert config.file.mode == "a"

    def test_ini_booleans_are_parsed_not_left_as_strings(self, tmp_path: Path) -> None:
        # `log_cli = false` must be False, not the truthy string "false".
        ini = tmp_path / "pytest.ini"
        ini.write_text("[pytest]\nlog_cli = false\n")

        manager = make_manager(IniSource(ini))
        config = manager.get(LoggingConfig)

        assert config.cli.enabled is False


class TestTomlSpellings:
    """pyproject.toml can use flat pytest keys or a nested layout."""

    def test_flat_keys_in_toml(self, tmp_path: Path) -> None:
        toml = tmp_path / "pyproject.toml"
        toml.write_text(
            dedent("""
            [pytest]
            log_level = "WARNING"
            log_cli_level = "DEBUG"
            log_file = "pytest.log"
        """)
        )

        manager = make_manager(TomlSource(toml))
        config = manager.get(LoggingConfig)

        assert config.cli.level == "DEBUG"
        assert config.file.path == "pytest.log"

    def test_nested_tables_in_toml(self, tmp_path: Path) -> None:
        toml = tmp_path / "pyproject.toml"
        toml.write_text(
            dedent("""
            [pytest]
            level = "WARNING"

            [pytest.cli]
            level = "DEBUG"

            [pytest.file]
            path = "pytest.log"
        """)
        )

        manager = make_manager(TomlSource(toml))
        config = manager.get(LoggingConfig)

        assert config.level == "WARNING"
        assert config.cli.level == "DEBUG"
        assert config.file.path == "pytest.log"

    def test_both_spellings_in_one_file(self, tmp_path: Path) -> None:
        toml = tmp_path / "pyproject.toml"
        toml.write_text(
            dedent("""
            [pytest]
            log_cli_level = "DEBUG"

            [pytest.file]
            path = "pytest.log"
        """)
        )

        manager = make_manager(TomlSource(toml))
        config = manager.get(LoggingConfig)

        assert config.cli.level == "DEBUG"
        assert config.file.path == "pytest.log"


class TestCLINames:
    """Each option gets pytest's real command-line spelling."""

    def test_top_level_option(self, tmp_path: Path) -> None:
        cli = CLISource(args=["--log-level", "DEBUG"], invocation_dir=tmp_path)
        config = load_config(cli)
        assert config.level == "DEBUG"

    def test_nested_option(self, tmp_path: Path) -> None:
        cli = CLISource(args=["--log-cli-level", "DEBUG"], invocation_dir=tmp_path)
        config = load_config(cli)
        assert config.cli.level == "DEBUG"

    def test_renamed_option(self, tmp_path: Path) -> None:
        # `file.path` is spelled --log-file, not --log-file-path.
        cli = CLISource(args=["--log-file", "out.log"], invocation_dir=tmp_path)
        config = load_config(cli)
        assert config.file.path == "out.log"

    def test_equals_form(self, tmp_path: Path) -> None:
        cli = CLISource(args=["--log-file-level=ERROR"], invocation_dir=tmp_path)
        config = load_config(cli)
        assert config.file.level == "ERROR"

    def test_ini_only_option_has_no_cli_flag(self, tmp_path: Path) -> None:
        # --log-cli must not exist; pytest has no such flag.
        cli = CLISource(args=["--log-cli"], invocation_dir=tmp_path)
        config = load_config(cli)

        assert config.cli.enabled is False
        assert "--log-cli" in cli.get_unknown_args()

    def test_repeatable_option_accumulates(self, tmp_path: Path) -> None:
        # pytest: --log-disable can be passed multiple times.
        cli = CLISource(
            args=["--log-disable", "urllib3", "--log-disable", "asyncio"],
            invocation_dir=tmp_path,
        )
        config = load_config(cli)
        assert config.logger_disable == ["urllib3", "asyncio"]

    def test_generic_override_reaches_nested_field(self, tmp_path: Path) -> None:
        cli = CLISource(args=["-o", "cli.level=DEBUG"], invocation_dir=tmp_path)
        config = load_config(cli)
        assert config.cli.level == "DEBUG"

    def test_generic_override_converts_types(self, tmp_path: Path) -> None:
        # Would be the truthy string "false" without type-aware conversion.
        cli = CLISource(args=["-o", "cli.enabled=false"], invocation_dir=tmp_path)
        config = load_config(cli)
        assert config.cli.enabled is False


class TestEnvNames:
    def test_nested_field_from_env(self) -> None:
        env = EnvSource(environ={"PYTEST_LOG_CLI_LEVEL": "DEBUG"})
        config = load_config(env)
        assert config.cli.level == "DEBUG"

    def test_renamed_field_from_env(self) -> None:
        env = EnvSource(environ={"PYTEST_LOG_FILE": "/tmp/out.log"})
        config = load_config(env)
        assert config.file.path == "/tmp/out.log"


class TestFallbackChains:
    """The six fallbacks in docs/pytest-logging-options.txt lines 77-82.

    pytest implements these by calling get_option_ini with two names and
    taking the first non-empty. Here they are the `from_parent` cascade.
    """

    @pytest.mark.parametrize(
        ("child", "attribute"),
        [
            ("cli", "level"),
            ("cli", "format"),
            ("cli", "date_format"),
            ("file", "level"),
            ("file", "format"),
            ("file", "date_format"),
        ],
    )
    def test_child_falls_back_to_parent(
        self, child: str, attribute: str, tmp_path: Path
    ) -> None:
        ini = tmp_path / "pytest.ini"
        ini.write_text(
            dedent("""
            [pytest]
            log_level = CRITICAL
            log_format = PARENT_FORMAT
            log_date_format = PARENT_DATE
        """)
        )

        manager = make_manager(IniSource(ini))
        config = manager.get(LoggingConfig)

        parent_value = getattr(config, attribute)
        assert getattr(getattr(config, child), attribute) == parent_value

    def test_explicit_child_value_wins_over_parent(self, tmp_path: Path) -> None:
        ini = tmp_path / "pytest.ini"
        ini.write_text(
            dedent("""
            [pytest]
            log_level = CRITICAL
            log_cli_level = DEBUG
        """)
        )

        config = load_config(IniSource(ini))

        assert config.level == "CRITICAL"
        assert config.cli.level == "DEBUG"
        assert config.file.level == "CRITICAL"  # not set, so cascades


class TestPrecedence:
    def test_cli_beats_env_beats_file(self, tmp_path: Path) -> None:
        ini = tmp_path / "pytest.ini"
        ini.write_text(
            dedent("""
            [pytest]
            log_level = FROM_FILE
            log_cli_level = FROM_FILE
            log_file = from_file.log
        """)
        )

        manager = make_manager(
            IniSource(ini),
            EnvSource(
                environ={
                    "PYTEST_LOG_LEVEL": "FROM_ENV",
                    "PYTEST_LOG_CLI_LEVEL": "FROM_ENV",
                }
            ),
            CLISource(args=["--log-level", "FROM_CLI"], invocation_dir=tmp_path),
        )
        config = manager.get(LoggingConfig)

        assert config.level == "FROM_CLI"
        assert config.cli.level == "FROM_ENV"
        assert config.file.path == "from_file.log"

    def test_higher_precedence_does_not_wipe_sibling_fields(
        self, tmp_path: Path
    ) -> None:
        # A CLI option inside `file` must not drop `file.path` from the file.
        ini = tmp_path / "pytest.ini"
        ini.write_text("[pytest]\nlog_file = from_file.log\n")

        manager = make_manager(
            IniSource(ini),
            CLISource(args=["--log-file-level", "ERROR"], invocation_dir=tmp_path),
        )
        config = manager.get(LoggingConfig)

        assert config.file.path == "from_file.log"
        assert config.file.level == "ERROR"


class TestProvenance:
    """Which of the four places that mention an option actually won."""

    def test_file_origin_names_file_and_key(self, tmp_path: Path) -> None:
        ini = tmp_path / "pytest.ini"
        ini.write_text("[pytest]\nlog_cli_level = DEBUG\n")

        manager = make_manager(IniSource(ini))
        manager.get(LoggingConfig)

        origin = manager.origin_of(LoggingConfig, "cli.level")
        assert origin.kind == "file"
        assert "pytest.ini" in origin.location
        assert "log_cli_level" in origin.location

    def test_env_overriding_file_reports_env(self, tmp_path: Path) -> None:
        ini = tmp_path / "pytest.ini"
        ini.write_text("[pytest]\nlog_cli_level = DEBUG\n")

        manager = make_manager(
            IniSource(ini),
            EnvSource(environ={"PYTEST_LOG_CLI_LEVEL": "INFO"}),
        )
        config = manager.get(LoggingConfig)

        assert config.cli.level == "INFO"
        origin = manager.origin_of(LoggingConfig, "cli.level")
        assert origin.kind == "env"
        assert origin.location == "PYTEST_LOG_CLI_LEVEL"

    def test_cli_origin_names_the_option(self, tmp_path: Path) -> None:
        manager = make_manager(
            CLISource(args=["--log-file", "out.log"], invocation_dir=tmp_path)
        )
        manager.get(LoggingConfig)

        origin = manager.origin_of(LoggingConfig, "file.path")
        assert origin.kind == "cli"
        assert origin.location == "--log-file"

    def test_cascaded_value_reports_where_the_parent_got_it(
        self, tmp_path: Path
    ) -> None:
        # cli.level was never set; it cascaded from log_level in the ini file.
        # Reporting it as a "default" would be wrong -- the field's own default
        # is None, and the file is what actually decided the value.
        ini = tmp_path / "pytest.ini"
        ini.write_text("[pytest]\nlog_level = WARNING\n")

        manager = make_manager(IniSource(ini))
        config = manager.get(LoggingConfig)
        assert config.cli.level == "WARNING"

        origin = manager.origin_of(LoggingConfig, "cli.level")
        assert origin.kind == "file"
        assert "inherited from level" in origin.location
        assert "log_level" in origin.location

    def test_cascaded_value_can_be_traced_to_the_command_line(
        self, tmp_path: Path
    ) -> None:
        manager = make_manager(
            CLISource(args=["--log-level", "DEBUG"], invocation_dir=tmp_path)
        )
        assert manager.get(LoggingConfig).file.level == "DEBUG"

        origin = manager.origin_of(LoggingConfig, "file.level")
        assert origin.kind == "cli"
        assert "--log-level" in origin.location

    def test_explicitly_set_child_is_not_reported_as_inherited(
        self, tmp_path: Path
    ) -> None:
        ini = tmp_path / "pytest.ini"
        ini.write_text("[pytest]\nlog_level = WARNING\nlog_cli_level = DEBUG\n")

        manager = make_manager(IniSource(ini))
        origin = manager.origin_of(LoggingConfig, "cli.level")

        assert "inherited" not in origin.location
        assert "log_cli_level" in origin.location

    def test_untouched_field_reports_its_default(self, tmp_path: Path) -> None:
        manager = make_manager(CLISource(args=[], invocation_dir=tmp_path))
        manager.get(LoggingConfig)

        assert manager.origin_of(LoggingConfig, "file.mode").kind == "default"

    def test_explain_lists_every_field(self, tmp_path: Path) -> None:
        ini = tmp_path / "pytest.ini"
        ini.write_text("[pytest]\nlog_cli_level = DEBUG\n")

        manager = make_manager(IniSource(ini))
        manager.get(LoggingConfig)

        report = manager.explain(LoggingConfig)
        assert "cli.level" in report
        assert "DEBUG" in report
        assert "log_cli_level" in report


class TestHelpOutput:
    def test_help_lists_options_with_their_text(self, tmp_path: Path) -> None:
        manager = make_manager(CLISource(args=[], invocation_dir=tmp_path))
        manager.get(LoggingConfig)

        rendered = manager.format_help(prog="pytest")

        assert "--log-cli-level" in rendered
        assert "--log-file" in rendered
        assert "path to log file" in rendered
        assert "disable a logger by name" in rendered

    def test_every_cli_option_is_listed(self, tmp_path: Path) -> None:
        manager = make_manager(CLISource(args=[], invocation_dir=tmp_path))
        manager.get(LoggingConfig)

        rendered = manager.format_help()
        for option in ALL_INI_OPTIONS:
            if option == "log_cli":  # ini-only, deliberately absent
                continue
            assert f"--{option.replace('_', '-')}" in rendered

    def test_ini_only_option_is_absent_from_help(self, tmp_path: Path) -> None:
        manager = make_manager(CLISource(args=[], invocation_dir=tmp_path))
        manager.get(LoggingConfig)

        options = {
            line.strip().split()[0]
            for line in manager.format_help().splitlines()
            if line.strip().startswith("--")
        }
        assert "--log-cli" not in options
        assert "--log-cli-level" in options
        assert "enable live logs" not in manager.format_help()

    def test_help_request_is_reported_not_acted_on(self, tmp_path: Path) -> None:
        # A library must not exit the process.
        manager = make_manager(CLISource(args=["--help"], invocation_dir=tmp_path))
        manager.get(LoggingConfig)

        assert manager.help_requested() is True

    def test_no_help_request(self, tmp_path: Path) -> None:
        manager = make_manager(CLISource(args=[], invocation_dir=tmp_path))
        manager.get(LoggingConfig)

        assert manager.help_requested() is False
