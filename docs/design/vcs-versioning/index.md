# vcs-versioning: a candidate binding

An evaluation, not a binding. Nothing here is committed to and nothing here
constrains the core. It is the record of holding one real, independent
configuration reader up against the design to see what breaks.

`vcs-versioning` is the versioning core extracted from `setuptools_scm`. It was
chosen because it has no argument parser at the configuration layer. Its CLI
parses six flags and hands two of them to a config object built from files and
the environment. Everything [the contract](../binding-contract.md) says about
a standalone application with no host was untested before this.

Read against `vcs-versioning` 2.2.3.

## What it does today

`Configuration.from_file` merges five layers with `dict.update`:

```python
args = get_args_for_pyproject(pyproject_data, dist_name, kwargs)   # {**section, **kwargs}
args.update(project_overrides)      # "lower priority than env overrides"
args.update(_env.read_toml_overrides(args["dist_name"]))   # "Env overrides: highest priority"
```

Read bottom-up: class defaults, then the `[tool.setuptools_scm]` or
`[tool.vcs-versioning]` section, then integrator keyword arguments, then
`.config/python-vcs-versioning.toml` from the SCM root, then a TOML document
held in an environment variable.

It is a [precedence ladder](../sources.md#the-precedence-ladder) expressed in
comments, and the comments do not quite describe the code. The per-project
override file's docstring places it between the pyproject settings and the
environment overrides, but it is applied after the integrator kwargs, so it
silently outranks a `setup.py` argument too.

## What maps

| vcs-versioning | core rule |
|---|---|
| `TagConfiguration` / `ScmConfiguration` / `GitConfiguration` and their three `from_data` classmethods | [`SubConfig`](../config-parts.md#configpart-and-subconfig) and the [assembly pass](../merging.md#building-sub-configs) |
| `SETUPTOOLS_SCM_OVERRIDES_FOR_<DIST>`, a TOML document in a variable | [`TomlEnvSource`](../sources.md#two-sources-two-dialects) at the [`override` rung](../sources.md#the-two-rungs-above-the-command-line) |
| `write_to` to `version_file`, `tag_regex` to `tag.regex`, `git_describe_command` to `scm.git.describe_command` | [`FieldSpec.aliases`](../specs.md#the-record) |
| `ConfigOverridesDict`, `ALLOWED_OVERRIDE_KEYS`, `read_toml(schema=)` | the [field model](../config-parts.md#fields); three hand-maintained restatements of one class's shape |
| unknown key in an override file raises `ValueError` | [`UnknownConfigKeyWarning`](../diagnostics.md#warnings) |
| CLI `-c/--config` selecting the pyproject to read | the [`config_source`](../sources.md#config-file-discovery) marker |
| `[tool.setuptools_scm]` then `[tool.vcs-versioning]`, first present wins | two sources over one file, ordered by precedence |
| `pyproject_tool_names()`, deriving TOML section names from env prefixes | [`prefix` versus the source's own prefix](../names.md#prefix-versus-name_prefix) |

## Two independent inventions

**A typed environment source.** [D15](../decisions.md#d15) splits `EnvSource`
into string and TOML dialects. `vcs-versioning` already has an environment
variable holding a TOML document, parsed to native types, sitting above every
file.

**Opt-in environment exposure.** [D13](../decisions.md#d13) makes a field
environment-readable only when it says so. Of roughly twenty-five
configuration fields here, eight have environment spellings. Under the
all-fields default D13 replaced, a port would have silently made
`version_scheme` and `parse` settable from the environment.

## What a port deletes

The alias machinery: three deprecated spellings implemented with two data
descriptors, two `InitVar` fields, conflict checks in `__post_init__`, and a
helper that walks up to seven stack frames so that `dataclasses.replace` does
not trigger a `DeprecationWarning`. Roughly 150 lines doing what an `aliases`
tuple and a [deprecation warning](../diagnostics.md#warnings) do declaratively.

Then the three `from_data` classmethods, the two restatements of the field set,
and the five-line update ladder.

## The four gaps it exposed

Each one is now a core rule. None of them could have been written from the
pytest side.

### Names parameterised by a runtime value

`{TOOL}_{NAME}_FOR_{DIST_NAME}` embeds the distribution name, which is itself
read from `[project] name` or from the `dist_name` configuration field. Every
spelling in the design derives statically from
[the qualified path](../names.md#the-qualified-path) ([I1](../invariants.md#i1)).

It is expressible without weakening I1: read the configuration, learn
`dist_name`, then add an `EnvSource` whose prefix embeds it. Only the source's
prefix is computed. But that is a source added during resolution on the basis
of a value read during resolution, which needs
[the fixpoint](../lifecycle.md#the-passes-iterate-to-a-fixpoint)
([D5](../decisions.md#d5)), and it is the first use case for
[`discover()`](../lifecycle.md#discover) that is not plugin loading.

No new core rule. It moves D5 ahead of any port.

### Conversion for domain types

`tag.regex: Pattern[str]`, `pre_parse: GitPreParse` (an enum),
`version_cls: type[Version]` and `parse: ParseFunction` all arrive from TOML as
strings and are converted by hand in `from_data`, `_check_tag_regex` and
`_validate_version_cls`. [Types](../types.md) covered the scalars, `list` and
`Literal` and nothing else. Now
[the conversion registry](../types.md#the-conversion-registry),
[D18](../decisions.md#d18).

### Relative paths mean different things per source

`root` and `relative_to` resolve against the config file that supplied them.
`get_args_for_pyproject` goes as far as warning and discarding a `relative_to`
written in a pyproject section. Coercion was `(raw, annotation) -> value`,
with no access to where the value came from, while the
[`Origin`](../reporting.md#the-manager-records-sources-refine) already knew the
file. Now [coercion sees the origin](../types.md#coercion-sees-the-origin),
[D19](../decisions.md#d19).

### Deprecation was missing from the warning set

[Diagnostics](../diagnostics.md) had three warnings and none of them covered
using an alias, even though `aliases` is a first-class spec field. Now
`DeprecatedNameWarning`.

A fifth, smaller: `SOURCE_DATE_EPOCH` is read unprefixed, being a cross-tool
convention. [`named()`](../names.md#per-field-overrides) replaces the flat name
and re-derives the environment spelling from it, so an absolute environment
name was not expressible. Now `env_named()`.

## What a port would need first

1. **Steps 1 to 8** of [the core order of work](../index.md#order-of-work).
2. **Step 9, the fixpoint**, required by `_FOR_<DIST_NAME>`.
3. **D18's registry and D19**, [deferred](../deferred.md#deferred) until this
   port because they have no other consumer.
4. Then the port, as a second binding.

## Why it is worth doing at all

[D6](../decisions.md#d6) commits to one conformance suite parameterised over
bindings, and a single implementation is how host policy quietly becomes
library design. A second binding is the only thing that can discharge that,
and a second argparse-shaped binding would discharge almost none of it.
`vcs-versioning` is the opposite shape in every dimension that matters. Four
gaps in one afternoon, against a design that had just been reviewed twice, is
the return rate that argues for it.
