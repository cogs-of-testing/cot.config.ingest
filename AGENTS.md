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
config = manager.register_fragment_type(LoggingConfig)   # returns the instance
```

### Modules under `src/cot/config/`

| Module | Contents |
|---|---|
| `_bases.py` | `ConfigPart`, `SubConfig` — frozen, kwargs-constructed, `@dataclass_transform` |
| `_annotations.py` | Field/class markers, all usable inside `Annotated[...]` |
| `_fields.py` | `FieldInfo` + `fields_of()` — the single field model everything reads |
| `_names.py` | Field path → per-source name mapping (CLI / ini / env / TOML) |
| `_origins.py` | `Origin` — where a value came from, and the optional `OriginAware` protocol |
| `_manager.py` | `ConfigManager`, the `ConfigSource` and `Discoverable` protocols |
| `_sources.py` | `TomlSource`, `IniSource`, `CLISource`, `EnvSource`, `ConfigFileDiscoverySource` |
| `_cli_parser.py` | `CLIParser` — hand-rolled, re-parses on demand, supports dynamic field registration |

`__init__.py` is a pure re-export facade with an explicit `__all__`; `no_implicit_reexport`
is on, so anything public must be listed there.

### Markers (`_annotations.py`)

All markers work as `Annotated[T, marker]`, and via the `T @ marker` shorthand
(`_MarkerMixin.__rmatmul__`).

| Marker | Purpose |
|---|---|
| `from_parent` | Value cascades from the enclosing config when the child does not set it |
| `prefix="x"` (class kwarg) | Section name in files, and default env prefix. **Not** part of option names |
| `name_prefix="x"` (class kwarg) | Prefixes every *field name*, in every source (`log_cli_level`) |
| `named("log_file")` | Overrides one field's derived name everywhere |
| `no_cli` | Field gets no CLI option (file/env only) |
| `help("text")` | Help text, rendered by `format_help()` |
| `config_source` | Field's value is a config file path; it gets added as a source |
| `bootstrap_only` | Field may not be set via addopts — CLI/bootstrap only |
| `addopts_field` | Field's value is re-parsed as CLI args and prepended |
| `short("v")` | Adds a `-v` short option |

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

`defaults < file(15) < addopts(18) < env(20) < cli(25)`

Sources are kept sorted by `precedence`; higher wins. `ConfigManager.add_source()`
maintains the order.

### The addopts feedback loop

`register_fragment_type()` is deliberately multi-pass, because you cannot know all
sources until you have read some config:

1. collect defaults from the class
2. register fields with `CLISource`, parse CLI
3. call `discover()` if the type defines it (may add sources)
4. process `config_source` fields → add the named config file as a source
5. load from file/env sources to obtain `addopts`
6. prepend addopts to `CLISource` and re-parse
7. re-load everything, merge `defaults < sources < cli`
8. build nested `SubConfig` instances, applying the `from_parent` cascade
9. instantiate and store

## Developer Workflows

The repo is **uv**-based. `[tool.uv] default-groups = ["test", "typing", "lint"]`
means `uv run` already has pytest, mypy and ruff available.

```bash
uv run pytest -q                 # all tests
uv run pytest testing/test_sources.py -q
uv run pytest -q -k test_name
uv run mypy src                  # strict
uv run ruff check src testing
pre-commit run -a                # everything, incl. zizmor on workflows
```

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

- plugin discovery (bootstrap stage 3) — the `Discoverable` protocol has no implementors
- list merge semantics (append / reset), addopts accumulation across several files
- change notification, hot reload, dependency graphs
- validation hooks (construction checks required fields and rejects unknown
  kwargs, but does not coerce types — coercion lives in the sources, where the
  raw string context is)
