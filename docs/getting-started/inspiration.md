# Inspiration

Why this library exists, and what the itch was.

The sketch on this page came first; the [design](../design/index.md) is what it
turned into. The proposed API below has been rewritten to be the one that
actually exists — an earlier version of this page showed `Config`, `field()` and
`sub_config()`, names that were never built, which is a rot the
[README's own tests](https://github.com/cogs-of-testing/cot.config.ingest/blob/main/testing/test_readme.py)
exist to prevent.

## The inspiring use case

pytest as of 2024 suffers from the design of its configuration system: CLI args
and ini options are handled by two different mechanisms.

Additionally, adding correct support for `pyproject.toml` data seems daunting.

### The problem

This is real pytest — the code that sets up configuration options and CLI
arguments for the logging plugin:

```python

from pytest import Parser

DEFAULT_LOG_FORMAT = "%(levelname)-8s %(name)s:%(filename)s:%(lineno)d %(message)s"
DEFAULT_LOG_DATE_FORMAT = "%H:%M:%S"

def pytest_addoption(parser: Parser) -> None:
    """Add options to control log capturing."""
    group = parser.getgroup("logging")

    def add_option_ini(option, dest, default=None, type=None, **kwargs):
        parser.addini(
            dest, default=default, type=type, help="Default value for " + option
        )
        group.addoption(option, dest=dest, **kwargs)

    add_option_ini(
        "--log-level",
        dest="log_level",
        default=None,
        metavar="LEVEL",
        help=(
            "Level of messages to catch/display."
            " Not set by default, so it depends on the root/parent log handler's"
            ' effective level, where it is "WARNING" by default.'
        ),
    )
    add_option_ini(
        "--log-format",
        dest="log_format",
        default=DEFAULT_LOG_FORMAT,
        help="Log format used by the logging module",
    )
    add_option_ini(
        "--log-date-format",
        dest="log_date_format",
        default=DEFAULT_LOG_DATE_FORMAT,
        help="Log date format used by the logging module",
    )
    parser.addini(
        "log_cli",
        default=False,
        type="bool",
        help='Enable log display during test run (also known as "live logging")',
    )
    add_option_ini(
        "--log-cli-level", dest="log_cli_level", default=None, help="CLI logging level"
    )
    add_option_ini(
        "--log-cli-format",
        dest="log_cli_format",
        default=None,
        help="Log format used by the logging module",
    )
    add_option_ini(
        "--log-cli-date-format",
        dest="log_cli_date_format",
        default=None,
        help="Log date format used by the logging module",
    )
    add_option_ini(
        "--log-file",
        dest="log_file",
        default=None,
        help="Path to a file when logging will be written to",
    )
    add_option_ini(
        "--log-file-mode",
        dest="log_file_mode",
        default="w",
        choices=["w", "a"],
        help="Log file open mode",
    )
    add_option_ini(
        "--log-file-level",
        dest="log_file_level",
        default=None,
        help="Log file logging level",
    )
    add_option_ini(
        "--log-file-format",
        dest="log_file_format",
        default=None,
        help="Log format used by the logging module",
    )
    add_option_ini(
        "--log-file-date-format",
        dest="log_file_date_format",
        default=None,
        help="Log date format used by the logging module",
    )
    add_option_ini(
        "--log-auto-indent",
        dest="log_auto_indent",
        default=None,
        help="Auto-indent multiline messages passed to the logging module. Accepts true|on, false|off or an integer.",
    )
    group.addoption(
        "--log-disable",
        action="append",
        default=[],
        dest="logger_disable",
        help="Disable a logger by name. Can be passed multiple times.",
    )


```

Thirteen ini keys, thirteen options, ninety lines and a local helper — and the
fallback from `log_cli_format` to `log_format` open-coded at every read site with
`get_option_ini`.

### The same thing, declared once

This is the declaration the library actually accepts. It is lifted from
`testing/test_pytest_logging.py`, the [acceptance test](../design/index.md#the-yardstick),
so it is executed on every run rather than being an illustration:

```python
from typing import Annotated

from pytest import Parser

from cot.config import ConfigPart, SubConfig, from_parent, help, named, no_cli

DEFAULT_LOG_FORMAT = "%(levelname)-8s %(name)s:%(filename)s:%(lineno)d %(message)s"
DEFAULT_LOG_DATE_FORMAT = "%H:%M:%S"


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
    # pytest calls this `log_cli`, and it is ini-only: live logging is switched
    # on from the command line with --log-cli-level instead.
    enabled: Annotated[bool, named("log_cli"), no_cli, help("enable live logs")] = False


class LogFileConfig(LogOutputConfig):
    # Structurally `file.path`, but pytest calls it `log_file`.
    path: Annotated[str | None, named("log_file"), help("path to log file")] = None
    mode: Annotated[str, named("log_file_mode"), help("log file open mode")] = "w"


class LoggingConfig(LogOutputConfig, ConfigPart, prefix="pytest", name_prefix="log"):
    auto_indent: Annotated[str | None, help("auto-indent multiline messages")] = None
    logger_disable: Annotated[
        list[str], named("log_disable"), help("disable a logger by name")
    ] = []

    cli: LogCliConfig
    file: LogFileConfig


def pytest_addoption(parser: Parser) -> None:
    parser.add_config(LoggingConfig)
```

What the sketch got right and what it got wrong, both worth recording:

- **Markers on fields, not a parallel schema.** The sketch's `field(from_parent,
  help=...)` is `Annotated[T, from_parent, help(...)]` — the annotation *is* the
  schema ([ConfigParts](../design/config-parts.md#markers)).
- **Inheritance for the shared settings.** `LogBaseConfig` became
  `LogOutputConfig`, and `from_parent` on its fields is what replaces every
  hand-written `get_option_ini` fallback
  ([the cascade](../design/merging.md#the-from_parent-cascade)).
- **`sub_config(primary=...)` did not survive.** The sketch tried to nominate one
  field of a sub-config as the one the parent's own name refers to — `log_file`
  meaning `file.path`. That is a naming problem, not a structural one, and it is
  solved by [`named()`](../design/names.md#per-field-overrides) without giving
  sub-configs a second kind of field.
- **`prefix` turned out to be two knobs.** The sketch's `prefix="log"` is doing
  the job of `name_prefix=` — pytest's options live in the `[pytest]` section but
  are individually called `log_*`, and
  [one knob cannot say both](../design/names.md#prefix-versus-name_prefix).

Two of the sketch's types are still ahead of the code. `mode` wants
`Literal["w", "a"]` and `auto_indent` wants `bool | int | None`; both are
[specified](../design/types.md#literal) and neither is
[built yet](../design/index.md#gap-list), which is why the declaration above
softens them to `str` and `str | None`.

## The open questions, since answered

| Question | Where it landed |
|---|---|
| mapping of prefixes/underscores and sub-objects | [the qualified path](../design/names.md#the-qualified-path) — one path, rendered per source |
| mapping of ini options | [both spellings in files](../design/names.md#both-spellings-in-files) — flat keys and nested tables reach the same field |
| ingestion of backward compatibility fields | [ingest](../design/pytest/evolution.md#binding-the-specs) — host options become specs and join the store |
| toml behaviours | a [typed-dialect source](../design/sources.md#dialect-is-a-property-of-the-source): values are checked, not coerced |
| yaml behaviours | [admitted as a format](../design/sources.md#yaml), and deliberately still open |
