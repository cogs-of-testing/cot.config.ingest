# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

cot.config.ingest is an experimental Python library that provides type annotations and helpers to ingest configuration from CLI arguments, environment variables, and configuration files. The library aims to simplify configuration management by using dataclass-like Config classes with field descriptors.

## Key Commands

### Testing
- Run tests: `hatch test testing/`
- Run a single test file: `hatch test testing/test_basic_usage.py`

### Development Environment
- The project uses Hatch for environment management
- Python versions supported: 3.9 through 3.13
- Test framework: pytest

## Architecture and Key Concepts

### Core Components

The library centers around a `Config` base class that uses a dataclass transform decorator to enable type-annotated configuration fields. Configuration classes inherit from `Config` and define fields using the `field()` function.

### Design Pattern

The library follows a declarative pattern where configuration structure is defined as classes with type annotations, similar to dataclasses. The `from_data()` class method ingests configuration from various sources into these structured objects.

### Current Implementation Status

The project is in early experimental stage with:
- Basic `Config` class with dataclass-like behavior (src/cot/config/__init__.py)
- Simple `field()` function placeholder
- Initial test demonstrating basic usage pattern

### Future Goals

The library aims to solve configuration complexity issues like those in pytest, where CLI arguments and ini options are handled differently. The goal is to provide unified handling of:
- Hierarchical configuration with sub-configs
- Field inheritance with `from_parent`
- Multiple input sources (CLI, env vars, config files)
- Support for TOML/YAML formats