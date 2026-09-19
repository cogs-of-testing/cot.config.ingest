# Decisions

Findings from the design review, resolved. Each records the decision, why, and
what it costs.

A decision is what turns a **[change]** marker elsewhere into a commitment.
Disagreeing with one means amending the record here, not quietly leaving the
code as it is. Rules marked **[change]** or **[new]** that appear in no decision
are corrections with no design content; they are listed in the
[gap list](index.md#gap-list).

## D1

**`-o` addresses fields by flat name, and reports as `kind="override"`.**
([names](names.md#the-o-override-key),
[reporting](reporting.md#overrides-report-as-overrides))

The `-o` key is currently the structural path, a namespace that appears in no
help text, no ini file and no error message. Of the three spellings a user
might try, the two they have seen elsewhere silently do nothing, and the one
that works is attributed to a CLI option the user never typed.

Reusing the flat name means `-o` is spelled exactly like the ini key, and
`flat_index()` already provides the lookup. The dotted path is not kept as an
alias.

*Cost:* breaking. `-o cli.level=X` stops working. The library is pre-1.0 and
this is noted in the changelog rather than deprecated.

Scope is a [binding](binding-contract.md) matter: a host may narrow which
fields `-o` reaches, and the pytest binding does. The addressing settled here
is not negotiable.

## D2

**Booleans get `--no-` variants, and an option that takes a value consumes the
next token unconditionally.** ([sources](sources.md#cli-parsing))

These are one structural hole. The ladder puts files below the CLI so that a
command-line argument can override a file. With `store_true` as the only
boolean form, a file-set `true` is unreachable from the command line. With
`not args[i+1].startswith("-")` guarding value consumption, every negative
number is unreachable. Both failures are silent.

Unconditional consumption needs a companion error: an option whose value is
missing must raise naming the option, rather than being dropped as unknown.

*Cost:* a token that looks like an option but is not registered is now consumed
as a value where it used to land in `unknown_args`. Hosts relying on
passthrough of unregistered options positioned directly after a value-taking
option are affected. pytest's usage is not.

## D3

**Unions are resolved by trying members left to right.**
([types](types.md#unions))

`bool | int | None` from `"4"` is currently `True`, because the first non-`None`
member wins unconditionally. `log_auto_indent` accepts `true|on`, `false|off`
or an integer, and the acceptance test had to declare it `str | None` to get
around it.

Trying members in order and taking the first that parses gives the obvious
answer for every case in the yardstick, because `bool` only accepts its known
literals.

*Cost:* a union whose members overlap resolves differently. `str | int` from
`"4"` becomes `"4"`, which is why `str` should be last in a union.

## D4

**Values from typed sources are checked against the annotation at construction.**
([types](types.md#values-from-typed-sources))

"Type-safe configuration" is the first line of the README, and a `str` field
currently accepts `5` from a TOML file. Coercion covers only string-bearing
sources; TOML and the host adapter deliver already-typed values that nothing
inspects.

The check goes in `_FrozenFromKwargsMixin.__init__`, which already walks every
field. That placement covers direct construction too, so a hand-built
`LoggingConfig(level=5)` fails the same way a config file does.

*Cost:* configurations that currently work with wrong types start failing. The
error must name the field, the declared type and the value.

## D5

**`resolve()` iterates its passes to a fixpoint.**
([lifecycle](lifecycle.md#the-passes-iterate-to-a-fixpoint))

Plugin discovery is the reason the multi-pass design exists, and the current
flat pass sequence cannot support it: a type declared during pass 3 or later
never receives `discover()` and never contributes a config file.

Repeating passes 2 to 5 until the declared set stops growing makes the
guarantee explicit and makes `Discoverable` implementable. It also makes
[I3](invariants.md#i3) hold for types the host never saw.

*Cost:* resolution can loop. A declaration cycle needs a bound and an error
naming the types involved.

## D6

**One conformance suite, parameterised over backends.**
([the binding contract](binding-contract.md#conformance))

The native ladder and the pytest binding already disagree about
[collisions](names.md#collisions), and each test file only asks its own backend
what it does. Nothing tests the claim that one declaration behaves the same
everywhere.

The suite is the executable form of [names](names.md), [types](types.md),
[merging](merging.md) and [reporting](reporting.md). When pytest uses the
library directly, it is what says whether the replacement is faithful.

*Cost:* the two acceptance test files partly merge, and the pytest backend will
fail cases the native one passes until it is brought into line.

## D7

**Markers are honoured at every depth; names are never built by hand.**
([names](names.md#names-are-never-constructed-by-hand),
[sources](sources.md#config-file-discovery),
[lifecycle](lifecycle.md#the-injected-arguments-loop))

`config_source`, `addopts_field` and `bootstrap_only` are scanned with
`recurse=False`, so they vanish inside a `SubConfig`. `bootstrap_only`'s
enforcement compares munged token strings against bare field names and never
fires when a `name_prefix` exists. `config_source` handles `.toml` and silently
ignores every other suffix.

These are three symptoms of one cause: components reaching around `_names.py`
and `_fields.py` ([I1](invariants.md#i1), [I7](invariants.md#i7)). Every
confirmed defect in the review traces here, which is why it is an invariant
rather than a style note.

*Cost:* none behaviourally, beyond markers starting to work where they
previously did nothing.

## D8

**`name_prefix` is a path segment, not a string prefix; unknown keys are judged
across all declared parts.** ([names](names.md#the-qualified-path),
[names](names.md#both-spellings-in-files),
[names](names.md#unknown-keys-are-judged-across-the-section))

`name_prefix` appears in the flat, CLI and env spellings and is dropped from
the nested one. `prefix` is shared by design, so `name_prefix` is the only
thing giving a ConfigPart identity inside its section, and the nested spelling
throws it away. Two plugins differing only in `name_prefix`, each with a `cli`
sub-config, silently read each other's values from `[pytest.cli] level`.

Treating `name_prefix` as a segment of a qualified path makes all four
spellings one path rendered four ways, so the flat name split on `_` is the
nested table path.

The unknown-key half is the same root cause seen from the merge side. Judging
keys per part makes correct configuration warn. The manager knows every
declared type and is the only place the judgement can be made correctly.

*Cost:* breaking, and the most user-visible change in this design. Nested TOML
written against the current behaviour (`[pytest.cli]`) must gain the segment
(`[pytest.log.cli]`). Parts with no `name_prefix` are unaffected. `named()` is
unaffected: it overrides the flat name only.

*Alternative rejected:* making the section itself `[pytest.log]` when a
`name_prefix` exists. pytest's keys really do live directly in the `[pytest]`
section as `log_cli_level`, and moving them would break the flat spelling to
fix the nested one.

## D9

**Options are specified as data; hosts bind that data.**
([specs](specs.md))

The mapping from a ConfigPart to `parser.addoption` and `parser.addini` lives
inside `PytestOptionSource.declare`, entangled with the source that reads
values back. The derivation can only be tested by standing up a real `Parser`
and inspecting its private dicts, a second host would duplicate it, and
`format_help()` derives the same facts separately.

Splitting it into [`field_specs(T)`](specs.md), pure and host-free, plus a
binder that loops over the result makes the derivation a value a test can
compare against a table. It also gives exactly one place, inside the binding,
where the library's vocabulary is translated into the host's parser words. It
is what makes [D6](#d6)'s conformance suite mechanical: two backends conform
when they bind the same specs. The native CLI parser is the first binder, so
the suite has two backends before a second host exists.

*Cost:* one more layer and a dataclass, plus a per-host translation function to
keep in step with that host's option vocabulary.

## D10

**The store retains every source's value, not just the winner.**
([merging](merging.md#the-layered-store))

`getoption` and `getini` are per-layer accessors, and a fragment holds the
merged value. Serving the legacy API over fragments needs all three answers
from one declaration, and the current manager can only give the third. It
overwrites both the value and the
[origin](reporting.md#the-manager-records-sources-refine) as it merges.

Retaining a `LayeredValue` per source per path makes provenance a projection of
the store, which also removes the ordering bug where origins are recorded
before unknown keys are pruned. `explain()` gains the ability to show what
lost.

pytest is converging on the same shape: `_pytest.config.findpaths.ConfigValue`
records `value`, `origin` and `mode`, and `Config._getini` resolves a two-rung
ladder over it.

*Cost:* memory is O(sources × paths) rather than O(paths), and `_origins` folds
into the store.

## D11

**A runtime layer exists; fragments imply context-managed instances.**
([lifecycle](lifecycle.md#the-runtime-layer),
[lifecycle](lifecycle.md#plugin-instances-and-lifetime))

Fragments are frozen, but a host may need to derive one setting from another
after resolution. A write lands in a runtime source at the top of the ladder,
the affected fragment is rebuilt, and a warning names the fragment and the
writer.

The warning is load-bearing because a fragment implies an instance. A
ConfigPart exposes a context manager that creates the object it configures and
destroys it, so mutating a fragment after that object exists means tearing it
down and building a new one. A constructor would have been enough to build an
instance. A context manager is what makes invalidation well defined, and it
gives configuration-scoped objects a teardown hook.

*Cost:* a mechanism that warns on every use is a mechanism that wants to be
deleted; whether it outlives the migration that motivated it is open. Entering
contexts eagerly also means a fragment that fails to build fails earlier.

## D12

**The library renders help from specs.** ([reporting](reporting.md#help),
[specs](specs.md))

Help derived from [`field_specs`](specs.md) can show what a host formatter
built from registration calls cannot: the closed value set behind a `Literal`,
the `--no-` form of a boolean, which file key an option corresponds to, and
grouping that follows the declared structure.

The library renders and returns text; it never prints and never exits
([I4](invariants.md#i4)). Whether a host adopts the output is that host's
decision.

*Cost:* a host with an established help format must either adopt this one or
forgo the extra information. That trade is recorded in the binding's own
decisions.

## D13

**The environment is never implied: a field is environment-readable only when
it says so.** ([sources](sources.md#exposure-is-opt-in))

`EnvSource` reads every field today, which makes exposure a property of having
been declared rather than of anyone deciding. An earlier version of this
decision made it a source-level policy with all-fields as the default. That
picked the wrong end twice over: a switch on the source cannot distinguish
`database.password` from `database.host`, and defaulting to open means every
field a part ever adds joins the surface silently.

Requiring `from_env` puts the decision next to the field, in the diff that
introduced it. It also makes [`FieldSpec`](specs.md) a pure function of a
ConfigPart, because `env_key` is answerable from the class alone.

*Cost:* breaking, and it removes a capability. A twelve-factor application that
wants every field environment-readable now marks every field. A future
`from_env` on a class would restore the bulk case without restoring the
implicit default.

## D14

**The ladder gains an `override` rung and a `runtime` rung, in that order,
above the command line.**
([sources](sources.md#the-two-rungs-above-the-command-line))

[I2](invariants.md#i2) says precedence is a total order with no exceptions, and
two mechanisms were exempt from it. `-o` was applied as a post-merge fixup, so
`--log-level=A -o log_level=B` had no documented answer. The
[runtime layer](lifecycle.md#the-runtime-layer) said "the top of the ladder"
without a rung to point at.

`override(30)` sits above `cli(25)` because `-o` names a field and supplies a
value regardless of what else addressed it. `runtime(40)` is the top and stays
the top, because a runtime write is made after the merge with the whole
configuration in view. Nothing may be constructed above `runtime`.

Every `-o` lands at `override`, whichever argv source carried it. One inside
injected arguments outranks a typed option, as it did when injected arguments
were spliced into argv.

*Cost:* two constants, and `-o` becomes a source rather than a fixup, which is
what lets it carry
[its own origin kind](reporting.md#overrides-report-as-overrides). Any
application that relied on `-o` losing to an explicit CLI option was relying on
undefined behaviour.

## D15

**A source's dialect is a property of the source, so the TOML-aware environment
reader is its own class.** ([sources](sources.md#two-sources-two-dialects))

`EnvSource(parse_toml=True)` makes one source deliver strings or native values
depending on a constructor argument, and [D4](#d4) then cannot say whether its
values are coerced or checked.

`EnvSource` (string dialect, coerced) and `TomlEnvSource` (typed dialect,
checked) are two sources. The dialect is visible where the source is
constructed, and `describe_origin` can say which one supplied a value. The same
rule applies to any format readable both ways, and a host splitting its own
file dialects follows it.

*Cost:* one more class, and `parse_toml=` goes.

## D16

**Warnings and errors are a designed set with a shared base and one rule for
choosing between them.** ([diagnostics](diagnostics.md))

[I8](invariants.md#i8) was stated as an invariant and then left for each
component to satisfy in its own vocabulary. The result is three silent drops, a
warning that fires on correct configuration, a `RuntimeError` subclass doing
duty as both "you called `declare()` too late" and "these two parts collide",
an unexported `CLIConflictError` that is the same collision under a second
name, and a bare `TypeError` for missing required fields.

Programmer error at `declare()` gets `ConfigDeclarationError`, with collisions
beneath it, so the rule's third row has a type to name.

A taxonomy means a host can filter or promote the whole set at once, an
application can tell "this library rejected the configuration" from any other
exception, and a new diagnostic has a place to go and a rule that says whether
it warns or raises.

*Cost:* breaking in the exception hierarchy. `ConfigLifecycleError` is rebased
from `RuntimeError` onto `ConfigError`, and collisions raise a different type.
Aggregation per `resolve()` means a diagnostic cannot be emitted the moment it
is discovered.

## D17

**YAML is a config file format like TOML and INI, and is deliberately
underspecified.** ([sources](sources.md#yaml))

Every question YAML raises is a source question: which suffix maps to which
loader, and whether that loader hands over strings or typed values. The
[name model](names.md#the-qualified-path), the ladder and the merge are
format-blind, so admitting YAML costs a row in the suffix table and a loader.

Leaving it out would not have kept it out. It is the third format anyone asks
for, and the [catalogue is open](sources.md#catalogue) by design. The only
effect of silence would have been that whoever added it first did so without a
rule to follow.

What it does not get is a settled specification. pytest does not read YAML, so
there is no real requirement to test a decision against. The parser dependency,
safe-loading and merge keys, multi-document streams, and YAML 1.1's type
surprises are listed as open questions rather than answered from an armchair.

*Cost:* a format in the design with no implementation and no acceptance test
behind it. The risk is that its open questions get answered incidentally by the
first person who needs it; naming them is the mitigation.

## D18

**Conversion is a registry keyed on the annotation; `Literal` and `Enum` are
closed value sets in it.** ([types](types.md#literal),
[types](types.md#the-conversion-registry), [types](types.md#enum))

Coercion answered "what does this string mean for this annotation" for a fixed
set: the scalars, `list[T]`, and now `Literal`. Real configuration has domain
types in it. With no registry, each of those is converted by hand after the
fragment is built, so the fragment briefly holds a value that does not match
its declaration ([I6](invariants.md#i6)), and every source converts it
separately or not at all.

`Literal` is the first closed set. The annotation carries both the type and
the permitted values, so no marker is needed, a value outside the set fails
like any other conversion, and the values reach help and bindings as
`FieldSpec.values`. `Enum` is a closed value set whose members have names, so
it is [`Literal`](types.md#literal) with a type attached and reaches help and
bindings through the same `FieldSpec.values`.

An unregistered annotation is an error at declaration time rather than a value
left as a string at merge time. A field the library cannot convert is a
declaration it cannot honour, and [I8](invariants.md#i8) says that is
programmer error.

*Cost:* a registry is global state, with the usual hazards of registration
order and two libraries registering the same type. Scoping it to the manager
was rejected: a conversion is a property of the type, and making it per-manager
means the same annotation means different things in two parts of one program.

*Sequencing:* `Literal` is in [the order of work](index.md#order-of-work). The
registry, `Enum` and [D19](#d19) are [deferred](deferred.md#deferred) until a
binding needs them; [vcs-versioning](vcs-versioning/index.md) is the candidate.

## D19

**Conversion receives the origin of the value it converts.**
([types](types.md#coercion-sees-the-origin))

A relative path means different things depending on which source supplied it.
A converter with the signature `(raw, annotation) -> value` cannot get all
three cases right, so `Path` fields are either wrong for one of them or fixed
up by the caller after construction, the same [I6](invariants.md#i6) violation
the conversion registry exists to remove.

The [`Origin`](reporting.md#the-manager-records-sources-refine) already records
the file or variable, so nothing new has to be discovered. It only has to be
threaded to the place that needs it.

*Cost:* every converter's signature gains a parameter, and sources have to
supply their origin before the merge attributes it rather than after. That
ordering constraint points the same way as the
[layered store](merging.md#the-layered-store).

*Sequencing:* deferred with [D18](#d18).
