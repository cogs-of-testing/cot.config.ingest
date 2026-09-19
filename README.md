# cot.config.ingest

Declare configuration once, as annotated classes, and ingest it from CLI
arguments, environment variables and config files — with the merge order, the
name mapping and the provenance all falling out of the declaration.

> **Experimental.** This is an early experiment that may or may not work out.
> The API moves between releases, and there is no deprecation policy yet.

> **Installing this package patches pytest.** See
> [pytest integration](#pytest-integration-a-hack-on-purpose) before installing
> it anywhere you care about. `-p no:cot_config` turns it off.

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

from cot.config import ConfigPart, SubConfig, from_parent, help, named, no_cli


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

## pytest integration (a hack, on purpose)

`cot.config.pytest_plugin` **monkeypatches pytest**. It adds three methods
pytest does not have:

- `Parser.add_config(part_type)`
- `Config.get_config(part_type)`
- `Config.explain_config(part_type)`

It is registered as a `pytest11` entry point, so **installing the package is
enough to activate it** — importing the plugin module patches
`_pytest.config.Parser` and `_pytest.config.Config` at import time, in every
environment the package is installed into, including as a transitive
dependency.

That is deliberate for now. The point of the proof of concept is to show the
library driving real pytest options, and a conftest-level
`pytest_plugins = [...]` would be too late: that conftest's own
`pytest_addoption` runs before its plugin list is processed. It is not how a
stable release should behave, and it will change: the plan is to replace it with
importable `add_config(parser, T)` / `get_config(config, T)` functions. See
[`docs/design/pytest/evolution.md`](docs/design/pytest/evolution.md).

What you should know:

- **The patch is additive only.** No option, ini key, hook or behaviour of
  pytest's is replaced.
- **Turn it off with `-p no:cot_config`.**
- **A type checker cannot see the patched methods.** Use
  `manager_for_config(config).get(T)` for the statically-typed equivalent.
- **The collision behaviour is pinned by tests**: an ini key pytest already
  declares (`log_level`) is *adopted* rather than clobbered, and a colliding CLI
  option raises `ConfigLifecycleError` naming the field instead of argparse's
  bare "conflicting option string".

```python
def pytest_addoption(parser):
    parser.add_config(LoggingConfig)        # declare

def pytest_configure(config):
    log = config.get_config(LoggingConfig)  # resolve + get, typed
    config.explain_config(LoggingConfig)    # provenance table
```

The intended end state is the reverse of this: pytest using the library
directly, with no patching at all.

## Installing

```bash
pip install cot-config
```

Requires Python 3.10+. Read the pytest section above first — installing is
activating.

## Where the code and the design differ

`docs/design/` is normative and every rule in it is marked **[built]**,
**[change]** or **[new]**. The [gap list](docs/design/index.md#gap-list) is the
full account of what the code does not do yet, and
[order of work](docs/design/index.md#order-of-work) is the sequence for closing
it. Plugin discovery, list merge semantics, YAML, the conversion registry and
hot reload are all design intent with no code behind them.

## Development

```bash
uv run pytest -q
uv run mypy src
pre-commit run -a
```

## License

MPL-2.0. See [LICENSE](LICENSE).
