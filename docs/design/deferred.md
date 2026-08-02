# Deferred and open questions

## Deferred

Present in the design as intent, absent from the code, and **not** to be assumed:

- **Plugin discovery** — the `Discoverable` protocol has no implementors
  ([lifecycle](lifecycle.md#discover)). Blocked on
  [the fixpoint resolve](lifecycle.md#the-passes-iterate-to-a-fixpoint).
- **List merge semantics** — append and reset modes ([types](types.md#lists)).
- **Validation hooks** — field validators, cross-field constraints, "is this file
  readable". Construction checks required fields, rejects unknown kwargs and
  [checks types](types.md#values-from-typed-sources); it does nothing beyond
  that.
- **Change notification and hot reload** — an observer API, dependency
  declaration between parts, reload on file change, error recovery when an
  observer raises. Everything about this is open, starting with whether a frozen
  configuration that can be replaced wholesale is a better answer than a mutable
  one that can be updated in place. It had a design document of its own once; it
  never got past sketches, and a paragraph of honest open ground is worth more
  than five pages of pseudocode.
- **Environment templating** — `host = "${DB_HOST}"` substitution.
- **Custom name transformers** — user-supplied path-to-name functions.

## Open questions

Genuinely undecided. Unlike a **[change]** rule, these have no committed answer.

1. **`help` shadows the builtin.** `from cot.config import help` is aggressive for
   a name that common. `T @ help("...")` reads better than any alternative
   considered, and the shadowing is scoped to what the user imports. Rename,
   alias, or leave it?
2. **`ConfigPart` versus `SubConfig`.** They share every behaviour; the split
   exists only so nesting can be detected
   ([config parts](config-parts.md#configpart-and-subconfig)). Is a single class
   with a `nested=` marker simpler, or is the type-level distinction worth
   keeping for the reader?
3. **Required fields with no source.** Construction raises `TypeError` naming
   them. Should that be a distinct exception type carrying the ConfigPart and the
   [origins](reporting.md#the-provenance-api) that *were* found?
4. **Per-source list tokenisation.** Newline-preferred-over-comma is an INI
   convention ([types](types.md#lists)). Does a TOML string field holding
   `"a,b"` really want splitting, or should only INI do it?
5. **`invocation_dir` without a CLI source.** Relative `config_source` paths fall
   back to `Path.cwd()`
   ([sources](sources.md#config-file-discovery)). Should a manager with no
   `CLISource` be required to state its own base directory instead?
6. **`Literal` has no decision record.** It is the one substantive
   [**[new]** rule](types.md#literal) with design content — how a closed value
   set reaches [help](reporting.md#help) and a binding — that is not argued
   anywhere. Write it up as a decision, or is the rule self-evident enough to
   stand alone?
7. **How much of a fragment's lifetime is the library's?**
   [D11](decisions.md#d11) gives a ConfigPart a context manager and the manager
   enters it "when the host asks". A host with no obvious configure/teardown pair
   has nowhere natural to put that. Does the library offer a default scope, or is
   entering always the host's call?
