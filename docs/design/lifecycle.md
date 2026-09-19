# Lifecycle

When each thing happens, and why the order is not negotiable.

## Three phases

| Phase | Call | What happens |
|---|---|---|
| declare | `manager.declare(T)` | the root is recorded, its [specs](specs.md) derived, [collisions](names.md#collisions) judged and [the index](names.md#the-spelling-index) extended. Nothing is loaded. |
| resolve | `manager.resolve()` | [the iteration](#resolution-is-an-iteration) runs to a fixpoint, then every fragment is built. Idempotent; triggered lazily by the first `get()`. |
| access | `manager.get(T)` | the built, typed instance. |

## Why declaration is separate

A host collects declarations from independent plugins before any of them can be
resolved. In pytest every plugin's `pytest_addoption` runs before a single
argument is parsed, so a fragment built at declaration time could not see a
config file, or a set of injected arguments, contributed by a plugin loaded
after it.

This is [I3](invariants.md#i3), and `testing/test_lifecycle.py` pins it.

It is also why [`BindingSource`](sources.md#the-protocol) exists. A
parser-backed source needs the specs; a file source needs only the index.

## Resolution is an iteration

You cannot know all the sources until you have read some configuration, and
you cannot know all the roots until you have read some sources: a config file
may name a plugin, and the plugin declares a root.

`resolve()` carries two things between iterations: the **base sources** the
application constructed, and the **declared set**. Everything else is
recomputed every time.

Each iteration:

1. derive specs and rebuild the index for every declared root; `bind()` every
   binding source
2. call [`discover()`](#discover) on every root that defines it; it may declare
   roots and add sources
3. load every source into a fresh [store](merging.md#the-layered-store)
4. read every [`config_source`](sources.md#config-file-discovery) field's
   winner and add each named file as a **derived source**; load it
5. read every [`injected_args`](#the-injected-arguments-loop) field's
   contributions and build the injected source; load it
6. if the declared set or the derived source set grew, discard the store and
   the derived sources and go to 1

When neither grows, the last store is projected: the
[`from_parent` cascade](merging.md#the-from_parent-cascade), assembly,
construction. Diagnostics are those of the final iteration only. An earlier
iteration parsed argv against fewer options, and what it complained about may
no longer be true.

Each step runs for every declared root before the next begins
([I3](invariants.md#i3)), so no fragment is built against a source a later
fragment was about to add. Because every iteration starts from the same base,
a source that iteration one derived from a stale parse does not survive into
iteration three unless iteration three derives it again.

The iteration is bounded: each one must grow the declared set or the derived
source set, and a set that grows past a limit the manager states is a
[`ConfigLifecycleError`](diagnostics.md#errors) naming what kept growing. A
root declared during projection is the same error. Rationale in
[D5](decisions.md#d5) and [D23](decisions.md#d23).

After resolution the configuration is frozen: `declare()` raises
`ConfigLifecycleError`.

## discover()

```python
class PluginConfig(ConfigPart):
    plugins: list[str] = []

    @classmethod
    def discover(cls, manager: ConfigManager) -> None:
        for name in manager.partial(cls).get("plugins", []):
            manager.declare(import_module(name).Config)
```

A classmethod returning `None`, whose effect is on the manager: it declares
roots or adds sources. It does not build or return an instance.

`manager.partial(cls)` is the view it reads: the winner per path from the
sources loaded so far, converted, with no cascade, no assembly and no
required-field check, because the iteration is not finished. It is a dict, not
an instance.

`discover()` runs once per iteration, so it must be a function of what it
reads: declaring a root already declared is a no-op, and a source it adds is a
derived source the next iteration will ask it for again.

## The injected-arguments loop

A field marked `injected_args` holds a string that is re-parsed as command-line
tokens and becomes a source of its own, at its own rung of
[the ladder](sources.md#the-precedence-ladder).

It is a source, not a splice into argv. That lets it sit below the environment
and above files ([I2](invariants.md#i2)), and lets an injected option be
reported as injected rather than as something the user typed.

Contributions accumulate: several config files, or several roots, may each
contribute. They are ordered by the rung of the source each came from, then by
that source's own order, and the later one wins. A reading's location names
its contributor, `injected --log-level (pytest.ini[addopts])`, so
[I5](invariants.md#i5) holds through the accumulation. This is the one place a
value [accumulates rather than replacing](types.md#lists).

pytest's `addopts` is the motivating instance, but the mechanism is general,
and the marker, source and rung are named for the capability.

`bootstrap_only` refuses an injected contribution that tries to set a field
whose decisions have already been made, above all which config file to open.
The refusal is a [`ConfigUsageError`](diagnostics.md#errors) naming the field.
It covers `-o` pairs carried by injected arguments as well as options.
Enforcement resolves the parsed tokens to paths through
[the index](names.md#the-spelling-index), never by comparing token strings.

## The runtime layer

A host may need to derive one setting from another after resolution. Fragments
are frozen, so that write cannot land on the instance.

It lands in a runtime source at
[`runtime(40)`](sources.md#the-two-rungs-above-the-command-line), the top rung.
The affected fragment is rebuilt, and a
[`RuntimeMutationWarning`](diagnostics.md#warnings) names the fragment and the
writer.

```
manager.set(OutputConfig, "color", False, writer="pager")
  RuntimeMutationWarning: OutputConfig.color set by pager after resolve;
  rebuilt, and any instance derived from it recreated

manager.origin_of(OutputConfig, "color")   ->  runtime:pager
```

`manager.set(T, path, value, writer=)` is the write. `writer` names whoever
made it and appears in the warning and in the origin.

A runtime write re-projects the store; it does not re-run the iteration. A
write to a `config_source` or `injected_args` field is therefore a
[`ConfigUsageError`](diagnostics.md#errors): honouring it would mean adding a
source after resolution, and not honouring it would be a silent drop. A write
to a field `discover()` reads is accepted and warned about like any other, and
declares nothing, because declaration is closed. Rationale in
[D29](decisions.md#d29).

The warning is there because a fragment implies an object, so mutating it late
means destroying and rebuilding that object. Rationale in
[D11](decisions.md#d11).

## Plugin instances and lifetime

A fragment does not just configure something; it implies it. A root may expose
a context manager that creates the object it configures and destroys it:

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
the host registers.

A context manager rather than a constructor gives two things:

- **Teardown is expressible.** Anything holding a file handle or a socket
  otherwise closes it by hand, if at all.
- **Invalidation has a protocol.** A [runtime](#the-runtime-layer) mutation
  exits the context, rebuilds the fragment, and enters a new one.
