# Configuration Fragments: Implementation Plan

## Overview

This document outlines the **incremental implementation steps** for the configuration fragments system.

See [config-fragments-design.md](config-fragments-design.md) for the complete design specification.

---

## Implementation Phases

### Phase 1: Core Fragment Types ✨

**Goal**: Implement the basic fragment data structures

#### Tasks
- [ ] Create `src/cot/config/fragments.py` module
- [ ] Implement `LoadedData` dataclass
- [ ] Implement `LoaderInfo` dataclass
- [ ] Implement `ConfigFragment` dataclass
- [ ] Implement `FieldPath` dataclass
- [ ] Add `MISSING` sentinel if not already available
- [ ] Add tests for fragment construction
- [ ] Add tests for LoaderInfo string representation

#### Acceptance Criteria
- Can create LoadedData instances with raw data and loader info
- Can create ConfigFragment instances
- LoaderInfo provides useful string representation
- All basic operations work correctly

#### Estimated Effort
- 2-3 hours

---

### Phase 2: Field Path Mappers ✨

**Goal**: Implement mappers that query field configuration for name mappings

#### Tasks
- [ ] Define `FieldPathMapper` Protocol in `fragments.py`
- [ ] Implement `EnvFieldMapper`
  - [ ] Query field API for env name (use `field_to_env_name`)
  - [ ] Handle prefix configuration
  - [ ] Handle nested field paths
- [ ] Implement `ArgparseFieldMapper`
  - [ ] Query field API for CLI name (use `field_to_cli_name`)
  - [ ] Handle prefix configuration
  - [ ] Handle nested field paths
- [ ] Implement `NestedFieldMapper`
  - [ ] Return immediate field name
  - [ ] Handle empty paths
- [ ] Add tests for each mapper
  - [ ] Test with flat field paths
  - [ ] Test with nested field paths
  - [ ] Test with prefixes
  - [ ] Test querying field configuration

#### Acceptance Criteria
- Each mapper correctly translates field paths to loader keys
- Mappers use field configuration API, not hardcoded conventions
- All mappers tested with various field path scenarios

#### Estimated Effort
- 3-4 hours

---

### Phase 3: Field Extractor ✨

**Goal**: Implement extraction of fragments from loaded data

#### Tasks
- [ ] Implement `FieldExtractor` class
- [ ] Implement `extract_fragment()` method
- [ ] Implement `_extract_fields()` recursive extraction
- [ ] Implement `_lookup_value()` helper
- [ ] Implement `_is_config_class()` helper
- [ ] Add comprehensive tests
  - [ ] Test with flat config (no nesting)
  - [ ] Test with nested configs
  - [ ] Test with missing fields
  - [ ] Test with EnvFieldMapper
  - [ ] Test with ArgparseFieldMapper
  - [ ] Test with NestedFieldMapper

#### Acceptance Criteria
- FieldExtractor correctly walks Config structure
- Uses mapper to query field configuration
- Extracts only fields present in loaded data
- Handles nested configs correctly
- All test scenarios pass

#### Estimated Effort
- 4-5 hours

---

### Phase 4: Fragment Merging ✨

**Goal**: Implement merging of multiple fragments with origin tracking

#### Tasks
- [ ] Implement `merge_fragments()` function
- [ ] Implement `_deep_merge_into()` helper
- [ ] Implement `MergedFragment` class
  - [ ] Implement `__init__` with fragment merging
  - [ ] Implement `_build_field_origins()`
  - [ ] Implement `_flatten_fields()`
  - [ ] Implement `get_origin()`
  - [ ] Implement `get_all_origins()`
  - [ ] Implement `_get_nested_value()`
- [ ] Add comprehensive tests
  - [ ] Test first-wins merge strategy
  - [ ] Test deep merge with nested dicts
  - [ ] Test field origin tracking
  - [ ] Test override chain tracking
  - [ ] Test with 2-4 fragments
  - [ ] Test priority ordering

