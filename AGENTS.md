# AI Coding Agent Instructions

## Project Overview

An **experimental** Python library for type-safe configuration management. It lets you
declare configuration as dataclass-like `ConfigPart` classes and ingest values from
multiple sources (CLI args, environment variables, TOML/INI files) with automatic
merging by precedence.

**Key inspiration**: pytest's configuration complexity, where CLI args and ini options
are handled by two separate mechanisms, making `pyproject.toml` support daunting. The
acceptance target for this library is replicating pytest's logging plugin
configuration (see `docs/pytest-logging-options.txt`) from a single declaration.

## Architecture (as built)

The flow is **ConfigParts + Sources → ConfigManager → instances**.

```python
from cot.config import ConfigManager, ConfigPart, SubConfig, CLISource, EnvSource

class LogCliConfig(SubConfig):
    level: Annotated[str, from_parent] = "WARNING"
    enabled: bool = False

class LoggingConfig(ConfigPart, prefix="log"):
    level: str = "WARNING"
    cli: LogCliConfig

manager = ConfigManager(sources=[CLISource(sys.argv[1:]), EnvSource("APP")])
manager.declare(LoggingConfig)
config = manager.get(LoggingConfig)
```

### Lifecycle: declare → resolve → get

| Phase | Call | What happens |
|---|---|---|
| declare | `manager.declare(T)` | The type is recorded and its options registered with any source that accepts declarations. Nothing is loaded. |
| resolve | `manager.resolve()` | Bootstrap runs once for *all* declared types, then every fragment is built. Idempotent; triggered lazily by the first `get()`. |
| access | `manager.get(T)` | The built, typed instance. |

Declaring after `resolve()` raises `ConfigLifecycleError` — the configuration
is frozen.

The split exists because a host collects declarations from independent plugins
before any of them can be resolved. In pytest every plugin's `pytest_addoption`
runs before a single argument is parsed, so a fragment built at declaration
time could not see a config file or `addopts` contributed by a plugin loaded
after it. `testing/test_lifecycle.py` pins that property: declaration order
must not change the result.

### Modules under `src/cot/config/`

`pytest_plugin.py` and `example_plugin.py` are public; every `_`-prefixed
module is internal.

A source implements `load()`; a source backed by an argument parser also
implements `declare()` (`DeclaringSource`), because a parser has to be told an
option exists before it can parse it. File and env sources have nothing to
declare.

`__init__.py` is a pure re-export facade with an explicit `__all__`; `no_implicit_reexport`
is on, so anything public must be listed there.

### Markers (`_annotations.py`)

All markers work as `Annotated[T, marker]`, and via the `T @ marker` shorthand
(`_MarkerMixin.__rmatmul__`).

`prefix` and `name_prefix` are separate on purpose. pytest's logging options
live in the `[pytest]` section but are individually called `log_cli_level` — one
prefix names the section, the other names the options.

### Name mapping

A field's structural path becomes a different name in each source. See
`_names.py`; for `LoggingConfig(prefix="pytest", name_prefix="log")`:

| path | CLI | INI / flat | env | TOML nested |
|---|---|---|---|---|
| `("level",)` | `--log-level` | `log_level` | `PYTEST_LOG_LEVEL` | `[pytest] level` |
| `("cli","level")` | `--log-cli-level` | `log_cli_level` | `PYTEST_LOG_CLI_LEVEL` | `[pytest.cli] level` |

File sources accept both spellings, so a nested table and a flat prefixed key
reach the same field.

### Provenance

Origins are recorded by the manager as it merges, so sources need no changes —
one that says nothing about itself is attributed by class and precedence. A
source that can be more specific implements `describe_origin`.

```python
manager.origin_of(LoggingConfig, "cli.level")   # Origin(kind="env", location="PYTEST_LOG_CLI_LEVEL", ...)
print(manager.explain(LoggingConfig))            # table of field / value / origin
```

### Help

`manager.format_help()` renders the registered options and returns the text.
`manager.help_requested()` reports whether `-h`/`--help` was passed. **Neither
prints nor exits** — this is a library, the application owns the process.

### Precedence ladder

`defaults(-1) < file(15) < addopts(18) < env(20) < cli(25)` — the values live in
`Precedence` (`_precedence.py`) and are the *defaults*, not an enum. Every
source takes `precedence=`, and so does every marker that creates one, so
`TomlSource(path, precedence=Precedence.CLI + 1)` really does outrank a typed
argument.

That is the whole ordering rule: sources are sorted by `precedence` and merged
in order, and nothing is special-cased above the ladder. `ConfigManager.add_source()`
maintains the order, including for sources added during `resolve()`.

`addopts` is a source (`AddoptsSource`), not a splice into `argv`. That is what
lets it sit *below* env and above files, and lets an injected option be reported
as `addopts --level` rather than looking like something the user typed.

