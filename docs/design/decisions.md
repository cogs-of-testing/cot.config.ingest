# Decisions

Findings from the design reviews, resolved. Each records the decision, why, and
what it costs.

A decision is what turns a rule elsewhere into a commitment. Disagreeing with
one means amending the record here, not quietly building something else.
D1 to D19 came out of two reviews of the first implementation; D20 to D30 out
of reading the resulting design as if there were no implementation at all,
which is what [D20](#d20) then made true. D31 onwards come from reading the
design for what it costs a reader.

## D1

**`-o` addresses fields by flat name, and reports as `kind="override"`.**
([names](names.md#the-o-override-key),
[reporting](reporting.md#overrides-report-as-overrides))

The structural path is a namespace that appears in no help text, no ini file
and no error message. Of the three spellings a user might try, the two they
have seen elsewhere would silently do nothing, and the one that worked would be
attributed to a CLI option the user never typed.

Reusing the flat name means `-o` is spelled exactly like the ini key, and
[the index](names.md#the-spelling-index) already provides the lookup. The
dotted path is not an alias.

*Cost:* none beyond the rule. Scope is a [binding](binding-contract.md)
matter: a host may narrow which fields `-o` reaches, and the pytest binding
does. The addressing settled here is not negotiable.

## D2

**Booleans get `--no-` variants, and an option that takes a value consumes the
next token unconditionally.** ([sources](sources.md#cli-parsing))

These are one structural hole. The ladder puts files below the CLI so that a
command-line argument can override a file. With `store_true` as the only
boolean form, a file-set `true` is unreachable from the command line. With a
`startswith("-")` guard on value consumption, every negative number is
unreachable. Both failures are silent.

Unconditional consumption needs a companion error: an option whose value is
missing must raise naming the option, rather than being dropped as unknown.

*Cost:* a token that looks like an option but is not registered is consumed
as a value where a host might have expected passthrough. pytest's usage is not
affected.

## D3

**Unions are resolved by trying members left to right.**
([types](types.md#unions))

`log_auto_indent` accepts `true|on`, `false|off` or an integer, and is
declared `bool | int | None`. Taking the first non-`None` member
unconditionally would turn `"4"` into `True`. Trying members in order and
taking the first that converts gives the obvious answer for every case in the
yardstick, because `bool` only accepts its known literals.

*Cost:* a union whose members overlap resolves by order. `str | int` from
`"4"` becomes `"4"`, which is why `str` should be last in a union.

## D4

**Values are checked against the annotation at construction, as well as
converted on entry to the store.** ([types](types.md#construction-checks))

"Type-safe configuration" is the first line of the README, and a hand-built
`LoggingConfig(level=5)` has to fail the same way a config file does. The
check goes in `__init__`, which already walks every field, so it covers direct
construction. For values from the store it is a second, cheap pass over
already-converted values.

*Cost:* one walk per construction.

## D5

**`resolve()` iterates to a fixpoint over both roots and derived sources.**
([lifecycle](lifecycle.md#resolution-is-an-iteration))

Plugin discovery is the reason resolution is multi-pass: a config file names a
plugin, the plugin declares a root, and that root must receive every pass. A
flat pass sequence cannot support that, because a root declared during a late
pass never receives the early ones.

Repeating until neither the declared set nor the derived source set grows
makes the guarantee explicit, makes `Discoverable` implementable, and makes
[I3](invariants.md#i3) hold for roots the host never saw. How each iteration
starts is [D23](#d23).

*Cost:* resolution can loop. The iteration needs a bound and an error naming
what kept growing.

## D6

**One conformance suite, parameterised over backends.**
([the binding contract](binding-contract.md#conformance))

A single implementation is how host policy quietly becomes library design,
and two acceptance test files that each only ask their own backend what it
does make divergence invisible by construction.

The suite is the executable form of [names](names.md), [types](types.md),
[merging](merging.md) and [reporting](reporting.md). When pytest uses the
library directly, it is what says whether the replacement is faithful. The
native parser is the first backend, so the suite has two before a second host
exists.

*Cost:* the acceptance tests are written once, against the suite's
parameterisation, rather than once per backend.

## D7

**Markers are honoured at every depth; names are never built by hand.**
([names](names.md#the-spelling-index),
[sources](sources.md#config-file-discovery),
[lifecycle](lifecycle.md#the-injected-arguments-loop))

Every confirmed defect in the first review traced to a component reaching
around `_names.py` and `_fields.py`: markers scanned without recursion,
`bootstrap_only` comparing munged token strings against bare field names, a
discovery source holding a hardcoded field name. That is why
[I1](invariants.md#i1) and [I7](invariants.md#i7) are invariants rather than
style notes, and why [the index](names.md#the-spelling-index) is the only
place a spelling is recognised ([D21](#d21)).

*Cost:* none.

## D8

**`name_prefix` is a path segment, not a string prefix.**
([names](names.md#the-qualified-path),
[names](names.md#two-spellings-in-files))

`prefix` is shared by design, so `name_prefix` is the only thing giving a
root identity inside its section. A nested spelling that dropped it would let
two plugins differing only in `name_prefix`, each with a `cli` nested part,
silently read each other's `[pytest.cli] level`.

Treating `name_prefix` as a segment of a qualified path makes all four
spellings one path rendered four ways. The unknown-key half of the earlier
form of this decision is now [D21](#d21): with one index over every root, a
key can only be judged across all of them.

*Cost:* nested TOML for a root with a `name_prefix` carries an extra table
level, `[pytest.log.cli]` rather than `[pytest.cli]`. Roots with no
`name_prefix` are unaffected. `named()` is unaffected: it overrides the flat
name only.

*Alternative rejected:* making the section itself `[pytest.log]` when a
`name_prefix` exists. pytest's keys really do live directly in the `[pytest]`
section as `log_cli_level`, and moving them would break the flat spelling to
fix the nested one.

## D9

**Options are specified as data; hosts bind that data.**
([specs](specs.md))

A mapping from a root to `parser.addoption` and `parser.addini` calls that
lives inside the source reading values back can only be tested by standing up
a real parser and inspecting its private state, a second host would duplicate
it, and help would derive the same facts separately.

[`field_specs(T)`](specs.md), pure and host-free, plus a `bind()` that loops
over the result, makes the derivation a value a test compares against a table.
It gives exactly one place, inside the binding, where the library's vocabulary
is translated into the host's parser words. It is what makes [D6](#d6)'s
conformance suite mechanical: two backends conform when they bind the same
specs. The native parser is the first binder.

*Cost:* one more layer and three dataclasses, plus a per-host translation
function to keep in step with that host's option vocabulary.

## D10

**The store retains every source's value, not just the winner, converted on
entry.** ([merging](merging.md#the-layered-store))

`getoption` and `getini` are per-layer accessors, and a fragment holds the
merged value. Serving the legacy API over fragments needs all three answers
from one declaration. A manager that overwrites value and origin as it merges
can only give the third.

Retaining a `LayeredValue` per source per path makes provenance a projection
of the store, lets `explain()` show what lost, and, because each reading is
converted as it enters with its origin in hand, is what
[D19](#d19) and [D28](#d28) stand on.

pytest is converging on the same shape: `_pytest.config.findpaths.ConfigValue`
records `value`, `origin` and `mode`, and `Config._getini` resolves a two-rung
ladder over it.

*Cost:* memory is O(sources × paths) rather than O(paths).

## D11

**A runtime layer exists: a late write lands at the top rung and rebuilds the
fragment.** ([lifecycle](lifecycle.md#the-runtime-layer))

Fragments are frozen, but a host may need to derive one setting from another
after resolution. A write lands in a runtime source at the top of the ladder,
the affected fragment is rebuilt, and a warning names the fragment and the
writer.

The warning is load-bearing because the old fragment has already been read.
Anything downstream may have copied a value out of it, derived a second value
from it, or built an object from it, and none of that is recomputed. Saying so
is the whole of what the library can do about it; what it must not do is
pretend to chase the consequences ([D32](#d32)).

*Cost:* a mechanism that warns on every use is a mechanism that wants to be
deleted; whether it outlives the migration that motivated it is open.

*Amended:* this decision originally also settled that fragments imply
context-managed instances and that the manager enters them, which made the
warning stand on invalidating those instances. That half is now [D32](#d32),
and it is answered the other way: the library does not hold the instances, so
it cannot invalidate them.

## D12

**The library renders help from specs.** ([reporting](reporting.md#help),
[specs](specs.md))

Help derived from [`field_specs`](specs.md) can show what a host formatter
built from registration calls cannot: the closed value set behind a `Literal`,
the `--no-` form of a boolean, every form of an option, which file key an
option corresponds to, and grouping that follows the declared structure.

The library renders and returns text; it never prints and never exits
([I4](invariants.md#i4)). Whether a host adopts the output is that host's
decision.

*Cost:* a host with an established help format must either adopt this one or
forgo the extra information. That trade is recorded in the binding's own
decisions.

## D13

**The environment is never implied: a field is environment-readable only when
it says so.** ([sources](sources.md#exposure-is-opt-in))

Reading every field would make exposure a property of having been declared
rather than of anyone deciding. An earlier form of this decision made it a
source-level policy with all-fields as the default. That picked the wrong end
twice over: a switch on the source cannot distinguish `database.password` from
`database.host`, and defaulting to open means every field a part ever adds
joins the surface silently.

Requiring `from_env` puts the decision next to the field, in the diff that
introduced it. It also makes [`FieldSpec`](specs.md) a pure function of a
root, because the spelling is answerable from the class alone. The bulk case
is [D27](#d27).

*Cost:* a twelve-factor application marks its root rather than getting
exposure for free.

## D14

**The ladder gains an `override` rung and a `runtime` rung, in that order,
above the command line.**
([sources](sources.md#the-two-rungs-above-the-command-line))

[I2](invariants.md#i2) says precedence is a total order with no exceptions,
and two mechanisms would otherwise be exempt from it. `-o` applied as a
post-merge fixup gives `--log-level=A -o log_level=B` no documented answer.
The [runtime layer](lifecycle.md#the-runtime-layer) needs a rung to point at.

`override(30)` sits above `cli(25)` because `-o` names a field and supplies a
value regardless of what else addressed it. `runtime(40)` is the top and stays
the top, because a runtime write is made after the merge with the whole
configuration in view. Nothing may be constructed above `runtime`.

Every `-o` lands at `override`, whichever argv source carried it. One inside
injected arguments outranks a typed option, as it did when injected arguments
were spliced into argv.

*Cost:* two constants, and `-o` is a source, which is what lets it carry
[its own origin kind](reporting.md#overrides-report-as-overrides).

## D15

**A source's dialect is a property of the source, so the TOML-aware environment
reader is its own class.** ([sources](sources.md#two-sources-two-dialects))

A source that delivers strings or native values depending on a constructor
argument leaves [D4](#d4) unable to say whether its values are converted or
checked.

`EnvSource` (string dialect, converted) and `TomlEnvSource` (typed dialect,
checked) are two sources. The dialect is visible where the source is
constructed, and the origin can say which one supplied a value. The same rule
applies to any format readable both ways, and a host splitting its own file
dialects follows it.

*Cost:* one more class.

## D16

**Warnings and errors are a designed set with a shared base and one rule for
choosing between them.** ([diagnostics](diagnostics.md))

[I8](invariants.md#i8) stated as an invariant and then left for each component
to satisfy in its own vocabulary produced silent drops, a warning that fired on
correct configuration, one exception type doing duty for two unrelated
failures, and bare `TypeError`s. Programmer error at `declare()` gets
`ConfigDeclarationError`, with collisions beneath it, so the rule's third row
has a type to name.

A taxonomy means a host can filter or promote the whole set at once, an
application can tell "this library rejected the configuration" from any other
exception, and a new diagnostic has a place to go and a rule that says whether
it warns or raises.

*Cost:* aggregation per `resolve()` means a diagnostic cannot be emitted the
moment it is discovered.

## D17

**YAML is a config file format like TOML and INI, and is deliberately
underspecified.** ([sources](sources.md#yaml))

Every question YAML raises is a source question: which suffix maps to which
loader, and whether that loader hands over strings or typed values. The
[name model](names.md#the-qualified-path), the ladder and the store are
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
closed value sets in it.** ([types](types.md#literal-and-enum),
[types](types.md#the-conversion-registry))

Real configuration has domain types in it: a compiled pattern, an enum, a
class resolved from an entry point, a version. With a fixed coercible set,
each of those is converted by hand after the fragment is built, so the fragment
briefly holds a value that does not match its declaration
([I6](invariants.md#i6)), and every source converts it separately or not at
all.

`Literal` is the first closed set. The annotation carries both the type and
the permitted values, so no marker is needed, a value outside the set fails
like any other conversion, and the values reach help and bindings as
`FieldSpec.values`. `Enum` is a closed value set whose members have names, so
it is `Literal` with a type attached.

An unregistered annotation is an error at declaration time rather than a value
left as a string at merge time. A field the library cannot convert is a
declaration it cannot honour, and [I8](invariants.md#i8) says that is
programmer error.

*Cost:* a registry is global state, with the usual hazards of registration
order and two libraries registering the same type. Scoping it to the manager
was rejected: a conversion is a property of the type, and making it
per-manager means the same annotation means different things in two parts of
one program.

*Sequencing:* the registry is the conversion mechanism, not an addition to
one, so it is built with the core rather than deferred. Its first non-scalar
consumer is still [vcs-versioning](vcs-versioning/index.md).

## D19

**Conversion receives the origin of the value it converts.**
([types](types.md#conversion-sees-the-origin))

A relative path means different things depending on which source supplied it.
A converter with the signature `(raw, annotation) -> value` cannot get all
three cases right, so `Path` fields are either wrong for one of them or fixed
up by the caller after construction, the same [I6](invariants.md#i6) violation
the conversion registry exists to remove.

The [`Origin`](reporting.md#the-manager-records-sources-refine) is built
before the reading enters the store ([D10](#d10)), so it only has to be handed
along.

*Cost:* every converter's signature carries the parameter.

## D20

**The code is rebuilt to the design.**

Nothing has been published. The first implementation, reviewed twice, left a
gap list of forty rows and a sixteen-step order of work whose tenth and
eleventh steps replace the source protocol and the store, which is the whole
of the manager and every source. Most of steps one to nine would have been
rewritten again at step ten.

Reading the design without the code in view ([D21](#d21) to [D30](#d30))
found that the source protocol, the tie-breaking rule, the fixpoint and the
spec record each described the old shape rather than the design's own
consequences. A rebuild under the same public API, with the existing tests as
its acceptance criteria, is cheaper than the sequence and ends with code that
matches these documents rather than approaching them.

*Cost:* until the rebuild lands, the code and the documents disagree
everywhere, and the status markers that tracked drift are suspended. A change
to behaviour during that window is a change to these documents, and the code
follows.

## D21

**Sources yield readings resolved through one spelling index; nothing else
recognises a name.** ([sources](sources.md#the-protocol),
[names](names.md#the-spelling-index))

A `load(part_type) -> dict` protocol makes every source assemble a nested
structure for one root at a time. It then has to decide which of a shared
section's keys belong to that root, which is exactly the judgement
[D8](#d8) says only something holding every root can make, and the manager
has to deep-merge the dicts it gets back.

With the index built at `declare()` over every root, a source reads its input
once, asks the index what each spelling means, and yields a reading per path.
Unknown keys are whatever the index did not resolve, judged once. There is no
dict merge, because readings are already per path. And a source never
constructs, splits or compares a name, which is [I1](invariants.md#i1) as a
protocol rather than a rule.

*Cost:* every source is written against the index rather than against a
class, and a source cannot be used without a manager to build one.

## D22

**No two sources share a rung; a source with several values for one path
orders them by a rule it documents.**
([sources](sources.md#no-two-sources-share-a-rung))

Breaking ties by insertion order makes the result depend on the order sources
were added, and `discover()` hooks add sources in declaration order. Two
plugins each contributing a file at `FILE` would then violate
[I3](invariants.md#i3) exactly where the fixpoint exists to uphold it.

Refusing the second source at an occupied rung makes the ladder a total order
in fact and not only in intent ([I2](invariants.md#i2)). The cases that
wanted ties, a chain of discovered files and a set of injected contributions,
are one source each with an order that does not depend on insertion: depth
for files, the contributor's rung for injected tokens.

*Cost:* an application with two config files at the same tier gives them
distinct precedences. Discovery assigns them.

## D23

**Every iteration starts from the base sources and the declared set; derived
sources and the store are recomputed.**
([lifecycle](lifecycle.md#resolution-is-an-iteration))

A parse is not monotone in the option set: a token that was a value in one
iteration can be an option in the next. Carrying derived sources across
iterations would keep a file that a stale parse named, and diagnostics from an
iteration that saw fewer options would be reported for a run that no longer
had those problems.

Recomputing from the same base each time makes an iteration a function of the
declared set alone, so the fixpoint is over declarations and derived sources
together and the last iteration is the only one that describes the run. The
bound and the error are [D5](#d5)'s.

*Cost:* every iteration re-reads every source. Iterations are few, because
each must grow a set, and files are small.

## D24

**A file has exactly two spellings for a field: fully flat in the section, or
fully nested with the bare name as key.**
([names](names.md#two-spellings-in-files))

The flat name is not the nested path joined on underscores. Field names contain
underscores, so `log_file_date_format` has no unique split, and `named()`
replaces a leaf's flat name with one that need not correspond to any path at
all. Deriving one spelling from the other by string manipulation is therefore
wrong in both directions, and admitting intermediate depths makes
`[pytest.log] file` mean both a table and a renamed leaf.

Two spellings, each looked up in the index as what it is, has no ambiguity and
no string manipulation.

*Cost:* `[pytest.log] cli_level` is an unknown key. A user who writes it gets
a warning naming it, which is what [I8](invariants.md#i8) asks for.

## D25

**A field has one spec and any number of CLI forms.**
([specs](specs.md#cli-forms))

pytest's `-x` is `maxfail=1`: a second option string for a path that also
takes `--maxfail N`. A single `accumulates_to` on the spec cannot express that
without making the value-taking form impossible. `flag` and a constant are
properties of a form; `counts`, `repeatable` and `values` are properties of
the field.

*Cost:* the spec record is one dataclass deeper, and a binder loops over forms
inside its loop over specs.

## D26

**The environment spelling in a spec stops short of the source prefix, and
says whether it is absolute.** ([specs](specs.md#the-record),
[names](names.md#the-qualified-path))

A spec is a pure function of the class, and the source prefix is a property of
a source, so the two cannot meet in one string. `env_named()` pins a name that
no prefix may touch. `EnvSpelling(name, absolute)` gives the source the two
facts it needs and nothing about the manager.

*Cost:* an `EnvSource` composes the name itself rather than reading it off the
spec.

## D27

**`from_env` on a nested field opts in its subtree; a root opts in with a class
keyword.** ([sources](sources.md#exposure-is-opt-in))

`TomlEnvSource` reads a whole table from one variable, so the variable must
name a nested path, and every leaf under it is thereby readable. Under a
per-leaf rule that would either be forbidden or would expose leaves that never
opted in, which is what [D13](#d13) exists to prevent. Making the marker on a
nested field mean its subtree gives the table variable a definition and
answers the bulk case: a root is a nested part with no parent, and
`from_env=True` on the class is that marker on it.

*Cost:* one marker on a nested field exposes everything beneath it, including
fields added later. That is the same trade as marking a root, made at a
smaller scope, and it is still one visible line.

## D28

**Every reading is converted on entry; a shadowed failure warns, a winning one
raises, and strict mode raises both.**
([types](types.md#when-conversion-fails),
[diagnostics](diagnostics.md#strict-mode))

Converting only the winner leaves losing layers raw, so `explain()` would show
unconverted text beside converted values and a broken file would go unnoticed
until nothing overrode it. Converting everything and raising on any failure
would stop a run over a value that did not apply.

The rule in [diagnostics](diagnostics.md#the-rule) decides: the run can
continue, so a shadowed failure warns, naming what shadowed it. The
application that wants to know now sets `strict=True`, which also promotes the
other input warnings, because an application that treats one kind of user
error as fatal has no reason to tolerate the rest.

*Cost:* every layer is converted, not only the winner. `RuntimeMutationWarning`
is exempt from strict mode, because it reports the host and not the user.

## D29

**A runtime write re-projects the store and never re-runs the iteration; a
write to a feedback field is an error.**
([lifecycle](lifecycle.md#the-runtime-layer))

The runtime layer exists for a host deriving one setting from another with the
whole configuration in view. A write to a `config_source` or `injected_args`
field asks for a source to be added after resolution, which is either a second
resolution or a silent no-op. Neither is what a late write means, so the write
is refused, naming the field.

*Cost:* a host that wants to change which files are read after resolution
builds a new manager.

## D30

**There is one class; `declare()` decides which instances are roots.**
([config-parts](config-parts.md#one-class-two-roles))

`ConfigPart` and `SubConfig` shared every behaviour and differed only so that
nesting could be detected. A field's identity is its path within the root
([I1](invariants.md#i1)), and a class has no position until it is declared or
nested, so the same class can be a root in one manager and a section in
another. The distinction that mattered, whether root keywords are meaningful,
is a property of the role, and a nested part carrying one is a declaration
error.

*Cost:* a reader cannot tell from a class definition whether it is meant to be
declared or nested. The class keywords are the tell when they are present.

## D31

**A marker bound to a union member is a declaration error, not a lost marker.**
([config-parts](config-parts.md#markers))

`@` binds tighter than `|`. `str | None @ from_parent` therefore annotates
`None` and the field carries no marker at all, so a cascade the author wrote
silently never fires. It is the one place in the design where a user's
declaration is read as something else without a word being said, which is what
[I8](invariants.md#i8) forbids everywhere a *value* is concerned and had no
answer for where a *declaration* is.

The mis-binding is detectable: markers belong to the field, so one found inside
a union member is never what the author meant. The field model raises, naming
the parenthesised spelling that works.

*Cost:* a per-member annotation is refused outright, so a marker cannot be used
to say something about one arm of a union. Nothing in the design gives a marker
that meaning, and a marker that acquired one would need its own spelling rather
than a binding accident.

*Alternative rejected:* dropping `__rmatmul__` and requiring `Annotated`. The
trap goes away, but so does the notation for the ninety per cent of fields that
are not unions, and `Annotated[str, from_parent, help("log level")]` is the
spelling the operator exists to avoid.

## D32

**A fragment originates a context manager; the integration owns its lifetime.**
([lifecycle](lifecycle.md#fragment-lifetime-belongs-to-the-integration))

A root that implies an object exposes `instance()`, a context manager that
builds the object and tears it down. The core defines that and stops.
`manager.instance(T)` hands the context manager over; the library never enters
it, never holds it open, and never decides when it ends.

Lifetime is what a context manager is for, and every toolset already has the
scope to enter one into. pytest's is the `Config`, which holds a
`contextlib.ExitStack` behind `add_cleanup`; a server's is startup and
shutdown; an application's is a `with` statement in `main`. None of those is
expressible in the core, and a manager that entered contexts itself would have
to invent a scope, enter every declared fragment in an order
[I3](invariants.md#i3) says may not matter, and unwind them in an order it has
no way to know is right. That last one is not hypothetical:
`dependency-injector`, which does own its resources' lifecycles, has had a
shutdown-ordering bug open since 2021.

The handle is the second half. A yielded object is registered somewhere — with
pytest's plugin manager, in a container, under a name. The library never sees
that handle, so it cannot replace one: a
[runtime write](lifecycle.md#the-runtime-layer) rebuilds the fragment and
warns, and whether the object built from the old one is torn down and replaced
is the integration's call. In the one host that exists, doing it eagerly would
be wrong anyway — pytest's logging plugin writes `config.option.verbose` from
inside `pytest_runtestloop`, so a rebuild-and-re-enter would tear down a live
plugin mid-hook.

Where the ecosystem draws this line is the same place. Hydra's `instantiate()`
builds objects from configuration and stops; lifecycle is the application's.
Click puts the scope on the host object, and user code pushes context managers
onto it with `Context.with_resource`. `svcs` splits the long-lived registry of
factories from the per-scope container that holds instances and cleanups.

*Cost:* an integration writes the `with` statement, or the enter-and-clean-up
pair, itself. Three lines in the pytest binding, and they are three lines only
the host can write. A fragment whose context fails to build now fails when the
integration enters it rather than at the end of `resolve()`.

*Alternative rejected:* dropping `instance()` and leaving object construction
entirely to the caller. The declaration that a fragment implies an object, and
the place its teardown is written, are worth keeping next to the fields that
configure it; what was worth giving up is the library holding it open.

