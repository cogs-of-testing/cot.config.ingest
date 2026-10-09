"""End-to-end: a ConfigPart used through pytest's own hooks.

These run a real pytest in a `pytester` sandbox, so what is under test is the
actual integration -- pytest parses the arguments and reads the ini file, and
this library supplies the structure, the cascade and the types.

Each plugin imports `add_config` and `get_config` from
`cot.config.pytest_binding`; nothing is patched onto pytest (P1).
"""

from __future__ import annotations

import textwrap

import pytest

pytest_plugins = ["pytester"]


# A plugin, as a plugin author would write it. Shared by most tests below.
PLUGIN = """
    from typing import Annotated

    from cot.config.pytest_binding import add_config, explain_config, get_config

    from cot.config import ConfigPart, from_parent, help, named, no_cli

    class LogOutput(ConfigPart):
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
        add_config(parser, LoggingConfig)

    def pytest_configure(config):
        config._seen = get_config(config, LoggingConfig)
"""


def run(pytester: pytest.Pytester, *args: str) -> pytest.RunResult:
    """Run pytest in the sandbox. The conftest imports the binding itself."""
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
                from cot.config.pytest_binding import explain_config
                print(explain_config(pytestconfig, LoggingConfig))
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
            from cot.config.pytest_binding import add_config, explain_config, get_config
            from cot.config import ConfigPart

            class Clash(ConfigPart, prefix="pytest", name_prefix="log"):
                level: str | None = None      # derives --log-level

            def pytest_addoption(parser):
                add_config(parser, Clash)
            """
        )
        result = run(pytester)

        assert result.ret != 0
        result.stderr.fnmatch_lines(
            ["*ConfigCollisionError: level cannot be declared as --log-level*"]
        )

    def test_colliding_ini_key_is_adopted_not_clobbered(
        self, pytester: pytest.Pytester
    ) -> None:
        # `log_level` is pytest's own ini option. Declaring a field that maps
        # onto it must reuse pytest's registration and read its value, not
        # replace pytest's help and type.
        pytester.makeconftest(
            """
            from typing import Annotated
            from cot.config.pytest_binding import add_config, explain_config, get_config
            from cot.config import ConfigPart, no_cli

            class Adopted(ConfigPart, prefix="pytest", name_prefix="log"):
                level: Annotated[str | None, no_cli] = None

            def pytest_addoption(parser):
                add_config(parser, Adopted)

            def pytest_configure(config):
                config._adopted = get_config(config, Adopted)
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

    def test_adopt_reads_pytests_own_options(self, pytester: pytest.Pytester) -> None:
        # A plugin that replaces pytest's logging plugin declares the same
        # options; pytest has declared them before any -p plugin loads (P9).
        pytester.makeconftest(
            """
            from typing import Annotated
            from cot.config.pytest_binding import add_config, get_config
            from cot.config import ConfigPart, named

            class Replacing(ConfigPart, prefix="pytest", name_prefix="log"):
                level: str | None = None
                file_mode: str = "w"
                logger_disable: Annotated[list[str], named("log_disable")] = []

            def pytest_addoption(parser):
                add_config(parser, Replacing, adopt=True)

            def pytest_configure(config):
                config._replacing = get_config(config, Replacing)
            """
        )
        pytester.makeini("[pytest]\nlog_level = WARNING\nlog_file_mode = a\n")
        pytester.makepyfile(
            test_adopted="""
            def test_adopted(pytestconfig):
                c = pytestconfig._replacing
                disabled = ",".join(c.logger_disable)
                print("SEEN=%s|%s|%s" % (c.level, c.file_mode, disabled))
            """
        )
        result = run(pytester, "-s", "--log-level=DEBUG", "--log-disable=a")
        result.stdout.fnmatch_lines(["*SEEN=DEBUG|a|a"])

        # not given on the command line: the ini value wins over pytest's
        # argparse default
        result = run(pytester, "-s")
        result.stdout.fnmatch_lines(["*SEEN=WARNING|a|"])

    def test_adopt_refuses_an_incompatible_option(
        self, pytester: pytest.Pytester
    ) -> None:
        pytester.makeconftest(
            """
            from cot.config.pytest_binding import add_config
            from cot.config import ConfigPart

            class Clash(ConfigPart, prefix="pytest", name_prefix="log"):
                level: bool = False      # a flag where pytest takes a value

            def pytest_addoption(parser):
                add_config(parser, Clash, adopt=True)
            """
        )
        result = run(pytester)
        assert result.ret != 0
        result.stderr.fnmatch_lines(["*ConfigCollisionError*not compatible*"])


