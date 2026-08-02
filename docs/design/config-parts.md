# ConfigParts

The data model: the classes a user writes, and the field model everything else
reads them through.

## ConfigPart and SubConfig

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

A `ConfigPart` used as a nested field is an error, raised at declaration time and
naming the field and both classes. **[new]** — today it produces
`TypeError: Outer missing required field(s): inner` at build time, which points
nowhere useful.

Both are:

- **keyword-only** — there is no positional construction **[built]**
- **frozen** — `__setattr__` and `__delattr__` raise **[built]**
- **materialised** — defaults are written into the instance `__dict__`, so
  equality, `repr` and [`explain()`](reporting.md#the-provenance-api) do not
  depend on whether a value was passed or inherited from the class body
  **[built]**
- **hashable** — list/dict/set values are frozen structurally for `__hash__`,
  rather than making every config object unhashable because one field might hold
  a list **[built]**

A mutable class-level default is copied per instance. The copy is deep, so a
`list[list[str]]` default is not shared through its inner lists. **[change]** —
the copy is currently shallow.

`@dataclass_transform(eq_default=True, kw_only_default=True, frozen_default=True)`
gives type checkers the right synthesised `__init__`. **[built]**

Construction is also where type checking belongs — see
[types](types.md#values-from-typed-sources).

## Fields

Type annotations are **required**. There is no inference: a class attribute
without an annotation is not a field. **[built]**

The field model in `_fields.py` is the single source of truth about a class's
shape. `fields_of(cls)` walks the MRO, resolves annotations with
`include_extras=True`, and returns `FieldInfo` records:

| Attribute | Meaning |
|---|---|
| `path` | `("cli", "level")` — the identity ([I1](invariants.md#i1)) |
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

## Markers

Markers are `Annotated` extras, written either way:

```python
level: Annotated[str, from_parent, help("log level")] = "WARNING"
level: str @ from_parent @ help("log level") = "WARNING"      # _MarkerMixin.__rmatmul__
```

| Marker | Effect | Documented in |
|---|---|---|
| `from_parent` | value cascades from the parent field of the same name | [merging](merging.md#the-from_parent-cascade) |
| `named("...")` | replaces the derived flat name | [names](names.md#per-field-overrides) |
| `no_cli` | suppresses the CLI option, keeps ini and env | [names](names.md#per-field-overrides) |
| `short("v")` | adds a short option | [names](names.md#per-field-overrides) |
| `help("...")` | help text | [reporting](reporting.md#help) |
| `config_source` | the value names a file that becomes a source | [sources](sources.md#config-file-discovery) |
| `injected_args` | the value is re-parsed as CLI tokens | [lifecycle](lifecycle.md#the-injected-arguments-loop) |
| `bootstrap_only` | cannot be set from injected arguments | [lifecycle](lifecycle.md#the-injected-arguments-loop) |
| `no_ini` | suppresses the file spelling | [names](names.md#per-field-overrides) |
| `from_env` | opts the field into environment reading | [sources](sources.md#environment-exposure) |
| `counted` | occurrences are summed | [specs](specs.md#derivation-over-declaration) |
| `contributes(v)` | presence contributes a fixed value | [specs](specs.md#derivation-over-declaration) |

Every one of them works at any depth ([I7](invariants.md#i7)). `config_source`,
`injected_args` and `bootstrap_only` currently do not — see
[names](names.md#names-are-never-constructed-by-hand). The last four are
**[new]**.

`prefix=` and `name_prefix=` are class keywords rather than field markers,
because they describe the ConfigPart, not a field. See
[names](names.md#prefix-versus-name_prefix).

## Required and optional

A field with no default and no `SubConfig` type is **required**: if no source
supplies it, construction raises `TypeError` naming every missing field at once.
A `SubConfig` field never needs a default — the manager builds it from its own
defaults. **[built]**
