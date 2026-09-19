# Sources

Where values come from, and the single rule that decides which one wins.

## The protocol

```python
@dataclass(frozen=True)
class Reading:
    root: type[ConfigPart]
    path: tuple[str, ...]       # resolved through the index
    raw: Any                    # text, or a typed value, by dialect
    location: str               # "pytest.ini[log_level]", "--log-level", "APP_DB_HOST"

@dataclass(frozen=True)
class Unmatched:
    spelling: str               # what the source saw
    location: str

class ConfigSource(Protocol):
    @property
    def precedence(self) -> int: ...
    @property
    def dialect(self) -> Literal["string", "typed"]: ...
    def load(self, index: SpellingIndex) -> Iterable[Reading | Unmatched]: ...
```

A source reads its input, asks [the index](names.md#the-spelling-index) what
each spelling it finds means, and yields one `Reading` per value it can place
and one `Unmatched` per spelling it cannot. It supplies only what it has:
absence is expressed by yielding nothing for a path, never by a `None` reading.
That is what lets [the store](merging.md#the-layered-store) distinguish "unset"
from "set to nothing".

Two things follow. A source never needs a part type, because the index knows
every declared root, so one read of a file serves all of them. And unknown keys
are judged in one place with everything declared in view, so a root never
warns about another root's keys
([names](names.md#unknown-keys-are-judged-across-every-declared-root)).
Rationale in [D21](decisions.md#d21).

One optional protocol refines a source:

```python
class BindingSource(ConfigSource, Protocol):
    def bind(self, specs: Iterable[FieldSpec]) -> None: ...
```

A file or environment source reads whatever the index knows about, so it has
nothing to bind. A source backed by an argument parser must be told an option
exists before it can parse it, in the parser's own vocabulary. `bind()` is the
loop over [specs](specs.md) that does that, and it is the whole of what a
binding knows about the core. That asymmetry is why
[declaration is a separate phase](lifecycle.md#why-declaration-is-separate).

The manager builds the
[`Origin`](reporting.md#the-manager-records-sources-refine) for each reading
from the source's kind and precedence and the reading's location. A source
says where a value came from and nothing else.

## The precedence ladder

```
defaults(-1) < file(15) < injected(18) < env(20) < cli(25) < override(30) < runtime(40)
```

These are defaults, not an enum. Every source takes `precedence=`, and so does
every marker that creates one:

```python
TomlSource(path, precedence=Precedence.ENV + 1)
```

`DEFAULTS` is negative so that a value nobody configured loses to every real
source, including one declared at precedence 0. Gaps between the rungs let
callers slot in without renumbering.

This ladder is the whole ordering rule ([I2](invariants.md#i2)). Nothing is
special-cased above it. That is why
[injected arguments](lifecycle.md#the-injected-arguments-loop) are a source at
their own rung rather than a splice into argv.

### No two sources share a rung

Adding a source at a precedence another source already holds is a
[`ConfigDeclarationError`](diagnostics.md#errors) naming both sources. A tie
would have to be broken by the order the sources were added, and that order is
the one thing [I3](invariants.md#i3) says may not matter: two plugins whose
`discover()` hooks each add a file at `FILE` would otherwise produce a
declaration-order result.

A source may hold several values for one path, and then its own documented
order decides between them. [Discovery](#config-file-discovery) orders files
by depth, nearest the invocation directory last; the
[injected source](lifecycle.md#the-injected-arguments-loop) orders
contributions by the rung of the source that contributed them. Neither depends
on insertion. Rationale in [D22](decisions.md#d22).

Tiers such as system, user and local are `FILE`, `FILE + 1`, `FILE + 2`,
assigned by whoever constructs the sources.

### The two rungs above the command line

`override` is where [`-o`](names.md#the-o-override-key) values land. `-o`
names a field by its flat key and says "use my value regardless", which is more
specific than the option it competes with. `--log-level=A -o log_level=B` is
`B`. As a source at a rung,
[its origin can say so](reporting.md#overrides-report-as-overrides).

The pairs come from every argv-parsing source, typed or
[injected](lifecycle.md#the-injected-arguments-loop). An `-o` carried by
injected arguments lands at the same rung and outranks a typed option, which is
what splicing injected arguments into argv gave pytest.

`runtime` is the top of the ladder and stays the top. A
[runtime write](lifecycle.md#the-runtime-layer) happens after everything else
has been merged, with the whole configuration in view, so it must win or the
derivation it encodes is discarded. Nothing may be constructed above `runtime`.
A source that wants to outrank a late write is describing input, and input
belongs below the command line.

Both rungs sort by integer, merge in order, and carry an
[origin](reporting.md#the-manager-records-sources-refine) naming their kind.
Rationale in [D14](decisions.md#d14).

## Catalogue

| Source | Reads | Dialect | Binds | Location |
|---|---|---|---|---|
| `TomlSource` | one TOML file, section by `prefix` | typed | – | file + key |
| `YamlSource` | one YAML file, section by `prefix` | typed | – | file + key |
| `IniSource` | one INI file, section case-insensitive | string | – | file + key |
| `CLISource` | argv tokens, through the native parser | string | ✓ | option, `-s/--long` if short exists |
| `InjectedArgsSource` | tokens from `injected_args` fields | string | ✓ | `injected --long (contributor)` |
| `OverrideSource` | `-o key=value` pairs from every argv-parsing source | string | – | `-o key` |
| `EnvSource` | `os.environ` or an injected dict | string | – | variable name |
| `TomlEnvSource` | the same, values parsed as TOML | typed | – | variable name |
| `RuntimeSource` | [`manager.set()`](lifecycle.md#the-runtime-layer) writes | typed | – | `runtime:writer` |
| `ConfigFileDiscoverySource` | finds files, delegates | delegates | – | delegates |
| a host binding's source | whatever the host already parsed | host's | ✓ | host-specific |

Which names each of these looks for comes from
[the qualified path](names.md#the-qualified-path), through the index.

### Dialect is a property of the source

The dialect column decides whether a source's values are
[converted or checked](types.md#two-dialects). A string-dialect source hands
over text and the library interprets it. A typed-dialect source hands over
values that already have types, and the library verifies them against the
annotation.

Because it is a property of the source, a format that can be read either way
becomes two sources rather than one source with a flag. See
[the environment](#two-sources-two-dialects). A host whose file formats span
both dialects splits them the same way, in its own
[binding](binding-contract.md).

## CLI parsing

The native parser exists because options must be registrable after parsing has
already happened. A config file read during resolution can contribute
[injected arguments](lifecycle.md#the-injected-arguments-loop) that must be
parsed against options a later plugin declared. argparse cannot re-open a
parsed namespace; this parser re-parses from scratch on every `load()`, which
makes registration order irrelevant.

`CLISource.bind()` is the first [binder](specs.md#why-it-is-a-layer): it
registers each spec's [CLI forms](specs.md#cli-forms) with the native parser
exactly as the pytest binding registers them with argparse.

Rules:

- `--opt value`, `--opt=value`, `-s value`, `-s`, `--flag`, `-vx` (combined
  boolean shorts)
- an option that takes a value consumes the next token unconditionally, unless
  that token is itself a registered option spelling or the tokens are
  exhausted, in which case it is a [`ConfigUsageError`](diagnostics.md#errors)
  naming the option
- every boolean has both `--flag` and `--no-flag`
- unknown tokens are collected for host passthrough, not treated as errors

With files below the CLI on the ladder, a value set in a file must be
overridable from the command line. The `--no-` form and unconditional
consumption are what make that true: without them a file's `verbose = true`
and a `--offset -5` are both unreachable, silently ([I8](invariants.md#i8)).
Rationale in [D2](decisions.md#d2).

`-o` is reserved by the parser for
[generic overrides](names.md#the-o-override-key), and `-h` for help.

## The environment

### Exposure is opt-in

A field gets an environment variable only when it says so. The `from_env`
marker creates the spelling; a field without it is not readable from the
environment by any `EnvSource`.

```python
class DatabaseConfig(ConfigPart, prefix="app"):
    host: Annotated[str, from_env] = "localhost"   # APP_HOST
    password: str = ""                             # not environment-readable
```

The environment is the one source nobody declares. Every process inherits one
it did not choose, from a CI runner, a container image or a shell profile.
Implicit exposure means every field a part ever adds becomes settable by any
variable that happens to match. Opt-in puts the decision next to the field, in
the diff that introduced it. Rationale in [D13](decisions.md#d13).

`from_env` on a nested field opts in its whole subtree: every leaf below it
gets a spelling, and the nested path itself gets one, which is what
[`TomlEnvSource`](#two-sources-two-dialects) reads a table from. A root that
wants every field readable says `from_env=True` as a class keyword, which is
the same marker on the one field that has no parent. The bulk case is one
line, and it is still a line someone wrote next to the thing it exposes.
Rationale in [D27](decisions.md#d27).

It is a per-field marker rather than a source-level policy because
[markers work at every depth](invariants.md#i7) and a source-level switch
cannot distinguish `database.password` from `database.host`.

`EnvSource`'s own prefix and the root's `prefix` still
[compose](names.md#prefix-versus-name_prefix) for the fields that opt in,
except for a field carrying [`env_named`](names.md#per-field-overrides), whose
spelling is absolute ([D26](decisions.md#d26)).

### Two sources, two dialects

A variable's value is a string, but a string is sometimes a serialised
structure. Those are different sources, not a flag:

```python
EnvSource("APP")        # string dialect: values are converted
TomlEnvSource("APP")    # typed dialect: each value is parsed as TOML
```

`TomlEnvSource` is what lets one variable carry a nested table:

```
APP_DATABASE='host = "db.internal"
port = 5432'
```

The variable exists because `database` carries `from_env`, so every key inside
the table is a field that opted in. `TomlEnvSource` is a
[typed-dialect source](#dialect-is-a-property-of-the-source), so its values
are checked. Rationale in [D15](decisions.md#d15).

## Config file discovery

Two front ends, one mechanism:

- **declarative**: a field marked `config_source`; its value names a file that
  becomes a source at the marker's precedence
- **imperative**: `ConfigFileDiscoverySource`, which searches `invocation_dir`
  and its ancestors for known filenames

Both resolve a `Path` to a source through one function that maps suffix to
source type:

| suffix | source | dialect |
|---|---|---|
| `.toml` | `TomlSource` | typed |
| `.yaml`, `.yml` | `YamlSource` | typed |
| `.ini`, `.cfg` | `IniSource` | string |

An unknown suffix is a [`ConfigUsageError`](diagnostics.md#errors) naming the
path and the field. That one function is the whole of what a new file format
costs: a row in the table plus a loader. [Names](names.md#the-qualified-path)
and [merging](merging.md) are format-blind.

`ConfigFileDiscoverySource` is one source. It yields the readings of every file
it found, ordered by depth with the file nearest the invocation directory
last, so the nearest file wins without any two files needing a rung of their
own. It reads the explicit-config-file field through
[the index](names.md#the-spelling-index), never a hardcoded name.

A relative path resolves against `CLISource.invocation_dir`, or the process cwd
if there is no CLI source. A file named explicitly but absent is a
[`ConfigUsageError`](diagnostics.md#errors) naming the path and the field or
option that named it; a file merely discovered to be absent is not an error.

When a discovered file becomes a source is covered by
[the iteration](lifecycle.md#resolution-is-an-iteration).

## YAML

YAML is a config file format on the same footing as TOML and INI: a
[typed-dialect](#dialect-is-a-property-of-the-source) source, addressed by
[the qualified path](names.md#the-qualified-path), sitting at `FILE` on the
ladder.

```yaml
pytest:
  log:
    cli:
      level: DEBUG
    level: WARNING
```

The flat spelling (`log_cli_level: DEBUG` under `pytest:`) works as it does in
TOML, because [both spellings](names.md#two-spellings-in-files) are a property
of the name model rather than of the file format.

It is underspecified on purpose. pytest does not read YAML, so the
[yardstick](index.md#the-yardstick) exerts no pressure on it. Four questions
are open, and a first implementation should not settle them by accident:

- **The dependency.** YAML needs a third-party parser where TOML and INI are in
  the standard library. An optional extra whose absence is a
  [`ConfigUsageError`](diagnostics.md#errors) naming the file is the obvious
  shape, but it makes a suffix's support conditional on the install.
- **Which YAML.** Safe-load only, presumably. Aliases and merge keys (`<<:`)
  then need a position, because they are the format's own composition
  mechanism, competing with [the ladder](#the-precedence-ladder).
- **Multi-document streams.** Ignore all but the first, treat them as
  successive readings, or reject them.
- **Duplicate keys and type surprises.** YAML 1.1 readers turn `no` into
  `False` and `1.0` into a float; duplicate keys are silently last-wins in most
  parsers. Both are [I8](invariants.md#i8) questions.

Tracked in [deferred](deferred.md#open-questions). Rationale in
[D17](decisions.md#d17).
