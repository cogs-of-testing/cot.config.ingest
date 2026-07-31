"""End-to-end: a ConfigPart used through pytest's own hooks.

These run a real pytest in a `pytester` sandbox, so what is under test is the
actual integration -- pytest parses the arguments and reads the ini file, and
this library supplies the structure, the cascade and the types.

The plugin is auto-enabled via its entry point; nothing here activates it.
"""

from __future__ import annotations

import textwrap

import pytest

pytest_plugins = ["pytester"]


# A plugin, as a plugin author would write it. Shared by most tests below.
PLUGIN = """
    from typing import Annotated

    from cot.config import ConfigPart, SubConfig, from_parent, help, named, no_cli

    class LogOutput(SubConfig):
        level: Annotated[str | None, from_parent, help("log level")] = None
        format: Annotated[str, from_parent, help("log format")] = "PLAIN"

    class LogCli(LogOutput):
        enabled: Annotated[bool, named("applog_cli"), no_cli, help("live logs")] = False

    class LogFile(LogOutput):
        path: Annotated[str | None, named("applog_file"), help("log file path")] = None

    class LoggingConfig(LogOutput, ConfigPart, prefix="pytest", name_prefix="applog"):
        cli: LogCli
        file: LogFile

    def pytest_addoption(parser):
        parser.add_config(LoggingConfig)

    def pytest_configure(config):
        config._seen = config.get_config(LoggingConfig)
"""


def run(pytester: pytest.Pytester, *args: str) -> pytest.RunResult:
    """Run pytest in the sandbox.

    No activation flag: the PoC auto-enables through its `pytest11` entry
    point, so `parser.add_config` is simply present.
    """
    return pytester.runpytest(*args)


@pytest.fixture
def plugin(pytester: pytest.Pytester) -> None:
    """Put a plugin that declares a ConfigPart into the sandbox."""
    pytester.makeconftest(textwrap.dedent(PLUGIN))


@pytest.fixture
def report_test(pytester: pytest.Pytester) -> None:
    """A test that prints the resolved config, so assertions can read it."""
    pytester.makepyfile(
        test_report="""
        def test_report(pytestconfig):
            cfg = pytestconfig._seen
            print("LEVEL=%r" % (cfg.level,))
            print("CLI_LEVEL=%r" % (cfg.cli.level,))
            print("CLI_ENABLED=%r" % (cfg.cli.enabled,))
            print("FILE_PATH=%r" % (cfg.file.path,))
            print("FILE_FORMAT=%r" % (cfg.file.format,))
        """
    )


@pytest.mark.usefixtures("plugin", "report_test")
class TestThroughPytestHooks:
    """pytest_addoption declares, pytest_configure reads."""

    def test_declared_options_appear_in_pytest_help(
        self, pytester: pytest.Pytester
    ) -> None:
        result = run(pytester, "--help")
        result.stdout.fnmatch_lines(["*--applog-cli-level*"])

    def test_help_shows_the_declared_help_text(self, pytester: pytest.Pytester) -> None:
        result = run(pytester, "--help")
        # pytest wraps the help text onto the following line for long options.
        result.stdout.fnmatch_lines(["*--applog-file=APPLOG_FILE*", "*log file path*"])

    def test_defaults_when_nothing_is_configured(
        self, pytester: pytest.Pytester
    ) -> None:
        result = run(pytester, "-s")
        result.stdout.fnmatch_lines(["*LEVEL=None*", "*CLI_ENABLED=False*"])
        assert result.ret == 0

    def test_value_from_command_line(self, pytester: pytest.Pytester) -> None:
        result = run(pytester, "-s", "--applog-cli-level", "DEBUG")
        result.stdout.fnmatch_lines(["*CLI_LEVEL='DEBUG'*"])

    def test_value_from_ini(self, pytester: pytest.Pytester) -> None:
        pytester.makeini("[pytest]\napplog_cli_level = INFO\n")
        result = run(pytester, "-s")
        result.stdout.fnmatch_lines(["*CLI_LEVEL='INFO'*"])

    def test_command_line_beats_ini(self, pytester: pytest.Pytester) -> None:
        pytester.makeini("[pytest]\napplog_cli_level = INFO\n")
        result = run(pytester, "-s", "--applog-cli-level", "DEBUG")
        result.stdout.fnmatch_lines(["*CLI_LEVEL='DEBUG'*"])

    def test_renamed_field_uses_pytest_spelling(
        self, pytester: pytest.Pytester
    ) -> None:
        # file.path is spelled --applog-file via named(), not --applog-file-path.
        result = run(pytester, "-s", "--applog-file", "out.log")
        result.stdout.fnmatch_lines(["*FILE_PATH='out.log'*"])

    def test_ini_only_field_has_no_command_line_option(
        self, pytester: pytest.Pytester
    ) -> None:
        result = run(pytester, "--applog-cli")
        # pytest itself rejects it, which is the point of `no_cli`.
        assert result.ret != 0
        result.stderr.fnmatch_lines(["*unrecognized arguments*--applog-cli*"])

    def test_ini_only_field_still_works_from_ini(
        self, pytester: pytest.Pytester
    ) -> None:
        pytester.makeini("[pytest]\napplog_cli = true\n")
        result = run(pytester, "-s")
        result.stdout.fnmatch_lines(["*CLI_ENABLED=True*"])

    def test_ini_bool_is_a_bool_not_a_string(self, pytester: pytest.Pytester) -> None:
        pytester.makeini("[pytest]\napplog_cli = false\n")
        result = run(pytester, "-s")
        result.stdout.fnmatch_lines(["*CLI_ENABLED=False*"])

    def test_cascade_applies_across_the_pytest_boundary(
        self, pytester: pytest.Pytester
    ) -> None:
        # `from_parent` is this library's, and pytest knows nothing about it.
        pytester.makeini("[pytest]\napplog_format = FROM_PARENT\n")
        result = run(pytester, "-s")
        result.stdout.fnmatch_lines(["*FILE_FORMAT='FROM_PARENT'*"])

    def test_explicit_child_value_wins_over_cascade(
        self, pytester: pytest.Pytester
    ) -> None:
        pytester.makeini(
            "[pytest]\napplog_format = FROM_PARENT\napplog_file_format = OWN\n"
        )
        result = run(pytester, "-s")
        result.stdout.fnmatch_lines(["*FILE_FORMAT='OWN'*"])


