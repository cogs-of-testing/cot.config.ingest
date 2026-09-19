# ConfigParts

The data model: the class a user writes, and the field model everything else
reads it through.

## One class, two roles

```python
class LogCliConfig(ConfigPart):
    level: Annotated[str | None, from_parent] = None
    enabled: bool = False

class LoggingConfig(ConfigPart, prefix="pytest", name_prefix="log"):
    level: str = "WARNING"
    cli: LogCliConfig
```

There is one class. A ConfigPart handed to `manager.declare()` is a **root**:
the unit a plugin declares and a host retrieves. A ConfigPart that is the type
of another part's field is **nested**: a section inside its parent, positioned
by its path. The same class may play both roles in different declarations,
because a field's identity is its path within the root ([I1](invariants.md#i1))
and a class carries no position of its own. `FieldInfo.is_nested` reports
which fields hold a part.

`prefix=`, `name_prefix=` and `from_env=` are class keywords that describe a
root. A nested part carrying any of them is a
[`ConfigDeclarationError`](diagnostics.md#errors) at `declare()`, naming the
field and the keyword: the keyword would have no effect, and its author
expected one. Rationale in [D30](decisions.md#d30).

Instances in either role are:

- **keyword-only**, with no positional construction
- **frozen**: `__setattr__` and `__delattr__` raise
- **materialised**: defaults are written into the instance `__dict__`, so
  equality, `repr` and [`explain()`](reporting.md#the-provenance-api) do not
  depend on whether a value was passed or inherited
- **hashable**: list, dict and set values are frozen structurally for
  `__hash__`

A mutable class-level default is deep-copied per instance, so a
`list[list[str]]` default is not shared through its inner lists.

`@dataclass_transform(eq_default=True, kw_only_default=True, frozen_default=True)`
gives type checkers the right synthesised `__init__`.

Construction is where required fields are enforced and where a directly
constructed instance is type-checked
([types](types.md#construction-checks)).

## Fields

Type annotations are required. A class attribute without an annotation is not a
field.

The field model in `_fields.py` is the single source of truth about a class's
shape. `fields_of(cls)` walks the MRO, resolves annotations with
`include_extras=True`, and returns `FieldInfo` records:

| Attribute | Meaning |
|---|---|
| `path` | `("cli", "level")`, the identity ([I1](invariants.md#i1)) |
| `name` | `"level"`, the bare attribute |
| `annotation` | as written, `Annotated[...]` preserved |
| `type` | `Annotated` and `Optional` stripped |
| `default` | the class-level default, or `MISSING` |
| `markers` | the `Annotated` extras, in declaration order |
| `owner` | the MRO class that declared it |
| `is_nested` | whether `type` is a `ConfigPart` subclass |

No other module may re-derive this. A `get_origin(x) is Annotated` loop outside
`_fields.py` is a bug.

Results are cached per `(cls, recurse)` in a `WeakKeyDictionary`, so classes
defined inside test functions do not leak.

Inheritance stays simple: parts pick up fields via `__mro__`, base classes
first. Nothing beyond what the acceptance test needs is supported, which is
`LogCliConfig(LogOutputConfig)` and
`LoggingConfig(LogOutputConfig, ConfigPart, ...)`.

## Markers

Markers are `Annotated` extras, written either way:

```python
level: Annotated[str, from_parent, help("log level")] = "WARNING"
level: str @ from_parent @ help("log level") = "WARNING"      # _MarkerMixin.__rmatmul__
```

`@` binds tighter than `|`, so `str | None @ from_parent` annotates `None`
alone and the marker is lost. A union takes `Annotated[...]` or parentheses:
`(str | None) @ from_parent`.

| Marker | Effect | Documented in |
|---|---|---|
| `from_parent` | value cascades from the parent field of the same name | [merging](merging.md#the-from_parent-cascade) |
| `named("...")` | replaces the derived flat name | [names](names.md#per-field-overrides) |
| `formerly("...")` | declares a legacy flat spelling; a value arriving under it warns | [names](names.md#per-field-overrides) |
| `env_named("...")` | pins an absolute environment variable name | [names](names.md#per-field-overrides) |
| `from_env` | gives the field, or a nested part's whole subtree, an environment spelling | [sources](sources.md#exposure-is-opt-in) |
| `no_cli` | suppresses the CLI option, keeps file and env | [names](names.md#per-field-overrides) |
| `no_ini` | suppresses the file spelling, keeps CLI and env | [names](names.md#per-field-overrides) |
| `short("v")` | adds a short option to the field's own CLI form | [names](names.md#per-field-overrides) |
| `form("--exitfirst", short="x", contributes=1)` | adds a further CLI form, optionally supplying a constant | [specs](specs.md#cli-forms) |
| `counted` | occurrences of any CLI form are summed | [specs](specs.md#derivation-over-declaration) |
| `help("...")` | help text | [reporting](reporting.md#help) |
| `config_source` | the value names a file that becomes a source | [sources](sources.md#config-file-discovery) |
| `injected_args` | the value is re-parsed as CLI tokens | [lifecycle](lifecycle.md#the-injected-arguments-loop) |
| `bootstrap_only` | cannot be set from injected arguments | [lifecycle](lifecycle.md#the-injected-arguments-loop) |

Every one of them works at any depth ([I7](invariants.md#i7)).

`prefix=`, `name_prefix=` and `from_env=` are class keywords rather than field
markers, because they describe the root, not a field. See
[names](names.md#prefix-versus-name_prefix) and
[the environment](sources.md#exposure-is-opt-in).

## Required and optional

A field with no default and no nested type is required. If no source supplies
it, construction raises [`MissingConfigError`](diagnostics.md#errors) naming
every missing field at once, along with the origins that were found. A nested
field never needs a default; the manager builds it from its own defaults.
