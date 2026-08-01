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
defaults(-1)  <  file(15)  <  addopts(18)  <  env(20)  <  cli(25)
```

These are **defaults, not an enum**. Every source takes `precedence=`, and so
does every marker that creates one, so an application that wants its config files
to outrank the environment says so:

```python
TomlSource(path, precedence=Precedence.ENV + 1)
```

`DEFAULTS` is negative so that a value nobody configured loses to every real
source, including one declared at precedence 0. Gaps between the rungs exist so
callers can slot in without renumbering. **[built]**

This ladder *is* the whole ordering rule ([I2](invariants.md#i2)). Nothing is
special-cased above it — which is why `addopts` is a source at its own rung
rather than a splice into argv
([lifecycle](lifecycle.md#the-addopts-feedback-loop)).

Ties are broken by **insertion order**: the sort is stable, so among sources at
the same precedence the one added later wins. This is how "the local config file
beats the one in the parent directory" works. It is a real rule and is documented
here rather than left incidental. **[built]**

There is one `Precedence.FILE`. Tiers such as system / user / local are expressed
as `FILE`, `FILE + 1`, `FILE + 2` by whoever constructs the sources, or by
insertion order. No new constants. **[built]**

## Catalogue

| Source | Reads | Declares | Describes origin |
|---|---|---|---|
| `TomlSource` | one TOML file, section by `prefix` | – | file + key |
| `IniSource` | one INI file, section case-insensitive | – | file + key |
| `CLISource` | argv tokens | ✓ | option, `-s/--long` if short exists |
| `AddoptsSource` | tokens from `addopts_field` values | ✓ | `addopts --long` |
| `EnvSource` | `os.environ` or an injected dict | – | variable name |
| `ConfigFileDiscoverySource` | finds a file, delegates | – | delegates |
| `PytestOptionSource` | pytest `Config` | ✓ | cli or ini ([host adapters](host-adapters.md)) |

**[built]**

Which names each of these looks for is not their own business — it comes from
[the qualified path](names.md#the-qualified-path).

## CLI parsing

The parser exists for one reason: **options must be registrable after parsing has
already happened**. A config file read during resolution can contribute `addopts`
that must be parsed against options a later plugin declared. argparse cannot
re-open a parsed namespace; this parser re-parses from scratch on every `load()`,
which makes registration order irrelevant. **[built]**

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

## Config file discovery

Two front ends, one mechanism:

- **declarative** — a field marked `config_source`; its value names a file that
  becomes a source at the marker's precedence
- **imperative** — `ConfigFileDiscoverySource`, which searches `invocation_dir`
  and its ancestors for known filenames

Both resolve a `Path` to a source through **one** function that maps suffix to
source type (`.toml` → `TomlSource`, `.ini`/`.cfg` → `IniSource`). An unknown
suffix is an error naming the path and the field. **[change]** — the decision is
currently made twice, differently: `ConfigFileDiscoverySource._create_source`
handles `.ini`, while the `config_source` path is `if value.suffix in (".toml",)`
— so a `config_source` field pointing at an `.ini` file has its existence checked
and enforced, and then nothing happens at all ([I8](invariants.md#i8)).

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
