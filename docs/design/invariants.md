# Invariants

The eight rules everything else follows from. Every defect found in the design
review traced to a violation of one of them. When a rule here and a mechanism
elsewhere disagree, the rule wins.

## I1

**A field's identity is its path.**

`("cli", "level")` is what a field is. Every name a user can type for it is
derived from that path by `_names.py` and by nothing else: the CLI option, the
ini key, the environment variable, the TOML table, the `-o` key and the
`bootstrap_only` rejection message. No component may build a source-facing name
by string manipulation.

**[change]**: five places do
([names](names.md#names-are-never-constructed-by-hand)).

## I2

**Precedence is a total order with no exceptions.**

Sources are sorted by their `precedence` integer and merged in that order.
Nothing is special-cased above the ladder. `addopts` is not spliced into argv,
defaults are not privileged, and the CLI is not hardcoded as final.

**[built]**: see [the ladder](sources.md#the-precedence-ladder).

## I3

**Declaration order does not affect the result.**

A host collects declarations from independent plugins in an order nobody
controls. Every resolution pass runs for all declared types before the next pass
begins.

**[built]**, pinned by `testing/test_lifecycle.py`. See
[the passes](lifecycle.md#the-passes).

## I4

**The library never prints and never exits.**

It renders help and reports that help was requested. The application owns the
process.

**[built]**: see [help](reporting.md#help).

## I5

**Every value that reaches an instance has an origin.**

That includes class defaults and values that arrived through the `from_parent`
cascade. A value that cannot be attributed means the merge is wrong.

**[built]**, except `-o`
([reporting](reporting.md#overrides-report-as-overrides)).

## I6

**Every value that reaches an instance matches its declared type.**

A `str` field never holds `5`.

**[change]**: only string-bearing sources are coerced today, and TOML values
pass through unchecked ([types](types.md#values-from-typed-sources)).

## I7

**Markers work at every depth.**

A marker on a field three levels down behaves exactly as it does at the top
level.

**[change]**: `config_source`, `addopts_field` and `bootstrap_only` are honoured
only on top-level fields
([names](names.md#names-are-never-constructed-by-hand)).

## I8

**User error is reported; it is never silently dropped.**

A misspelled key, an option with no value and an `-o` key that addresses nothing
each produce a warning or an error naming the thing that went wrong. Programmer
error raises at `declare()`. Which of the three an input gets, and what the
message must contain, is [diagnostics](diagnostics.md).

**[change]**: three silent drops remain, the
[`-o` key](names.md#the-o-override-key), a
[CLI value beginning with `-`](sources.md#cli-parsing) and a
[`config_source` file that is not TOML](sources.md#config-file-discovery).

A warning that fires on correct configuration violates this rule as much as a
silent drop does, because it trains the user to stop reading warnings. See
[unknown keys](names.md#unknown-keys-are-judged-across-the-section) for the case
that does this today.
