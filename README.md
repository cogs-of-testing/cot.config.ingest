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

```python
import sys
from pathlib import Path

from cot.config import CLISource, ConfigManager, EnvSource, TomlSource

manager = ConfigManager(sources=[
    TomlSource(Path("pyproject.toml")),
    EnvSource("PYTEST"),
    CLISource(sys.argv[1:]),
])
manager.declare(LoggingConfig)

config = manager.get(LoggingConfig)
```

Three phases: `declare()` registers a type and its options, `resolve()` runs the
bootstrap once for everything declared, `get()` returns the built instance.
`get()` resolves implicitly; calling `resolve()` yourself is how you pin the
moment configuration freezes. Declaring after that raises
`ConfigLifecycleError`.

The split exists because a host collects declarations from independent plugins
before any of them can be resolved — in pytest, every plugin's
`pytest_addoption` runs before a single argument is parsed.

### Names

One structural path, a different spelling per source. For
`LoggingConfig(prefix="pytest", name_prefix="log")`:

| path | CLI | INI / flat | env | TOML nested |
|---|---|---|---|---|
| `("level",)` | `--log-level` | `log_level` | `PYTEST_LOG_LEVEL` | `[pytest] level` |
| `("cli","level")` | `--log-cli-level` | `log_cli_level` | `PYTEST_LOG_CLI_LEVEL` | `[pytest.cli] level` |

File sources accept both spellings, so a nested table and a flat prefixed key
reach the same field. `prefix=` names the config-file section and namespaces the
environment; `name_prefix=` prefixes the option names. They are separate because
pytest's logging options live in `[pytest]` but are individually called
`log_cli_level`.

### Precedence

```
defaults(-1) < file(15) < addopts(18) < env(20) < cli(25)
```

These are defaults, not an enum — every source takes `precedence=`, and that
number is the only thing that decides a winner:

```python
from cot.config import Precedence, TomlSource

TomlSource(path, precedence=Precedence.CLI + 1)   # outranks a typed argument
```

### Where did this value come from?

Merging several sources means the winner is not obvious from any one of them:

```python
manager.origin_of(LoggingConfig, "cli.level")
# Origin(kind="env", location="PYTEST_LOG_CLI_LEVEL", precedence=20)

print(manager.explain(LoggingConfig))
# field           value       origin
# --------------------------------------------------
# level           'WARNING'   default:level default
# cli.level       'DEBUG'     env:PYTEST_LOG_CLI_LEVEL
# file.path       None        default:file.path default
```

An option injected through an `addopts` field reports as
`addopts --log-cli-level` rather than looking like something you typed.

### Help

`manager.format_help()` returns the rendered option help and
`manager.help_requested()` reports whether `-h`/`--help` was passed. Neither
prints nor exits — this is a library, the application owns the process.

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
stable release should behave, and it will change.

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

### Example plugin

`cot.config.example_plugin` is a worked example — a slow-test reporter with a
nested structure, the `from_parent` cascade, `named()`, `no_cli`, help text, ini
and CLI. It is **not** auto-enabled:

```bash
pytest -p cot.config.example_plugin --timing-report --timing-threshold=0.5
```

## Installing

```bash
pip install cot-config
```

Requires Python 3.10+. Read the pytest section above first — installing is
activating.

## Not implemented yet

Present in `docs/design.md` as intent, absent from the code:

- plugin discovery — the `Discoverable` protocol has no implementors
- list merge semantics (append / reset)
- change notification, hot reload, dependency graphs
- type coercion as a validation hook (construction checks required fields and
  rejects unknown kwargs; coercion itself lives in `_coerce.py`, driven by the
  sources)

## Open questions

- [x] mapping of prefixes/underscores and sub-objects — `prefix=` names the file
      section, `name_prefix=` prefixes the option names, and a field's dotted
      path flattens into each source's spelling. See `src/cot/config/_names.py`.
- [x] mapping of ini options — INI has no nesting, so flat keys are resolved
      against the same mapping; `log_cli_level` reaches `cli.level`.
- [ ] ingestion of backward compatibility fields
- [ ] toml/yaml behaviours — TOML accepts both nested tables and flat keys;
      YAML is not implemented.

## Development

```bash
uv run pytest -q
uv run mypy src
pre-commit run -a
```

## License

MPL-2.0. See [LICENSE](LICENSE).
