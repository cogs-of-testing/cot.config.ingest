# The binding contract

A binding connects this library to a host that already has its own argument
parser, config files and accessors. This document is the boundary: what the
core guarantees, what a binding may decide for itself, and what neither may do
to the other.

It exists because pytest is the only binding, and a single implementation is
how host policy quietly becomes library design.

## The layering rule

The core knows nothing about any host. It does not import one, name one,
accommodate one, or carry a vocabulary borrowed from one.

Two consequences, both testable:

- **No core module may reference a host.** If expressing a host's policy needs
  a change to `_names.py`, `_fields.py`, `_coerce.py` or the manager, that
  policy is in the wrong place, or the core is missing a general capability,
  which requires a core decision.
- **No normative core document may cite a binding document.** `pytest/` may
  cite `names.md`; `names.md` may not cite `pytest/`. The [index](index.md) and
  its [gap list](index.md#gap-list) are maps rather than normative text, and
  are exempt.

## The test for which side a rule belongs on

> Would a standalone application, with no pytest anywhere, still want this?

If yes, it is a core capability with a **D** decision. If no, it is host policy
with a decision in that binding's documents.

A capability's motivation does not determine where it lives, only its
generality does. The [layered store](merging.md#the-layered-store) exists
because pytest's `getoption` and `getini` need per-layer values, but "show me
what each source said" is something any application debugging a merge wants,
so it is core.

The inverse trap is a general mechanism given a host's name. The precedence
rung for arguments injected by configuration is a general idea; calling it
`ADDOPTS` put a pytest word in the ladder every other application reads
(corrected in [sources](sources.md#the-precedence-ladder)).

## What a binding may decide

| Area | Examples |
|---|---|
| **Which sources exist, and where on the ladder** | a host's own file dialects; whether its injected-argument mechanism sits above or below the environment |
| **Which spellings a field gets** | suppressing file keys for command-line-only options; declining to add `from_env` to an option it converts |
| **Legacy accessors** | whether they exist, what they report, and where they deliberately diverge from the host's current behaviour |
| **Help rendering and errors** | which formatter is used, and whether the host adopts a new format |
| **File layout and section naming** | which tables in which files, and which are compatibility namespaces |
| **Migration policy** | ingest, conversion order, what un-migrated options look like |

None of that requires core changes, and none of it constrains another binding.

## What a binding may not decide

The [invariants](invariants.md) hold for every binding. A binding may not:

- change how a field's [qualified path](names.md#the-qualified-path) derives
  its spellings. It may suppress a spelling, never rename one
  ([I1](invariants.md#i1))
- special-case a source above the ladder ([I2](invariants.md#i2))
- make the result depend on declaration order ([I3](invariants.md#i3))
- print or exit from library code ([I4](invariants.md#i4))
- deliver a value with no origin ([I5](invariants.md#i5)) or one that does not
  match its declared type ([I6](invariants.md#i6))
- honour a marker at one depth and not another ([I7](invariants.md#i7))
- drop user error silently ([I8](invariants.md#i8))

A binding that cannot satisfy one of these has found either a bug in the core
or a gap in the design. Both are core decisions; neither is a local workaround.

## Vocabulary stops at the boundary

The core describes a field in its own terms: is it a flag, does it repeat,
does it have a closed value set ([specs](specs.md)). Words like `store_true`,
`append`, `linelist` and `dest` belong to argparse and pytest, and appear only
inside a binding.

A second host that is not argparse-shaped would otherwise have to translate
out of argparse's model before translating into its own, and would inherit
argparse's limitations on the way through.

## Conformance

Every binding must satisfy one shared conformance suite, parameterised over
bindings, covering name derivation, the
[`from_parent` cascade](merging.md#the-from_parent-cascade), collision policy,
type handling, unknown keys, and provenance kind. **[new]**

A binding conforms when it binds the same [specs](specs.md) to its host and
produces the same answers for everything the invariants cover, while remaining
free to differ on everything in
[what a binding may decide](#what-a-binding-may-decide).

Today the [yardstick](index.md#the-yardstick) has two implementations that
each only ask their own backend what it does, so divergence is invisible by
construction. Rationale in [D6](decisions.md#d6).
