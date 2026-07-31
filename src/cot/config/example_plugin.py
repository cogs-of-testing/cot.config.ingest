"""An example pytest plugin built on cot.config.

A slow-test reporter. It is small enough to read in one sitting and real enough
to run, and it exercises every feature the library has that pytest's own option
machinery does not: nested structure, value cascade, per-field renaming,
ini-only options and provenance.

Unlike `pytest_plugin`, this is **not** auto-enabled -- it is an example, not
infrastructure:

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

from typing import TYPE_CHECKING, Annotated, Any

from ._annotations import from_parent, help, named, no_cli
from ._bases import ConfigPart, SubConfig
from .pytest_plugin import install

# A plugin loaded with `-p` is loaded *before* entry-point plugins, so the
# patch cannot be assumed to be in place yet. install() is idempotent; any
# plugin that calls add_config and might load early should do this.
install()

if TYPE_CHECKING:
    from _pytest.config import Config
    from _pytest.reports import TestReport
    from _pytest.terminal import TerminalReporter


class TimingOutput(SubConfig):
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


def pytest_addoption(parser: Any) -> None:
    """Declare the whole structure. One call."""
    parser.add_config(TimingConfig)


def pytest_configure(config: Config) -> None:
    """Read it back, typed, and register the reporter only if it is wanted."""
    # `get_config` is monkeypatched onto Config, so a type checker cannot see
    # it -- one more reason the end state should be pytest adopting the library
    # rather than being patched. `manager_for_config(config).get(TimingConfig)`
    # is the statically-typed spelling of the same thing.
    timing: TimingConfig = config.get_config(TimingConfig)  # type: ignore[attr-defined]

    if not timing.report and timing.file.path is None:
        # Nothing was asked for: add no hooks at all.
        return

    config.pluginmanager.register(TimingReporter(timing), "cot-timing-reporter")


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

        path = self._timing.file.path
        if path is not None:
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
