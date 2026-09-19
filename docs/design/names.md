# Names

One declaration, four spellings. This document is the mapping between a field's
structural identity and every name a user can type for it.

It carries the most outstanding **[change]** rules, because
[I1](invariants.md#i1) is the invariant the code has drifted furthest from.

Every rule here is general. pytest appears as the stress case, because its
option naming is the most demanding example available. Nothing here is pytest
policy. A host may suppress a spelling, never rename one
([the contract](binding-contract.md#what-a-binding-may-not-decide)).

## The qualified path

A field's qualified path is its structural path with the ConfigPart's
`name_prefix` prepended as a segment:

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
| env | `"_".join([source prefix, prefix, *qualified])`, upper | `PYTEST_LOG_CLI_LEVEL` |
| `-o` | the flat name | `-o log_cli_level=…` |
| nested file | `[section, *qualified[:-1]]` + leaf | `[pytest.log.cli] level` |

`section`, and the `prefix` segment of the env spelling, come from `prefix=`,
which is a separate axis ([below](#prefix-versus-name_prefix)). The source
prefix is the `EnvSource`'s own; an empty one contributes no segment, so
`EnvSource()` is what reads `PYTEST_LOG_CLI_LEVEL` for a part with
`prefix="pytest"`, and `EnvSource("PYTEST")` would read
`PYTEST_PYTEST_LOG_CLI_LEVEL`. An ordinary application:

```python
class PoolConfig(SubConfig):
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

The flat name split on `_` is the nested table path. The two spellings are
derivable from each other.

**[change]**: the nested spelling currently omits `name_prefix`
(`[pytest.cli] level`), which is the one place a part's identity is dropped. See
[both spellings](#both-spellings-in-files) and [D8](decisions.md#d8).

`FieldNames` is the record; `names_of()` produces it; `flat_index()` inverts it.
**[built]**

## prefix versus name_prefix

`prefix=` names the section a ConfigPart occupies in a config file, and the
default environment-variable prefix. It is not part of any option name.

`name_prefix=` leads every field name, in every source. It is part of the
option name.

pytest needs both at once: its logging options live in the `[pytest]` section
and are individually called `log_cli_level`. **[built]**

`prefix` is shared: every pytest plugin's options live in `[pytest]`, so it
cannot distinguish one ConfigPart from another. `name_prefix` is the
ConfigPart's identity inside that shared section, and the only thing that keeps
`log_cli_level` and `cache_cli_level` apart. Any spelling that drops
`name_prefix` drops the part's identity.

An `EnvSource`'s own prefix and the part's `prefix` compose: `EnvSource("APP")`
reading a part with `prefix="log"` looks at `APP_LOG_*`. **[built]**

### When there is no prefix

A part with no `prefix=` has no section of its own: its keys sit at the top
level of the file, and its variables under the source's prefix alone. Nesting is
opt-in, so an application with a single ConfigPart writes a flat config file.
**[change]**: today the file side names the section after the class
(`[LoggingConfig]`, undowncased) while the environment drops the segment. A
section named after a Python class exposes an implementation detail, and
renaming the class silently moves the section.

## Both spellings in files

A nested table and a flat key reach the same field:

```toml
[pytest.log.cli]
level = "DEBUG"
# identical to
[pytest]
log_cli_level = "DEBUG"
```

`expand_flat_keys()` rewrites recognised flat keys into their structural paths;
keys that are already structural pass through. A key that matches neither is
kept, so the manager can report it as unknown ([I8](invariants.md#i8)).
**[built]** as a mechanism, **[change]** in what counts as the structural
spelling.

Without the `log` segment the nested spelling cannot say which ConfigPart it
means, and two plugins sharing the `[pytest]` section receive each other's
values:

```toml
[pytest.cli]
level = "NESTED"
```
```
Logging.cli.level = NESTED      Cache.cli.level = NESTED    # both, silently
```

Both parts declare `prefix="pytest"`, differ only in `name_prefix`, and each
has a `cli` sub-config. The flat spelling keeps them apart
(`log_cli_level` versus `cache_cli_level`); today the nested spelling cannot.
With `name_prefix` as a path segment, `[pytest.log.cli]` and
`[pytest.cache.cli]` are distinct tables.

## Unknown keys are judged across the section

A shared section means a ConfigPart sees keys that belong to other parts.
Unknown-key detection therefore belongs to the manager, which knows every
declared type. A key is unknown only when no declared ConfigPart claims it.

**[change]**: detection is per part today, so parts sharing a section warn
about each other:

```
UnknownConfigKeyWarning: Unknown config option(s) for Logging: cache_cli_level
UnknownConfigKeyWarning: Unknown config option(s) for Cache: log_cli_level
```

The warning fires on correct configuration, which
[I8](invariants.md#i8) forbids. See [D8](decisions.md#d8), and
[merging](merging.md#unknown-keys) for what happens to a key once it is judged
unknown.

## Per-field overrides

`named("log_file")` replaces the derived flat name outright. CLI and env
spellings are re-derived from the override, so all three stay consistent. It
exists for fields whose structural path and conventional name diverge:
`file.path` would derive `log_file_path`, but pytest calls it `log_file`.
**[built]**

`named()` does not affect the nested spelling. `("file", "path")` stays
`[pytest.log.file] path` nested and `[pytest] log_file` flat.

`no_cli` suppresses the CLI option only. The field keeps its ini key and
environment variable. pytest's `log_cli` is an ini-only switch of this kind.
**[built]**

`short("v")` adds a short option. `-o` and `-h` are reserved. **[built]**

`env_named("SOURCE_DATE_EPOCH")` pins an absolute environment variable name: no
source prefix, no part prefix, no derivation. **[new]**

It exists for cross-tool conventions that every tool must spell identically.
`named()` cannot serve, because the environment spelling is derived from the
flat name it replaces. `env_named` sets one spelling and states it literally. A
field carrying it still needs [`from_env`](sources.md#exposure-is-opt-in) to be
read at all.

`formerly("write_to")` declares a legacy flat spelling. The field stays
reachable under it from every source that has a flat spelling, a value arriving
that way fires [`DeprecatedNameWarning`](diagnostics.md#warnings), and the
spelling reaches a binding as [`FieldSpec.aliases`](specs.md#the-record). It is
the only way an alias comes to exist: `named()` replaces the derived name and
leaves nothing behind. **[new]**

`no_ini` is the mirror of `no_cli`: it suppresses the file spelling and keeps
the CLI option and, with `from_env`, the environment variable. A host that
wants command-line-only options, or that scopes an override flag to file-backed
fields, needs "has a file spelling" to be able to be false. **[new]**, tracked
as `file_key` in [specs](specs.md).

## The -o override key

```
-o log_cli_level=DEBUG      # the ini spelling
```

The `-o` key is the flat name, the same string the ini file uses.
**[change]**: it is currently the structural path, so with a `name_prefix` in
play the user must write `-o cli.level=DEBUG`, a third namespace that appears
nowhere else. The two spellings a user has seen, `log_cli_level` and
`log.cli.level`, both silently do nothing today.

Overrides are collected by a source of their own at
[`override(30)`](sources.md#the-two-rungs-above-the-command-line), above the
command line. `--log-level=A -o log_level=B` is `B`, and so is the same `-o`
carried by [injected arguments](lifecycle.md#the-injected-arguments-loop).
**[new]**: `-o` is applied as a post-merge fixup today, so what it outranks is
undefined.

A `-o` key matching no field is an
[`UnknownOverrideKeyWarning`](diagnostics.md#warnings) naming the key and the
ConfigPart ([I8](invariants.md#i8)). **[change]**: currently silent.

Rationale in [D1](decisions.md#d1). The dotted-path spelling is not retained as
an alias. What `-o` reports as its origin is covered in
[reporting](reporting.md#overrides-report-as-overrides).

Which fields `-o` may reach is a [binding](binding-contract.md) matter. A host
may narrow it to file-backed fields, and the pytest binding does. The addressing
above is not negotiable.

## Names are never constructed by hand

Five places build or match a source-facing name without going through
`_names.py`, and all five are wrong at the edges ([I1](invariants.md#i1)):

| Place | Symptom |
|---|---|
| the nested file spelling | drops `name_prefix` ([above](#the-qualified-path)); the only user-visible one |
| `_reject_bootstrap_only` | compares `--app-config-file` to the bare field name `config_file`; never matches when a `name_prefix` exists, so the guard does nothing |
| `_apply_overrides` | [the `-o` key](#the-o-override-key) |
| `ConfigFileDiscoverySource(config_file_cli_arg="config_file")` | a raw string that is only correct with no `name_prefix` |
| the `config_source` / `addopts_field` / `bootstrap_only` scans | `recurse=False`, so the markers vanish inside a `SubConfig` ([I7](invariants.md#i7)) |

All five route through `flat_index()`, `names_of()` and `leaf_fields()`.
**[change]** Rationale in [D7](decisions.md#d7); the nested spelling has its own
decision, [D8](decisions.md#d8).

## Collisions

Two ConfigParts declaring the same flat name is one rule for every backend:

- identical declared type and identical default: **adoption**. One option, both
  parts read it. This is the migration case, a plugin and its host declaring the
  same option during a transition.
- anything else: [`ConfigCollisionError`](diagnostics.md#errors) naming both
  ConfigParts, the field paths and the ways out (`named()`, `no_cli`,
  `name_prefix`), raised at `declare()` because the declaration is wrong.

**[change]**: the native CLI source silently skips the second registration and
lets the second part read a value parsed under the first part's type, while the
pytest binding raises a `ConfigLifecycleError`. Two bindings disagreeing about a
core rule is what [conformance](binding-contract.md#conformance) exists to
catch. A third spelling, an unexported `CLIConflictError` in the CLI parser, is
why the error gets a [named type](diagnostics.md#errors).

A file key the host already declares is always adopted, never clobbered: the
existing help and type survive and the value is read. **[built]**