#### Acceptance Criteria
- Fragments merge correctly (first wins)
- Deep merge handles nested dicts
- Origin tracking works for all fields
- Override chains are complete and ordered
- All test scenarios pass

#### Estimated Effort
- 4-5 hours

---

### Phase 5: Adapter Integration ✨

**Goal**: Add fragment extraction to existing adapters

#### Tasks
- [ ] Add `load_data()` method to `EnvironmentAdapter`
  - [ ] Return `LoadedData` with raw env vars
  - [ ] Include `LoaderInfo` with EnvironmentAdapter type
- [ ] Add `load_data()` method to `ConfigToArgparseAdapter`
  - [ ] Return `LoadedData` with raw parsed args
  - [ ] Include `LoaderInfo` with argparse adapter type
- [ ] Add `load_data()` method to `PytestAdapter`
  - [ ] Return `LoadedData` with raw pytest config
  - [ ] Include `LoaderInfo` with pytest adapter type
- [ ] Create `DefaultsExtractor` utility
  - [ ] Extract defaults from Config class
  - [ ] Return `LoadedData` with defaults
  - [ ] Include `LoaderInfo` with DefaultsExtractor type
- [ ] Maintain backward compatibility
  - [ ] Keep existing `extract_config()` methods
  - [ ] Existing code continues to work
- [ ] Add tests for each adapter
  - [ ] Test LoadedData creation
  - [ ] Test LoaderInfo metadata
  - [ ] Test backward compatibility

#### Acceptance Criteria
- All adapters can produce LoadedData
- LoaderInfo includes correct loader type and location
- Backward compatibility maintained
- All adapter tests pass

#### Estimated Effort
- 5-6 hours

---

### Phase 6: End-to-End Fragment Workflow ✨

**Goal**: Complete workflow from loading → transforming → merging

#### Tasks
- [ ] Create example demonstrating full workflow
  - [ ] Load from CLI
  - [ ] Load from ENV
  - [ ] Load from file
  - [ ] Load defaults
  - [ ] Transform each to fragment
  - [ ] Merge fragments
  - [ ] Create Config from merged data
  - [ ] Query origins
- [ ] Add integration tests
  - [ ] Test complete workflow with all loaders
  - [ ] Test with nested configs
  - [ ] Test priority ordering
  - [ ] Test origin tracking
- [ ] Add documentation
  - [ ] Usage examples
  - [ ] API reference
  - [ ] Migration guide

#### Acceptance Criteria
- Complete workflow works end-to-end
- Can load from multiple sources
- Can transform and merge correctly
- Can query origins for debugging
- Documentation is clear and complete

#### Estimated Effort
- 4-5 hours

---

### Phase 7: Config Integration ✨

**Goal**: Add fragment-aware methods to Config class

See [config-loading-integration-plan.md](config-loading-integration-plan.md) for detailed integration plan.

#### Tasks
- [ ] Add `Config.from_fragments()` class method
- [ ] Add `Config.from_loaders()` class method
- [ ] Add optional fragment tracking to Config instances
  - [ ] Store `_fragments` attribute
  - [ ] Store `_merged_fragment` attribute
- [ ] Maintain backward compatibility
- [ ] Add tests for new methods

#### Acceptance Criteria
- Can create Config from fragments
- Can create Config from loaders directly
- Fragment info attached when requested
- Backward compatibility maintained
- All tests pass

#### Estimated Effort
- 3-4 hours

---

### Phase 8: Debug Visualization ✨

**Goal**: Tools for visualizing and debugging fragments

#### Tasks
- [ ] Create `FragmentDebugger` class
- [ ] Implement `explain_field()` method
  - [ ] Show field value
  - [ ] Show origin loader
  - [ ] Show override chain
- [ ] Implement `show_override_chain()` visualization
  - [ ] Display all fragments in order
  - [ ] Show which values from each
  - [ ] Highlight winning values
- [ ] Implement `show_inheritance_tree()` visualization
  - [ ] Show nested config structure
  - [ ] Show from_parent relationships
  - [ ] Show origins for each field
