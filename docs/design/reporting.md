# Reporting

What the library tells the user: where a value came from, and what the options
are. Both obey [I4](invariants.md#i4) — it renders text and returns it, and never
prints or exits.

## The manager records; sources refine

Origins are recorded by the manager as it merges, so a source that says nothing
about itself is still attributed — by class and precedence. A source that can be
more specific implements [`describe_origin`](sources.md#the-protocol). This is
why adding a source type costs nothing in provenance support. **[built]**

```python
@dataclass(frozen=True)
class Origin:
    kind: OriginKind      # default | file | env | cli | addopts | override
    location: str         # "PYTEST_LOG_CLI_LEVEL", "pytest.ini[log_level]", "--log-level"
    precedence: int
```

Every value has one, including class defaults and values that arrived through the
[`from_parent` cascade](merging.md#the-from_parent-cascade)
([I5](invariants.md#i5)). A value that cannot be attributed means the merge is
wrong, not that the report is incomplete.

## The provenance API

```python
manager.origin_of(LoggingConfig, "cli.level")   # one field
manager.origins(LoggingConfig)                  # every field
print(manager.explain(LoggingConfig))           # field / value / origin table
```

`explain()` is the `--debug-config` output: the whole point of merging sources is
that the winner is not obvious from any one of them. **[built]**

`origins()` reports only paths that reached the instance — see
[merging](merging.md#unknown-keys) for the ordering that guarantees it.

## Overrides report as overrides

A value set with [`-o`](names.md#the-o-override-key) has `kind="override"` and a
location naming the `-o` key. **[change]** — `OriginKind` declares `"override"`
and nothing ever constructs one; a `-o` value is reported as coming from the CLI
option it happens to address:

```
-o level=D    ->    origin = cli:--log-level     # the user never typed that
```

That is provenance actively lying, in exactly the case provenance exists for
([I5](invariants.md#i5)). Rationale in [D1](decisions.md#d1).

## Help

`format_help()` renders every registered option and returns the text.
`help_requested()` reports whether `-h`/`--help` was passed.

**Neither prints nor exits** ([I4](invariants.md#i4)). This is a library; the
application owns the process, decides whether help goes to stdout or a pager, and
decides the exit code. **[built]**

Help text comes from the `help()` marker. Choices from a
[`Literal`](types.md#literal) annotation appear in the rendered option.
**[built]** / **[new]**

An option's rendered name is [the CLI spelling of its qualified
path](names.md#the-qualified-path), so help text and error messages cannot drift
from what the parser accepts.
