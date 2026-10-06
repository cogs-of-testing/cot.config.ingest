# cot.config.ingest

Declare configuration once, as annotated classes, and ingest it from CLI
arguments, environment variables and config files — with the merge order, the
name mapping and the provenance all falling out of the declaration.

> **Experimental.** This is an early experiment that may or may not work out.
> The API moves between releases, and there is no deprecation policy yet.

> **0.1.0 patched pytest on install.** That release registered a `pytest11`
> entry point that monkeypatched `Parser` and `Config`. The next release
> patches nothing; see [pytest integration](#pytest-integration).

## The problem

pytest declares every logging option twice — once as an ini option, once as a
CLI option — and reconciles the two by hand at read time:

```python
def pytest_addoption(parser: Parser) -> None:
    group = parser.getgroup("logging")

    def add_option_ini(option, dest, default=None, type=None, **kwargs):
        parser.addini(dest, default=default, type=type,
                      help="Default value for " + option)
        group.addoption(option, dest=dest, **kwargs)

    add_option_ini("--log-level", dest="log_level", default=None, metavar="LEVEL",
                   help="Level of messages to catch/display.")
    add_option_ini("--log-format", dest="log_format", default=DEFAULT_LOG_FORMAT,
                   help="Log format used by the logging module")
    # ... 11 more, plus a bare parser.addini for log_cli, plus a bare
    # group.addoption for --log-disable
```

Then, at use:

```python
log_cli_format = get_option_ini(config, "log_cli_format", "log_format")
```

Thirteen options, ~90 lines, a local helper, and a fallback chain spelled out by
hand at every read site. Adding `pyproject.toml` support on top of that is
daunting, which is the itch this library exists to scratch.

## The same thing, declared once

This is the real declaration from
[`testing/test_pytest_logging.py`](testing/test_pytest_logging.py), the
project's acceptance test — all 13 ini options plus the CLI-only
`--log-disable`, reachable by their real pytest names from ini, TOML, env and
CLI:

```python
from typing import Annotated

from cot.config import ConfigPart, from_parent, help, named, no_cli


class LogOutputConfig(ConfigPart):
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


class LoggingConfig(
    LogOutputConfig, ConfigPart, prefix="pytest", name_prefix="log", from_env=True
):
    auto_indent: Annotated[str | None, help("auto-indent multiline messages")] = None
    logger_disable: Annotated[
        list[str], named("log_disable"), help("disable a logger by name")
    ] = []

    cli: LogCliConfig
    file: LogFileConfig
```

The fallback pytest hand-rolls with `get_option_ini(config, "log_cli_format",
"log_format")` is the `from_parent` cascade. Reading a value is attribute
access:

```python
config.cli.format      # falls back to config.format when unset
config.file.path       # the --log-file / log_file value
```

## Using it

The usage walkthrough, names, precedence, provenance and help live in
[the documentation](docs/index.md); it
is executed by `testing/test_docs_index.py` the same way this README is by
`testing/test_readme.py`. In short:

```python
import sys

from cot.config import CLISource, ConfigManager, EnvSource

manager = ConfigManager(sources=[EnvSource(), CLISource(sys.argv[1:])])
manager.declare(LoggingConfig)
config = manager.get(LoggingConfig)
```

`declare()` registers a type, `get()` resolves every declared type once and
returns the built instance, and `manager.explain(LoggingConfig)` says where each
value came from.

## pytest integration

`cot.config.pytest_binding` has two typed functions, and nothing is patched or
auto-enabled: a plugin that does not import them is untouched.

```python
from cot.config.pytest_binding import add_config, explain_config, get_config

def pytest_addoption(parser):
    add_config(parser, LoggingConfig)        # declare and register options

def pytest_configure(config):
    log = get_config(config, LoggingConfig)  # resolve + get, typed
    explain_config(config, LoggingConfig)    # provenance table
```

pytest keeps argument parsing and ini reading; the binding translates each
field's spec into `addoption`/`addini` calls and reads the values back. An ini
key pytest already declares (`log_level`) is adopted rather than clobbered,
and a colliding CLI option raises `ConfigCollisionError` naming the field. See
[`docs/design/pytest/index.md`](docs/design/pytest/index.md).

## Installing

```bash
pip install cot-config
```

Requires Python 3.10+.

## Where the code and the design differ

`docs/design/` is normative. The code has been rebuilt to it
([D20](docs/design/decisions.md#d20)) through step 9 of
[the build order](docs/design/index.md#build-order); conformance and YAML
remain.
Plugin discovery, list merge semantics, YAML and hot reload are design intent
with no code behind them either way.

## Development

```bash
uv run pytest -q
uv run mypy src
pre-commit run -a
```

## License

MPL-2.0. See [LICENSE](LICENSE).
