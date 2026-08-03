# Specs

What an option *is*, as data, in the library's own vocabulary. **[new]**

A `FieldSpec` is a pure function of a ConfigPart: no parser, no host, no I/O.
It is what [bindings](binding-contract.md) bind, what [help](reporting.md#help)
renders, and what the [conformance suite](binding-contract.md#conformance)
compares.

*Pure function of a ConfigPart* is a constraint, not a description. Every
spelling in the record has to be answerable from the class alone — which is why
[environment exposure](sources.md#exposure-is-opt-in) is a marker on the field
and not a policy on the source. A spec that needed to know which sources exist
would be a different value for each manager, and neither help nor conformance
could compare it to anything.

## The record

```python
@dataclass(frozen=True)
class FieldSpec:
    path: tuple[str, ...]       # ("cli", "level") — the identity (I1)
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

Two properties earn `FieldSpec` its own layer rather than inlining the
derivation wherever options get registered:

- **it is assertable without a host.** `field_specs(LoggingConfig)` is a value. A
  test states what it should be and compares. There is no parser to stand up and
  no private dictionary to inspect.
- **it is the boundary.** Everything downstream of a spec is host-shaped;
  everything upstream is the field model. Keeping the two apart is what stops a
  host's vocabulary leaking inward
  ([the contract](binding-contract.md#vocabulary-stops-at-the-boundary)).

## The vocabulary is the library's

`flag`, `repeatable`, `counts`, `optional`, `values` and `accumulates_to`
describe the *field*: what it does when it appears, whether appearing twice means
something, and whether its values are a closed set. They are answerable by
reading the annotation, with no parser in the room.

A host's own words for the same ideas — the action names, the type names, the
attribute a parser stores under — are that host's, and the mapping onto them
lives in that [binding](binding-contract.md), as a function over specs rather
than a field on one. There is then exactly one translation step per host, in one
place, and **the core never learns any host's vocabulary**
([the contract](binding-contract.md#vocabulary-stops-at-the-boundary)).

That table used to be printed here, in argparse's terms, immediately above a
sentence claiming none of those words appear in the core. It was the residue of a
spec layer designed inside a pytest plan; it now lives on the binding side, where
its second copy already was.

## Derivation over declaration

Almost everything is **derived** from the annotation. A marker is added only
where nothing can be inferred.

| Spec field | derived from | marker |
|---|---|---|
| `flag` | `bool` | – |
| `negative` | `bool` — every boolean gets its `--no-` form | – |
| `repeatable` | `list[T]` | – |
| `optional` | `T \| None` | – |
| `values` | `Literal[...]` | – |
| `long` / `short` / `flat` | the [qualified path](names.md#the-qualified-path), `named()`, `short()` | – |
| `file_key` | the flat name, unless suppressed | `no_ini` |
| `env_key` | the flat name, only when the field opts in | `from_env`, required |
| `aliases` | `named()` plus declared legacy spellings | – |
| `counts` | **nothing** — `-j 4` and `-v -v` are both `int` with a short option | required |
| `accumulates_to` | **nothing** — the constant is not in the type | required |

The two that resist derivation are the honest residue. A counter and a
one-shot integer option have identical annotations, and a fixed contributed
value is not expressible as a type, so both need a marker. Everything else falls
out of the declaration.

Note what disappears: a "store false" concept is unnecessary, because every
boolean already has a `--no-` form ([D2](decisions.md#d2)).

An arbitrary converter function — a host letting a plugin supply its own
string-to-value callable — has no annotation that implies it. Such options
cannot be specced and stay host-native; a binding that supports them handles
them through ingest.
