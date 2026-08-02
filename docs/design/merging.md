# Merging and assembly

Given values from several sources, which one wins, and how a flat merge becomes
a nested instance.

## Deep merge

Sources are merged in ascending precedence order, deeply. A shallow update would
let `--log-file-level` from the CLI wipe the whole `log_file` table read from a
config file. **[built]**

Because every source omits what it does not supply
([the protocol](sources.md#the-protocol)), the merge never has to distinguish
"this source said `None`" from "this source said nothing".

## Unknown keys

A key a source supplied that **no declared ConfigPart** claims, at any depth, is
user error in a config file — not programmer error. It is dropped with an
`UnknownConfigKeyWarning` naming every offending dotted path, and the load
continues. Letting it reach the constructor raised `TypeError` and took the whole
load down over a typo in one nested table. **[built]**, except that the judgement
is made per-part rather than across all declared parts, so a shared section
produces warnings on correct configuration — see
[names](names.md#unknown-keys-are-judged-across-the-section). **[change]**

Pruning happens before origins are finalised, so
[`origins()`](reporting.md#the-provenance-api) never reports paths that were
dropped. **[change]** — pruning currently runs after origin recording, so the
origins dict retains entries for keys that never reached the instance.
`explain()` hides this because it iterates `leaf_fields`, but `origins()` leaks
it.

## The layered store

The merge keeps **every source's value per path**, not only the winner.
**[new]**

```python
@dataclass(frozen=True)
class LayeredValue:
    value: Any
    source: ConfigSource      # the source carries its own dialect
    origin: Origin

store.layers(AppConfig, ("database", "host"))   # every source that supplied one, in ladder order
store.winner(AppConfig, ("database", "host"))   # what the fragment got
```

Discarding the losers costs two things. [Provenance](reporting.md#the-provenance-api)
has to be maintained as a structure *alongside* the merge rather than derived
from it — which is how origins came to be recorded before unknown keys are
pruned. And `explain()` can say where the winning value came from but not what
it beat, which is the question someone debugging a merge is actually asking.

With the store, `origin_of()` is `winner().origin` and provenance is a
projection. **[change]** — today the manager keeps the merged value and the
winning origin only.

It is also the precondition for any host that exposes *per-layer* accessors —
one reporting what the command line supplied and another what a file supplied,
with the merged value a third answer. That is not a hypothetical: it is how
pytest's `getoption` and `getini` differ, and no amount of merged value answers
it. Rationale in [D10](decisions.md#d10).

## Building sub-configs

For each `SubConfig`-typed field, in order: class defaults, then cascaded parent
values, then explicitly supplied values. The result is constructed recursively,
depth-first. **[built]**

Construction is where required fields are enforced and
[types are checked](types.md#values-from-typed-sources).

## The from_parent cascade

A field marked `from_parent` takes the parent's value for the **same field name**
when the child has none of its own:

```python
class LogOutputConfig(SubConfig):
    level: Annotated[str | None, from_parent] = None

class LoggingConfig(LogOutputConfig, ConfigPart, name_prefix="log"):
    cli: LogCliConfig     # cli.level falls back to level
    file: LogFileConfig   # file.level falls back to level
```

This is `get_option_ini(config, "log_cli_level", "log_level")`, declared once
instead of open-coded per option. It is the feature the
[yardstick](index.md#the-yardstick) leans on hardest: pytest hand-rolls the same
fallback for `level`, `format` and `date_format` across `cli` and `file`.

Matching is by field name, not by [`named()`](names.md#per-field-overrides)
override — the cascade is structural. The child's own value always wins.
**[built]**

A cascaded value is attributed to **wherever the parent got it**, not to the
child's default ([I5](invariants.md#i5)): `--log-level DEBUG` reports `cli.level`
as `inherited from level (--log-level)`, not as a default. **[built]**
