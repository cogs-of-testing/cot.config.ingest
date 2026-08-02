# Specs

What an option *is*, as data, in the library's own vocabulary. **[new]**

A `FieldSpec` is a pure function of a ConfigPart: no parser, no host, no I/O.
It is what [bindings](binding-contract.md) bind, what [help](reporting.md#help)
renders, and what the [conformance suite](binding-contract.md#conformance)
compares.

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
    env_key: str | None         # None unless the field opts in
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

`flag`, `repeatable`, `counts` and `values` describe the *field*. A binding maps
them to whatever its host calls them, inside the binding, as a function rather
than a stored record — so there is exactly one translation step and it is
per-host.

```
flag=True                ->  argparse action="store_true"
repeatable=True          ->  argparse action="append"
counts=True              ->  argparse action="count"
values=(...)             ->  argparse choices=(...)
accumulates_to=X         ->  argparse action="store_const", const=X
optional=True            ->  argparse nargs="?"
```

None of those words appear in the core.

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
| `env_key` | the flat name, only when opted in | required |
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
