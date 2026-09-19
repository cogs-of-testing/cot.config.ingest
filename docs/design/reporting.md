# Reporting

What the library tells the user: where a value came from, and what the options
are. Both obey [I4](invariants.md#i4). The library renders text and returns it.

What it says when something is wrong is [diagnostics](diagnostics.md). The two
share a vocabulary: an error about a value names the same
[`Origin`](#the-manager-records-sources-refine) that `explain()` shows for it.

## The manager records; sources refine

The manager builds an origin for every [reading](sources.md#the-protocol) from
the source's kind and precedence and the location the reading carries. A
source that says nothing about itself is still attributed by class and
precedence, so adding a source type costs nothing in provenance support.

```python
@dataclass(frozen=True)
class Origin:
    kind: OriginKind      # default | file | env | cli | injected | override | runtime
    location: str         # "PYTEST_LOG_CLI_LEVEL", "pytest.ini[log_level]", "--log-level"
    precedence: int
```

Every value has one, including class defaults, values that arrived through the
[`from_parent` cascade](merging.md#the-from_parent-cascade), and injected
arguments, whose location names the contributor ([I5](invariants.md#i5)).

## The provenance API

```python
manager.origin_of(LoggingConfig, "cli.level")   # one field
manager.origins(LoggingConfig)                  # every field
print(manager.explain(LoggingConfig))           # field / value / origin table
```

`explain()` is the `--debug-config` output. Because [the
store](merging.md#the-layered-store) keeps every layer, it shows what the
winning value beat, so a user can see why their file's value did not apply.

`origins()` reports only paths that reached the instance
([unknown keys](merging.md#unknown-keys) never enter the store).

## Overrides report as overrides

A value set with [`-o`](names.md#the-o-override-key) has `kind="override"`, a
location naming the `-o` key, and the precedence of
[the `override` rung](sources.md#the-two-rungs-above-the-command-line). It is
never attributed to the CLI option it happens to address, because the user
never typed that. Rationale in [D1](decisions.md#d1).

## Help

`format_help()` renders every declared option and returns the text.
`help_requested()` reports whether `-h` or `--help` was passed. Neither prints
nor exits ([I4](invariants.md#i4)).

Help is rendered from [specs](specs.md). That is what lets it show the closed
value set behind a [`Literal`](types.md#literal-and-enum), the `--no-` form of
a boolean, every [form](specs.md#cli-forms) of an option, and the file key an
option corresponds to. Rationale in [D12](decisions.md#d12).

An option's rendered name is [the CLI spelling of its qualified
path](names.md#the-qualified-path), so help text and error messages cannot drift
from what the parser accepts.

Whether a host adopts this output instead of its own formatter is that host's
decision ([the contract](binding-contract.md#what-a-binding-may-decide)).
