# cot.config.ingest

Type-safe configuration management with multi-source ingestion.

## Overview

`cot.config.ingest` is an experimental Python library that simplifies configuration management by providing a unified way to ingest configuration from:

- **CLI arguments** (built-in parser, no argparse required)
- **Environment variables**
- **Configuration files** (TOML, INI)

The library uses dataclass-like `ConfigPart` classes to define configuration structure, then automatically handles loading and merging from multiple sources.

## Key Features

- **Type-safe configuration** with Python type hints
- **Multiple sources** with automatic merging and precedence
- **Origin tracking** to debug where values come from
- **Hierarchical configs** with SubConfig composition
- **Value cascade** from parent config to sub-configs via `from_parent`
- **Bootstrap feedback** — config files and `addopts` discovered from earlier stages

> Not implemented yet: plugin discovery, list append/reset merge semantics, change
> notification and hot reload. Those appear in the design documents as intent only.

## Quick Example

```python
import sys
from typing import Annotated

from cot.config import (
    CLISource, ConfigManager, ConfigPart, EnvSource, SubConfig, from_parent,
)

class DatabaseConfig(SubConfig):
    host: Annotated[str, from_parent] = "localhost"
    port: int = 5432

class AppConfig(ConfigPart, prefix="app"):
    debug: bool = False
    database: DatabaseConfig

manager = ConfigManager(sources=[
    CLISource(sys.argv[1:]),
    EnvSource("APP"),
])
manager.declare(AppConfig)
config = manager.get(AppConfig)

print(f"Connecting to {config.database.host}:{config.database.port}")
```

Configuration has three phases: `declare()` registers a type and its options,
`resolve()` runs the bootstrap once for everything declared, and `get()` returns
the built instance. `get()` resolves implicitly, so `resolve()` only matters when
you want to pin the moment configuration freezes. Declaring after that raises
`ConfigLifecycleError`.

## pytest — a hack, on purpose

!!! warning "Installing this package patches pytest"

    `cot.config.pytest_plugin` **monkeypatches pytest**, adding
    `Parser.add_config`, `Config.get_config` and `Config.explain_config`. It is
    registered as a `pytest11` entry point and patches at *import* time, so
    installing the package activates it — in every environment it lands in,
    including as a transitive dependency.

    The patch is additive only: no option, ini key, hook or behaviour of
    pytest's is replaced. Turn it off with `-p no:cot_config`.

    This is deliberate for the proof of concept and is not how a stable release
    should behave. It is planned for removal in favour of importable
    `add_config(parser, T)` / `get_config(config, T)` functions — see
    [D11](design/decisions.md#d11) and [Evolution](design/evolution.md).

A conftest-level `pytest_plugins = [...]` would be too late as an activation
route — that conftest's own `pytest_addoption` runs before its plugin list is
processed — which is why the entry point is used.

With it in place, a plugin can `parser.add_config(...)` in `pytest_addoption`
and `config.get_config(...)` afterwards. Because the patch happens at import
time, a type checker cannot see those methods;
`manager_for_config(config).get(T)` is the statically-typed equivalent.

`cot.config.example_plugin` is a worked example — a slow-test reporter, opt-in
with `-p cot.config.example_plugin`:

```ini
[pytest]
timing_report = true
timing_threshold = 0.5
timing_file = timings.txt
```

```bash
pytest --timing-report --timing-terminal-threshold=1.0
```

## Project Status

**Experimental**: the API is still moving. See `AGENTS.md` for the as-built architecture.

## Documentation

### Getting Started

- [Inspiration](getting-started/inspiration.md) - Why this project exists

### Design

[**Design**](design/index.md) is the normative specification, split by component.
Every rule is marked **[built]**, **[change]** or **[new]**, so the design and
the gap between it and the code are one artifact rather than two that drift
apart. The [gap list](design/index.md#gap-list) collects every outstanding rule
in one table.

| Document | What it settles |
|----------|-------------|
| [Invariants](design/invariants.md) | The eight rules everything else follows from |
| [ConfigParts](design/config-parts.md) | Classes, fields, the field model, frozen semantics |
| [Names](design/names.md) | The qualified path, `prefix`/`name_prefix`, `named()`, `-o` |
| [Types](design/types.md) | Coercion, unions, `Literal`, where type checking happens |
| [Sources](design/sources.md) | The source protocol, the precedence ladder, CLI parsing |
| [Lifecycle](design/lifecycle.md) | declare → resolve → get, and the feedback passes |
| [Merging](design/merging.md) | Deep merge, unknown keys, `from_parent` cascade |
| [Reporting](design/reporting.md) | Provenance and help |
| [Host adapters](design/host-adapters.md) | The pytest proof of concept, and conformance |
| [Evolution](design/evolution.md) | The staged plan toward replacing pytest's config layer |
| [Decisions](design/decisions.md) | Review findings, resolved, with rationale and cost |
| [Deferred](design/deferred.md) | Absent from the code, plus the open questions |

Start with [Invariants](design/invariants.md) — they are short, and everything
else refers back to them.