- [ ] Implement `generate_report()` comprehensive report
  - [ ] Load order
  - [ ] Final configuration
  - [ ] Field origins
  - [ ] Override chains
  - [ ] Inheritance tree
- [ ] Add tests for all visualization methods

#### Acceptance Criteria
- All visualization methods produce readable output
- Reports include all relevant information
- Output is well-formatted
- All tests pass

#### Estimated Effort
- 5-6 hours

---

### Phase 9: Advanced Features ✨

**Goal**: Additional capabilities for production use

#### Tasks
- [ ] Implement fragment diffing
  - [ ] Compare two fragments
  - [ ] Show added/removed/changed fields
  - [ ] Show value differences
- [ ] Implement change detection
  - [ ] Source hashing
  - [ ] Detect when source data changed
  - [ ] Trigger reload when needed
- [ ] Implement required value validation
  - [ ] Mark fields as required
  - [ ] Validate all required fields have values
  - [ ] Helpful error messages
- [ ] Implement fragment serialization
  - [ ] Save fragments to JSON
  - [ ] Load fragments from JSON
  - [ ] Preserve metadata
- [ ] Add comprehensive tests

#### Acceptance Criteria
- Can diff fragments and see changes
- Change detection works correctly
- Required validation catches missing fields
- Serialization round-trips correctly
- All tests pass

#### Estimated Effort
- 6-8 hours

---

## Testing Strategy

### Unit Tests
- Test each class and function in isolation
- Mock dependencies where appropriate
- Cover edge cases and error conditions

### Integration Tests
- Test complete workflows
- Test with real adapter implementations
- Test with actual Config classes
- Verify origin tracking accuracy

### Performance Tests
- Measure fragment creation overhead
- Measure merge performance with many fragments
- Ensure acceptable performance for typical use cases

### Compatibility Tests
- Verify backward compatibility
- Test with existing codebase
- Ensure no breaking changes

---

## Migration Strategy

### Opt-in Approach
- Fragments are optional, not required
- Existing code continues to work
- New code can adopt fragments incrementally

### Gradual Adoption
1. **Phase 1**: Fragments available, not used
2. **Phase 2**: Internal tools use fragments
3. **Phase 3**: Recommend fragments for debugging
4. **Phase 4**: Fragments become standard

### Documentation
- Clear examples showing benefits
- Migration guide for existing code
- Best practices for fragment usage

---

## Success Criteria

The implementation is successful when:

1. ✅ All core types implemented and tested
2. ✅ Field mappers query field configuration correctly
3. ✅ Extraction works for all loader types
4. ✅ Merging preserves complete origin tracking
5. ✅ Adapters produce LoadedData
6. ✅ End-to-end workflow works correctly
7. ✅ Config integration is seamless
8. ✅ Debug tools provide useful information
9. ✅ Performance impact is acceptable
10. ✅ Documentation is complete
11. ✅ Backward compatibility maintained
12. ✅ All tests pass

---

## Timeline Estimate

| Phase | Estimated Effort | Dependencies |
|-------|-----------------|--------------|
| Phase 1: Core Types | 2-3 hours | None |
| Phase 2: Mappers | 3-4 hours | Phase 1 |
| Phase 3: Extractor | 4-5 hours | Phase 1, 2 |
| Phase 4: Merging | 4-5 hours | Phase 1 |
| Phase 5: Adapters | 5-6 hours | Phase 1, 2, 3 |
| Phase 6: Workflow | 4-5 hours | Phase 1-5 |
| Phase 7: Config Integration | 3-4 hours | Phase 1-6 |
| Phase 8: Visualization | 5-6 hours | Phase 1-7 |
| Phase 9: Advanced | 6-8 hours | Phase 1-8 |

**Total: 36-46 hours** (~1-1.5 weeks full-time, or 2-3 weeks part-time)

---

## Next Steps

1. Review this plan
2. Prioritize phases based on needs
3. Set up development environment
4. Begin Phase 1 implementation
5. Regular check-ins and adjustments
