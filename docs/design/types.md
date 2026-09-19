# Types

What a raw value from a source means for a field with a declared annotation, and
where that question is allowed to be answered.

## Tokenisation versus interpretation

Every source hands over strings, and every source needs the same question
answered: what does this string mean for a field declared `list[str]`, or
`Annotated[bool, no_cli]`, or `int | None`? That question is answered once, in
`_coerce.py`.

What stays in each source is tokenisation, which differs: an INI list is
newline- or comma-separated inside one value, while a repeated CLI option
carries one element per occurrence. Splitting is the source's business;
interpreting the pieces is not. **[built]**

This split is what keeps [the source catalogue](sources.md#catalogue) open. A
new source has to know how to find and tokenise its input, never what a `bool`
looks like.

## Scalars

`bool` accepts `true/yes/on/1` and their negations, case-insensitively. `int`
and `float` parse strictly. Anything else is left as `str`. `Annotated` and
`Optional` wrappers are stripped before dispatch. **[built]**

## Unions

A union is resolved by trying each member in declaration order and taking the
first that parses. `bool | int | None` from `"4"` is `4`; from `"true"` is
`True`; from `"maybe"` is an error. **[change]**: the first non-`None` member
wins unconditionally today, so `"4"` becomes `True`. `log_auto_indent` accepts
`true|on`, `false|off` or an integer, and the acceptance test had to declare it
`str | None` to work around this. Rationale in [D3](decisions.md#d3).

Because `str` parses everything, a union containing `str` should list it last.

## Literal

`Literal["w", "a"]` declares both the type and the permitted values. A value
outside the set is a [`ConfigValueError`](diagnostics.md#errors) naming the field
and the permitted values. Those values appear in
[`format_help()`](reporting.md#help) and reach a host as
[`FieldSpec.values`](specs.md#the-record). **[new]**

`log_file_mode` is `choices=["w", "a"]` in pytest, and the acceptance test
currently declares it `str`. Until this exists the
[yardstick](index.md#the-yardstick) is measured against a softened target.

## Enum

`Enum` behaves as [`Literal`](#literal) does: a closed set, matched by value,
reported by name, reaching [help](reporting.md#help) and a binding as
[`FieldSpec.values`](specs.md#the-record). **[new]**

## The conversion registry

A field's annotation decides how a string becomes its value, and the mapping is
a registry keyed on the annotation:

```python
register_conversion(Pattern[str], re.compile)
register_conversion(MyVersion, MyVersion.parse)
```

The built-in entries are the scalars, `list[T]`, `Literal`, `Enum` and `Path`.
An application registers the rest. A field whose annotation has no entry is a
[`ConfigValueError`](diagnostics.md#errors) at declaration time, naming the
field and its type. **[new]**

Real configuration has domain types in it: a compiled pattern, an enum, a class
resolved from an entry point, a version. Converting those by hand after
construction means the fragment briefly holds a value that does not match its
declaration, which [I6](invariants.md#i6) forbids.

A converter turns text into a value of the declared type and raises if it
cannot. Range checks and cross-field constraints remain
[out of scope](deferred.md). Rationale in [D18](decisions.md#d18).

## Coercion sees the origin

Conversion receives the
[`Origin`](reporting.md#the-manager-records-sources-refine) of the value it is
converting. **[new]**

A relative path means different things depending on who supplied it. In a
config file it is relative to that file. On the command line it is relative to
the invocation directory. From the environment it means whatever the application
decides. Without the origin, `Path` fields are either wrong for one of those or
resolved by the caller after the fact, which is the same
[I6](invariants.md#i6) violation as any other post-construction fixup. Rationale
in [D19](decisions.md#d19).

## Values from typed sources

Some sources deliver values that are already typed: TOML and YAML files,
[`TomlEnvSource`](sources.md#two-sources-two-dialects), and a host adapter
handing back what its own parser produced. Those are checked against the
declared annotation and rejected on mismatch; they are not run through `coerce`.

Which of the two a source gets is decided by
[its dialect](sources.md#dialect-is-a-property-of-the-source), once.

**[change]**: typed values are neither checked nor coerced today:

```toml
[app]
mode = 5                 # str field  -> instance holds 5
port = "not-a-number"    # int field  -> instance holds "not-a-number"
```

The check belongs in `_FrozenFromKwargsMixin.__init__`, which already walks
every field, so it covers
[direct construction](config-parts.md#configpart-and-subconfig) as well as the
merge path. A failure is a [`ConfigValueError`](diagnostics.md#errors) naming
the field, the declared type, the value and its origin. Rationale in
[D4](decisions.md#d4).

Type checking is not validation: range checks, cross-field constraints and "is
this file readable" remain [out of scope](deferred.md).

## Lists

`list[T]` fields accumulate one element per repeated CLI option, and split on
newlines or commas from a single file or environment value. **[built]**

Across sources, a list is replaced wholesale by the highest-precedence source
that supplies one. Append and reset semantics are [deferred](deferred.md). The
one exception is [injected arguments](lifecycle.md#the-injected-arguments-loop),
which accumulate because every contribution is appended to the single source.
**[built]**
