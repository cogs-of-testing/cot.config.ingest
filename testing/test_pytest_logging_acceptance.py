"""Acceptance: pytest's whole logging option set, declared once, run by pytest.

`test_pytest_logging.py` proves the declaration works against this library's own
sources. This file proves the same declaration works when **pytest** is the one
parsing argv and reading the ini file -- which is the actual migration target,
and the only place the pytest adapter, pytest's `get_option_ini` precedence and
the `from_parent` cascade have to agree with each other.

The option set is the full inventory from `docs/pytest-logging-options.txt`:
13 ini options plus the CLI-only `--log-disable`. The names carry a `mylog`
prefix rather than `log`, because pytest's own logging plugin is loaded and owns
`--log-*` -- a collision there is its own test, in `test_pytest_plugin.py`.

The plugin is auto-enabled via its entry point; nothing here activates it.
"""

from __future__ import annotations

import textwrap

import pytest

pytest_plugins = ["pytester"]


# The declaration, as a plugin author would write it: one nested structure for
# what `_pytest/logging.py` spells out in ~90 lines of paired addini/addoption.
PLUGIN = '''
    from typing import Annotated

    from cot.config import (
        ConfigPart, SubConfig, from_parent, help, named, no_cli,
    )

    DEFAULT_LOG_FORMAT = "%(levelname)-8s %(name)s:%(filename)s:%(lineno)d %(message)s"
    DEFAULT_LOG_DATE_FORMAT = "%H:%M:%S"


    class LogOutputConfig(SubConfig):
        """Shared by every log output. `from_parent` is the fallback chain."""

        level: Annotated[
            str | None, from_parent, help("level of messages to catch")
        ] = None
        format: Annotated[str, from_parent, help("log format")] = DEFAULT_LOG_FORMAT
        date_format: Annotated[
            str, from_parent, help("log date format")
        ] = DEFAULT_LOG_DATE_FORMAT


    class LogCliConfig(LogOutputConfig):
        # pytest calls this `log_cli` and gives it no CLI flag: live logging is
        # switched on with --log-cli-level instead.
        enabled: Annotated[
            bool, named("mylog_cli"), no_cli, help("enable live logs")
        ] = False


    class LogFileConfig(LogOutputConfig):
        # Structurally `file.path`, but pytest calls it `log_file`. `mode` needs
        # no named() -- it already derives `mylog_file_mode`.
        path: Annotated[
            str | None, named("mylog_file"), help("path to log file")
        ] = None
        mode: Annotated[str, help("log file open mode")] = "w"


    class LoggingConfig(
        LogOutputConfig, ConfigPart, prefix="pytest", name_prefix="mylog"
    ):
        auto_indent: Annotated[
            str | None, help("auto-indent multiline messages")
        ] = None
        logger_disable: Annotated[
            list[str], named("mylog_disable"), help("disable a logger by name")
        ] = []

        cli: LogCliConfig
        file: LogFileConfig


    def pytest_addoption(parser):
        parser.add_config(LoggingConfig)


    def pytest_configure(config):
        config._logging = config.get_config(LoggingConfig)
'''


#: Every ini option pytest's logging plugin declares by hand, under this
#: plugin's prefix. Derived from docs/pytest-logging-options.txt.
ALL_INI_OPTIONS = [
    "mylog_level",
    "mylog_format",
    "mylog_date_format",
    "mylog_auto_indent",
    "mylog_cli",
    "mylog_cli_level",
    "mylog_cli_format",
    "mylog_cli_date_format",
    "mylog_file",
    "mylog_file_mode",
    "mylog_file_level",
    "mylog_file_format",
    "mylog_file_date_format",
]

#: The same options as command line flags. `mylog_cli` is absent on purpose --
#: it is `no_cli`, exactly as pytest's `log_cli` is ini-only.
ALL_CLI_OPTIONS = [
    f"--{name.replace('_', '-')}" for name in ALL_INI_OPTIONS if name != "mylog_cli"
] + ["--mylog-disable"]


