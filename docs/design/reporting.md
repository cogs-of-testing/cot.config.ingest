# Reporting

What the library tells the user: where a value came from, and what the options
are. Both obey [I4](invariants.md#i4). The library renders text and returns it.

What it says when something is wrong is [diagnostics](diagnostics.md). The two
share a vocabulary: an error about a value names the same
[`Origin`](#the-manager-records-sources-refine) that `explain()` shows for it.

## The manager records; sources refine

The manager records origins as it merges, so a source that says nothing about
itself is still attributed by class and precedence. A source that can be more
specific implements [`describe_origin`](sources.md#the-protocol). Adding a source
type therefore costs nothing in provenance support. **[built]**

```python
@dataclass(frozen=True)
class Origin:
    kind: OriginKind      # default | file | env | cli | injected | override | runtime
    location: str         # "PYTEST_LOG_CLI_LEVEL", "pytest.ini[log_level]", "--log-level"
    precedence: int
```

Every value has one, including class defaults and values that arrived through
the [`from_parent` cascade](merging.md#the-from_parent-cascade)
([I5](invariants.md#i5)).

## The provenance API

```python
manager.origin_of(LoggingConfig, "cli.level")   # one field
manager.origins(LoggingConfig)                  # every field
print(manager.explain(LoggingConfig))           # field / value / origin table
```

`explain()` is the `--debug-config` output. **[built]**

`origins()` reports only paths that reached the instance. See
[merging](merging.md#unknown-keys) for the ordering that guarantees it.

## Overrides report as overrides

A value set with [`-o`](names.md#the-o-override-key) has `kind="override"`, a
location naming the `-o` key, and the precedence of
[the `override` rung](sources.md#the-two-rungs-above-the-command-line).
**[change]**: `OriginKind` declares `"override"` and nothing constructs one. A
`-o` value is reported as coming from the CLI option it happens to address:

```
-o level=D    ->    origin = cli:--log-level     # the user never typed that
```

That is provenance lying in the case it exists for ([I5](invariants.md#i5)).
Rationale in [D1](decisions.md#d1).

## Help

`format_help()` renders every registered option and returns the text.
`help_requested()` reports whether `-h` or `--help` was passed. Neither prints
nor exits ([I4](invariants.md#i4)). **[built]**

Help is rendered from [specs](specs.md). That is what lets it show the closed
value set behind a [`Literal`](types.md#literal), the `--no-` form of a boolean
and the file key an option corresponds to. **[built]** for the `help()` marker,
**[new]** for the rest. Rationale in [D12](decisions.md#d12).

An option's rendered name is [the CLI spelling of its qualified
path](names.md#the-qualified-path), so help text and error messages cannot drift
from what the parser accepts.

Whether a host adopts this output instead of its own formatter is that host's
decision ([the contract](binding-contract.md#what-a-binding-may-decide)).
