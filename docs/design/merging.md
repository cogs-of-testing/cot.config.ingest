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
