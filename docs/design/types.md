# Types

What a raw value from a source means for a field with a declared annotation,
where that question is answered, and what happens when the answer is no.

## Tokenisation versus conversion

Every source hands over raw values, and every one of them needs the same
question answered: what does this mean for a field declared `list[str]`, or
`Annotated[bool, no_cli]`, or `int | None`? That question is answered once, by
[the conversion registry](#the-conversion-registry), when the value enters
[the store](merging.md#the-layered-store).

What stays in each source is tokenisation, which differs: an INI list is
newline- or comma-separated inside one value, while a repeated CLI option
carries one element per occurrence. Splitting is the source's business;
interpreting the pieces is not.

This split is what keeps [the source catalogue](sources.md#catalogue) open. A
new source has to know how to find and tokenise its input, never what a `bool`
looks like.

## Two dialects

A [string-dialect source](sources.md#dialect-is-a-property-of-the-source) hands
over text and the registry **converts** it. A typed-dialect source, TOML, YAML,
`TomlEnvSource` or a host adapter handing back what its own parser produced,
hands over values that already have types, and the registry **checks** them
against the annotation instead. Which of the two a value gets is decided by its
source's dialect, once. A value is never converted twice.

## Scalars

`bool` accepts `true/yes/on/1` and their negations, case-insensitively. `int`
and `float` parse strictly. `str` accepts any text. `Annotated` and `Optional`
wrappers are stripped before dispatch.

## Unions

A union is resolved by trying each member in declaration order and taking the
first that converts or checks. `bool | int | None` from `"4"` is `4`; from
`"true"` is `True`; from `"maybe"` is an error. Because `str` accepts
everything, a union containing `str` should list it last. Rationale in
[D3](decisions.md#d3).

## Literal and Enum

`Literal["w", "a"]` declares both the type and the permitted values. A value
outside the set is a [`ConfigValueError`](diagnostics.md#errors) naming the
field and the permitted values. Those values appear in
[`format_help()`](reporting.md#help) and reach a host as
[`FieldSpec.values`](specs.md#the-record).

`Enum` is a closed value set whose members have names: matched by value,
reported by name, reaching help and bindings the same way.

## The conversion registry

The mapping from annotation to conversion is a registry keyed on the
annotation:

```python
register_conversion(Pattern[str], re.compile)
register_conversion(MyVersion, MyVersion.parse)
```

The built-in entries are the scalars, `list[T]`, `Literal`, `Enum` and `Path`.
An application registers the rest. A field whose annotation has no entry is a
[`ConfigDeclarationError`](diagnostics.md#errors) at `declare()`, naming the
field and its type: a field the library cannot convert is a declaration it
cannot honour.

A converter turns a raw value into a value of the declared type and raises if
it cannot. Range checks and cross-field constraints remain
[out of scope](deferred.md). Rationale in [D18](decisions.md#d18).

The registry is global, not per manager, because a conversion is a property of
the type: the same annotation must mean the same thing in every part of one
program.

## Conversion sees the origin

A converter receives the
[`Origin`](reporting.md#the-manager-records-sources-refine) of the value it is
converting.

A relative path means different things depending on who supplied it. In a
config file it is relative to that file. On the command line it is relative to
the invocation directory. From the environment it means whatever the
application decides. Without the origin, `Path` fields are either wrong for one
of those or resolved by the caller after construction, which is the
[I6](invariants.md#i6) violation the registry exists to remove. Rationale in
[D19](decisions.md#d19).

## When conversion fails

Every reading entering the store is converted, whether or not it will win
([merging](merging.md#the-layered-store)). A failure is reported according to
what the reading would have done:

| the failing reading | response |
|---|---|
| is the winner for its path | [`ConfigValueError`](diagnostics.md#errors) naming the field, the declared type, the value and its origin |
| is shadowed by a higher layer | [`ShadowedValueWarning`](diagnostics.md#warnings) naming the same four things and the origin that shadowed it |
| is shadowed, under `strict=True` | `ConfigValueError` |

A shadowed bad value is still a broken file: the day the override goes away it
becomes the winner. The warning says so while the run can continue
([the diagnostics rule](diagnostics.md#the-rule)); strict mode is for the
application that would rather know now. Rationale in [D28](decisions.md#d28).

## Construction checks

`__init__` walks every field and checks each value against its annotation.
Values arriving from the store have already been converted, so for them this is
a second, cheap pass. It exists for direct construction: a hand-built
`LoggingConfig(level=5)` fails the same way a config file does, with a
[`ConfigValueError`](diagnostics.md#errors) naming the field, the type and the
value. Rationale in [D4](decisions.md#d4).

Type checking is not validation: range checks, cross-field constraints and "is
this file readable" remain [out of scope](deferred.md).

## Lists

`list[T]` fields accumulate one element per repeated CLI option, and split on
newlines or commas from a single file or environment value.

Across sources, a list is replaced wholesale by the highest-precedence source
that supplies one. Append and reset semantics are [deferred](deferred.md). The
one exception is [injected arguments](lifecycle.md#the-injected-arguments-loop),
which accumulate because every contribution is appended to the single injected
source.
