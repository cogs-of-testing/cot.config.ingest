# Project Roadmap for cot.config.ingest

## Project Goal

Provide type annotations and helpers to ingest configuration from:
- CLI arguments (via argparse/click/others)
- Environment variables
- Configuration files of different formats/structures

**Inspiring use case:** Simplify pytest's configuration system where CLI args and ini options are handled differently.

---

## Current State vs. Stated Goals

### ✅ What's Currently Implemented

1. **Core Config System**
   - Basic `Config` base class with metaclass and dataclass-like behavior
   - Field descriptors with metadata (default, help, choices, actions, etc.)
   - Sub-configuration support with `sub_config()`
   - Field inheritance marker with `from_parent` ✨ **NEWLY IMPLEMENTED**
   - Configuration class inheritance
   - Prefix support at class level

2. **Adapters for Multiple Sources**
   - ArgparseAdapter - full CLI integration
   - EnvironmentAdapter - env var loading with rich parsing
   - PytestAdapter - pytest integration (ini + CLI)
   - File loaders for JSON, TOML, YAML

3. **Advanced Features**
   - ConfigLoader with source tracking and debugging
   - Deep merging of multiple configuration sources
   - Name mapping utilities (snake_case → kebab-case → UPPER_CASE)
   - Primary field pattern for sub-configs
   - Origin/source tracking for debugging
   - **from_parent value propagation** ✨ **NEWLY IMPLEMENTED (Phase 1)**

### ❌ What's Missing or Incomplete

Based on the README example and stated goals:

1. **Multiple Inheritance Pattern**
   - README shows: `class LoggingPluginConfig(Config, LogBaseConfig, prefix="log")`
   - This pattern isn't fully supported - need proper MRO handling

2. **Primary Field Syntax Enhancement**
   - README shows: `cli: LogCliConfig = sub_config(primary=LogBaseConfig.enable)`
   - Current implementation expects string names, not field references

3. **Parser Integration Convenience**
   - README shows: `parser.add_config(LoggingPluginConfig)`
   - This convenience method doesn't exist

4. **Advanced Type Inference**
   - Complex types like `int | str | None` or `bool | int | None` need better handling
   - `Literal` types not fully handled

5. **Documentation & Examples**
   - No examples directory
   - Limited documentation beyond tests

---

## Phase 1: Implement Field Inheritance (`from_parent`) ✅ **COMPLETED**

**Status:** ✅ Completed in commit `38d5188`

**Goal:** Make `from_parent` actually inherit values from parent configs

**What was done:**
- ✅ Implemented value propagation in sub-configs when `from_parent` is set
- ✅ Added `_merge_parent_values()` method to Config class
- ✅ Updated Config initialization to use phased approach (fields first, then sub-configs)
- ✅ Modified ArgparseAdapter to return dicts for sub-configs (enables proper inheritance)
- ✅ Added comprehensive tests for inheritance scenarios
- ✅ Tested with README logging example

**Test Results:**
- All 86 tests passing
- New test files:
  - `testing/test_from_parent_values.py` - Core functionality (9 tests)
  - `testing/test_readme_example.py` - Real-world example (6 tests)

**Files Changed:**
- `src/cot/config/__init__.py` - Core implementation
- `src/cot/config/adapters/argparse.py` - Return dicts instead of instances
- `testing/test_argparse_adapter.py` - Updated expectations

---

## Phase 2: Support Multiple Inheritance Pattern

**Status:** 📋 Planned

**Goal:** Enable `class Config(Config, BaseConfig)` pattern from README

**Tasks:**
- [ ] Fix metaclass to properly handle multiple Config base classes
- [ ] Merge fields from all Config ancestors correctly
- [ ] Ensure proper MRO (Method Resolution Order) handling
- [ ] Test complex inheritance hierarchies
- [ ] Handle conflicts when same field defined in multiple bases

**Example to support:**
```python
class LogBaseConfig(Config):
    level: str = field(from_parent, default="INFO")
    format: str = field(from_parent, default="%(message)s")

class LogCliConfig(LogBaseConfig):
    enable: bool = field(default=False)

class LoggingPluginConfig(Config, LogBaseConfig, prefix="log"):
    # Should inherit fields from LogBaseConfig
    cli: LogCliConfig = sub_config(LogCliConfig)
```

**Design Considerations:**
- Python's MRO should guide field resolution
- Need to decide: what happens when field defined in multiple bases?
- Should we allow diamond inheritance patterns?

---

## Phase 3: Improve Primary Field Reference

**Status:** 📋 Planned

**Goal:** Allow `primary=BaseConfig.field` syntax instead of string names

**Tasks:**
- [ ] Update `sub_config()` to accept field references
- [ ] Resolve field references at class definition time
- [ ] Keep backward compatibility with string names
- [ ] Add validation for primary field existence
- [ ] Handle forward references properly

**Current limitation:**
```python
# Current - uses string
cli: LogCliConfig = sub_config(LogCliConfig, primary="enable")

# Desired - uses field reference
cli: LogCliConfig = sub_config(LogCliConfig, primary=LogCliConfig.enable)
```

