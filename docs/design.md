# Design

This is the normative design of `cot.config.ingest`: what the library is meant
to be, why, and where the code has yet to catch up. It replaces the five
pre-implementation intent documents that used to live in `docs/design/`.

Every rule carries a status marker:

| Marker | Meaning |
|---|---|
| **[built]** | The code does this today. |
| **[change]** | The code does something else. The code is wrong, not this document. |
| **[new]** | Not in the code at all. |

A **[change]** or **[new]** rule is a commitment, not a wish. If one turns out
to be a bad idea, the rule changes here first and the reasoning is recorded in
[Decisions](#decisions).

---

## 1. Purpose

### 1.1 The problem

An application that reads configuration from more than one place ends up
declaring each option more than once. pytest is the worked example: every
logging option exists as a CLI option *and* as an ini key, declared by two
different calls, reconciled by hand at read time:

```python
add_option_ini("--log-cli-level", dest="log_cli_level", default=None, ...)
...
level = get_option_ini(config, "log_cli_level", "log_level")   # by hand, per option
```

Ninety lines of `pytest_addoption` and a local helper produce thirteen ini keys
and twelve options, with the fallback chains open-coded at each use site. Adding
`pyproject.toml` means a third mechanism.

The duplication is not accidental. Each source needs different things: a parser
must be told an option exists before it can parse it; a file needs a section and
a key; an environment variable needs a name. What is *missing* is a single
declaration those three can all be derived from.

### 1.2 What this library is

A declaration of configuration **structure** — nested, typed, annotated — from
which every source-facing name is derived, and into which every source's values
are merged by a single precedence rule, with provenance recorded throughout.

```python
class LoggingConfig(ConfigPart, prefix="pytest", name_prefix="log"):
    level: str = "WARNING"
    cli: LogCliConfig
    file: LogFileConfig
```

That one declaration yields `--log-cli-level`, `log_cli_level`,
`PYTEST_LOG_CLI_LEVEL` and `[pytest.log.cli] level`, all addressing the same field,
with `log_cli_level` falling back to `log_level` because the child field is
marked `from_parent`.

### 1.3 The yardstick

`testing/test_pytest_logging.py` declares pytest's entire logging plugin — the
thirteen ini options in `docs/pytest-logging-options.txt` plus the CLI-only
`log_disable` — as one nested structure, and checks each is reachable by its
real pytest name from ini, TOML, env and CLI, with the fallback chains, the
provenance and the help output.

**A change that makes that file harder to write is going the wrong way.** It is
the acceptance criterion for the design, and its declaration must be able to use
the *real* types pytest uses: `Literal["w", "a"]` for `log_file_mode`,
`bool | int | None` for `log_auto_indent` (§5.3, §5.4).

### 1.4 Non-goals

- **Not a serialisation library.** Configuration is read, never written back.
- **Not a schema language.** The type annotations are the schema; there is no
  parallel declaration format.
- **Not a runtime store.** Configuration freezes at `resolve()` (§7.4).
  Change notification and hot reload are deferred (§12).
- **Not an argparse replacement.** The CLI parser exists because options must be
  registrable after parsing has already happened once. Anything beyond that
  belongs to the host.

---

## 2. Invariants

These are the load-bearing rules. Every defect found in the design review traced
to a violation of one of them, which is why they are stated separately from the
mechanisms that implement them.

**I1 — A field's identity is its path.** `("cli", "level")` is what a field
*is*. Every name a user ever types — CLI option, ini key, environment variable,
TOML table, `-o` key, `bootstrap_only` rejection message — is derived from that
path by `_names.py` and by nothing else. No component may construct a
source-facing name by string manipulation. **[change]** — four places currently
do (§4.7).

**I2 — Precedence is a total order with no exceptions.** Sources are sorted by
their `precedence` integer and merged in that order. Nothing is special-cased
above the ladder; `addopts` is not spliced into argv, defaults are not
privileged, the CLI is not hardcoded as final. **[built]**

**I3 — Declaration order does not affect the result.** A host collects
declarations from independent plugins, in an order nobody controls. Every
resolution pass runs for *all* declared types before the next pass begins.
**[built]**, pinned by `testing/test_lifecycle.py`.

**I4 — The library never prints and never exits.** It renders help and reports
that help was requested; the application owns the process. **[built]**

**I5 — Every value that reaches an instance has an origin.** Including values
that came from a class default, and values that arrived through the
`from_parent` cascade. If a value cannot be attributed, the merge is wrong.
**[built]**, except `-o` (§9.3).

**I6 — Every value that reaches an instance matches its declared type.** A
`str` field never holds `5`. **[change]** — only string-bearing sources are
coerced today; TOML values pass through unchecked (§5.5).

**I7 — Markers work at every depth.** A marker on a field three levels down
behaves exactly as it does at the top level. **[change]** — `config_source`,
`addopts_field` and `bootstrap_only` are only honoured on top-level fields
(§6.5, §7.5).

**I8 — User error is reported; it is never silently dropped.** A misspelled key,
an option with no value, an `-o` key that addresses nothing: each produces a
warning or an error naming the thing that went wrong. Programmer error raises.
**[change]** — several silent drops remain (§4.6, §5.6, §6.5).

---

## 3. The data model

### 3.1 ConfigPart and SubConfig

```python
class LogCliConfig(SubConfig):
    level: Annotated[str | None, from_parent] = None
    enabled: bool = False

class LoggingConfig(ConfigPart, prefix="pytest", name_prefix="log"):
    level: str = "WARNING"
    cli: LogCliConfig
```

`ConfigPart` is a top-level unit — the thing a plugin declares and a host
retrieves. `SubConfig` is a nested section inside one. They share all
construction behaviour; the distinction is structural, and it is what
`FieldInfo.is_sub_config` reports.

A `ConfigPart` used as a nested field is an error, raised at declaration time
and naming the field and both classes. **[new]** — today it produces
`TypeError: Outer missing required field(s): inner` at build time, which points
nowhere useful.

Both are:

- **keyword-only** — there is no positional construction **[built]**
- **frozen** — `__setattr__` and `__delattr__` raise **[built]**
- **materialised** — defaults are written into the instance `__dict__`, so
  equality, `repr` and `explain()` do not depend on whether a value was passed
  or inherited from the class body **[built]**
- **hashable** — list/dict/set values are frozen structurally for `__hash__`,
  rather than making every config object unhashable because one field might
  hold a list **[built]**

A mutable class-level default is copied per instance. The copy is deep, so a
`list[list[str]]` default is not shared through its inner lists. **[change]** —
the copy is currently shallow.

`@dataclass_transform(eq_default=True, kw_only_default=True, frozen_default=True)`
gives type checkers the right synthesised `__init__`. **[built]**

### 3.2 Fields

Type annotations are **required**. There is no inference: a class attribute
without an annotation is not a field. **[built]**

The field model in `_fields.py` is the single source of truth about a class's
shape. `fields_of(cls)` walks the MRO, resolves annotations with
`include_extras=True`, and returns `FieldInfo` records:

| Attribute | Meaning |
|---|---|
| `path` | `("cli", "level")` — the identity (I1) |
| `name` | `"level"` — the bare attribute |
| `annotation` | as written, `Annotated[...]` preserved |
| `type` | `Annotated` and `Optional` stripped |
| `default` | the class-level default, or `MISSING` |
| `markers` | the `Annotated` extras, in declaration order |
| `owner` | the MRO class that declared it |
| `is_sub_config` | whether `type` is a `SubConfig` subclass |

No other module may re-derive this. A `get_origin(x) is Annotated` loop outside
`_fields.py` is a bug — that duplication, in eight places, is what the field
model replaced. **[built]**

Results are cached per `(cls, recurse)` in a `WeakKeyDictionary`, so inspecting
classes defined inside test functions does not leak them. **[built]**

Inheritance stays simple: sub-configs pick up fields via `__mro__`, base classes
first. Elaborate multiple inheritance produces field resolution nobody can
follow, and is not supported beyond what the acceptance test needs
(`LogCliConfig(LogOutputConfig)`, `LoggingConfig(LogOutputConfig, ConfigPart)`).
**[built]**

### 3.3 Required and optional

A field with no default and no `SubConfig` type is **required**: if no source
supplies it, construction raises `TypeError` naming every missing field at
once. A `SubConfig` field never needs a default — the manager builds it from its
own defaults. **[built]**

---

## 4. Names

### 4.1 The qualified path

A field's **qualified path** is its structural path with the ConfigPart's
`name_prefix` prepended as a segment:

```
path            ("cli", "level")
name_prefix     "log"
qualified       ("log", "cli", "level")
```

Every spelling is that one path rendered with a different separator. Nothing
else varies:

| spelling | rule | `("cli", "level")` |
|---|---|---|
| flat (ini, flat TOML) | `"_".join(qualified)` | `log_cli_level` |
| CLI | `"-".join(qualified)` | `--log-cli-level` |
| env | source prefix + `"_"` + flat, upper | `PYTEST_LOG_CLI_LEVEL` |
| `-o` | the flat name (§4.6) | `-o log_cli_level=…` |
| nested file | `[section, *qualified[:-1]]` + leaf | `[pytest.log.cli] level` |

`section` comes from `prefix=` and is a **separate axis** (§4.2). For
`LoggingConfig(ConfigPart, prefix="pytest", name_prefix="log")`:

| path | flat | CLI | env | nested |
|---|---|---|---|---|
| `("level",)` | `log_level` | `--log-level` | `PYTEST_LOG_LEVEL` | `[pytest.log] level` |
| `("cli", "level")` | `log_cli_level` | `--log-cli-level` | `PYTEST_LOG_CLI_LEVEL` | `[pytest.log.cli] level` |
| `("file", "path")` | `log_file` * | `--log-file` | `PYTEST_LOG_FILE` | `[pytest.log.file] path` |

\* via `named("log_file")`, which replaces the flat name only — see §4.5.

The consequence worth stating explicitly: **the flat name split on `_` is the
nested table path.** The two spellings are mechanically derivable from each
other rather than being two independent names that happen to reach the same
field.

**[change]** — the nested spelling currently omits `name_prefix` entirely
(`[pytest.cli] level`), which is the one place a part's identity is dropped. See
§4.3 for why that breaks, and [D8](#d8).

`FieldNames` is the record; `names_of()` produces it; `flat_index()` inverts it.
**[built]**

### 4.2 `prefix` versus `name_prefix`

These are deliberately separate, and the separation is the reason the acceptance
test is expressible at all.

`prefix=` names the **section** a ConfigPart occupies in a config file, and the
default environment-variable prefix. It is not part of any option name.

`name_prefix=` leads every **field name**, in every source. It is part of the
option name.

pytest needs both at once: its logging options live in the `[pytest]` section
but are individually called `log_cli_level` — never `[log] cli_level`, never
`[pytest] cli_level`. One knob could not express that. **[built]**

The two axes carry different jobs, and this is the part that was previously
left implicit:

- `prefix` is **shared**. That is its purpose — every pytest plugin's options
  live in `[pytest]`. It cannot distinguish one ConfigPart from another.
- `name_prefix` is the ConfigPart's **identity inside that shared section**. It
  is the only thing that keeps `log_cli_level` and `cache_cli_level` apart.

So any spelling that drops `name_prefix` drops the part's identity, which is
exactly what §4.3 is about.

An `EnvSource`'s own prefix and the part's `prefix` **compose** rather than one
shadowing the other: `EnvSource("APP")` reading a part with `prefix="log"` looks
at `APP_LOG_*`. An application that namespaces its environment keeps that
namespace even for parts that name a file section of their own. **[built]**

### 4.3 File sources accept both spellings

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
kept, so the manager can report it as unknown (I8) rather than dropping it in
the source. **[built]** as a mechanism, **[change]** in what counts as the
structural spelling.

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
`cache_cli_level`); today the nested spelling cannot express it at all, making
it strictly less capable than the flat form it is supposed to mirror.

With `name_prefix` as a path segment (§4.1) the collision disappears:
`[pytest.log.cli]` and `[pytest.cache.cli]` are distinct tables.

### 4.4 Unknown keys are judged across the whole section

A shared section means a ConfigPart sees keys that belong to other parts.
Unknown-key detection therefore belongs to the **manager**, which knows every
declared type, not to a single part's merge: a key is unknown only when *no*
declared ConfigPart claims it.

**[change]** — detection is per-part today, so parts sharing a section warn
about each other:

```
UnknownConfigKeyWarning: Unknown config option(s) for Logging: cache_cli_level
UnknownConfigKeyWarning: Unknown config option(s) for Cache: log_cli_level
```

Both keys are perfectly valid; each is simply the other part's. The warning
fires on correct configuration, which trains users to ignore it — and I8 depends
on that warning being trustworthy. See [D8](#d8).

### 4.5 Per-field overrides

`named("log_file")` replaces the derived flat name outright; CLI and env
spellings are then re-derived from the override, so all three stay consistent. It
is needed wherever a field's structural path and its conventional name diverge —
`file.path` would derive `log_file_path`, but pytest calls it `log_file`.
**[built]**

`no_cli` suppresses the CLI option only. The field keeps its ini key and
environment variable. pytest's `log_cli` is exactly this: an ini-only switch,
because live logging is turned on from the command line with `--log-cli-level`.
**[built]**

`short("v")` adds a short option. `-o` and `-h` are reserved. **[built]**

### 4.6 `-o` addresses fields by flat name

```
-o log_cli_level=DEBUG      # the ini spelling
```

The `-o` key is the **flat name** — the same string the ini file uses. **[change]**
— it is currently the structural path, so with a `name_prefix` in play the user
must write `-o cli.level=DEBUG`, a third namespace that appears nowhere else and
that nothing in the help output mentions. The two spellings a user has actually
seen (`log_cli_level` and `log.cli.level`) both silently do nothing today.

A `-o` key matching no field is a warning naming the key and the ConfigPart
(I8). **[change]** — currently silent.

Rationale in [D1](#d1). The dotted-path spelling is *not* retained as an alias:
two spellings for one thing is how the current confusion arose.

### 4.7 Names are never constructed by hand

Four places currently build or match a source-facing name without going through
`_names.py`, and all four are wrong at the edges (I1):

| Place | Symptom |
|---|---|
| `_reject_bootstrap_only` | compares `--app-config-file` to the bare field name `config_file`; never matches when a `name_prefix` exists, so the guard silently does nothing |
| `_apply_overrides` | §4.6 |
| `ConfigFileDiscoverySource(config_file_cli_arg="config_file")` | a raw string that is only correct with no `name_prefix` |
| the `config_source` / `addopts_field` / `bootstrap_only` scans | `recurse=False`, so the markers vanish inside a `SubConfig` (I7) |

All four route through `flat_index()` / `names_of()` / `leaf_fields()`.
**[change]** Rationale in [D7](#d7); the nested-spelling case is the fifth and
largest instance, and it gets its own decision because it is user-visible
([D8](#d8)).

### 4.8 Collisions

Two ConfigParts declaring the same flat name is **one rule for every backend**:

- identical declared type **and** identical default → **adoption**: one option,
  both parts read it. This is the migration case — a plugin and its host
  declaring the same option during a transition.
- anything else → `ConfigLifecycleError` naming both ConfigParts, the field
  paths, and the ways out (`named()`, `no_cli`, `name_prefix`).

**[change]** — the native CLI source silently skips the second registration and
lets the second part read a value parsed under the first part's type (an `int`
field and a `str` field both get `--level 7`, one as `7` and one as `"7"`),
while the pytest adapter raises. The two backends currently disagree about a
core rule (§11.3).

An **ini key** the host already declares is always adopted, never clobbered: the
existing help and type survive and the value is read. **[built]** in the pytest
adapter, and it is load-bearing for a migration.

---

## 5. Types

### 5.1 Tokenisation versus interpretation

Every source ultimately hands over strings, and every source needs the same
question answered: what does this string mean for a field declared `list[str]`,
or `Annotated[bool, no_cli]`, or `int | None`?

That question is answered once, in `_coerce.py`.

What stays in each source is **tokenisation**, which genuinely differs: an INI
list is newline- or comma-separated inside one value, while a repeated CLI
option carries one element per occurrence. Splitting is the source's business;
interpreting the pieces is not. **[built]**

### 5.2 Scalars

`bool` accepts `true/yes/on/1` and their negations, case-insensitively. `int`
and `float` parse strictly. Anything else is left as `str`. `Annotated` and
`Optional` wrappers are stripped before dispatch — without that,
`Annotated[bool, no_cli]` never reaches the bool branch and `"false"` comes back
as a truthy string. **[built]**

### 5.3 Unions

A union is resolved by **trying each member in declaration order and taking the
first that parses**. `bool | int | None` from `"4"` is `4`; from `"true"` is
`True`; from `"maybe"` is an error. **[change]** — the first non-`None` member
currently wins unconditionally, so `bool | int | None` from `"4"` is `True`.

This matters directly: `log_auto_indent` is documented as accepting
`true|on`, `false|off` *or an integer*, and the acceptance test had to declare it
as `str | None` to work around it. Rationale in [D3](#d3).

### 5.4 `Literal`

`Literal["w", "a"]` declares both the type and the permitted values.
A value outside the set is an error naming the field and the choices; the
choices appear in `format_help()` and are passed to the host adapter
(`choices=` for pytest). **[new]**

`log_file_mode` is `choices=["w", "a"]` in real pytest, and the acceptance test
currently declares it `str`. Until this exists the yardstick is being measured
against a softened target (§1.3).

### 5.5 Values from typed sources are validated, not coerced

TOML and the host adapter deliver values that are *already* typed. Those are
checked against the declared annotation and rejected on mismatch; they are not
run through `coerce`. **[change]** — they are neither checked nor coerced today:

```toml
[app]
mode = 5                 # str field  -> instance holds 5
port = "not-a-number"    # int field  -> instance holds "not-a-number"
```

The check belongs in `_FrozenFromKwargsMixin.__init__`, which already walks
every field, so it covers direct construction as well as the merge path (I6).
Rationale in [D4](#d4).

Type *checking* is not type *validation*: range checks, cross-field constraints
and "is this file readable" remain out of scope (§12).

### 5.6 Lists

`list[T]` fields accumulate one element per repeated CLI option, and split on
newlines (preferred) or commas from a single file or environment value.
**[built]**

Across sources, a list is **replaced** wholesale by the highest-precedence
source that supplies one. Append and reset semantics are deferred (§12); the one
exception is `addopts`, which accumulates by construction because every
contribution is appended to the single `AddoptsSource` (§7.6). **[built]**

---

## 6. Sources

### 6.1 The protocol

```python
class ConfigSource(Protocol):
    @property
    def precedence(self) -> int: ...
    def load(self, part_type: type[ConfigPart]) -> dict[str, Any]: ...
```

`load()` returns a nested dict shaped like the ConfigPart, containing **only
what this source actually supplies**. Absence is expressed by omitting the key,
never by `None` — that is what lets the merge distinguish "unset" from "set to
nothing". **[built]**

Two optional protocols refine a source:

```python
class DeclaringSource(Protocol):
    def declare(self, part_type: type[ConfigPart]) -> None: ...

class OriginAware(Protocol):
    def describe_origin(self, part_type, path) -> Origin | None: ...
```

A file or environment source reads whatever name it is asked about, so it has
nothing to declare. A source backed by an argument parser does: the parser must
be told an option exists before it can parse it.

Both are tested with `isinstance()` against the runtime-checkable protocol.
**[change]** — the manager uses `getattr(source, "declare", None)` and
`getattr(source, "describe_origin", None)`, leaving two exported protocols
carrying no weight.

### 6.2 The ladder

```
defaults(-1)  <  file(15)  <  addopts(18)  <  env(20)  <  cli(25)
```

These are **defaults, not an enum**. Every source takes `precedence=`, and so
does every marker that creates one, so an application that wants its config
files to outrank the environment says so:

```python
TomlSource(path, precedence=Precedence.ENV + 1)
```

`DEFAULTS` is negative so that a value nobody configured loses to every real
source, including one declared at precedence 0. Gaps between the rungs exist so
callers can slot in without renumbering. **[built]**

Ties are broken by **insertion order**: the sort is stable, so among sources at
the same precedence the one added later wins. This is how "the local config file
beats the one in the parent directory" works. It is a real rule and must be
documented rather than incidental. **[built, undocumented]**

The design docs used to describe four separate file tiers (system, user, local).
There is one `Precedence.FILE`; tiers are expressed as `FILE`, `FILE + 1`,
`FILE + 2` by whoever constructs the sources, or by insertion order. No new
constants. **[built]**

### 6.3 Catalogue

| Source | Reads | Declares | Describes origin |
|---|---|---|---|
| `TomlSource` | one TOML file, section by `prefix` | – | file + key |
| `IniSource` | one INI file, section case-insensitive | – | file + key |
| `CLISource` | argv tokens | ✓ | option, `-s/--long` if short exists |
| `AddoptsSource` | tokens from `addopts_field` values | ✓ | `addopts --long` |
| `EnvSource` | `os.environ` or an injected dict | – | variable name |
| `ConfigFileDiscoverySource` | finds a file, delegates | – | delegates |
| `PytestOptionSource` | pytest `Config` | ✓ | cli or ini (§11) |

**[built]**

### 6.4 CLI parsing

The parser exists for one reason: **options must be registrable after parsing
has already happened**. A config file read during resolution can contribute
`addopts` that must be parsed against options a later plugin declared. argparse
cannot re-open a parsed namespace; this parser re-parses from scratch on every
`load()`, which makes registration order irrelevant. **[built]**

Rules:

- `--opt value`, `--opt=value`, `-s value`, `-s`, `--flag`, `-vx` (combined
  boolean shorts) **[built]**
- an option that takes a value **consumes the next token unconditionally**,
  unless that token is itself a registered option spelling or the tokens are
  exhausted — in which case it is an error naming the option **[change]**
- booleans get both `--flag` and `--no-flag` **[new]**
- unknown tokens are collected for host passthrough, not treated as errors —
  pytest needs `pytest tests/ -k foo` to work **[built]**

The two **[change]/[new]** items are the same hole from two sides: with a file
layer *below* the CLI on the ladder, a value set in a file must be
overridable from the command line. Today it is not:

```
[app] verbose = true   +   --no-verbose    ->    True   (--no-verbose is "unknown")
--offset -5                                ->    0      (both tokens dropped)
```

A negative number is unreachable and a file-set boolean cannot be turned off.
Both are silent (I8). Rationale in [D2](#d2).

### 6.5 Config file discovery

Two front ends, one mechanism:

- **declarative** — a field marked `config_source`; its value names a file that
  becomes a source at the marker's precedence
- **imperative** — `ConfigFileDiscoverySource`, which searches
  `invocation_dir` and its ancestors for known filenames

Both resolve a `Path` to a source through **one** function that maps suffix to
source type (`.toml` → `TomlSource`, `.ini`/`.cfg` → `IniSource`). An unknown
suffix is an error naming the path and the field. **[change]** — the decision is
currently made twice, differently: `ConfigFileDiscoverySource._create_source`
handles `.ini`, while the `config_source` path is `if value.suffix in (".toml",)`
— so a `config_source` field pointing at an `.ini` file has its existence
checked and enforced, and then nothing happens at all (I8).

`ConfigFileDiscoverySource` reads the explicit-config-file field through a
**field reference**, not a hardcoded `"config_file"` string (§4.7), and through
the source's public API rather than `env_source._environ`. **[change]**

A relative path resolves against `CLISource.invocation_dir`, or the process cwd
if there is no CLI source. A file named explicitly but absent is
`FileNotFoundError`; a file merely *discovered* to be absent is not an error.
**[built]**

---

## 7. Lifecycle

### 7.1 Three phases

| Phase | Call | What happens |
|---|---|---|
| declare | `manager.declare(T)` | the type is recorded and its options registered with every `DeclaringSource`. Nothing is loaded. |
| resolve | `manager.resolve()` | the feedback passes run for *all* declared types, then every fragment is built. Idempotent; triggered lazily by the first `get()`. |
| access | `manager.get(T)` | the built, typed instance. |

**[built]**

### 7.2 Why declaration is separate from resolution

A host collects declarations from independent plugins before any of them can be
resolved. In pytest every plugin's `pytest_addoption` runs before a single
argument is parsed — so a fragment built at declaration time could not see a
config file, or an `addopts`, contributed by a plugin loaded after it.

This is I3, and `testing/test_lifecycle.py` pins it: declaration order must not
change the result. **[built]**

### 7.3 The passes

`resolve()` is deliberately multi-pass, because you cannot know all the sources
until you have read some configuration:

1. collect class defaults
2. call `discover()` on every type that defines it — may add sources
3. process `config_source` fields → add each named file as a source
4. load every source to obtain `addopts` values
5. hand those to `AddoptsSource`, which parses them at its own precedence
6. re-load everything and merge in precedence order
7. build nested `SubConfig` instances, applying the `from_parent` cascade
8. instantiate, validate and store

**Each pass runs for every declared type before the next begins** (I3), so no
fragment is built against a source a later fragment was about to add. **[built]**

### 7.4 The passes iterate to a fixpoint

A type declared *during* resolution — by a `discover()` hook, or by a plugin
loaded from a config file — must receive every pass, not just the ones that have
not run yet.

`resolve()` therefore repeats passes 2–5 until the set of declared types stops
growing, then runs 6–8 once. A type declared during the final build pass is an
error: the configuration is closing. **[change]** — the passes are a flat
sequence of `for t in self._declared` loops today. A type declared during pass 2
happens to be picked up (list iteration sees appends); a type declared during
pass 3 or later never gets `discover()` and contributes no config file, silently.

Since plugin discovery is *precisely* "read a config file, then declare more
types", the current loop structure cannot support the one goal the `Discoverable`
protocol exists for. Rationale in [D5](#d5).

After resolution the configuration is **frozen**: `declare()` raises
`ConfigLifecycleError`. **[built]**

### 7.5 `discover()`

```python
class PluginConfig(ConfigPart):
    plugins: list[str] = []

    @classmethod
    def discover(cls, manager: ConfigManager) -> None:
        for name in manager.load_for_part(cls).get("plugins", []):
            manager.declare(import_module(name).Config)
```

A classmethod, returning `None`, whose effect is on the manager — it adds
sources or declares types. It does not build or return an instance; the manager
does that in pass 8. **[built]** as a protocol, **[new]** as anything with an
implementor.

The protocol has no implementors, which means its shape is a guess. The first
real one — plugin loading — is what will validate or refute it, and it is
blocked on §7.4.

### 7.6 The addopts feedback loop

`addopts` is a **source**, not a splice into argv. That is what lets it sit
*below* env and above files on the ladder (I2), and lets an injected option be
reported as `addopts --level` rather than looking like something the user typed
— an option nobody typed is the hardest kind to debug. **[built]**

Tokens accumulate: several config files, or several ConfigParts, may each
contribute, and later contributions win, matching the parser's own rule.
**[built]**

`bootstrap_only` refuses an addopts contribution that tries to set a field whose
decisions have already been made — which config file to open, above all.
Enforcement resolves the parsed tokens to field paths through the parser
(§4.7), not by munging the token string. **[change]**

---

## 8. Merge and assembly

### 8.1 Deep merge

Sources are merged in ascending precedence order, deeply. A shallow update would
let `--log-file-level` from the CLI wipe the whole `log_file` table read from a
config file. **[built]**

### 8.2 Unknown keys

A key a source supplied that **no declared ConfigPart** claims, at any depth, is
user error in a config file — not programmer error. It is dropped with an
`UnknownConfigKeyWarning` naming every offending dotted path, and the load
continues. Letting it reach the constructor raised `TypeError` and took the
whole load down over a typo in one nested table. **[built]**, except that the
judgement is made per-part rather than across all declared parts (§4.4), so a
shared section produces warnings on correct configuration. **[change]**

Pruning happens before origins are finalised, so `origins()` never reports paths
that were dropped. **[change]** — pruning currently runs after origin recording,
so the origins dict retains entries for keys that never reached the instance.
`explain()` hides this because it iterates `leaf_fields`, but `origins()` leaks
it.

### 8.3 Building sub-configs

For each `SubConfig`-typed field, in order: class defaults, then cascaded parent
values, then explicitly supplied values. The result is constructed recursively,
depth-first. **[built]**

### 8.4 The `from_parent` cascade

A field marked `from_parent` takes the parent's value for the **same field
name** when the child has none of its own:

```python
class LogOutputConfig(SubConfig):
    level: Annotated[str | None, from_parent] = None

class LoggingConfig(LogOutputConfig, ConfigPart, name_prefix="log"):
    cli: LogCliConfig     # cli.level falls back to level
    file: LogFileConfig   # file.level falls back to level
```

This is `get_option_ini(config, "log_cli_level", "log_level")`, declared once
instead of open-coded per option. Matching is by field name, not by `named()`
override — the cascade is structural. The child's own value always wins.
**[built]**

A cascaded value is attributed to **wherever the parent got it**, not to the
child's default (I5): `--log-level DEBUG` reports `cli.level` as
`inherited from level (--log-level)`, not as a default. **[built]**

---

## 9. Provenance

### 9.1 The manager records; sources refine

Origins are recorded by the manager as it merges, so a source that says nothing
about itself is still attributed — by class and precedence. A source that can be
more specific implements `describe_origin`. This is why adding a source type
costs nothing in provenance support. **[built]**

```python
@dataclass(frozen=True)
class Origin:
    kind: OriginKind      # default | file | env | cli | addopts | override
    location: str         # "PYTEST_LOG_CLI_LEVEL", "pytest.ini[log_level]", "--log-level"
    precedence: int
```

### 9.2 The API

```python
manager.origin_of(LoggingConfig, "cli.level")   # one field
manager.origins(LoggingConfig)                  # every field
print(manager.explain(LoggingConfig))           # field / value / origin table
```

`explain()` is the `--debug-config` output: the whole point of merging sources
is that the winner is not obvious from any one of them. **[built]**

### 9.3 `-o` reports as an override

A value set with `-o` has `kind="override"` and a location naming the `-o` key.
**[change]** — `OriginKind` declares `"override"` and nothing ever constructs
one; a `-o` value is reported as coming from the CLI option it happens to
address:

```
-o level=D    ->    origin = cli:--log-level     # the user never typed that
```

That is provenance actively lying, in exactly the case provenance exists for
(I5). Rationale in [D1](#d1).

---

## 10. Help

`format_help()` renders every registered option and returns the text.
`help_requested()` reports whether `-h`/`--help` was passed.

**Neither prints nor exits** (I4). This is a library; the application owns the
process, decides whether help goes to stdout or a pager, and decides the exit
code. **[built]**

Help text comes from the `help()` marker. Choices from a `Literal` annotation
(§5.4) appear in the rendered option. **[built]** / **[new]**

---

## 11. Host adapters

### 11.1 Division of labour

`cot/config/pytest_plugin.py` is a proof of concept that **monkeypatches
pytest**, adding `Parser.add_config`, `Config.get_config` and
`Config.explain_config`. The patch is additive only: no option, ini key, hook or
behaviour of pytest's is replaced. **[built]**

pytest keeps argument parsing; this library supplies the structure:

- **declare** — each leaf field becomes a `parser.addoption` and/or
  `parser.addini` under the same name mapping every other source uses
- **load** — values come back through `config.getoption` then `config.getini`
  (pytest's own `get_option_ini` precedence) and are reassembled into the nested
  shape, where defaults and the `from_parent` cascade apply

That split is the interesting part: pytest is good at parsing argv and reading
ini files and has no notion of structure. The intended end state is the reverse
of this arrangement — pytest using the library directly — and the adapter exists
to find out what that would need. **[built]**

### 11.2 Activation

A `pytest11` entry point, patching at import time. A conftest-level
`pytest_plugins = [...]` would be too late: that conftest's own
`pytest_addoption` runs before its plugin list is processed. Plugins loaded with
`-p` load before entry points and must call `install()` themselves; it is
idempotent. **[built]**

Auto-enabling means the patch reaches every environment the package lands in,
including as a transitive dependency. That is a deliberate trade for a proof of
concept and is not how a stable release should behave.

### 11.3 Adapters must share semantics

`PytestOptionSource` is the *only* source in the pytest path, at a single
precedence, because pytest has already merged argv and ini by the time values
come back. That is correct — but it means nothing in `_precedence.py` is
exercised there, and the two backends have already diverged on collision
handling (§4.8).

**Every host adapter must satisfy one shared conformance suite**, parameterised
over backends, covering: name mapping, the `from_parent` cascade, collision
policy, type handling, unknown keys, and provenance kind. **[new]**

Today the yardstick has two implementations —
`testing/test_pytest_logging.py` (native ladder) and
`test_pytest_logging_acceptance.py` (pytester) — and each only asks its own
backend what it does. Divergence is invisible by construction. Rationale in
[D6](#d6).

---

## 12. Deferred

Present in the design as intent, absent from the code, and **not** to be assumed:

- **Plugin discovery** — the `Discoverable` protocol has no implementors (§7.5).
  Blocked on the fixpoint resolve (§7.4).
- **List merge semantics** — append and reset modes (§5.6).
- **Validation hooks** — field validators, cross-field constraints, "is this
  file readable". Construction checks required fields, rejects unknown kwargs
  and (per §5.5) checks types; it does nothing beyond that.
- **Change notification and hot reload** — an observer API, dependency
  declaration between parts, reload on file change, error recovery when an
  observer raises. Everything about this is open, starting with whether a frozen
  configuration that can be replaced wholesale is a better answer than a mutable
  one that can be updated in place. This was `docs/design/change-notifications.md`
  and it never got past sketches.
- **Environment templating** — `host = "${DB_HOST}"` substitution.
- **Custom name transformers** — user-supplied path-to-name functions.

---

## Decisions

Findings from the design review, resolved. Each records the decision, why, and
what it costs.

### D1

**`-o` addresses fields by flat name, and reports as `kind="override"`.**
(§4.6, §9.3)

The `-o` key is currently the structural path, which is a namespace that appears
in no help text, no ini file and no error message. Of the three plausible
spellings a user might try, the two they have actually seen elsewhere silently
do nothing, and the one that works is attributed to a CLI option the user never
typed.

Reusing the flat name means `-o` is spelled exactly like the ini key — one name
to learn, and `flat_index()` already provides the lookup. The dotted path is not
kept as an alias: two spellings for one thing is the problem, not the fix.

*Cost:* breaking. `-o cli.level=X` stops working. The library is pre-1.0 and
this is noted in the changelog rather than deprecated.

### D2

**Booleans get `--no-` variants, and an option that takes a value consumes the
next token unconditionally.** (§6.4)

These look like two conveniences; they are one structural hole. The ladder puts
files below the CLI specifically so that a command-line argument can override a
file. With `store_true` as the only boolean form, a file-set `true` is
unreachable from the command line. With `not args[i+1].startswith("-")` guarding
value consumption, every negative number is unreachable — and both failures are
silent, which turns a wrong value into a debugging session.

The unconditional-consumption rule needs a companion error: an option whose value
is missing (end of tokens, or the next token is a registered option) must raise
naming the option, rather than being dropped as unknown.

*Cost:* a token that looks like an option but is not registered is now consumed
as a value where it used to land in `unknown_args`. Hosts relying on passthrough
of unregistered options *positioned directly after* a value-taking option are
affected. pytest's usage (`pytest tests/ -k foo`) is not.

### D3

**Unions are resolved by trying members left to right.** (§5.3)

`bool | int | None` from `"4"` is currently `True`, because the first non-`None`
member wins unconditionally. That is not a defensible reading of the annotation,
and it is not hypothetical: `log_auto_indent` accepts `true|on`, `false|off` *or
an integer*, and the acceptance test had to declare it `str | None` to get
around it.

Trying members in order and taking the first that parses gives the obvious
answer for every case in the yardstick, and makes `bool` last-resort-safe
because it only accepts its known literals.

*Cost:* a union whose members overlap now resolves differently. `str | int` from
`"4"` becomes `"4"` (str parses everything), which is why `str` should be last
in a union — worth a note in the field documentation.

### D4

**Values from typed sources are checked against the annotation at
construction.** (§5.5)

"Type-safe configuration" is the first line of the README, and a `str` field
currently accepts `5` from a TOML file without complaint. Coercion covers only
string-bearing sources; TOML and the host adapter deliver already-typed values
that nothing inspects.

The check goes in `_FrozenFromKwargsMixin.__init__`, which already walks every
field to apply defaults and reject unknown kwargs. That placement covers direct
construction too, so a hand-built `LoggingConfig(level=5)` fails the same way a
config file does.

*Cost:* configurations that currently "work" with wrong types start failing.
That is the point, but it is breaking, and the error must name the field, the
declared type and the value.

### D5

**`resolve()` iterates its passes to a fixpoint.** (§7.4)

Plugin discovery is the reason the multi-pass design exists, and the current
flat pass sequence cannot support it: a type declared during pass 3 or later
never receives `discover()` and never contributes a config file. That a type
declared during pass 2 *is* picked up is an accident of list-iteration
semantics, not a designed behaviour.

Repeating passes 2–5 until the declared set stops growing makes the guarantee
explicit and makes `Discoverable` implementable. It also makes I3 hold for
types the host never saw.

*Cost:* resolution can loop. A declaration cycle needs a bound and an error
naming the types involved.

### D6

**One conformance suite, parameterised over backends.** (§11.3)

The native ladder and the pytest adapter already disagree about collisions, and
each test file only asks its own backend what it does. The library's value
proposition is that one declaration behaves the same everywhere; nothing
currently tests that claim.

The suite is the executable form of §4, §5, §8 and §9 — and when pytest
eventually uses the library directly, it is the thing that says whether the
replacement is faithful.

*Cost:* the two acceptance test files partly merge, and the pytest backend will
fail cases the native one passes until it is brought into line.

### D7

**Markers are honoured at every depth; names are never built by hand.**
(§4.7, §6.5, §7.6)

`config_source`, `addopts_field` and `bootstrap_only` are scanned with
`recurse=False`, so they silently vanish inside a `SubConfig`, while every other
marker works anywhere. `bootstrap_only`'s enforcement compares munged token
strings against bare field names and never fires when a `name_prefix` exists.
`config_source` handles `.toml` and silently ignores every other suffix after
checking the file exists.

These are three symptoms of one cause: components reaching around `_names.py`
and `_fields.py` (I1, I7). Every confirmed defect in the review traces here,
which is the argument for making it an invariant rather than a style note.

*Cost:* none behaviourally, beyond markers starting to work where they
previously did nothing.

### D8

**`name_prefix` is a path segment, not a string prefix; unknown keys are judged
across all declared parts.** (§4.1, §4.3, §4.4)

`name_prefix` appears in the flat, CLI and env spellings and is dropped from the
nested one. That is not a cosmetic asymmetry: `prefix` is *shared* by design —
every pytest plugin's options live in `[pytest]` — so `name_prefix` is the only
thing giving a ConfigPart identity inside its section, and the nested spelling
throws it away. Two ordinary plugins, differing only in `name_prefix` and each
with a `cli` sub-config, silently read each other's values from
`[pytest.cli] level`. The flat spelling handles the same case correctly, which
makes the nested form strictly less capable than the one it mirrors.

Treating `name_prefix` as a segment of a **qualified path** makes all four
spellings one path rendered four ways, and yields the property §4.3 previously
claimed without delivering: the flat name split on `_` *is* the nested table
path. It also collapses two knobs that behaved differently per source into one
rule plus a separate section axis.

The unknown-key half is the same root cause seen from the merge side. A shared
section means a part sees keys belonging to other parts; judging them per-part
makes correct configuration warn (`Unknown config option(s) for Logging:
cache_cli_level`). The manager knows every declared type and is the only place
the judgement can be made correctly.

*Cost:* breaking, and the most user-visible change in this document. Nested TOML
written against the current behaviour (`[pytest.cli]`) must gain the segment
(`[pytest.log.cli]`). Parts with no `name_prefix` are unaffected — their
qualified path is just their path. `named()` is unaffected: it overrides the
flat name only, so `("file","path")` stays `[pytest.log.file] path` structurally
and `[pytest] log_file` flat.

*Alternative rejected:* making the section itself `[pytest.log]` when a
`name_prefix` exists. It reads well but contradicts the motivating case —
pytest's keys really do live directly in the `[pytest]` section as
`log_cli_level`, and moving them would break the flat spelling to fix the nested
one.

---

## Open questions

1. **`help` shadows the builtin.** `from cot.config import help` is aggressive
   for a name that common. `T @ help("...")` reads better than any alternative
   considered, and the shadowing is scoped to what the user imports. Rename,
   alias, or leave it?
2. **`ConfigPart` versus `SubConfig`.** They share every behaviour; the split
   exists only so nesting can be detected. Is a single class with a `nested=`
   marker simpler, or is the type-level distinction worth keeping for the reader?
3. **Required fields with no source.** Construction raises `TypeError` naming
   them. Should that be a distinct exception type carrying the ConfigPart and
   the origins that *were* found?
4. **Per-source list tokenisation.** Newline-preferred-over-comma is an INI
   convention. Does a TOML string field holding `"a,b"` really want splitting,
   or should only INI do it?
5. **`invocation_dir` without a CLI source.** Relative `config_source` paths fall
   back to `Path.cwd()`. Should a manager with no `CLISource` be required to
   state its own base directory instead?
