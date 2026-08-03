# Diagnostics

Every warning and every error the library raises, and the rule that decides
which one an input gets.

[I8](invariants.md#i8) — *user error is reported, never silently dropped* — is
the invariant this document implements. It was stated as a rule and then left to
each component to satisfy in its own vocabulary, which is how three of the
outstanding silent drops got there.

## The rule

| Input | Response |
|---|---|
| the run can continue, and everything the user got right still holds | **warn**, naming what was ignored |
| the input cannot be honoured, or honouring it would put a forbidden value in a field | **raise** |
| the *declaration* is wrong — not the input | **raise at `declare()`**, never at `resolve()` |

The three-way split is what keeps a typo in a config file from taking down a
test run while a `str` field holding `5` still fails loudly.

Two corollaries, both load-bearing:

- **A warning must never fire on correct configuration.** A warning the user
  learns to ignore is worth less than no warning at all — this is what makes
  [unknown keys judged per-part](names.md#unknown-keys-are-judged-across-the-section)
  a defect rather than noise.
- **Programmer error never waits for `resolve()`.** A collision or a malformed
  declaration is known the moment `declare()` sees the class, and reporting it
  then puts the traceback at the call site that caused it.

## Warnings

```
ConfigWarning(UserWarning)
├── UnknownConfigKeyWarning       a key no declared ConfigPart claims          [built]
├── UnknownOverrideKeyWarning     an -o key addressing no field                [new]
└── RuntimeMutationWarning        a fragment rebuilt after resolve             [new]
```

A shared base is what lets a host filter the whole set with one
`filterwarnings` entry, and lets an application promote them to errors
wholesale. `UnknownConfigKeyWarning` is a `UserWarning` today with no base of
its own. **[change]**

| Warning | Fires when | Names |
|---|---|---|
| `UnknownConfigKeyWarning` | a source supplied a key that *no* declared part claims, at any depth ([merging](merging.md#unknown-keys)) | every offending dotted path, and the source it came from |
| `UnknownOverrideKeyWarning` | an [`-o` key](names.md#the-o-override-key) matches no field's flat name | the key, and the parts that were searched |
| `RuntimeMutationWarning` | a [runtime write](lifecycle.md#the-runtime-layer) rebuilds a fragment | the fragment, the field, and the writer |

## Errors

```
ConfigError(Exception)
├── ConfigLifecycleError    declaring after resolve; a declaration cycle       [built]
├── ConfigCollisionError    two parts claim one name, incompatibly             [new]
├── ConfigUsageError        input that cannot be honoured as written           [new]
├── ConfigValueError        a value cannot be the field's declared type        [new]
└── MissingConfigError      required fields nobody supplied                    [new]
```

| Error | Raised when | Names |
|---|---|---|
| `ConfigLifecycleError` | `declare()` after `resolve()`; the [fixpoint](lifecycle.md#the-passes-iterate-to-a-fixpoint) fails to converge | the type, and the phase that had closed |
| `ConfigCollisionError` | two parts declare one flat name with differing type or default ([collisions](names.md#collisions)) | both parts, both field paths, and `named()` / `no_cli` / `name_prefix` |
| `ConfigUsageError` | an option's value is missing; a [`config_source`](sources.md#config-file-discovery) names an unreadable suffix; `-o` addresses a field with no file spelling under a host that scopes it | the option or path, and what was expected |
| `ConfigValueError` | a value fails [coercion or the type check](types.md#values-from-typed-sources); a value falls outside a [`Literal`](types.md#literal) | the field path, the declared type, the value, and its [origin](reporting.md#the-provenance-api) |
| `MissingConfigError` | construction finds required fields no source supplied | every missing field at once, and the origins that *were* found |

`ConfigError` is the base every one of them shares, so an application can
distinguish "this library rejected the configuration" from any other exception in
one `except`. **[new]**

Three consolidations are folded into that table:

- `ConfigLifecycleError` currently derives from `RuntimeError` and is also what
  a collision raises. Collisions get their own type, and the base becomes
  `ConfigError`. **[change]**
- `CLIConflictError` exists in `_cli_parser.py`, is not exported, and appears in
  no document. It is `ConfigCollisionError` under a second name; it goes.
  **[change]**
- Required fields raise a bare `TypeError` naming them
  ([config parts](config-parts.md#required-and-optional)). `MissingConfigError`
  carries the ConfigPart and the origins that were found, which is
  [open question 3](deferred.md#open-questions) settled. **[change]**

## What every diagnostic says

Three things, in this order: **what**, **where**, and **the way out** when one
exists.

```
ConfigCollisionError: LoggingConfig.cli.level and CacheConfig.cli.level
  both declare the flat name 'cli_level' with different defaults
  ('WARNING' / None).
  Give one of them a name_prefix=, a named(...) override, or no_cli.
```

*Where* uses the same vocabulary as
[provenance](reporting.md#the-manager-records-sources-refine): a diagnostic about
a value names the [`Origin`](reporting.md#the-manager-records-sources-refine) it
came from, so the location in an error and the location in `explain()` are the
same string. A diagnostic that cannot say where an input came from is a
[merge that lost its provenance](invariants.md#i5), not a reporting gap.

## Aggregation

Diagnostics are collected per `resolve()` and raised or warned **once**, naming
every instance. A config file with six typos produces one warning listing six
keys, not six warnings; a construction missing four required fields names four.
**[built]** for unknown keys and required fields, **[new]** as a general rule.

The reason is [I3](invariants.md#i3): the order declared types are visited is not
something the user controls, so a per-type diagnostic stream would come out in an
order nobody can predict or diff.

## The library still does not print

Warnings go through `warnings.warn` with a filterable category; errors are
raised. Nothing here writes to stdout or stderr, and nothing exits
([I4](invariants.md#i4)). A host that wants a diagnostic rendered its own way
catches or filters it.