@pytest.mark.usefixtures("plugin")
class TestProvenanceThroughPytest:
    def test_explain_reports_cli_and_ini(self, pytester: pytest.Pytester) -> None:
        pytester.makeini("[pytest]\napplog_file = from_ini.log\n")
        pytester.makepyfile(
            test_explain="""
            def test_explain(pytestconfig):
                from conftest import LoggingConfig
                print(pytestconfig.explain_config(LoggingConfig))
            """
        )
        result = run(pytester, "-s", "--applog-cli-level", "DEBUG")

        result.stdout.fnmatch_lines(["*cli.level*DEBUG*cli:--applog-cli-level*"])
        result.stdout.fnmatch_lines(["*file.path*from_ini.log*applog_file*"])


class TestCollisionWithPytestsOwnOptions:
    """pytest already owns names a migrating plugin will want.

    pytest's built-in logging plugin declares `--log-level` and the ini key
    `log_level`. A ConfigPart that derives the same names has to meet those
    two cases differently, and both behaviours matter for the migration.
    """

    def test_colliding_cli_option_reports_the_field(
        self, pytester: pytest.Pytester
    ) -> None:
        pytester.makeconftest(
            """
            from cot.config import ConfigPart

            class Clash(ConfigPart, prefix="pytest", name_prefix="log"):
                level: str | None = None      # derives --log-level

            def pytest_addoption(parser):
                parser.add_config(Clash)
            """
        )
        result = run(pytester)

        assert result.ret != 0
        result.stderr.fnmatch_lines(["*Cannot declare --log-level for field 'level'*"])

    def test_colliding_ini_key_is_adopted_not_clobbered(
        self, pytester: pytest.Pytester
    ) -> None:
        # `log_level` is pytest's own ini option. Declaring a field that maps
        # onto it must reuse pytest's registration and read its value, not
        # replace pytest's help and type.
        pytester.makeconftest(
            """
            from typing import Annotated
            from cot.config import ConfigPart, no_cli

            class Adopted(ConfigPart, prefix="pytest", name_prefix="log"):
                level: Annotated[str | None, no_cli] = None

            def pytest_addoption(parser):
                parser.add_config(Adopted)

            def pytest_configure(config):
                config._adopted = config.get_config(Adopted)
            """
        )
        pytester.makeini("[pytest]\nlog_level = WARNING\n")
        pytester.makepyfile(
            test_adopted="""
            def test_adopted(pytestconfig):
                print("ADOPTED=%r" % (pytestconfig._adopted.level,))
                print("PYTEST_OWN=%r" % (pytestconfig.getini("log_level"),))
            """
        )
        result = run(pytester, "-s")

        result.stdout.fnmatch_lines(["*ADOPTED='WARNING'*", "*PYTEST_OWN='WARNING'*"])
        assert result.ret == 0


class TestLateDeclarationIsRejected:
    def test_declaring_after_configure_raises(self, pytester: pytest.Pytester) -> None:
        pytester.makeconftest(
            """
            from cot.config import ConfigPart
            from cot.config.pytest_plugin import manager_for_config

            class Early(ConfigPart, prefix="pytest"):
                value: str = "x"

            class Late(ConfigPart, prefix="pytest"):
                other: str = "y"

            def pytest_addoption(parser):
                parser.add_config(Early)

            def pytest_configure(config):
                config.get_config(Early)          # resolves
                try:
                    manager_for_config(config).declare(Late)
                except Exception as exc:
                    config._late_error = type(exc).__name__
                else:
                    config._late_error = None
            """
        )
        pytester.makepyfile(
            test_late="""
            def test_late(pytestconfig):
                print("LATE=%s" % pytestconfig._late_error)
            """
        )
        result = run(pytester, "-s")
        result.stdout.fnmatch_lines(["*LATE=ConfigLifecycleError*"])


class TestPluginIsOptIn:
    def test_pytest_is_unpatched_without_the_plugin(
        self, pytester: pytest.Pytester
    ) -> None:
        # Without loading the plugin, add_config must not exist -- the patch is
        # opt-in, not something installing the package does to everyone.
        pytester.makepyfile(
            test_unpatched="""
            import subprocess, sys, textwrap

            def test_unpatched():
                code = textwrap.dedent('''
                    from _pytest.config.argparsing import Parser
                    print("HAS=%s" % hasattr(Parser, "add_config"))
                ''')
                out = subprocess.run(
                    [sys.executable, "-c", code], capture_output=True, text=True
                )
                assert "HAS=False" in out.stdout, out
            """
        )
        result = pytester.runpytest_subprocess()
        assert result.ret == 0