### The addopts feedback loop

`resolve()` is deliberately multi-pass, because you cannot know all
sources until you have read some config:

1. collect defaults from the class
2. call `discover()` if the type defines it (may add sources)
3. process `config_source` fields → add the named config file as a source
4. load every source to obtain `addopts`
5. hand addopts to `AddoptsSource`, which parses them at its own precedence
6. re-load everything and merge in precedence order
7. build nested `SubConfig` instances, applying the `from_parent` cascade
8. instantiate and store

Each pass runs for *every* declared type before the next begins, so no fragment
is built against a source a later fragment was about to add.

## Constraints

1. **Type annotations are required** on fields — there is no type inference.
2. **Tests live in `testing/`**, not `tests/` (`testpaths = ["testing"]`).
3. **`mypy --strict` must stay clean.** Use `from __future__ import annotations`,
   `if TYPE_CHECKING:` blocks, and keep `Annotated` metadata by passing
   `include_extras=True` to `get_type_hints`.
4. **Read field metadata through `_fields.iter_fields()`**, never by re-implementing
   a `get_origin(x) is Annotated` loop. That duplication is what the field model
   replaced.
5. `cot` is a **PEP 420 namespace package** — do not add `src/cot/__init__.py`.
   The PEP 561 marker lives at `src/cot/config/py.typed`.
6. Keep inheritance simple. Sub-configs pick up fields via `__mro__`; elaborate
   multiple inheritance causes hard-to-follow field resolution.

## pytest integration (proof of concept)

`cot/config/pytest_plugin.py` **monkeypatches pytest**, adding methods it does
not have. It is **auto-enabled** via a `pytest11` entry point (`cot_config`), so
installing the package is enough — turn it off with `-p no:cot_config`.

The patch is additive only: no option, ini key, hook or behaviour of pytest's is
replaced. Note that `pytest_plugins = [...]` inside a conftest would be *too
late* as an activation route — that conftest's own `pytest_addoption` runs
before its plugin list is processed — which is why the entry point is used.

Because it patches at import time, a type checker cannot see `add_config` /
`get_config`. `manager_for_config(config).get(T)` is the statically-typed
equivalent.

```python
def pytest_addoption(parser):
    parser.add_config(LoggingConfig)      # declare

def pytest_configure(config):
    log = config.get_config(LoggingConfig)   # resolve + get, typed
    config.explain_config(LoggingConfig)     # provenance table
```

**Division of labour.** pytest keeps argument parsing; this library supplies
the structure. Each leaf field becomes a `parser.addoption` and/or
`parser.addini` under the same name mapping every other source uses, and values
come back through `config.getoption` then `config.getini` — pytest's own
`get_option_ini` precedence — to be reassembled into the nested shape, where
defaults and the `from_parent` cascade apply. The intended end state is the
reverse: pytest using the library directly.

Two collision behaviours, both load-bearing for a migration and both tested:

- an **ini key** pytest already declares (`log_level`) is *adopted*, not
  clobbered — the existing help and type survive and the value is read;
- a **CLI option** pytest already owns raises `ConfigLifecycleError` naming the
  field and pointing at `named()`, `no_cli` and `name_prefix`, instead of
  argparse's bare "conflicting option string".

### Example plugin

`cot/config/example_plugin.py` is a working slow-test reporter built on the
PoC — nested structure, `from_parent` cascade, `named()`, `no_cli`, help text,
ini and CLI. It is **not** auto-enabled (it is an example, not infrastructure):

```bash
pytest -p cot.config.example_plugin --timing-report --timing-threshold=0.5
```

Everything it adds lives under `timing_` / `--timing-*`, a namespace pytest does
not use. `testing/test_example_plugin.py` pins that it clobbers nothing: with no
options given it registers no hooks and the run output is unchanged, and
pytest's own `--durations` keeps working alongside it.

## Acceptance test

`testing/test_pytest_logging.py` declares pytest's whole logging plugin — all 13
ini options from `docs/pytest-logging-options.txt` plus the CLI-only
`log_disable` — as one nested structure, and checks each one is reachable by its
real pytest name from ini, TOML, env and CLI, with the fallback chains, the
provenance and the help output. It is the yardstick: a change that makes that
file harder to write is going the wrong way.

## Not implemented yet

Documented in `docs/design/` as intent, but absent from the code. Do not assume these
exist:

- plugin discovery — the `Discoverable` protocol has no implementors
- list merge semantics (append / reset). addopts *do* accumulate now: every
  contribution is appended to the one `AddoptsSource`, later ones winning
- change notification, hot reload, dependency graphs
- validation hooks (construction checks required fields and rejects unknown
  kwargs, but does not coerce types — coercion is `_coerce.py`; what stays in
  each source is *tokenisation*, which genuinely differs between an INI list
  and a repeated CLI option)
