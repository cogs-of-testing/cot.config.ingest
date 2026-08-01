# Types

What a raw value from a source means for a field with a declared annotation, and
where that question is allowed to be answered.

## Tokenisation versus interpretation

Every source ultimately hands over strings, and every source needs the same
question answered: what does this string mean for a field declared `list[str]`,
or `Annotated[bool, no_cli]`, or `int | None`?

That question is answered once, in `_coerce.py`.

What stays in each source is **tokenisation**, which genuinely differs: an INI
list is newline- or comma-separated inside one value, while a repeated CLI option
carries one element per occurrence. Splitting is the source's business;
interpreting the pieces is not. **[built]**

The split matters because it is what keeps [the source
catalogue](sources.md#catalogue) open. A new source has to know how to find and
tokenise its input; it never has to know what a `bool` looks like.

## Scalars

`bool` accepts `true/yes/on/1` and their negations, case-insensitively. `int` and
`float` parse strictly. Anything else is left as `str`. `Annotated` and
`Optional` wrappers are stripped before dispatch — without that,
`Annotated[bool, no_cli]` never reaches the bool branch and `"false"` comes back
as a truthy string. **[built]**

## Unions

A union is resolved by **trying each member in declaration order and taking the
first that parses**. `bool | int | None` from `"4"` is `4`; from `"true"` is
`True`; from `"maybe"` is an error. **[change]** — the first non-`None` member
currently wins unconditionally, so `bool | int | None` from `"4"` is `True`.

This matters directly: `log_auto_indent` is documented as accepting `true|on`,
`false|off` *or an integer*, and the acceptance test had to declare it as
`str | None` to work around it. Rationale in [D3](decisions.md#d3).

Because `str` parses everything, a union containing `str` should list it last.

## Literal

`Literal["w", "a"]` declares both the type and the permitted values. A value
outside the set is an error naming the field and the choices; the choices appear
in [`format_help()`](reporting.md#help) and are passed to the host adapter
(`choices=` for pytest). **[new]**

`log_file_mode` is `choices=["w", "a"]` in real pytest, and the acceptance test
currently declares it `str`. Until this exists the
[yardstick](index.md#the-yardstick) is being measured against a softened target.

## Values from typed sources

TOML and the host adapter deliver values that are *already* typed. Those are
checked against the declared annotation and rejected on mismatch; they are not
run through `coerce`. **[change]** — they are neither checked nor coerced today:

```toml
[app]
mode = 5                 # str field  -> instance holds 5
port = "not-a-number"    # int field  -> instance holds "not-a-number"
```

The check belongs in `_FrozenFromKwargsMixin.__init__`, which already walks every
field, so it covers [direct construction](config-parts.md#configpart-and-subconfig)
as well as the merge path ([I6](invariants.md#i6)). Rationale in
[D4](decisions.md#d4).

Type *checking* is not type *validation*: range checks, cross-field constraints
and "is this file readable" remain [out of scope](deferred.md).

## Lists

`list[T]` fields accumulate one element per repeated CLI option, and split on
newlines (preferred) or commas from a single file or environment value.
**[built]**

Across sources, a list is **replaced** wholesale by the highest-precedence source
that supplies one. Append and reset semantics are [deferred](deferred.md); the
one exception is `addopts`, which accumulates by construction because every
contribution is appended to the single `AddoptsSource`
([lifecycle](lifecycle.md#the-addopts-feedback-loop)). **[built]**
