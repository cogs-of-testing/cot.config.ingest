# cot.config.ingest

Declare configuration once, as annotated classes, and ingest it from CLI
arguments, environment variables and config files. The merge order, the name
mapping and the provenance all fall out of the declaration.

> **Experimental.** The API moves between releases and there is no deprecation
> policy yet.

> **Installing this package patches pytest.** See
> [pytest](#pytest-a-hack-on-purpose) before installing it anywhere you care
> about. `-p no:cot_config` turns it off.

Every code block on this page is executed by `testing/test_docs_index.py`, so
what it shows is what the code does today. Where the
[design](design/index.md) commits to something else, a note says so.

## Declaring

A `ConfigPart` is the unit an application declares, and a `ConfigPart` used as
the type of another one's field is a nested section inside it. There is one
class, and the declaration decides which role it plays. Markers on a field say
what the annotation cannot:

```python
from typing import Annotated

from cot.config import ConfigPart, from_parent, help


class PoolConfig(ConfigPart):
    size: Annotated[int, help("connections to keep open")] = 5
    timeout: Annotated[float | None, from_parent, help("seconds before giving up")] = None


class DatabaseConfig(ConfigPart, prefix="app", name_prefix="db", from_env=True):
    host: Annotated[str, help("database host")] = "localhost"
    timeout: Annotated[float | None, help("seconds before giving up")] = None
    pool: PoolConfig
```

`from_parent` on `pool.timeout` makes it fall back to `timeout` when nothing
sets it directly. `prefix="app"` is the config-file section and the environment
namespace; `name_prefix="db"` leads every option name. They are separate knobs
because a section is shared between parts and a name prefix is not
([names](design/names.md#prefix-versus-name_prefix)). `from_env=True` makes
every field readable from the environment, which no field is unless it says so
([sources](design/sources.md#exposure-is-opt-in)).

The full marker set is in [ConfigParts](design/config-parts.md#markers).

## Reading

```python
import sys
from pathlib import Path

from cot.config import CLISource, ConfigManager, EnvSource, TomlSource

manager = ConfigManager(sources=[
    TomlSource(Path("app.toml")),
    EnvSource(),                 # prefix="app" on the part supplies APP_
    CLISource(sys.argv[1:]),
])
manager.declare(DatabaseConfig)

config = manager.get(DatabaseConfig)
config.pool.size          # int, from whichever source won
config.pool.timeout       # falls back to config.timeout
```

Three phases: `declare()` registers a type and its options, `resolve()` runs
the iteration to a fixpoint for everything declared, `get()` returns the built
instance. `get()` resolves implicitly; calling `resolve()` yourself pins the
moment configuration freezes, and declaring after that raises
`ConfigLifecycleError`. The split exists because a host collects declarations
from independent plugins before any of them can be resolved
([lifecycle](design/lifecycle.md)).

## Names

One structural path, one spelling per source:

| path | CLI | INI / flat | env | TOML nested |
|---|---|---|---|---|
| `("host",)` | `--db-host` | `db_host` | `APP_DB_HOST` | `[app.db] host` |
| `("pool", "size")` | `--db-pool-size` | `db_pool_size` | `APP_DB_POOL_SIZE` | `[app.db.pool] size` |

File sources accept both spellings, so this file sets `host` and `pool.size`:

```toml
[app]
db_host = "db.internal"

[app.db.pool]
size = 20
```

`name_prefix` is a segment of the nested spelling, which is what keeps two
parts sharing a section from reading each other's tables
([names](design/names.md#the-qualified-path)).

## Precedence

```
defaults(-1) < file(15) < named file(16) < injected(18) < env(20) < cli(25) < override(30) < runtime(40)
```

A file a `config_source` field names outranks one found by searching, `-o`
outranks the option it addresses, and a [runtime write](design/lifecycle.md#the-runtime-layer)
is the top ([the ladder](design/sources.md#the-precedence-ladder)). No two
sources may share a rung.

These are defaults, not an enum. Every source takes `precedence=`, and that
number is the only thing that decides a winner:

```python
from cot.config import Precedence, TomlSource

TomlSource(path, precedence=Precedence.CLI + 1)   # outranks a typed argument
```

## Where did this value come from?

With the file above, `APP_DB_TIMEOUT=2.5` in the environment and
`--db-pool-size 8` on the command line:

```python
manager.origin_of(DatabaseConfig, "pool.timeout")
# Origin(kind="env", location="inherited from timeout (APP_DB_TIMEOUT)", precedence=20)

print(manager.explain(DatabaseConfig))
```

```
DatabaseConfig:
field         value          origin
-----------------------------------
host          'db.internal'  file:app.toml[app.db_host]
timeout       2.5            env:APP_DB_TIMEOUT
pool.size     8              cli:--db-pool-size (over file:app.toml[app.db.pool.size])
pool.timeout  2.5            env:inherited from timeout (APP_DB_TIMEOUT)
```

A cascaded value is attributed to wherever the parent got it, never to the
child's default. A value that beat another names what it beat, so a file
setting that did not apply is visible. An option injected through an `injected_args` field reports
as `injected --db-pool-size (app.toml[addopts])` rather than looking like
something you typed.

## Help

`manager.format_help()` renders every declared option from its spec, grouped
by part, with the file key each one corresponds to, and returns the text.
`manager.help_requested()` reports whether `-h` or `--help` was passed. Neither
prints nor exits; the application owns the process.

```
usage: app [options]

options:
  -h, --help               show this help
  -o KEY=VALUE             set any option by its file key

db:
  --db-host VALUE          database host  [file key: db_host]
  --db-pool-size VALUE     connections to keep open  [file key: db_pool_size]
  --db-pool-timeout VALUE  seconds before giving up  [file key: db_pool_timeout]
  --db-timeout VALUE       seconds before giving up  [file key: db_timeout]
```

## pytest, a hack on purpose

!!! warning "Installing this package patches pytest"

    `cot.config.pytest_plugin` **monkeypatches pytest**, adding
    `Parser.add_config`, `Config.get_config` and `Config.explain_config`. It is
    registered as a `pytest11` entry point and patches at *import* time, so
    installing the package activates it in every environment it lands in,
    including as a transitive dependency.

    The patch is additive only: no option, ini key, hook or behaviour of
    pytest's is replaced. Turn it off with `-p no:cot_config`.

    This is deliberate for the proof of concept and is not how a stable release
    should behave. It is planned for removal in favour of importable
    `add_config(parser, T)` / `get_config(config, T)` functions; see
    [P1](design/pytest/decisions.md#p1) and
    [Evolution](design/pytest/evolution.md).

A conftest-level `pytest_plugins = [...]` would be too late as an activation
route, because that conftest's own `pytest_addoption` runs before its plugin
list is processed, which is why the entry point is used.

With it in place, a plugin declares in `pytest_addoption` and reads afterwards:

```python
def pytest_addoption(parser):
    parser.add_config(DatabaseConfig)        # declare

def pytest_configure(config):
    db = config.get_config(DatabaseConfig)   # resolve + get, typed
    config.explain_config(DatabaseConfig)    # provenance table
```

Because the patch happens at import time, a type checker cannot see those
methods; `manager_for_config(config).get(T)` is the statically typed
equivalent. An ini key pytest already declares is adopted rather than
clobbered, and a colliding CLI option raises `ConfigLifecycleError` naming the
field.

`cot.config.example_plugin` is a worked example: a slow-test reporter with a
nested structure, the `from_parent` cascade, `named()`, `no_cli`, help text,
ini and CLI. It is not auto-enabled:

```ini
[pytest]
timing_report = true
timing_threshold = 0.5
timing_file = timings.txt
```

```bash
pytest -p cot.config.example_plugin --timing-report --timing-threshold=0.5
```

## Where the code and the design differ

[**Design**](design/index.md) is the normative specification, split by
component. The code is being rebuilt to it
([D20](design/decisions.md#d20)) in [the build order](design/index.md#build-order);
until that lands, the code is the pre-rebuild shape and the design describes
the target.

Absent from the code either way: plugin discovery, list append and reset merge
semantics, YAML files, and change notification. Those are
[deferred](design/deferred.md) and never to be assumed.

## The documents

| Document | What it settles |
|----------|-------------|
| [Inspiration](getting-started/inspiration.md) | Why this project exists |
| [Invariants](design/invariants.md) | The eight rules everything else follows from |
| [ConfigParts](design/config-parts.md) | Classes, fields, the field model, frozen semantics |
| [Names](design/names.md) | The qualified path, `prefix`/`name_prefix`, `named()`, `-o` |
| [Types](design/types.md) | Coercion, unions, `Literal`, where type checking happens |
| [Sources](design/sources.md) | The source protocol, the precedence ladder, CLI parsing |
| [Lifecycle](design/lifecycle.md) | declare, resolve, get, and the feedback passes |
| [Merging](design/merging.md) | Deep merge, unknown keys, `from_parent` cascade |
| [Specs](design/specs.md) | What an option is, as data, in the library's vocabulary |
| [Reporting](design/reporting.md) | Provenance and help |
| [Diagnostics](design/diagnostics.md) | The warning and error set, and which one an input gets |
| [Binding contract](design/binding-contract.md) | The core/host boundary, and conformance |
| [Decisions](design/decisions.md) | D1 to D34, core, with rationale and cost |
| [Deferred](design/deferred.md) | Absent from the code, plus the open questions |

Those are **core**, true for every host and for an application with no host.
pytest's own policy is separate and may not be cited by a core document:

| Document | What it settles |
|----------|-------------|
| [pytest binding](design/pytest/index.md) | the adapter as it is today |
| [pytest: Evolution](design/pytest/evolution.md) | the staged plan to replace pytest's config layer |
| [pytest: Decisions](design/pytest/decisions.md) | P1 to P8, pytest policy |
| [vcs-versioning](design/vcs-versioning/index.md) | a candidate binding, evaluated against the design |

Start with [Invariants](design/invariants.md); they are short, and everything
else refers back to them. Read
[the binding contract](design/binding-contract.md) before anything under
`pytest/`.