REPORT = """
    def test_report(pytestconfig):
        cfg = pytestconfig._logging
        print("LEVEL=%r" % (cfg.level,))
        print("FORMAT=%r" % (cfg.format,))
        print("DATE_FORMAT=%r" % (cfg.date_format,))
        print("AUTO_INDENT=%r" % (cfg.auto_indent,))
        # Not %r: fnmatch_lines reads [...] as a character class, so a repr'd
        # list can never be matched literally.
        print("DISABLE=(%s)" % ",".join(cfg.logger_disable))
        print("CLI_ENABLED=%r" % (cfg.cli.enabled,))
        print("CLI_LEVEL=%r" % (cfg.cli.level,))
        print("CLI_FORMAT=%r" % (cfg.cli.format,))
        print("CLI_DATE_FORMAT=%r" % (cfg.cli.date_format,))
        print("FILE_PATH=%r" % (cfg.file.path,))
        print("FILE_MODE=%r" % (cfg.file.mode,))
        print("FILE_LEVEL=%r" % (cfg.file.level,))
        print("FILE_FORMAT=%r" % (cfg.file.format,))
        print("FILE_DATE_FORMAT=%r" % (cfg.file.date_format,))
"""


@pytest.fixture
def logging_plugin(pytester: pytest.Pytester) -> None:
    """A conftest declaring the whole logging option set, plus a reporting test."""
    pytester.makeconftest(textwrap.dedent(PLUGIN))
    pytester.makepyfile(test_report=REPORT)


@pytest.mark.usefixtures("logging_plugin")
class TestTheWholeOptionSetIsRegistered:
    """Parity with what pytest's logging plugin declares by hand."""

    def test_every_ini_option_is_known_to_pytest(
        self, pytester: pytest.Pytester
    ) -> None:
        """`config.getini` raises for an unregistered key, so this is the check."""
        pytester.makepyfile(
            test_inis=f"""
            OPTIONS = {ALL_INI_OPTIONS!r}

            def test_inis(pytestconfig):
                for name in OPTIONS:
                    pytestconfig.getini(name)   # ValueError if never declared
                print("INI_COUNT=%d" % len(OPTIONS))
            """
        )
        result = pytester.runpytest("-s", "test_inis.py")

        result.stdout.fnmatch_lines(["*INI_COUNT=13*"])
        assert result.ret == 0

    @pytest.mark.parametrize("option", ALL_CLI_OPTIONS)
    def test_every_cli_option_appears_in_help(
        self, pytester: pytest.Pytester, option: str
    ) -> None:
        result = pytester.runpytest("--help")
        result.stdout.fnmatch_lines([f"*{option}*"])

    def test_the_ini_only_option_has_no_cli_flag(
        self, pytester: pytest.Pytester
    ) -> None:
        # `no_cli`, matching pytest's `log_cli`.
        result = pytester.runpytest("--mylog-cli")

        assert result.ret != 0
        result.stderr.fnmatch_lines(["*unrecognized arguments*--mylog-cli*"])

    def test_defaults_survive_the_round_trip(self, pytester: pytest.Pytester) -> None:
        result = pytester.runpytest("-s", "test_report.py")

        # fnmatch_lines matches in order, so these follow the print order.
        result.stdout.fnmatch_lines(
            [
                "*LEVEL=None*",
                "*DATE_FORMAT='%H:%M:%S'*",
                "*DISABLE=()*",
                "*CLI_ENABLED=False*",
                "*FILE_MODE='w'*",
            ]
        )
        assert result.ret == 0


