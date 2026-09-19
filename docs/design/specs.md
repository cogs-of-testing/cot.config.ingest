# Specs

What an option is, as data, in the library's own vocabulary. **[new]**

A `FieldSpec` is a pure function of a ConfigPart: no parser, no host, no I/O.
It is what [bindings](binding-contract.md) bind, what [help](reporting.md#help)
renders, and what the [conformance suite](binding-contract.md#conformance)
compares.

Every spelling in the record has to be answerable from the class alone. That is
why [environment exposure](sources.md#exposure-is-opt-in) is a marker on the
field and not a policy on the source. A spec that needed to know which sources
exist would be a different value for each manager.

## The record

```python
@dataclass(frozen=True)
class FieldSpec:
    path: tuple[str, ...]       # ("cli", "level"), the identity (I1)
    flat: str                   # "log_cli_level"
    long: str | None            # "--log-cli-level", None when no_cli
    negative: str | None        # "--no-log-cli", booleans only
    short: str | None           # "-v"
    file_key: str | None        # None when the field has no file spelling
    env_key: str | None         # None unless the field carries from_env
    annotation: Any
    default: Any

    flag: bool                  # presence alone carries the value
    repeatable: bool            # each occurrence accumulates
    optional: bool              # absence is meaningful
    values: tuple[Any, ...] | None   # a closed set, from Literal
    accumulates_to: Any | None  # the value presence contributes, if fixed
    counts: bool                # occurrences are summed

    aliases: tuple[str, ...]    # legacy spellings
    help: str
    group: str
```

`field_specs(T) -> tuple[FieldSpec, ...]` is the single derivation. Nothing else
may re-derive what an option looks like.

## Why it is a layer

- **It is assertable without a host.** `field_specs(LoggingConfig)` is a value
  a test compares against a table. No parser has to be stood up.
- **It is the boundary.** Everything downstream of a spec is host-shaped and
  everything upstream is the field model
  ([the contract](binding-contract.md#vocabulary-stops-at-the-boundary)).

## The vocabulary is the library's

`flag`, `repeatable`, `counts`, `optional`, `values` and `accumulates_to`
describe the field: what it does when it appears, whether appearing twice means
something, and whether its values are a closed set. They are answerable by
reading the annotation.

A host's own words for the same ideas belong to that host. The mapping onto them
lives in its [binding](binding-contract.md), as a function over specs rather
than a field on one. The core never learns any host's vocabulary
([the contract](binding-contract.md#vocabulary-stops-at-the-boundary)).

## Derivation over declaration

Almost everything is derived from the annotation. A marker is added only where
nothing can be inferred.

| Spec field | derived from | marker |
|---|---|---|
| `flag` | `bool` | – |
| `negative` | `bool`; every boolean gets its `--no-` form | – |
| `repeatable` | `list[T]` | – |
| `optional` | `T \| None` | – |
| `values` | `Literal[...]` | – |
| `long` / `short` / `flat` | the [qualified path](names.md#the-qualified-path), `named()`, `short()` | – |
| `file_key` | the flat name, unless suppressed | `no_ini` |
| `env_key` | the flat name, only when the field opts in | `from_env`, required |
| `aliases` | `named()` plus declared legacy spellings | – |
| `counts` | nothing; `-j 4` and `-v -v` are both `int` with a short option | required |
| `accumulates_to` | nothing; the constant is not in the type | required |

A "store false" concept is unnecessary, because every boolean already has a
`--no-` form ([D2](decisions.md#d2)).

An arbitrary converter function has no annotation that implies it. Such options
cannot be specced and stay host-native; a binding that supports them handles
them through ingest.
