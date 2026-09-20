# Merging and assembly

Given values from several sources, which one wins, how the losers are kept,
and how a set of paths becomes a nested instance.

## The layered store

The store is a map from `(root, path)` to the readings every source supplied
for it, in ladder order. Sources yield [readings](sources.md#the-protocol) per
path, so there is no dict merge, deep or shallow: a CLI option for
`("file", "level")` and a file table for `("file",)` never meet as structures,
only as rows for different paths.

```python
@dataclass(frozen=True)
class LayeredValue:
    value: Any                # converted or checked, by the source's dialect
    origin: Origin

store.layers(AppConfig, ("database", "host"))   # every source that supplied one, in ladder order
store.winner(AppConfig, ("database", "host"))   # what the fragment gets
```

A reading is converted as it enters the store ([types](types.md)), with its
origin in hand, so nothing downstream sees a raw value ([I6](invariants.md#i6))
and a failure is reported by
[what the reading would have done](types.md#when-conversion-fails).

Provenance is a projection: `origin_of()` is `winner().origin`, and `explain()`
shows what a winning value beat. The store is also the precondition for a host
that exposes per-layer accessors, one reporting what the command line supplied
and another what a file supplied; pytest's `getoption` and `getini` are that
pair. Rationale in [D10](decisions.md#d10).

Within one source, several readings for one path are ordered as
[that source documents](sources.md#no-two-sources-share-a-rung).

## Unknown keys

A spelling a source saw that [the index](names.md#the-spelling-index) resolves
to nothing, at any depth, is user error. The source yields it as `Unmatched`,
the manager collects every one across every source and root, and reports them
in one [`UnknownConfigKeyWarning`](diagnostics.md#warnings) naming each
spelling and where it was found. Nothing about an unmatched spelling reaches
the store, so `origins()` never reports a path that was dropped.

## Building nested parts

For each nested field, in order: class defaults, then cascaded parent values,
then the winners for paths below it. The result is constructed recursively,
depth-first. Construction is where required fields are enforced and where
[direct construction is type-checked](types.md#construction-checks).

## The from_parent cascade

A field marked `from_parent` takes the parent's value for the same field name
when the child has none of its own:

```python
class LogOutputConfig(ConfigPart):
    level: Annotated[str | None, from_parent] = None

class LoggingConfig(LogOutputConfig, ConfigPart, name_prefix="log"):
    cli: LogCliConfig     # cli.level falls back to level
    file: LogFileConfig   # file.level falls back to level
```

This is `get_option_ini(config, "log_cli_level", "log_level")`, declared once
instead of open-coded per option. pytest hand-rolls the same fallback for
`level`, `format` and `date_format` across `cli` and `file`.

Matching is by field name, not by [`named()`](names.md#per-field-overrides)
override. The child's own value always wins. Presence is what is tested, not
truthiness: an explicit `0`, `""` or `[]` in the child stays.

A `from_parent` field whose parent declares no field of that name is a
[`ConfigDeclarationError`](diagnostics.md#errors) at `declare()`, because a
misplaced marker would otherwise look like a cascade that never fires.

A cascaded value is attributed to wherever the parent got it, not to the child's
default ([I5](invariants.md#i5)): `--log-level DEBUG` reports `cli.level` as
`inherited from level (--log-level)`.
