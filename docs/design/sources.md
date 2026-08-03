# Sources

Where values come from, and the single rule that decides which one wins.

## The protocol

```python
class ConfigSource(Protocol):
    @property
    def precedence(self) -> int: ...
    def load(self, part_type: type[ConfigPart]) -> dict[str, Any]: ...
```

`load()` returns a nested dict shaped like the ConfigPart, containing **only what
this source actually supplies**. Absence is expressed by omitting the key, never
by `None` — that is what lets [the merge](merging.md#deep-merge) distinguish
"unset" from "set to nothing". **[built]**

Two optional protocols refine a source:

```python
class DeclaringSource(Protocol):
    def declare(self, part_type: type[ConfigPart]) -> None: ...

class OriginAware(Protocol):
    def describe_origin(self, part_type, path) -> Origin | None: ...
```

A file or environment source reads whatever name it is asked about, so it has
nothing to declare. A source backed by an argument parser does: the parser must
be told an option exists before it can parse it. That asymmetry is why
[declaration is a separate phase](lifecycle.md#why-declaration-is-separate).

`describe_origin` is optional for a different reason: a source that says nothing
about itself is [still attributed](reporting.md#the-manager-records-sources-refine),
so implementing it is a refinement, never a requirement.

Both are tested with `isinstance()` against the runtime-checkable protocol.
**[change]** — the manager uses `getattr(source, "declare", None)` and
`getattr(source, "describe_origin", None)`, leaving two exported protocols
carrying no weight.

## The precedence ladder

```
defaults(-1) < file(15) < injected(18) < env(20) < cli(25) < override(30) < runtime(40)
```

These are **defaults, not an enum**. Every source takes `precedence=`, and so
does every marker that creates one, so an application that wants its config files
to outrank the environment says so:

```python
TomlSource(path, precedence=Precedence.ENV + 1)
```

`DEFAULTS` is negative so that a value nobody configured loses to every real
source, including one declared at precedence 0. Gaps between the rungs exist so
callers can slot in without renumbering. **[built]** for the first five rungs.

This ladder *is* the whole ordering rule ([I2](invariants.md#i2)). Nothing is
special-cased above it — which is why
[injected arguments](lifecycle.md#the-injected-arguments-loop) are a source at
their own rung rather than a splice into argv, and why the two rungs above the
command line are rungs rather than a post-merge fixup.

The `injected` rung is named for the capability, not for the host that motivated
it. It was `ADDOPTS`, which put a pytest concept in the core ladder for everyone.
**[change]**

### The two rungs above the command line

`override(30)` and `runtime(40)` are **[new]**; the ladder stopped at `cli` and
both mechanisms reached around it.

**`override`** is where [`-o`](names.md#the-o-override-key) values land. `-o`
arrives *on* the command line but is not one of the declared options: it names a
field by its flat key and says "whatever else decided this, use my value". That
is more specific than the option it competes with, so it sits above it — and it
resolves what an unranked `-o` left undefined, which is what `--log-level=A -o
log_level=B` means. It is a source, at a rung, so
[its origin can say so](reporting.md#overrides-report-as-overrides) instead of
impersonating a CLI option.

**`runtime`** is the top of the ladder, and it stays the top. A
[runtime write](lifecycle.md#the-runtime-layer) happens *after* everything else
has been read and merged — it is a host deriving one setting from another with
the whole configuration in front of it. A value written then must win, or the
derivation it encodes is silently discarded. Nothing may be constructed above
`runtime`; a source that wants to outrank a late write is describing input, and
input belongs below the command line.

Both rungs are ordinary in every other respect: they sort by integer, they are
merged in order, and a value from either carries an
[origin](reporting.md#the-manager-records-sources-refine) naming its kind.
Rationale in [D14](decisions.md#d14).

Ties are broken by **insertion order**: the sort is stable, so among sources at
the same precedence the one added later wins. This is how "the local config file
beats the one in the parent directory" works. It is a real rule and is documented
here rather than left incidental. **[built]**

There is one `Precedence.FILE`. Tiers such as system / user / local are expressed
as `FILE`, `FILE + 1`, `FILE + 2` by whoever constructs the sources, or by
insertion order. No new constants. **[built]**

## Catalogue

| Source | Reads | Dialect | Declares | Describes origin |
|---|---|---|---|---|
| `TomlSource` | one TOML file, section by `prefix` | typed | – | file + key |
| `YamlSource` | one YAML file, section by `prefix` | typed | – | file + key |
| `IniSource` | one INI file, section case-insensitive | string | – | file + key |
| `CLISource` | argv tokens | string | ✓ | option, `-s/--long` if short exists |
| `InjectedArgsSource` | tokens from an `injected_args` field | string | ✓ | `injected --long` |
| `OverrideSource` | `-o key=value` pairs | string | – | `-o key` |
| `EnvSource` | `os.environ` or an injected dict | string | – | variable name |
| `TomlEnvSource` | the same, values parsed as TOML | typed | – | variable name |
| `ConfigFileDiscoverySource` | finds a file, delegates | delegates | – | delegates |
| a host binding's source | whatever the host already parsed | host's | ✓ | host-specific |

**[built]** except `YamlSource`, `OverrideSource` and `TomlEnvSource`, which are
**[new]**.

Which names each of these looks for is not their own business — it comes from
[the qualified path](names.md#the-qualified-path).

### Dialect is a property of the source

The **dialect** column is not decoration: it decides whether a source's values
are [coerced or checked](types.md#values-from-typed-sources). A string-dialect
source hands over text and the library interprets it; a typed-dialect source
hands over values that already have types, and the library verifies them against
the annotation.

Because it is a property of the *source*, a format that can be read either way
becomes two sources rather than one source with a flag — see
[the environment](#the-environment) below. A host whose file formats span both
dialects splits them the same way, in its own [binding](binding-contract.md).

## CLI parsing

The parser exists for one reason: **options must be registrable after parsing has
already happened**. A config file read during resolution can contribute
[injected arguments](lifecycle.md#the-injected-arguments-loop) that must be
parsed against options a later plugin declared. argparse cannot
re-open a parsed namespace; this parser re-parses from scratch on every `load()`,
which makes registration order irrelevant. **[built]**

Rules:

- `--opt value`, `--opt=value`, `-s value`, `-s`, `--flag`, `-vx` (combined
  boolean shorts) **[built]**
- an option that takes a value **consumes the next token unconditionally**,
  unless that token is itself a registered option spelling or the tokens are
  exhausted — in which case it is an error naming the option **[change]**
- booleans get both `--flag` and `--no-flag` **[new]**
- unknown tokens are collected for host passthrough, not treated as errors — a
  host that takes positional arguments alongside options needs them **[built]**

The two **[change]/[new]** items are the same hole from two sides: with a file
layer *below* the CLI on the ladder, a value set in a file must be overridable
from the command line. Today it is not:

```
[app] verbose = true   +   --no-verbose    ->    True   (--no-verbose is "unknown")
--offset -5                                ->    0      (both tokens dropped)
```

A negative number is unreachable and a file-set boolean cannot be turned off.
Both are silent ([I8](invariants.md#i8)). Rationale in [D2](decisions.md#d2).

`-o` is reserved by the parser for [generic
overrides](names.md#the-o-override-key), and `-h` for help.

## The environment

### Exposure is opt-in

**A field gets an environment variable only when it says so.** The `from_env`
marker is what creates the spelling; a field without it is not readable from the
environment by any `EnvSource`, whatever prefix that source carries. **[change]**
— `EnvSource` reads every field today.

```python
class DatabaseConfig(ConfigPart, prefix="app"):
    host: Annotated[str, from_env] = "localhost"   # APP_HOST
    password: str = ""                             # not environment-readable
```

The environment is the one source nobody declares. A file is opened because
something named it and a command line is typed on purpose, but every process
inherits an environment it did not choose, from a CI runner, a container image or
a shell profile. Implicit exposure means every field a part ever adds silently
becomes settable by any variable that happens to match — a widening surface that
grows with the declaration and that nothing in the declaration asked for.

Opt-in also makes the spelling reviewable: `from_env` in the class body is where
someone decides a value may come from ambient state, next to the field it
affects, in the diff that introduced it. Rationale in [D13](decisions.md#d13).

It is a per-field marker rather than a source-level policy because
[markers work at every depth](invariants.md#i7) and a source-level switch cannot
distinguish `database.password` from `database.host`. A source-level policy was
the earlier answer here; it made the decision at the wrong end.

`EnvSource`'s own prefix and the part's `prefix` still
[compose](names.md#prefix-versus-name_prefix) for the fields that do opt in.

### Two sources, two dialects

A variable's value is a string, but a string is sometimes a serialised
structure. Those are different sources, not a flag:

```python
EnvSource("APP")        # string dialect: values are coerced
TomlEnvSource("APP")    # typed dialect: each value is parsed as TOML
```

`TomlEnvSource` is what lets one variable carry a nested table:

```
APP_DATABASE='host = "db.internal"
port = 5432'
```

Splitting them settles a question `parse_toml=True` left open: whether such a
value is [coerced or checked](types.md#values-from-typed-sources). It is a
[typed-dialect source](#dialect-is-a-property-of-the-source), so its values are
checked, and the answer no longer depends on a constructor argument that a
reader of the merge cannot see. **[change]** — today it is
`EnvSource(parse_toml=True)`, and its values are neither coerced nor checked.
Rationale in [D15](decisions.md#d15).

## Config file discovery

Two front ends, one mechanism:

- **declarative** — a field marked `config_source`; its value names a file that
  becomes a source at the marker's precedence
- **imperative** — `ConfigFileDiscoverySource`, which searches `invocation_dir`
  and its ancestors for known filenames

Both resolve a `Path` to a source through **one** function that maps suffix to
source type:

| suffix | source | dialect |
|---|---|---|
| `.toml` | `TomlSource` | typed |
| `.yaml`, `.yml` | `YamlSource` | typed |
| `.ini`, `.cfg` | `IniSource` | string |

An unknown suffix is a
[`ConfigUsageError`](diagnostics.md#errors) naming the path and the field.
**[change]** — the decision is currently made twice, differently:
`ConfigFileDiscoverySource._create_source` handles `.ini`, while the
`config_source` path is `if value.suffix in (".toml",)` — so a `config_source`
field pointing at an `.ini` file has its existence checked and enforced, and then
nothing happens at all ([I8](invariants.md#i8)).

That one function is also the whole of what a new file format costs. Adding YAML
is a row in the table plus a loader; it needs no name model, no precedence rule
and no merge behaviour of its own, because [names](names.md#the-qualified-path)
and [merging](merging.md) are already format-blind. See
[YAML](#yaml) for what is still open about it.

`ConfigFileDiscoverySource` reads the explicit-config-file field through a **field
reference**, not a hardcoded `"config_file"` string
([names](names.md#names-are-never-constructed-by-hand)), and through the source's
public API rather than `env_source._environ`. **[change]**

A relative path resolves against `CLISource.invocation_dir`, or the process cwd
if there is no CLI source. A file named explicitly but absent is
`FileNotFoundError`; a file merely *discovered* to be absent is not an error.
**[built]**

When a discovered file becomes a source matters as much as which one — see
[the passes](lifecycle.md#the-passes).

## YAML

YAML is a config file format on the same footing as TOML and INI: a
[typed-dialect](#dialect-is-a-property-of-the-source) source, addressed by
[the qualified path](names.md#the-qualified-path) like every other, sitting at
`FILE` on the ladder like every other. **[new]**

```yaml
pytest:
  log:
    cli:
      level: DEBUG
    level: WARNING
```

It is in the design because the format question is a *source* question and the
[source catalogue is open](types.md#tokenisation-versus-interpretation) —
leaving YAML out would not have kept it out, it would only have meant the first
person to add it did so without a rule to follow. The flat spelling
(`log_cli_level: DEBUG` under `pytest:`) works exactly as it does in TOML,
because [both spellings](names.md#both-spellings-in-files) are a property of the
name model rather than of the file format.

**It is underspecified on purpose.** pytest does not read YAML, so the
[yardstick](index.md#the-yardstick) exerts no pressure on it and nothing here has
been tested against a real requirement. Four questions are open, and each has a
plausible answer that a first implementation should not settle by accident:

- **The dependency.** YAML needs a third-party parser where TOML and INI are in
  the standard library. An optional extra whose absence is a
  [`ConfigUsageError`](diagnostics.md#errors) naming the file is the obvious
  shape, but it makes a suffix's support conditional on the install.
- **Which YAML.** Safe-load only, presumably — a config file that can construct
  arbitrary Python objects is a different security posture from TOML. Aliases
  and merge keys (`<<:`) then need a position: they are the format's own
  composition mechanism, competing with [the ladder](#the-precedence-ladder).
- **Multi-document streams.** One file, several `---` documents. Ignore all but
  the first, treat them as successive sources, or reject them.
- **Duplicate keys and type surprises.** YAML 1.1 readers turn `no` into `False`
  and `1.0` into a float; duplicate keys are silently last-wins in most parsers.
  Both are [I8](invariants.md#i8) questions before they are parsing questions.

Tracked in [deferred](deferred.md#open-questions). Rationale for admitting it to
the design in [D17](decisions.md#d17).
