# Diagnostics

Every warning and every error the library raises, and the rule that decides
which one an input gets. This document implements [I8](invariants.md#i8).

## The rule

| Input | Response |
|---|---|
| the run can continue, and everything the user got right still holds | **warn**, naming what was ignored |
| the input cannot be honoured, or honouring it would put a forbidden value in a field | **raise** |
| the declaration is wrong, not the input | **raise `ConfigDeclarationError` at `declare()`**, never at `resolve()` |

Two corollaries:

- **A warning must never fire on correct configuration.** A warning the user
  learns to ignore is worth less than no warning at all. This is why
  [unknown keys are judged across every root](names.md#unknown-keys-are-judged-across-every-declared-root).
- **Programmer error never waits for `resolve()`.** A collision or a malformed
  declaration is known the moment `declare()` sees the class, and reporting it
  then puts the traceback at the call site that caused it.

## Warnings

```
ConfigWarning(UserWarning)
├── UnknownConfigKeyWarning       a spelling no declared root claims
├── UnknownOverrideKeyWarning     an -o key addressing no field
├── DeprecatedNameWarning         a field reached by a deprecated alias
├── ShadowedValueWarning          a losing value that failed conversion
└── RuntimeMutationWarning        a fragment rebuilt after resolve
```

A shared base lets a host filter the whole set with one `filterwarnings` entry,
and lets an application promote them to errors wholesale.

| Warning | Fires when | Names |
|---|---|---|
| `UnknownConfigKeyWarning` | a source yielded an [`Unmatched`](sources.md#the-protocol) spelling ([merging](merging.md#unknown-keys)) | every offending spelling, and the source it came from |
| `UnknownOverrideKeyWarning` | an [`-o` key](names.md#the-o-override-key) matches no field's flat name | the key, and the roots that were searched |
| `DeprecatedNameWarning` | a value arrives under one of a field's [aliases](specs.md#the-record) rather than its current name | the alias, the current spelling, and the source that used it |
| `ShadowedValueWarning` | a reading [failed conversion](types.md#when-conversion-fails) and a higher layer won its path | the field, the declared type, the value, its origin, and the origin that shadowed it |
| `RuntimeMutationWarning` | a [runtime write](lifecycle.md#the-runtime-layer) rebuilds a fragment | the fragment, the field, and the writer |

`DeprecatedNameWarning` is a `ConfigWarning` rather than a `DeprecationWarning`
so that it reaches a user by default. Python hides `DeprecationWarning` outside
`__main__`, and the person who needs to rename a key in a config file is not the
person running the interpreter. A host that prefers the standard category
filters this one and re-emits.

An alias is a declared fact ([`FieldSpec.aliases`](specs.md#the-record)), so
noticing that one was used is the store's job, not the field's.

## Errors

```
ConfigError(Exception)
├── ConfigLifecycleError        declaring after resolve; an iteration that never settles
├── ConfigDeclarationError      a class or a source set the library cannot honour
│   └── ConfigCollisionError    two roots claim one name, incompatibly
├── ConfigUsageError            input that cannot be honoured as written
├── ConfigValueError            a value cannot be the field's declared type
└── MissingConfigError          required fields nobody supplied
```

| Error | Raised when | Names |
|---|---|---|
| `ConfigLifecycleError` | `declare()` after `resolve()`; [the iteration](lifecycle.md#resolution-is-an-iteration) exceeds its bound | the root, and the phase that had closed, or the set that kept growing |
| `ConfigDeclarationError` | `declare()` finds a [nested part with a root keyword](config-parts.md#one-class-two-roles), an [annotation with no conversion](types.md#the-conversion-registry), a [`from_parent` field whose parent has no such field](merging.md#the-from_parent-cascade), or a `short()` that is `-o` or `-h`; a source is added at [a rung already held](sources.md#no-two-sources-share-a-rung) | the class, the field path, and what was expected; or both sources |
| `ConfigCollisionError` | two roots declare one flat name with differing specs ([collisions](names.md#collisions)) | both roots, both field paths, and `named()` / `no_cli` / `name_prefix` |
| `ConfigUsageError` | an option's value is missing; a [`config_source`](sources.md#config-file-discovery) names an unreadable suffix or a file that does not exist; a [`bootstrap_only`](lifecycle.md#the-injected-arguments-loop) field is set from injected arguments; a [runtime write](lifecycle.md#the-runtime-layer) targets a feedback field; `-o` addresses a field with no file spelling under a host that scopes it | the option or path, and what was expected |
| `ConfigValueError` | a winning value [fails conversion or the check](types.md#when-conversion-fails); a value falls outside a [`Literal`](types.md#literal-and-enum); [direct construction](types.md#construction-checks) is passed the wrong type | the field path, the declared type, the value, and its [origin](reporting.md#the-provenance-api) |
| `MissingConfigError` | construction finds required fields no source supplied | every missing field at once, and the origins that were found |

`ConfigError` is the base every one of them shares, so an application can
distinguish "this library rejected the configuration" from any other exception
in one `except`.

## Strict mode

`ConfigManager(strict=True)` raises where the table above warns, for the
warnings that report input:

| warning | raised as |
|---|---|
| `UnknownConfigKeyWarning` | `ConfigUsageError` |
| `UnknownOverrideKeyWarning` | `ConfigUsageError` |
| `DeprecatedNameWarning` | `ConfigUsageError` |
| `ShadowedValueWarning` | `ConfigValueError` |

`RuntimeMutationWarning` is exempt: it reports what the host did, not what the
user wrote, and promoting it would make [`manager.set()`](lifecycle.md#the-runtime-layer)
unusable. Strict mode is the application's choice, so a host that wants the
default to be strict makes it so in its binding. Rationale in
[D28](decisions.md#d28).

## What every diagnostic says

Three things, in this order: what, where, and the way out when one exists.

```
ConfigCollisionError: LoggingConfig.cli.level and CacheConfig.cli.level
  both declare the flat name 'cli_level' with different defaults
  ('WARNING' / None).
  Give one of them a name_prefix=, a named(...) override, or no_cli.
```

*Where* uses the same vocabulary as
[provenance](reporting.md#the-manager-records-sources-refine): a diagnostic
about a value names the [`Origin`](reporting.md#the-manager-records-sources-refine)
it came from, so the location in an error and the location in `explain()` are
the same string.

## Aggregation

Diagnostics are collected per `resolve()` and raised or warned once, naming
every instance. A config file with six typos produces one warning listing six
keys. Only [the final iteration](lifecycle.md#resolution-is-an-iteration)
reports; an earlier one saw fewer options and its complaints may be stale.

The reason is [I3](invariants.md#i3): the order declared roots are visited is
not something the user controls, so a per-root diagnostic stream would come
out in an order nobody can predict or diff.

## The library still does not print

Warnings go through `warnings.warn` with a filterable category; errors are
raised. Nothing here writes to stdout or stderr, and nothing exits
([I4](invariants.md#i4)).
