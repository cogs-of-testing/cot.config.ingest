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
  the fragment is rebuilt

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

The warning is there because everything downstream read a value that has now
changed: a frozen fragment is something a caller is entitled to have copied,
derived from or built an object out of. What the library does not do is chase
those consequences. It rebuilds the fragment, and anything an integration made
from the old one is that integration's to replace
([lifetime](#fragment-lifetime-belongs-to-the-integration)). Rationale in
[D11](decisions.md#d11).

## Fragment lifetime belongs to the integration

A fragment does not just configure something; it implies it. A root may say so
by originating a context manager for the object it configures:

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

That is the whole of the core's involvement. `manager.instance(T)` returns the
context manager the fragment originated; the library never enters it, never
holds it open and never decides when it ends. Lifetime is a context manager's
concern, and which scope a context manager belongs to is a property of the
toolset it is running in, not of the configuration that described it
([D32](decisions.md#d32)).

A context manager rather than a constructor is what makes teardown expressible:
anything holding a file handle or a socket otherwise closes it by hand, if at
all, and a fragment that yields `None` says the thing was not configured, which
is the check every host writes anyway.

### The integration owns the scope

Every toolset already has the scope, and no two of them agree on what it is. An
integration binds the fragment's context manager to the one it has:

```python
# pytest's scope is the Config, and it already owns an ExitStack
def pytest_configure(config: Config) -> None:
    timing = get_config(config, TimingConfig)

    stack = ExitStack()
    reporter = stack.enter_context(timing.instance())
    config.add_cleanup(stack.close)

    if reporter is not None:
        config.pluginmanager.register(reporter, "cot-timing-reporter")
        config.add_cleanup(lambda: config.pluginmanager.unregister(reporter))
```

`Config.add_cleanup` is the `callback` of a `contextlib.ExitStack` the `Config`
holds, so those run last-registered first: the reporter is unregistered, and
then its context closes. The stack closes when the `Config` goes out of use,
which is what `pytest_unconfigure` coincides with, and the idiom of handing a
whole stack over that way is pytest's own, in `_pytest/warnings.py`.

A long-running server enters the same context manager into its startup and
shutdown instead. A command-line application enters it in `main`, in a `with`
statement, and that is the whole mechanism.

None of those scopes is expressible in the core. A manager that entered
contexts itself would have to invent one, enter every declared fragment in an
order [I3](invariants.md#i3) says may not matter, and unwind them in an order
it cannot know is right. What it would buy is the `with` statement an
integration writes once.

### Registration is the integration's too

A yielded object usually goes somewhere: pytest registers it with the plugin
manager, another host puts it in a container, an application assigns it to a
name. The library never sees that handle, which is why it also does not
re-place one. A [runtime write](#the-runtime-layer) rebuilds the fragment and
warns; whether the object built from the old fragment should be torn down and
replaced is a question only the integration holding it can answer.
