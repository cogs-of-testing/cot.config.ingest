# Names

One declaration, four spellings. This document is the mapping between a field's
structural identity and every name a user can type for it, in both directions.

Every rule here is general. pytest appears as the stress case, because its
option naming is the most demanding example available. Nothing here is pytest
policy. A host may suppress a spelling, never rename one
([the contract](binding-contract.md#what-a-binding-may-not-decide)).

## The qualified path

A field's qualified path is its structural path with the root's `name_prefix`
prepended as a segment:

```
path            ("cli", "level")
name_prefix     "log"
qualified       ("log", "cli", "level")
```

Every spelling is that one path rendered with a different separator:

| spelling | rule | `("cli", "level")` |
|---|---|---|
| flat (ini, flat TOML) | `"_".join(qualified)` | `log_cli_level` |
| CLI | `"-".join(qualified)` | `--log-cli-level` |
| env | `"_".join([prefix, *qualified])`, upper; the source puts its own prefix in front | `PYTEST_LOG_CLI_LEVEL` |
| `-o` | the flat name | `-o log_cli_level=…` |
| nested file | `[section, *qualified[:-1]]` + leaf | `[pytest.log.cli] level` |

`section`, and the `prefix` segment of the env spelling, come from `prefix=`,
which is a separate axis ([below](#prefix-versus-name_prefix)). The source
prefix is the `EnvSource`'s own; an empty one contributes no segment, so
`EnvSource()` is what reads `PYTEST_LOG_CLI_LEVEL` for a part with
`prefix="pytest"`, and `EnvSource("PYTEST")` would read
`PYTEST_PYTEST_LOG_CLI_LEVEL`. An ordinary application:

```python
class PoolConfig(ConfigPart):
    size: int = 5

class DatabaseConfig(ConfigPart, prefix="app", name_prefix="db"):
    host: str = "localhost"
    pool: PoolConfig
```

| path | flat | CLI | env | nested |
|---|---|---|---|---|
| `("host",)` | `db_host` | `--db-host` | `APP_DB_HOST` | `[app.db] host` |
| `("pool", "size")` | `db_pool_size` | `--db-pool-size` | `APP_DB_POOL_SIZE` | `[app.db.pool] size` |

The stress case, `LoggingConfig(ConfigPart, prefix="pytest", name_prefix="log")`,
has a shared section, a three-level path and a field whose conventional name
does not match its structure:

| path | flat | CLI | env | nested |
|---|---|---|---|---|
| `("level",)` | `log_level` | `--log-level` | `PYTEST_LOG_LEVEL` | `[pytest.log] level` |
| `("cli", "level")` | `log_cli_level` | `--log-cli-level` | `PYTEST_LOG_CLI_LEVEL` | `[pytest.log.cli] level` |
| `("file", "path")` | `log_file` * | `--log-file` | `PYTEST_LOG_FILE` | `[pytest.log.file] path` |

\* via `named("log_file")`, which replaces the flat name only. See
[per-field overrides](#per-field-overrides).

`FieldNames` is the record; `names_of()` produces it. The reverse direction is
[the spelling index](#the-spelling-index).

## prefix versus name_prefix

`prefix=` names the section a root occupies in a config file, and the default
environment-variable prefix. It is not part of any option name.

`name_prefix=` leads every field name, in every source. It is part of the
option name.

pytest needs both at once: its logging options live in the `[pytest]` section
and are individually called `log_cli_level`.

`prefix` is shared: every pytest plugin's options live in `[pytest]`, so it
cannot distinguish one root from another. `name_prefix` is the root's identity
inside that shared section, and the only thing that keeps `log_cli_level` and
`cache_cli_level` apart. Any spelling that drops `name_prefix` drops the
root's identity.

An `EnvSource`'s own prefix and the root's `prefix` compose: `EnvSource("APP")`
reading a root with `prefix="log"` looks at `APP_LOG_*`.

### When there is no prefix

A root with no `prefix=` has no section of its own: its keys sit at the top
level of the file, and its variables under the source's prefix alone. Nesting
is opt-in, so an application with a single root writes a flat config file. A
class name is never a section: it is an implementation detail, and renaming
the class would silently move the section.

## Two spellings in files

A nested table and a flat key reach the same field:

```toml
[pytest.log.cli]
level = "DEBUG"
# identical to
[pytest]
log_cli_level = "DEBUG"
```

These are the only two. The flat spelling is a key directly in the section.
The nested spelling is the full structural path as tables, with the bare field
name as the key. A key at an intermediate depth, `[pytest.log] cli_level`, is
unknown.

Anything in between would be ambiguous. `("file", "path")` is
`[pytest.log.file] path` nested and `[pytest] log_file` flat, via `named()`.
Allow `[pytest.log] file` and it means both the `file` table and the renamed
leaf. Field names may also contain underscores, so `log_file_date_format` has
no unique split. The two spellings are therefore not derived from each other
by splitting or joining; each is looked up in
[the index](#the-spelling-index) as what it is. Rationale in
[D24](decisions.md#d24).

The nested spelling carries `name_prefix` as a segment. Without it two roots
sharing the `[pytest]` section, differing only in `name_prefix` and each with a
`cli` nested part, would both read `[pytest.cli] level`. `[pytest.log.cli]`
and `[pytest.cache.cli]` are distinct tables. Rationale in
[D8](decisions.md#d8).

## Unknown keys are judged across every declared root

A shared section means a source sees keys that belong to several roots. A key
is unknown only when [the index](#the-spelling-index), which holds every
declared root, resolves it to nothing. No root judges, so no root warns about
another root's keys, and the warning never fires on correct configuration
([I8](invariants.md#i8)). What happens to an unknown key is
[merging](merging.md#unknown-keys).

## Per-field overrides

`named("log_file")` replaces the derived flat name outright. CLI and env
spellings are re-derived from the override, so all three stay consistent. It
exists for fields whose structural path and conventional name diverge:
`file.path` would derive `log_file_path`, but pytest calls it `log_file`.

`named()` does not affect the nested spelling. `("file", "path")` stays
`[pytest.log.file] path` nested and `[pytest] log_file` flat.

`no_cli` suppresses the CLI option only. The field keeps its file key and
environment variable. pytest's `log_cli` is an ini-only switch of this kind.

`no_ini` is the mirror of `no_cli`: it suppresses the file spelling and keeps
the CLI option and, with `from_env`, the environment variable. A host that
wants command-line-only options, or that scopes an override flag to file-backed
fields, needs "has a file spelling" to be able to be false. It is `file_key`
in [specs](specs.md#the-record).

`short("v")` adds a short option to the field's own CLI form. `-o` and `-h`
are reserved. Further forms, and forms that supply a constant, are
[`form()`](specs.md#cli-forms).

`env_named("SOURCE_DATE_EPOCH")` pins an absolute environment variable name: no
source prefix, no root prefix, no derivation. It exists for cross-tool
conventions that every tool must spell identically. `named()` cannot serve,
because the environment spelling is derived from the flat name it replaces.
`env_named` sets one spelling and states it literally. A field carrying it
still needs [`from_env`](sources.md#exposure-is-opt-in) to be read at all.

`formerly("write_to")` declares a legacy flat spelling. The field stays
reachable under it from every source that has a flat spelling, a value arriving
that way fires [`DeprecatedNameWarning`](diagnostics.md#warnings), and the
spelling reaches a binding as [`FieldSpec.aliases`](specs.md#the-record). It is
the only way an alias comes to exist: `named()` replaces the derived name and
leaves nothing behind.

## The -o override key

```
-o log_cli_level=DEBUG      # the ini spelling
```

The `-o` key is the flat name, the same string the ini file uses. Overrides are
collected by a source of their own at
[`override(30)`](sources.md#the-two-rungs-above-the-command-line), above the
command line. `--log-level=A -o log_level=B` is `B`, and so is the same `-o`
carried by [injected arguments](lifecycle.md#the-injected-arguments-loop).

A `-o` key matching no field is an
[`UnknownOverrideKeyWarning`](diagnostics.md#warnings) naming the key and the
roots that were searched ([I8](invariants.md#i8)).

Rationale in [D1](decisions.md#d1). What `-o` reports as its origin is covered
in [reporting](reporting.md#overrides-report-as-overrides).

Which fields `-o` may reach is a [binding](binding-contract.md) matter. A host
may narrow it to file-backed fields, and the pytest binding does. The
addressing above is not negotiable.

## The spelling index

`_names.py` derives spellings from paths. The manager's `SpellingIndex`, built
at `declare()` over every declared root, resolves spellings back to paths.
Those are the only two places a source-facing name is produced or recognised
([I1](invariants.md#i1)). A source asks the index; it never splits a key,
strips a prefix or compares token strings.

```python
index.flat("log_cli_level")                        # -> LoggingConfig, ("cli", "level")
index.nested("pytest", ("log", "cli"), "level")    # -> the same
index.cli("--log-cli-level")                       # -> the same
index.env("PYTEST_LOG_CLI_LEVEL")                  # -> the same, for an EnvSource with no prefix
```

Each lookup returns the root and the path, or nothing. The
[`-o` key](#the-o-override-key) resolves through `flat()`, and
`bootstrap_only` enforcement through `cli()`.

The flat name, and with it the CLI option and the `-o` key, is one namespace
across every declared root, whatever their `prefix`. `prefix` places keys in a
file section and variables under an environment prefix; it does not scope
option names, because `--log-level` has no section. A binding that scopes `-o`
scopes which fields it reaches, never which namespace it reads.

## Collisions

Two roots declaring the same flat name, or one root's alias matching another's
name, is one rule for every backend:

- specs identical in everything but path: **adoption**. One spelling, both
  roots read it. This is the migration case, a plugin and its host declaring
  the same option during a transition.
- anything else: [`ConfigCollisionError`](diagnostics.md#errors) naming both
  roots, the field paths and the ways out (`named()`, `no_cli`,
  `name_prefix`), raised at `declare()` because the declaration is wrong.

Adoption compares the whole [spec](specs.md), so the index holds one spec and
it does not matter which root supplied it ([I3](invariants.md#i3)).

A file key the host already declares is always adopted, never clobbered: the
existing help and type survive and the value is read. Which host keys exist is
a [binding](binding-contract.md) matter.
