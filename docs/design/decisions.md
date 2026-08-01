# Decisions

Findings from the design review, resolved. Each records the decision, why, and
what it costs.

A decision is what turns a **[change]** marker elsewhere in these documents into
a commitment. Disagreeing with one means amending the record here, not quietly
leaving the code as it is.

Rules marked **[change]** or **[new]** that appear in no decision below are
corrections with no design content — there was nothing to weigh. They are listed
in the [gap list](index.md#gap-list).

## D1

**`-o` addresses fields by flat name, and reports as `kind="override"`.**
([names](names.md#the-o-override-key),
[reporting](reporting.md#overrides-report-as-overrides))

The `-o` key is currently the structural path, which is a namespace that appears
in no help text, no ini file and no error message. Of the three plausible
spellings a user might try, the two they have actually seen elsewhere silently do
nothing, and the one that works is attributed to a CLI option the user never
typed.

Reusing the flat name means `-o` is spelled exactly like the ini key — one name
to learn, and `flat_index()` already provides the lookup. The dotted path is not
kept as an alias: two spellings for one thing is the problem, not the fix.

*Cost:* breaking. `-o cli.level=X` stops working. The library is pre-1.0 and this
is noted in the changelog rather than deprecated.

## D2

**Booleans get `--no-` variants, and an option that takes a value consumes the
next token unconditionally.** ([sources](sources.md#cli-parsing))

These look like two conveniences; they are one structural hole. The ladder puts
files below the CLI specifically so that a command-line argument can override a
file. With `store_true` as the only boolean form, a file-set `true` is
unreachable from the command line. With `not args[i+1].startswith("-")` guarding
value consumption, every negative number is unreachable — and both failures are
silent, which turns a wrong value into a debugging session.

The unconditional-consumption rule needs a companion error: an option whose value
is missing (end of tokens, or the next token is a registered option) must raise
naming the option, rather than being dropped as unknown.

*Cost:* a token that looks like an option but is not registered is now consumed
as a value where it used to land in `unknown_args`. Hosts relying on passthrough
of unregistered options *positioned directly after* a value-taking option are
affected. pytest's usage (`pytest tests/ -k foo`) is not.

## D3

**Unions are resolved by trying members left to right.**
([types](types.md#unions))

`bool | int | None` from `"4"` is currently `True`, because the first non-`None`
member wins unconditionally. That is not a defensible reading of the annotation,
and it is not hypothetical: `log_auto_indent` accepts `true|on`, `false|off` *or
an integer*, and the acceptance test had to declare it `str | None` to get around
it.

Trying members in order and taking the first that parses gives the obvious answer
for every case in the yardstick, and makes `bool` last-resort-safe because it
only accepts its known literals.

*Cost:* a union whose members overlap now resolves differently. `str | int` from
`"4"` becomes `"4"` (str parses everything), which is why `str` should be last in
a union — worth a note in the field documentation.

## D4

**Values from typed sources are checked against the annotation at construction.**
([types](types.md#values-from-typed-sources))

"Type-safe configuration" is the first line of the README, and a `str` field
currently accepts `5` from a TOML file without complaint. Coercion covers only
string-bearing sources; TOML and the host adapter deliver already-typed values
that nothing inspects.

The check goes in `_FrozenFromKwargsMixin.__init__`, which already walks every
field to apply defaults and reject unknown kwargs. That placement covers direct
construction too, so a hand-built `LoggingConfig(level=5)` fails the same way a
config file does.

*Cost:* configurations that currently "work" with wrong types start failing. That
is the point, but it is breaking, and the error must name the field, the declared
type and the value.

## D5

**`resolve()` iterates its passes to a fixpoint.**
([lifecycle](lifecycle.md#the-passes-iterate-to-a-fixpoint))

Plugin discovery is the reason the multi-pass design exists, and the current flat
pass sequence cannot support it: a type declared during pass 3 or later never
receives `discover()` and never contributes a config file. That a type declared
during pass 2 *is* picked up is an accident of list-iteration semantics, not a
designed behaviour.

Repeating passes 2–5 until the declared set stops growing makes the guarantee
explicit and makes `Discoverable` implementable. It also makes
[I3](invariants.md#i3) hold for types the host never saw.

*Cost:* resolution can loop. A declaration cycle needs a bound and an error naming
the types involved.

## D6

**One conformance suite, parameterised over backends.**
([host adapters](host-adapters.md#adapters-must-share-semantics))

The native ladder and the pytest adapter already disagree about
[collisions](names.md#collisions), and each test file only asks its own backend
what it does. The library's value proposition is that one declaration behaves the
same everywhere; nothing currently tests that claim.

The suite is the executable form of [names](names.md), [types](types.md),
[merging](merging.md) and [reporting](reporting.md) — and when pytest eventually
uses the library directly, it is the thing that says whether the replacement is
faithful.

*Cost:* the two acceptance test files partly merge, and the pytest backend will
fail cases the native one passes until it is brought into line.

## D7

**Markers are honoured at every depth; names are never built by hand.**
([names](names.md#names-are-never-constructed-by-hand),
[sources](sources.md#config-file-discovery),
[lifecycle](lifecycle.md#the-addopts-feedback-loop))

`config_source`, `addopts_field` and `bootstrap_only` are scanned with
`recurse=False`, so they silently vanish inside a `SubConfig`, while every other
marker works anywhere. `bootstrap_only`'s enforcement compares munged token
strings against bare field names and never fires when a `name_prefix` exists.
`config_source` handles `.toml` and silently ignores every other suffix after
checking the file exists.

These are three symptoms of one cause: components reaching around `_names.py` and
`_fields.py` ([I1](invariants.md#i1), [I7](invariants.md#i7)). Every confirmed
defect in the review traces here, which is the argument for making it an
invariant rather than a style note.

*Cost:* none behaviourally, beyond markers starting to work where they previously
did nothing.

## D8

**`name_prefix` is a path segment, not a string prefix; unknown keys are judged
across all declared parts.** ([names](names.md#the-qualified-path),
[names](names.md#both-spellings-in-files),
[names](names.md#unknown-keys-are-judged-across-the-section))

`name_prefix` appears in the flat, CLI and env spellings and is dropped from the
nested one. That is not a cosmetic asymmetry: `prefix` is *shared* by design —
every pytest plugin's options live in `[pytest]` — so `name_prefix` is the only
thing giving a ConfigPart identity inside its section, and the nested spelling
throws it away. Two ordinary plugins, differing only in `name_prefix` and each
with a `cli` sub-config, silently read each other's values from
`[pytest.cli] level`. The flat spelling handles the same case correctly, which
makes the nested form strictly less capable than the one it mirrors.

Treating `name_prefix` as a segment of a **qualified path** makes all four
spellings one path rendered four ways, and yields the property the design
previously claimed without delivering: the flat name split on `_` *is* the nested
table path. It also collapses two knobs that behaved differently per source into
one rule plus a separate section axis.

The unknown-key half is the same root cause seen from the merge side. A shared
section means a part sees keys belonging to other parts; judging them per-part
makes correct configuration warn (`Unknown config option(s) for Logging:
cache_cli_level`). The manager knows every declared type and is the only place
the judgement can be made correctly.

*Cost:* breaking, and the most user-visible change in this design. Nested TOML
written against the current behaviour (`[pytest.cli]`) must gain the segment
(`[pytest.log.cli]`). Parts with no `name_prefix` are unaffected — their
qualified path is just their path. `named()` is unaffected: it overrides the flat
name only, so `("file","path")` stays `[pytest.log.file] path` structurally and
`[pytest] log_file` flat.

*Alternative rejected:* making the section itself `[pytest.log]` when a
`name_prefix` exists. It reads well but contradicts the motivating case —
pytest's keys really do live directly in the `[pytest]` section as
`log_cli_level`, and moving them would break the flat spelling to fix the nested
one.