@pytest.mark.usefixtures("logging_plugin")
class TestValuesArriveFromBothSides:
    """pytest parses argv and reads the ini; the structure is reassembled here."""

    def test_every_ini_option_reaches_its_field(
        self, pytester: pytest.Pytester
    ) -> None:
        pytester.makeini(
            """
            [pytest]
            mylog_level = INI_LEVEL
            mylog_format = INI_FORMAT
            mylog_date_format = INI_DATE
            mylog_auto_indent = 4
            mylog_cli = true
            mylog_cli_level = INI_CLI_LEVEL
            mylog_cli_format = INI_CLI_FORMAT
            mylog_cli_date_format = INI_CLI_DATE
            mylog_file = ini.log
            mylog_file_mode = a
            mylog_file_level = INI_FILE_LEVEL
            mylog_file_format = INI_FILE_FORMAT
            mylog_file_date_format = INI_FILE_DATE
            """
        )
        result = pytester.runpytest("-s", "test_report.py")

        result.stdout.fnmatch_lines(
            [
                "*LEVEL='INI_LEVEL'*",
                "*FORMAT='INI_FORMAT'*",
                "*DATE_FORMAT='INI_DATE'*",
                "*AUTO_INDENT='4'*",
                "*CLI_ENABLED=True*",
                "*CLI_LEVEL='INI_CLI_LEVEL'*",
                "*CLI_FORMAT='INI_CLI_FORMAT'*",
                "*CLI_DATE_FORMAT='INI_CLI_DATE'*",
                "*FILE_PATH='ini.log'*",
                "*FILE_MODE='a'*",
                "*FILE_LEVEL='INI_FILE_LEVEL'*",
                "*FILE_FORMAT='INI_FILE_FORMAT'*",
                "*FILE_DATE_FORMAT='INI_FILE_DATE'*",
            ]
        )
        assert result.ret == 0

    def test_every_cli_option_reaches_its_field(
        self, pytester: pytest.Pytester
    ) -> None:
        result = pytester.runpytest(
            "-s",
            "test_report.py",
            "--mylog-level=CLI_LEVEL",
            "--mylog-format=CLI_FORMAT",
            "--mylog-date-format=CLI_DATE",
            "--mylog-auto-indent=2",
            "--mylog-cli-level=CLI_CLI_LEVEL",
            "--mylog-cli-format=CLI_CLI_FORMAT",
            "--mylog-cli-date-format=CLI_CLI_DATE",
            "--mylog-file=cli.log",
            "--mylog-file-mode=a",
            "--mylog-file-level=CLI_FILE_LEVEL",
            "--mylog-file-format=CLI_FILE_FORMAT",
            "--mylog-file-date-format=CLI_FILE_DATE",
        )

        result.stdout.fnmatch_lines(
            [
                "*LEVEL='CLI_LEVEL'*",
                "*FORMAT='CLI_FORMAT'*",
                "*DATE_FORMAT='CLI_DATE'*",
                "*AUTO_INDENT='2'*",
                "*CLI_LEVEL='CLI_CLI_LEVEL'*",
                "*CLI_FORMAT='CLI_CLI_FORMAT'*",
                "*CLI_DATE_FORMAT='CLI_CLI_DATE'*",
                "*FILE_PATH='cli.log'*",
                "*FILE_MODE='a'*",
                "*FILE_LEVEL='CLI_FILE_LEVEL'*",
                "*FILE_FORMAT='CLI_FILE_FORMAT'*",
                "*FILE_DATE_FORMAT='CLI_FILE_DATE'*",
            ]
        )
        assert result.ret == 0

    def test_command_line_beats_ini(self, pytester: pytest.Pytester) -> None:
        """pytest's own get_option_ini precedence, applied per leaf field."""
        pytester.makeini(
            "[pytest]\nmylog_cli_level = FROM_INI\nmylog_file = from_ini.log\n"
        )
        result = pytester.runpytest(
            "-s", "test_report.py", "--mylog-cli-level=FROM_CLI"
        )

        result.stdout.fnmatch_lines(
            ["*CLI_LEVEL='FROM_CLI'*", "*FILE_PATH='from_ini.log'*"]
        )

    def test_renamed_fields_use_the_pytest_spelling(
        self, pytester: pytest.Pytester
    ) -> None:
        """`named()` is what makes `file.path` answer to `--mylog-file`."""
        pytester.makeini("[pytest]\nmylog_cli = true\n")
        result = pytester.runpytest("-s", "test_report.py", "--mylog-file=out.log")

        result.stdout.fnmatch_lines(["*CLI_ENABLED=True*", "*FILE_PATH='out.log'*"])


@pytest.mark.usefixtures("logging_plugin")
class TestTheFallbackChains:
    """The `from_parent` cascade.

    This is what pytest hand-rolls at every read site as
    `get_option_ini(config, "log_cli_format", "log_format")`.
    """

    def test_parent_level_cascades_to_both_outputs(
        self, pytester: pytest.Pytester
    ) -> None:
        pytester.makeini("[pytest]\nmylog_level = DEBUG\n")
        result = pytester.runpytest("-s", "test_report.py")

        result.stdout.fnmatch_lines(
            ["*LEVEL='DEBUG'*", "*CLI_LEVEL='DEBUG'*", "*FILE_LEVEL='DEBUG'*"]
        )

    def test_parent_format_cascades_to_both_outputs(
        self, pytester: pytest.Pytester
    ) -> None:
        result = pytester.runpytest("-s", "test_report.py", "--mylog-format=SHARED")

        result.stdout.fnmatch_lines(
            ["*FORMAT='SHARED'*", "*CLI_FORMAT='SHARED'*", "*FILE_FORMAT='SHARED'*"]
        )

    def test_an_explicit_child_value_wins_over_the_cascade(
        self, pytester: pytest.Pytester
    ) -> None:
        pytester.makeini("[pytest]\nmylog_level = PARENT\nmylog_file_level = OWN\n")
        result = pytester.runpytest("-s", "test_report.py")

        result.stdout.fnmatch_lines(["*CLI_LEVEL='PARENT'*", "*FILE_LEVEL='OWN'*"])

    def test_the_cascade_crosses_the_source_boundary(
        self, pytester: pytest.Pytester
    ) -> None:
        """Parent from the command line, child unset: the child still inherits."""
        pytester.makeini("[pytest]\nmylog_file_level = FROM_INI\n")
        result = pytester.runpytest("-s", "test_report.py", "--mylog-level=FROM_CLI")

        result.stdout.fnmatch_lines(
            ["*CLI_LEVEL='FROM_CLI'*", "*FILE_LEVEL='FROM_INI'*"]
        )


