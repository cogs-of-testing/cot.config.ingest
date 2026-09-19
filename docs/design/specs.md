# Specs

What an option is, as data, in the library's own vocabulary.

A `FieldSpec` is a pure function of a root: no parser, no host, no I/O. It is
what [binders](binding-contract.md) bind, what
[the index](names.md#the-spelling-index) is built from, what
[help](reporting.md#help) renders, and what the
[conformance suite](binding-contract.md#conformance) compares.

Every spelling in the record has to be answerable from the class alone. That is
why [environment exposure](sources.md#exposure-is-opt-in) is a marker on the
field and not a policy on the source, and why the environment spelling stops
short of the source's own prefix. A spec that needed to know which sources
exist would be a different value for each manager.

## The record

```python
@dataclass(frozen=True)
class CliForm:
    long: str | None            # "--log-cli-level"; None for a short-only form
    short: str | None           # "-v"
    negative: str | None        # "--no-verbose"; every boolean form has one
    flag: bool                  # presence alone carries the value
    contributes: Any            # MISSING, or the constant this form supplies

@dataclass(frozen=True)
class EnvSpelling:
    name: str                   # "PYTEST_LOG_CLI_LEVEL", or "SOURCE_DATE_EPOCH"
    absolute: bool              # env_named(): the source adds no prefix

@dataclass(frozen=True)
class FieldSpec:
    path: tuple[str, ...]       # ("cli", "level"), the identity (I1)
    flat: str                   # "log_cli_level"
    file_key: str | None        # None under no_ini
    env: EnvSpelling | None     # None unless the field opts in
    cli: tuple[CliForm, ...]    # empty under no_cli
    annotation: Any
    default: Any

    repeatable: bool            # each occurrence accumulates
    optional: bool              # absence is meaningful
    counts: bool                # occurrences of any form are summed
    values: tuple[Any, ...] | None   # a closed set, from Literal or Enum

    aliases: tuple[str, ...]    # from formerly()
    help: str
    group: str
```

`field_specs(T) -> tuple[FieldSpec, ...]` is the single derivation. Nothing
else may re-derive what an option looks like.

## CLI forms

A field has one spec and any number of command-line forms, because one path
can be addressed by several option strings with different behaviour. pytest's
`maxfail` is `--maxfail N` and also `-x`, which supplies the constant `1`. One
form per spec could not say that without making `--maxfail 5` impossible.

The first form is derived from the qualified path and `short()`. Each
`form()` marker adds one more. `counts`, `repeatable` and `values` describe
the field and apply to every form; `flag` and `contributes` describe a form.
Rationale in [D25](decisions.md#d25).

## Why it is a layer

- **It is assertable without a host.** `field_specs(LoggingConfig)` is a value
  a test compares against a table. No parser has to be stood up.
- **It is the boundary.** Everything downstream of a spec is host-shaped and
  everything upstream is the field model
  ([the contract](binding-contract.md#vocabulary-stops-at-the-boundary)).
- **The native parser is the first binder.** `CLISource.bind()` registers
  specs with the library's own parser the way the pytest binding registers
  them with argparse, so [conformance](binding-contract.md#conformance) has
  two backends before a second host exists.

## The vocabulary is the library's

`flag`, `repeatable`, `counts`, `optional`, `values` and `contributes`
describe the field: what it does when it appears, whether appearing twice means
something, and whether its values are a closed set. They are answerable by
reading the annotation and the markers.

A host's own words for the same ideas belong to that host. The mapping onto
them lives in its [binding](binding-contract.md), as a function over specs
rather than a field on one. The core never learns any host's vocabulary
([the contract](binding-contract.md#vocabulary-stops-at-the-boundary)).

## Derivation over declaration

Almost everything is derived from the annotation. A marker is added only where
nothing can be inferred.

| Spec field | derived from | marker |
|---|---|---|
| `cli[0].flag` | `bool` | – |
| `cli[0].negative` | `bool`; every boolean form gets its `--no-` form | – |
| `repeatable` | `list[T]` | – |
| `optional` | `T \| None` | – |
| `values` | `Literal[...]`, `Enum` | – |
| `cli[0].long` / `cli[0].short` / `flat` | the [qualified path](names.md#the-qualified-path), `named()`, `short()` | – |
| `cli[1:]` | nothing; a second spelling is not in the type | `form()`, required |
| `file_key` | the flat name, unless suppressed | `no_ini` |
| `env` | `prefix` and the flat name, only when the field opts in | `from_env`, required; `env_named()` for an absolute name |
| `aliases` | nothing; a legacy name is not in the type | `formerly()`, required |
| `counts` | nothing; `-j 4` and `-v -v` are both `int` with a short option | `counted`, required |
| `cli[n].contributes` | nothing; the constant is not in the type | `form(..., contributes=)`, required |

A "store false" concept is unnecessary, because every boolean form already has
a `--no-` form ([D2](decisions.md#d2)).

An arbitrary converter function has no annotation that implies it. Such options
cannot be specced and stay host-native; a binding that supports them handles
them through ingest.
