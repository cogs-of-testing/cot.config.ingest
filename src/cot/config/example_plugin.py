"""An example pytest plugin built on cot.config.

A slow-test reporter. It is small enough to read in one sitting and real enough
to run, and it exercises every feature the library has that pytest's own option
machinery does not: nested structure, value cascade, per-field renaming,
ini-only options and provenance.

It is not auto-enabled -- nothing in this package is:

    pytest -p cot.config.example_plugin --timing-report

## It does not clobber pytest

Every name it introduces sits under `timing_` / `--timing-*`, a namespace pytest
does not use, so it adds options without taking anything over:

- no option, ini key or hook of pytest's is replaced or shadowed
- pytest's own `--durations` keeps working, independently and side by side
- with none of its options given, the plugin registers nothing and the run is
  byte-for-byte what it would have been

Contrast with what pytest's built-in logging plugin would collide with: a
ConfigPart using `name_prefix="log"` derives `--log-level`, which pytest already
owns, and declaring it raises rather than silently winning. Picking a free
namespace is the whole trick.

## The declaration

Compare the class below with what the same options cost in `pytest_addoption`:
five `parser.addoption` calls, five matching `parser.addini` calls, and a
hand-written fallback for every setting that defaults to a more general one.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from typing import TYPE_CHECKING, Annotated

from ._annotations import from_parent, help, named, no_cli
from ._bases import ConfigPart
from .pytest_binding import add_config, get_config

if TYPE_CHECKING:
    from collections.abc import Iterator

    from _pytest.config import Config
    from _pytest.config.argparsing import Parser
    from _pytest.reports import TestReport
    from _pytest.terminal import TerminalReporter


class TimingOutput(ConfigPart):
    """Settings shared by every place the report can go.

    `threshold` is marked `from_parent`, so `--timing-threshold` sets it for
    both outputs at once while either can still override it. That fallback is
    the thing pytest plugins otherwise hand-roll per setting.
    """

    threshold: Annotated[
        float, from_parent, help("only report tests at least this slow, in seconds")
    ] = 0.0


class TerminalOutput(TimingOutput):
    """The table printed in the terminal summary."""


class FileOutput(TimingOutput):
    """An optional plain-text copy of the report."""

    # Structurally `file.path`; called `timing_file` because that is what a
    # user would expect to type.
    path: Annotated[str | None, named("timing_file"), help("write the report here")] = (
        None
    )


class TimingConfig(TimingOutput, ConfigPart, prefix="pytest", name_prefix="timing"):
    """Configuration for the slow-test reporter.

    `prefix="pytest"` puts these in the `[pytest]` ini section, alongside
    pytest's own settings; `name_prefix="timing"` keeps every individual name
    inside a namespace pytest does not use.

        --timing-report                  timing_report
        --timing-threshold SECONDS       timing_threshold
        --timing-terminal-threshold S    timing_terminal_threshold
        --timing-file PATH               timing_file
        --timing-file-threshold SECONDS  timing_file_threshold
                                         timing_ignore   (ini only)
    """

    report: Annotated[bool, help("report tests slower than the threshold")] = False

    # No command-line spelling: a list of substrings belongs in a config file,
    # not in an argument the user retypes on every run.
    ignore: Annotated[
        list[str],
        named("timing_ignore"),
        no_cli,
        help("node id substrings to leave out of the report"),
    ] = []

    terminal: TerminalOutput
    file: FileOutput

    @contextmanager
    def instance(self) -> Iterator[TimingReporter | None]:
        """The reporter this configuration implies, and its teardown.

        Yields None when nothing was asked for, so the run gains no hooks.
        """
        if not self.report and self.file.path is None:
            yield None
            return
        reporter = TimingReporter(self)
        try:
            yield reporter
        finally:
            reporter.close()


def pytest_addoption(parser: Parser) -> None:
    """Declare the whole structure. One call."""
    add_config(parser, TimingConfig)


def pytest_configure(config: Config) -> None:
    """Enter the fragment's context into the Config's scope (D32).

    The fragment says what the reporter is and owns its teardown; the scope it
    lives in, and the plugin manager it is registered with, are pytest's.
    """
    timing = get_config(config, TimingConfig)

    stack = ExitStack()
    reporter = stack.enter_context(timing.instance())
    config.add_cleanup(stack.close)

    if reporter is not None:
        config.pluginmanager.register(reporter, "cot-timing-reporter")
        config.add_cleanup(lambda: config.pluginmanager.unregister(reporter))


class TimingReporter:
    """Collects call durations and reports the slow ones."""

    def __init__(self, timing: TimingConfig) -> None:
        self._timing = timing
        self._durations: list[tuple[str, float]] = []

    def pytest_runtest_logreport(self, report: TestReport) -> None:
        if report.when == "call":
            self._durations.append((report.nodeid, report.duration))

    def _slower_than(self, threshold: float) -> list[tuple[str, float]]:
        ignored = self._timing.ignore
        selected = [
            (nodeid, duration)
            for nodeid, duration in self._durations
            if duration >= threshold
            and not any(fragment in nodeid for fragment in ignored)
        ]
        return sorted(selected, key=lambda item: item[1], reverse=True)

    def pytest_terminal_summary(self, terminalreporter: TerminalReporter) -> None:
        if self._timing.report:
            # terminal.threshold cascades from the top-level threshold unless
            # --timing-terminal-threshold was given.
            slow = self._slower_than(self._timing.terminal.threshold)
            terminalreporter.write_sep("=", "slow tests")
            if not slow:
                terminalreporter.write_line("no tests over the threshold")
            for nodeid, duration in slow:
                terminalreporter.write_line(f"{duration:8.3f}s  {nodeid}")

    def close(self) -> None:
        """Write the file copy, if one was asked for. Runs at teardown."""
        path = self._timing.file.path
        if path is None:
            return
        lines = [
            f"{duration:.3f}\t{nodeid}"
            for nodeid, duration in self._slower_than(self._timing.file.threshold)
        ]
        with open(path, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + ("\n" if lines else ""))


__all__ = [
    "FileOutput",
    "TerminalOutput",
    "TimingConfig",
    "TimingOutput",
    "TimingReporter",
]