**Benefits:**
- Better IDE support (autocomplete, refactoring)
- Compile-time checking of field existence
- Less error-prone

---

## Phase 4: Add Parser Convenience Methods

**Status:** 📋 Planned

**Goal:** Implement `parser.add_config()` for pytest/argparse

**Tasks:**
- [ ] Add `add_config()` extension method to argparse.ArgumentParser
- [ ] Add `add_config()` extension method to pytest Parser
- [ ] Create unified interface for both systems
- [ ] Simplify adapter usage to one-line integration
- [ ] Document the convenience methods

**Example usage:**
```python
# Instead of:
adapter = ConfigToArgparseAdapter(MyConfig)
parser = argparse.ArgumentParser()
adapter.add_to_parser(parser)

# Enable this:
parser = argparse.ArgumentParser()
parser.add_config(MyConfig)
```

**Implementation approaches:**
- Monkey-patching (simple but fragile)
- Extension class (more robust)
- Factory function (cleanest)

---

## Phase 5: Enhanced Type Support

**Status:** 📋 Planned

**Goal:** Handle complex type annotations

**Tasks:**
- [ ] Support Union types (`int | str | None`, `str | int`)
- [ ] Handle `Literal` types for constrained values
- [ ] Improve type inference for parsing
- [ ] Add type validation during initialization
- [ ] Support `Annotated` types for metadata

**Type handling examples:**
```python
class Config:
    # Union types
    level: int | str | None = field(default=None)

    # Literal types
    mode: Literal["r", "w", "a"] = field(default="r")

    # Complex unions
    value: bool | int | None = field(default=None)
```

**Challenges:**
- Parsing string values to correct type
- Ambiguous conversions (bool vs int)
- Runtime type checking

---

## Phase 6: Documentation & Examples

**Status:** 📋 Planned

**Goal:** Make library easy to adopt

**Tasks:**
- [ ] Create `examples/` directory with real-world use cases
- [ ] Document the pytest logging example from README
- [ ] Add migration guide from raw argparse/configparser
- [ ] Create API documentation (Sphinx or mkdocs)
- [ ] Write tutorial for common patterns
- [ ] Add type annotation guide
- [ ] Document best practices

**Example topics:**
- Basic usage tutorial
- Multi-source configuration loading
- Testing configurations
- Hierarchical configs with from_parent
- Custom adapters
- Integration with popular frameworks

---

## Phase 7: Configuration Fragments System

**Status:** 🚧 In Design/Implementation

**Goal:** Implement origin tracking and debugging for configuration loading

Configuration fragments provide complete visibility into where configuration values come from across multiple sources (CLI, environment, files, defaults). This system enables powerful debugging and validation capabilities.

**Documentation:**
- Design specification: [config-fragments-design.md](config-fragments-design.md)
- Implementation plan: [fragments-implementation-plan.md](fragments-implementation-plan.md)
- ConfigLoader integration: [config-loading-integration-plan.md](config-loading-integration-plan.md)

**Key capabilities when complete:**
- Track origin of every configuration value
- Visualize override chains across sources
- Debug configuration loading issues
- Validate required fields
- Compare configurations

---

## Phase 8: Advanced Features (Future)

**Status:** 💡 Ideas for future consideration

**Potential features:**
- [ ] Backward compatibility field mappings (deprecation support)
- [ ] Config validation and post-processing hooks
- [ ] Config schema generation (JSON Schema, etc.)
- [ ] Config file generation from Config classes
- [ ] Watch mode for config file changes
- [ ] Environment-specific config profiles
- [ ] Secret/sensitive field handling
- [ ] Config diffing and comparison tools
- [ ] Interactive config builder CLI

---

## Implementation Guidelines

### Testing Strategy
- Add tests before implementing features
- Maintain 100% test pass rate
- Test with real-world examples (like pytest logging)
- Test all adapters (argparse, env, pytest, files)
- Test edge cases and error handling

### Code Quality
- Follow existing code style
- Add docstrings to all public APIs
- Use type hints consistently
- Keep backward compatibility when possible
- Document breaking changes

### Commit Strategy
- One phase = one commit (or multiple related commits)
- Clear commit messages with examples
- Include test results in commit message
- Reference related issues/discussions

---

## Success Metrics

For the project to achieve its stated goals:

1. **Simplicity:** Reduce boilerplate compared to raw argparse/configparser
2. **Type Safety:** Leverage Python type system for better IDE support
3. **Flexibility:** Support multiple config sources seamlessly
4. **Debuggability:** Track where config values come from
5. **Real-world Viability:** Successfully handle pytest logging plugin use case

---

## Current Status

**Phase 1: ✅ COMPLETED** (2025-10-15)
- from_parent field inheritance working
- 86 tests passing
- README example functional

**Phase 7: 🚧 IN PROGRESS** (Configuration Fragments)
- Design complete
- Implementation planned
- See fragment-specific documents for details

**Next recommended phase:** Phase 2 (Multiple inheritance) or Phase 6 (Documentation)

---

## Notes

- This is an experimental library - some features may be redesigned
- Breaking changes are acceptable at this stage
- Focus on solving real problems (like pytest configuration complexity)
- Keep the API intuitive and discoverable
