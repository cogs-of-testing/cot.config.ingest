# Lifecycle

When each thing happens, and why the order is not negotiable.

## Three phases

| Phase | Call | What happens |
|---|---|---|
| declare | `manager.declare(T)` | the type is recorded and its options registered with every [`DeclaringSource`](sources.md#the-protocol). Nothing is loaded. |
| resolve | `manager.resolve()` | the feedback passes run for all declared types, then every fragment is built. Idempotent; triggered lazily by the first `get()`. |
| access | `manager.get(T)` | the built, typed instance. |

**[built]**

## Why declaration is separate

A host collects declarations from independent plugins before any of them can be
resolved. In pytest every plugin's `pytest_addoption` runs before a single
argument is parsed, so a fragment built at declaration time could not see a
config file, or a set of injected arguments, contributed by a plugin loaded
after it.

This is [I3](invariants.md#i3), and `testing/test_lifecycle.py` pins it.
**[built]**

It is also why [`DeclaringSource`](sources.md#the-protocol) exists. A
parser-backed source needs the declaration; a file source does not.

## The passes

`resolve()` is multi-pass, because you cannot know all the sources until you
have read some configuration:

1. collect class defaults
2. call [`discover()`](#discover) on every type that defines it; this may add
   sources
3. process [`config_source`](sources.md#config-file-discovery) fields and add
   each named file as a source
4. load every source to obtain `injected_args` values
5. hand those to [`InjectedArgsSource`](#the-injected-arguments-loop), which
   parses them at its own precedence
6. re-load everything and [merge](merging.md#deep-merge) in precedence order
7. build nested `SubConfig` instances, applying the
   [`from_parent` cascade](merging.md#the-from_parent-cascade)
8. instantiate, [check types](types.md#values-from-typed-sources) and store

Each pass runs for every declared type before the next begins
([I3](invariants.md#i3)), so no fragment is built against a source a later
fragment was about to add. **[built]**

## The passes iterate to a fixpoint

A type declared during resolution, by a [`discover()`](#discover) hook or by a
plugin loaded from a config file, must receive every pass.

`resolve()` therefore repeats passes 2 to 5 until the set of declared types
stops growing, then runs 6 to 8 once. A type declared during the final build
pass is a [`ConfigLifecycleError`](diagnostics.md#errors). So is a set of
declarations that never stops growing, with the error naming the types in the
cycle. **[change]**: the passes are a flat sequence of `for t in
self._declared` loops today. A type declared during pass 2 happens to be picked
up because list iteration sees appends; a type declared during pass 3 or later
never gets `discover()` and contributes no config file, silently.

Plugin discovery is "read a config file, then declare more types", so the
current loop structure cannot support the one goal the `Discoverable` protocol
exists for. Rationale in [D5](decisions.md#d5).

After resolution the configuration is frozen: `declare()` raises
`ConfigLifecycleError`. **[built]**

## discover()

```python
class PluginConfig(ConfigPart):
    plugins: list[str] = []

    @classmethod
    def discover(cls, manager: ConfigManager) -> None:
        for name in manager.load_for_part(cls).get("plugins", []):
            manager.declare(import_module(name).Config)
```

A classmethod returning `None`, whose effect is on the manager: it adds sources
or declares types. It does not build or return an instance. **[built]** as a
protocol, **[new]** as anything with an implementor.

The protocol has no implementors, so its shape is a guess. The first real one,
plugin loading, is blocked on [the fixpoint](#the-passes-iterate-to-a-fixpoint).
Tracked in [deferred](deferred.md).

## The injected-arguments loop

A field marked `injected_args` holds a string that is re-parsed as command-line
tokens and becomes a source of its own, at its own rung of
[the ladder](sources.md#the-precedence-ladder).

It is a source, not a splice into argv. That lets it sit below the environment
and above files ([I2](invariants.md#i2)), and lets an injected option be
reported as `injected --level` rather than as something the user typed.
**[built]**

Tokens accumulate: several config files, or several ConfigParts, may each
contribute, and later contributions win. This is the one place a value
[accumulates rather than replacing](types.md#lists). **[built]**

pytest's `addopts` is the motivating instance, but the mechanism is general.
The marker, source and precedence rung are named for the capability rather than
for pytest. **[change]**: they are spelled `addopts_field`, `AddoptsSource` and
`Precedence.ADDOPTS` today.

`bootstrap_only` refuses an injected contribution that tries to set a field
whose decisions have already been made, above all which config file to open.
The refusal is a [`ConfigUsageError`](diagnostics.md#errors) naming the field.
Enforcement resolves the parsed tokens to field paths through the parser
([names](names.md#names-are-never-constructed-by-hand)), not by munging the
token string. **[change]**

## The runtime layer

A host may need to derive one setting from another after resolution. Fragments
are frozen, so that write cannot land on the instance.

It lands in a runtime source at
[`runtime(40)`](sources.md#the-two-rungs-above-the-command-line), the top rung.
The affected fragment is rebuilt, and a
[`RuntimeMutationWarning`](diagnostics.md#warnings) names the fragment and the
writer. **[new]**

```
manager.set(OutputConfig, "color", False, writer="pager")
  RuntimeMutationWarning: OutputConfig.color set by pager after resolve;
  rebuilt, and any instance derived from it recreated

manager.origin_of(OutputConfig, "color")   ->  runtime:pager
```

`manager.set(T, path, value, writer=)` is the write. `writer` names whoever
made it and appears in the warning and in the origin.

The warning is there because a fragment implies an object, so mutating it late
means destroying and rebuilding that object. Rationale in
[D11](decisions.md#d11).

## Plugin instances and lifetime

A fragment does not just configure something; it implies it. A ConfigPart may
expose a context manager that creates the object it configures and destroys it:

```python
class TimingConfig(ConfigPart, prefix="app", name_prefix="timing"):
    report: bool = False
    file: FileOutput

    @contextmanager
    def instance(self) -> Iterator[object | None]:
        if not (self.report or self.file.path):
            yield None                      # not configured; nothing to build
            return
        reporter = TimingReporter(self)
        try:
            yield reporter
        finally:
            reporter.close()
```

The manager enters every declared fragment's context when the host asks it to
and exits at the end of the host's lifetime. A yielded non-`None` value is what
the host registers. **[new]**

A context manager rather than a constructor gives two things:

- **Teardown is expressible.** Anything holding a file handle or a socket
  currently closes it by hand, if at all.
- **Invalidation has a protocol.** A [runtime](#the-runtime-layer) mutation
  exits the context, rebuilds the fragment, and enters a new one.
