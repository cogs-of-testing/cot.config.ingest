# Invariants

The eight rules everything else follows from. Every defect found in the design
review traced to a violation of one of them. When a rule here and a mechanism
elsewhere disagree, the rule wins.

## I1

**A field's identity is its path.**

`("cli", "level")` is what a field is. Every name a user can type for it is
derived from that path by `_names.py` and by nothing else: the CLI option, the
ini key, the environment variable, the TOML table, the `-o` key and the
`bootstrap_only` rejection message. Every name a user did type is matched by
[the spelling index](names.md#the-spelling-index) and by nothing else. No
component builds, splits or compares a source-facing name.

## I2

**Precedence is a total order with no exceptions.**

Sources are sorted by their `precedence` integer and merged in that order.
Nothing is special-cased above the ladder. Injected arguments are not spliced
into argv, defaults are not privileged, `-o` is not a fixup, and the CLI is not
hardcoded as final. Two sources never share a rung, so the order is total
([the ladder](sources.md#the-precedence-ladder)).

## I3

**Neither declaration order nor the order sources were added affects the
result.**

A host collects declarations from independent plugins in an order nobody
controls, and their `discover()` hooks add sources in that same order. Every
resolution step runs for all declared roots before the next begins, and a tie
between sources is impossible rather than broken by insertion
([lifecycle](lifecycle.md#resolution-is-an-iteration)).

## I4

**The library never prints and never exits.**

It renders help and reports that help was requested. The application owns the
process ([help](reporting.md#help)).

## I5

**Every value that reaches an instance has an origin.**

That includes class defaults, values that arrived through the `from_parent`
cascade, and values carried by injected arguments, which name the source that
contributed the tokens. A value that cannot be attributed means the merge is
wrong.

## I6

**Every value that reaches an instance matches its declared type.**

A `str` field never holds `5`. Conversion happens once, when a value enters
[the store](merging.md#the-layered-store), so nothing downstream of the store
sees a raw value ([types](types.md)).

## I7

**Markers work at every depth.**

A marker on a field three levels down behaves exactly as it does at the top
level.

## I8

**User error is reported; it is never silently dropped.**

A misspelled key, an option with no value, an `-o` key that addresses nothing
and a value that failed conversion each produce a warning or an error naming the
thing that went wrong. Programmer error raises at `declare()`. Which of the
three an input gets, and what the message must contain, is
[diagnostics](diagnostics.md).

A warning that fires on correct configuration violates this rule as much as a
silent drop does, because it trains the user to stop reading warnings.