class TestLateDeclarationIsRejected:
    def test_declaring_after_configure_raises(self, pytester: pytest.Pytester) -> None:
        pytester.makeconftest(
            """
            from cot.config.pytest_binding import add_config, explain_config, get_config
            from cot.config import ConfigPart
            from cot.config.pytest_binding import manager_for

            class Early(ConfigPart, prefix="pytest"):
                value: str = "x"

            class Late(ConfigPart, prefix="pytest"):
                other: str = "y"

            def pytest_addoption(parser):
                add_config(parser, Early)

            def pytest_configure(config):
                get_config(config, Early)          # resolves
                try:
                    manager_for(config).declare(Late)
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
        # Installing the package patches nothing (P1): pytest's own classes
        # carry no add_config, and the package registers no pytest11 plugin.
        pytester.makepyfile(
            test_unpatched="""
            import subprocess, sys, textwrap

            def test_unpatched():
                code = textwrap.dedent('''
                    from importlib.metadata import entry_points
                    import cot.config.pytest_binding
                    from _pytest.config.argparsing import Parser
                    from _pytest.config import Config
                    names = [e.value for e in entry_points(group="pytest11")]
                    patched = hasattr(Parser, "add_config") or hasattr(
                        Config, "get_config"
                    )
                    ours = any(n.startswith("cot.config") for n in names)
                    print("HAS=%s" % (patched or ours))
                ''')
                out = subprocess.run(
                    [sys.executable, "-c", code], capture_output=True, text=True
                )
                assert "HAS=False" in out.stdout, out
            """
        )
        result = pytester.runpytest_subprocess()
        assert result.ret == 0


class TestTheBinderTranslatesSpecs:
    """The table in docs/design/pytest/index.md, each row once."""

    CONFTEST = """
        import enum
        from typing import Annotated, Literal
        from cot.config import ConfigPart, counted, form, formerly, short
        from cot.config.pytest_binding import add_config, get_config

        class Run(ConfigPart, prefix="pytest", name_prefix="run"):
            mode: Literal["fast", "slow"] = "fast"
            jobs: int = 1
            ratio: float = 0.5
            verbose: Annotated[int, short("R"), counted] = 0
            maxfail: Annotated[int, form("--run-x", contributes=1)] = 0
            renamed: Annotated[str, formerly("run_oldname")] = ""

        def pytest_addoption(parser):
            add_config(parser, Run)

        def pytest_configure(config):
            config._run = get_config(config, Run)
    """

    REPORT = """
        def test_report(pytestconfig):
            run = pytestconfig._run
            print("RUN=%r" % ((run.mode, run.jobs, run.ratio, run.verbose,
                               run.maxfail, run.renamed),))
    """

    def _run(self, pytester: pytest.Pytester, *args: str) -> pytest.RunResult:
        pytester.makeconftest(textwrap.dedent(self.CONFTEST))
        pytester.makepyfile(test_report=textwrap.dedent(self.REPORT))
        return run(pytester, "-s", *args)

    def test_closed_values_become_choices(self, pytester: pytest.Pytester) -> None:
        result = self._run(pytester, "--run-mode", "medium")

        assert result.ret != 0
        result.stderr.fnmatch_lines(["*invalid choice*medium*"])

    def test_typed_ini_values_arrive_typed(self, pytester: pytest.Pytester) -> None:
        pytester.makeini("[pytest]\nrun_jobs = 4\nrun_ratio = 0.25\n")
        result = self._run(pytester)

        result.stdout.fnmatch_lines(["*RUN=('fast', 4, 0.25, 0, 0, '')*"])

    def test_counted_and_constant_forms(self, pytester: pytest.Pytester) -> None:
        result = self._run(pytester, "-RRR", "--run-x", "--run-mode=slow")

        result.stdout.fnmatch_lines(["*RUN=('slow', 1, 0.5, 3, 1, '')*"])

    def test_an_ini_alias_reaches_the_field(self, pytester: pytest.Pytester) -> None:
        pytester.makeini("[pytest]\nrun_oldname = legacy\n")
        result = self._run(pytester)

        result.stdout.fnmatch_lines(["*RUN=(*'legacy')*"])