@pytest.mark.usefixtures("logging_plugin")
class TestTheRepeatableCliOnlyOption:
    """`--log-disable` is pytest's one append-action logging option."""

    def test_repeating_the_option_accumulates(self, pytester: pytest.Pytester) -> None:
        result = pytester.runpytest(
            "-s", "test_report.py", "--mylog-disable=noisy", "--mylog-disable=chatty"
        )

        result.stdout.fnmatch_lines(["*DISABLE=(noisy,chatty)*"])

    def test_a_single_occurrence_is_still_a_list(
        self, pytester: pytest.Pytester
    ) -> None:
        """One occurrence must not collapse to a bare string."""
        result = pytester.runpytest("-s", "test_report.py", "--mylog-disable=noisy")

        result.stdout.fnmatch_lines(["*DISABLE=(noisy)*"])

    def test_the_list_can_come_from_ini(self, pytester: pytest.Pytester) -> None:
        pytester.makeini("[pytest]\nmylog_disable =\n    noisy\n    chatty\n")
        result = pytester.runpytest("-s", "test_report.py")

        result.stdout.fnmatch_lines(["*DISABLE=(noisy,chatty)*"])


@pytest.mark.usefixtures("logging_plugin")
class TestProvenance:
    """Which of the places that mention an option won, and how."""

    def test_explain_names_the_ini_key_and_the_option(
        self, pytester: pytest.Pytester
    ) -> None:
        pytester.makeini("[pytest]\nmylog_file = from_ini.log\n")
        pytester.makepyfile(
            test_explain="""
            def test_explain(pytestconfig):
                from conftest import LoggingConfig
                print(pytestconfig.explain_config(LoggingConfig))
            """
        )
        result = pytester.runpytest("-s", "test_explain.py", "--mylog-cli-level=DEBUG")

        result.stdout.fnmatch_lines(["*cli.level*DEBUG*--mylog-cli-level*"])
        result.stdout.fnmatch_lines(["*file.path*from_ini.log*mylog_file*"])

    def test_a_cascaded_value_is_attributed_to_the_parent(
        self, pytester: pytest.Pytester
    ) -> None:
        """A child that inherited must not claim the value as its own default."""
        pytester.makepyfile(
            test_explain="""
            def test_explain(pytestconfig):
                from conftest import LoggingConfig
                print(pytestconfig.explain_config(LoggingConfig))
            """
        )
        result = pytester.runpytest("-s", "test_explain.py", "--mylog-level=DEBUG")

        result.stdout.fnmatch_lines(["*cli.level*DEBUG*inherited from level*"])


class TestPytestsOwnLoggingStillWorks:
    """The declaration must sit alongside pytest's logging plugin, not on top."""

    @pytest.mark.usefixtures("logging_plugin")
    def test_pytests_log_level_is_untouched(self, pytester: pytest.Pytester) -> None:
        pytester.makeini("[pytest]\nlog_level = WARNING\nmylog_level = DEBUG\n")
        pytester.makepyfile(
            test_both="""
            def test_both(pytestconfig):
                print("PYTEST_OWN=%r" % (pytestconfig.getini("log_level"),))
                print("OURS=%r" % (pytestconfig._logging.level,))
            """
        )
        result = pytester.runpytest("-s", "test_both.py")

        result.stdout.fnmatch_lines(["*PYTEST_OWN='WARNING'*", "*OURS='DEBUG'*"])
        assert result.ret == 0
