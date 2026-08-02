# Names

One declaration, four spellings. This document is the mapping between a field's
structural identity and every name a user can type for it.

It is the densest part of the design, and the one with the most outstanding
**[change]** rules, because [I1](invariants.md#i1) — *a field's identity is its
path* — is the invariant the code has drifted furthest from.

## The qualified path

A field's **qualified path** is its structural path with the ConfigPart's
`name_prefix` prepended as a segment:

```
path            ("cli", "level")
name_prefix     "log"
qualified       ("log", "cli", "level")
```

Every spelling is that one path rendered with a different separator. Nothing else
varies:

| spelling | rule | `("cli", "level")` |
|---|---|---|
| flat (ini, flat TOML) | `"_".join(qualified)` | `log_cli_level` |
| CLI | `"-".join(qualified)` | `--log-cli-level` |
| env | source prefix + `"_"` + flat, upper | `PYTEST_LOG_CLI_LEVEL` |
| `-o` | the flat name | `-o log_cli_level=…` |
| nested file | `[section, *qualified[:-1]]` + leaf | `[pytest.log.cli] level` |

`section` comes from `prefix=` and is a **separate axis**
([below](#prefix-versus-name_prefix)). For
`LoggingConfig(ConfigPart, prefix="pytest", name_prefix="log")`:

| path | flat | CLI | env | nested |
|---|---|---|---|---|
| `("level",)` | `log_level` | `--log-level` | `PYTEST_LOG_LEVEL` | `[pytest.log] level` |
| `("cli", "level")` | `log_cli_level` | `--log-cli-level` | `PYTEST_LOG_CLI_LEVEL` | `[pytest.log.cli] level` |
| `("file", "path")` | `log_file` * | `--log-file` | `PYTEST_LOG_FILE` | `[pytest.log.file] path` |

\* via `named("log_file")`, which replaces the flat name only — see
[per-field overrides](#per-field-overrides).

The consequence worth stating explicitly: **the flat name split on `_` is the
nested table path.** The two spellings are mechanically derivable from each other
rather than being two independent names that happen to reach the same field.

**[change]** — the nested spelling currently omits `name_prefix` entirely
(`[pytest.cli] level`), which is the one place a part's identity is dropped. See
[both spellings](#both-spellings-in-files) for why that breaks, and
[D8](decisions.md#d8).

`FieldNames` is the record; `names_of()` produces it; `flat_index()` inverts it.
**[built]**

## prefix versus name_prefix

These are deliberately separate, and the separation is the reason the
[yardstick](index.md#the-yardstick) is expressible at all.

`prefix=` names the **section** a ConfigPart occupies in a config file, and the
default environment-variable prefix. It is not part of any option name.

`name_prefix=` leads every **field name**, in every source. It is part of the
option name.

pytest needs both at once: its logging options live in the `[pytest]` section but
are individually called `log_cli_level` — never `[log] cli_level`, never
`[pytest] cli_level`. One knob could not express that. **[built]**

The two axes carry different jobs:

- `prefix` is **shared**. That is its purpose — every pytest plugin's options
  live in `[pytest]`. It cannot distinguish one ConfigPart from another.
- `name_prefix` is the ConfigPart's **identity inside that shared section**. It
  is the only thing that keeps `log_cli_level` and `cache_cli_level` apart.

So any spelling that drops `name_prefix` drops the part's identity, which is what
the next section is about.

An `EnvSource`'s own prefix and the part's `prefix` **compose** rather than one
shadowing the other: `EnvSource("APP")` reading a part with `prefix="log"` looks
at `APP_LOG_*`. An application that namespaces its environment keeps that
namespace even for parts that name a file section of their own. **[built]**

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
kept, so the manager can report it as unknown ([I8](invariants.md#i8)) rather
than dropping it in the source. **[built]** as a mechanism, **[change]** in what
counts as the structural spelling.

**Why the `log` segment has to be there.** Without it the nested spelling has no
way to say *which* ConfigPart it means, and two plugins sharing the `[pytest]`
section silently receive each other's values:

```toml
[pytest.cli]
level = "NESTED"
```
```
Logging.cli.level = NESTED      Cache.cli.level = NESTED    # both, silently
```
```toml
[pytest]
level = "TOP"
```
```
Logging.level = TOP             Cache.level = TOP           # same at top level
```

Both parts declare `prefix="pytest"`, differ only in `name_prefix`, and each has
a `cli` sub-config — an entirely ordinary arrangement, and the exact one pytest
plugins are in. The flat spelling gets this right (`log_cli_level` versus
`cache_cli_level`); today the nested spelling cannot express it at all, making it
strictly less capable than the flat form it is supposed to mirror.

With `name_prefix` as a path segment ([above](#the-qualified-path)) the collision
disappears: `[pytest.log.cli]` and `[pytest.cache.cli]` are distinct tables.

## Unknown keys are judged across the section

A shared section means a ConfigPart sees keys that belong to other parts.
Unknown-key detection therefore belongs to the **manager**, which knows every
declared type, not to a single part's merge: a key is unknown only when *no*
declared ConfigPart claims it.

**[change]** — detection is per-part today, so parts sharing a section warn about
each other:

```
UnknownConfigKeyWarning: Unknown config option(s) for Logging: cache_cli_level
UnknownConfigKeyWarning: Unknown config option(s) for Cache: log_cli_level
```

Both keys are perfectly valid; each is simply the other part's. The warning fires
on correct configuration, which trains users to ignore it — and
[I8](invariants.md#i8) depends on that warning being trustworthy. See
[D8](decisions.md#d8), and [merging](merging.md#unknown-keys) for what happens to
a key once it is judged unknown.

## Per-field overrides

`named("log_file")` replaces the derived flat name outright; CLI and env
spellings are then re-derived from the override, so all three stay consistent. It
is needed wherever a field's structural path and its conventional name diverge —
`file.path` would derive `log_file_path`, but pytest calls it `log_file`.
**[built]**

`named()` does **not** affect the nested spelling. It is a flat-namespace device
by nature — a rename that exists precisely because name and structure diverge
should not then claim to describe the structure. `("file", "path")` stays
`[pytest.log.file] path` nested and `[pytest] log_file` flat.

`no_cli` suppresses the CLI option only. The field keeps its ini key and
environment variable. pytest's `log_cli` is exactly this: an ini-only switch,
because live logging is turned on from the command line with `--log-cli-level`.
**[built]**

`short("v")` adds a short option. `-o` and `-h` are reserved. **[built]**

There is no mirror of `no_cli` suppressing the *ini* spelling, so every field
gets an ini key. That was harmless while the ini side was write-only, but
[`-o` is scoped to ini-backed fields](#the-o-override-key), which makes "has an
ini spelling" load-bearing and therefore something that needs to be able to be
false. **[new]** — see
[evolution, open question 2](evolution.md#open-questions).

## The -o override key

```
-o log_cli_level=DEBUG      # the ini spelling
```

The `-o` key is the **flat name** — the same string the ini file uses.
**[change]** — it is currently the structural path, so with a `name_prefix` in
play the user must write `-o cli.level=DEBUG`, a third namespace that appears
nowhere else and that nothing in the help output mentions. The two spellings a
user has actually seen (`log_cli_level` and `log.cli.level`) both silently do
nothing today.

A `-o` key matching no field is a warning naming the key and the ConfigPart
([I8](invariants.md#i8)). **[change]** — currently silent.

Rationale in [D1](decisions.md#d1). The dotted-path spelling is *not* retained as
an alias: two spellings for one thing is how the current confusion arose. What
`-o` reports as its origin is covered in
[reporting](reporting.md#overrides-report-as-overrides).

## Names are never constructed by hand

Five places currently build or match a source-facing name without going through
`_names.py`, and all five are wrong at the edges ([I1](invariants.md#i1)):

| Place | Symptom |
|---|---|
| the nested file spelling | drops `name_prefix` ([above](#the-qualified-path)) — the largest instance, and the only user-visible one |
| `_reject_bootstrap_only` | compares `--app-config-file` to the bare field name `config_file`; never matches when a `name_prefix` exists, so the guard silently does nothing |
| `_apply_overrides` | [the `-o` key](#the-o-override-key) |
| `ConfigFileDiscoverySource(config_file_cli_arg="config_file")` | a raw string that is only correct with no `name_prefix` |
| the `config_source` / `addopts_field` / `bootstrap_only` scans | `recurse=False`, so the markers vanish inside a `SubConfig` ([I7](invariants.md#i7)) |

All five route through `flat_index()` / `names_of()` / `leaf_fields()`.
**[change]** Rationale in [D7](decisions.md#d7); the nested spelling gets its own
decision, [D8](decisions.md#d8), because it is the one users can see.

## Collisions

Two ConfigParts declaring the same flat name is **one rule for every backend**:

- identical declared type **and** identical default → **adoption**: one option,
  both parts read it. This is the migration case — a plugin and its host
  declaring the same option during a transition.
- anything else → `ConfigLifecycleError` naming both ConfigParts, the field
  paths, and the ways out (`named()`, `no_cli`, `name_prefix`).

**[change]** — the native CLI source silently skips the second registration and
lets the second part read a value parsed under the first part's type (an `int`
field and a `str` field both get `--level 7`, one as `7` and one as `"7"`), while
the pytest adapter raises. The two backends currently disagree about a core rule
— see [host adapters](host-adapters.md#adapters-must-share-semantics).

An **ini key** the host already declares is always adopted, never clobbered: the
existing help and type survive and the value is read. **[built]** in the pytest
adapter, and it is load-bearing for a migration.
