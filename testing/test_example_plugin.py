"""The example plugin, run for real, and checked for not clobbering pytest.

`cot.config.example_plugin` is a slow-test reporter. These tests run it in a
`pytester` sandbox to show the library working end to end inside pytest, and to
pin the claim that it adds options without taking anything over.

Note the absence of `-p cot.config.pytest_plugin`: the PoC is auto-enabled
through its entry point, so `parser.add_config` is simply there.
"""

from __future__ import annotations

import pytest

pytest_plugins = ["pytester"]

EXAMPLE = ("-p", "cot.config.example_plugin")

SLOW_AND_FAST = """
    import time

    def test_fast():
        pass

    def test_slow():
        time.sleep(0.25)
"""


@pytest.fixture
def tests(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(test_timed=SLOW_AND_FAST)


@pytest.mark.usefixtures("tests")
class TestItWorks:
    def test_report_lists_the_slow_test(self, pytester: pytest.Pytester) -> None:
        result = pytester.runpytest(*EXAMPLE, "--timing-report")

        result.stdout.fnmatch_lines(["*slow tests*", "*test_timed.py::test_slow*"])
        assert result.ret == 0

    def test_threshold_filters(self, pytester: pytest.Pytester) -> None:
        result = pytester.runpytest(
            *EXAMPLE, "--timing-report", "--timing-threshold=10"
        )

        result.stdout.fnmatch_lines(["*no tests over the threshold*"])

    def test_threshold_cascades_to_both_outputs(
        self, pytester: pytest.Pytester
    ) -> None:
        # One knob sets terminal.threshold and file.threshold at once. That is
        # `from_parent`; pytest has no equivalent.
        result = pytester.runpytest(
            *EXAMPLE,
            "--timing-report",
            "--timing-threshold=10",
            "--timing-file=out.txt",
        )

        result.stdout.fnmatch_lines(["*no tests over the threshold*"])
        assert pytester.path.joinpath("out.txt").read_text() == ""

    def test_child_threshold_overrides_the_cascade(
        self, pytester: pytest.Pytester
    ) -> None:
        # The file output keeps everything while the terminal filters it out.
        result = pytester.runpytest(
            *EXAMPLE,
            "--timing-report",
            "--timing-terminal-threshold=10",
            "--timing-file=out.txt",
        )

        result.stdout.fnmatch_lines(["*no tests over the threshold*"])
        assert "test_slow" in pytester.path.joinpath("out.txt").read_text()

    def test_renamed_field_uses_the_expected_spelling(
        self, pytester: pytest.Pytester
    ) -> None:
        # file.path is --timing-file, not --timing-file-path.
        pytester.runpytest(*EXAMPLE, "--timing-file=out.txt")

        assert "test_slow" in pytester.path.joinpath("out.txt").read_text()

    def test_configuration_from_ini(self, pytester: pytest.Pytester) -> None:
        pytester.makeini("[pytest]\ntiming_report = true\ntiming_threshold = 0.1\n")
        result = pytester.runpytest(*EXAMPLE)

        result.stdout.fnmatch_lines(["*test_timed.py::test_slow*"])
        assert "test_fast" not in result.stdout.str().split("slow tests")[-1]

    def test_ini_only_option_has_no_command_line_form(
        self, pytester: pytest.Pytester
    ) -> None:
        result = pytester.runpytest(*EXAMPLE, "--timing-ignore=test_slow")

        assert result.ret != 0
        result.stderr.fnmatch_lines(["*unrecognized arguments*--timing-ignore*"])

    def test_ini_only_option_works_from_ini(self, pytester: pytest.Pytester) -> None:
        pytester.makeini(
            "[pytest]\ntiming_report = true\ntiming_ignore =\n    test_slow\n"
        )
        result = pytester.runpytest(*EXAMPLE)

        report = result.stdout.str().split("slow tests")[-1]
        assert "test_slow" not in report
        assert "test_fast" in report  # still listed; only test_slow is ignored

    def test_command_line_beats_ini(self, pytester: pytest.Pytester) -> None:
        pytester.makeini("[pytest]\ntiming_report = true\ntiming_threshold = 10\n")
        result = pytester.runpytest(*EXAMPLE, "--timing-threshold=0.0")

        result.stdout.fnmatch_lines(["*test_timed.py::test_slow*"])


@pytest.mark.usefixtures("tests")
class TestItDoesNotClobberPytest:
    """Adding options must not take anything over."""

    def test_inactive_by_default(self, pytester: pytest.Pytester) -> None:
        # Loaded but unconfigured: it registers no hooks and prints nothing.
        result = pytester.runpytest(*EXAMPLE)

        assert result.ret == 0
        assert "slow tests" not in result.stdout.str()

    def test_output_is_unchanged_when_unconfigured(
        self, pytester: pytest.Pytester
    ) -> None:
        without = pytester.runpytest()
        with_plugin = pytester.runpytest(*EXAMPLE)

        def summary(result: pytest.RunResult) -> str:
            return result.stdout.str().rsplit("=", 1)[-1]

        assert summary(without) == summary(with_plugin)
        assert without.ret == with_plugin.ret

    def test_pytests_own_durations_still_works(self, pytester: pytest.Pytester) -> None:
        # Same job, pytest's own implementation, running alongside ours.
        result = pytester.runpytest(*EXAMPLE, "--durations=5", "--timing-report")

        result.stdout.fnmatch_lines(["*slowest*durations*"])
        result.stdout.fnmatch_lines(["*slow tests*"])
        assert result.ret == 0

    def test_pytests_own_options_are_untouched(self, pytester: pytest.Pytester) -> None:
        result = pytester.runpytest(*EXAMPLE, "-q", "--tb=no", "-p", "no:cacheprovider")

        assert result.ret == 0

    def test_no_pytest_option_is_shadowed(self, pytester: pytest.Pytester) -> None:
        # Every option the example adds is in its own namespace.
        result = pytester.runpytest(*EXAMPLE, "--help")

        added = {
            line.strip().split("=")[0].split()[0]
            for line in result.stdout.lines
            if line.strip().startswith("--timing")
        }
        assert added == {
            "--timing-report",
            "--timing-threshold",
            "--timing-terminal-threshold",
            "--timing-file",
            "--timing-file-threshold",
        }


@pytest.mark.usefixtures("tests")
class TestInACleanProcess:
    """Subprocess runs, because in-process ones lie here.

    `pytester.runpytest` runs in this very interpreter, where the PoC has
    already patched pytest globally. That hides the fact that a `-p` plugin
    loads *before* entry-point plugins and so cannot assume the patch exists.
    Only a fresh process shows it.
    """

    def test_p_flag_works_from_a_cold_start(self, pytester: pytest.Pytester) -> None:
        result = pytester.runpytest_subprocess(*EXAMPLE, "--timing-report")

        result.stdout.fnmatch_lines(["*slow tests*", "*test_timed.py::test_slow*"])
        assert result.ret == 0

    def test_entry_point_activation_from_a_cold_start(
        self, pytester: pytest.Pytester
    ) -> None:
        pytester.makeconftest(
            """
            from cot.config import ConfigPart

            class Demo(ConfigPart, prefix="pytest", name_prefix="demo"):
                value: str = "default"

            def pytest_addoption(parser):
                parser.add_config(Demo)

            def pytest_configure(config):
                config._demo = config.get_config(Demo)
            """
        )
        pytester.makepyfile(
            test_demo="""
            def test_demo(pytestconfig):
                print("VALUE=%r" % (pytestconfig._demo.value,))
            """
        )
        result = pytester.runpytest_subprocess("-s", "--demo-value", "given")

        result.stdout.fnmatch_lines(["*VALUE='given'*"])
        assert result.ret == 0


class TestAutoEnabled:
    """The PoC itself needs no activation."""

    def test_add_config_is_available_without_any_flag(
        self, pytester: pytest.Pytester
    ) -> None:
        pytester.makeconftest(
            """
            from cot.config import ConfigPart

            class Demo(ConfigPart, prefix="pytest", name_prefix="demo"):
                value: str = "default"

            def pytest_addoption(parser):
                parser.add_config(Demo)

            def pytest_configure(config):
                config._demo = config.get_config(Demo)
            """
        )
        pytester.makepyfile(
            test_demo="""
            def test_demo(pytestconfig):
                print("VALUE=%r" % (pytestconfig._demo.value,))
            """
        )
        result = pytester.runpytest("-s", "--demo-value", "given")

        result.stdout.fnmatch_lines(["*VALUE='given'*"])
        assert result.ret == 0

    def test_can_be_switched_off(self, pytester: pytest.Pytester) -> None:
        # Must be a subprocess: the patch is applied when the module is
        # imported, and an in-process run inherits an already-patched pytest
        # from this very test session.
        pytester.makeconftest(
            """
            def pytest_addoption(parser):
                assert not hasattr(parser, "add_config"), "should be unpatched"
            """
        )
        pytester.makepyfile(test_nothing="def test_nothing(): pass")
        result = pytester.runpytest_subprocess("-p", "no:cot_config")

        assert result.ret == 0

    def test_switched_off_really_means_unpatched(
        self, pytester: pytest.Pytester
    ) -> None:
        pytester.makeconftest(
            """
            def pytest_addoption(parser):
                parser.add_config(object)
            """
        )
        pytester.makepyfile(test_nothing="def test_nothing(): pass")
        result = pytester.runpytest_subprocess("-p", "no:cot_config")

        assert result.ret != 0
        result.stderr.fnmatch_lines(["*no attribute 'add_config'*"])
