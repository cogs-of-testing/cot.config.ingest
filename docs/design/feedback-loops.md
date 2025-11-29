# Cooperating Feedback Loops

## Overview

The configuration system has multiple feedback loops that cooperate to build up the final configuration:

1. **CLI Override Loop** - Command-line arguments override config files
2. **Config File Precedence Loop** - Multiple config files with precedence order
3. **Environment Override Loop** - Environment variables override files
4. **Discovery Feedback Loop** - Discovered config triggers reconfiguration

## Feedback Loop Types

### 1. CLI Override Loop

```
Input: Config files loaded
Process: Parse CLI args
Feedback: CLI values override file values
Result: Final config includes CLI overrides
```

**Characteristics:**
- Highest precedence
- Immediate application
- Can override any source
- Provides user control

**Example:**
```python
# app.toml: debug = false
# CLI: --debug
# Result: debug = true (CLI wins)
```

### 2. Config File Precedence Loop

```
Input: Multiple config files discovered
Process: Load files in order
Feedback: Later files override earlier files
Result: Merged config from all files
```

**Characteristics:**
- Order matters
- Deep merge semantics
- File discovery affects precedence
- Location-based priority

**Example:**
```python
# /etc/app/config.toml: level = "INFO"
# ~/.config/app/config.toml: level = "DEBUG"
# ./app.toml: level = "ERROR"
# Result: level = "ERROR" (local file wins)
```

### 3. Environment Override Loop

```
Input: Config files + CLI args
Process: Read environment variables
Feedback: Env vars override files, but not CLI
Result: Config with env overrides
```

**Characteristics:**
- Medium precedence
- System-level configuration
- Container-friendly
- Overrides files, not CLI

**Example:**
```python
# app.toml: host = "localhost"
# ENV: APP_HOST=production.example.com
# Result: host = "production.example.com"

# But CLI wins:
# ENV: APP_HOST=production.example.com
# CLI: --host localhost
# Result: host = "localhost"
```

### 4. Discovery Feedback Loop

```
Input: Initial config fragment
Process: Discover config sources
Feedback: New sources added to loading pipeline
Result: Reconfigured loader includes new sources
```

**Characteristics:**
- Changes loader configuration
- Affects subsequent loading
- Enables dynamic source discovery
- One-time per bootstrap stage

**Example:**
```python
# Fragment 1: invocation_dir = "/home/user/project"
# Process: Discover config files
# Feedback: Add FileSource("/home/user/project/app.toml")
# Result: Next fragments can load from app.toml
```

## Precedence Order

Full precedence order (lowest to highest):

```
1. Default values (in ConfigPart class)
2. System config files (/etc/app/)
3. User config files (~/.config/app/)
4. Local config files (./app.toml)
5. Environment variables (APP_*)
6. Command-line arguments (--flag)
```

## Cooperation Between Loops

### addopts Pattern (pytest-style)

```
Config File Loop:
  app.toml: addopts = "-v"
  local.toml: addopts = "-x"
  Merged: addopts = "-v -x"

CLI Override Loop:
  Input: merged addopts + CLI args
  CLI: --debug
  Final args: ["-v", "-x", "--debug"]
```

**Key insight:** addopts accumulates across files, then CLI adds more.

### Plugin Discovery Loop

```
Bootstrap Discovery Loop:
  app.toml: plugins = ["plugin1"]
  Feedback: Register plugin1.ConfigPart
  
Config File Loop (second pass):
  Load plugin1 config from app.toml
  app.toml: [plugin1] setting = "value"
  
Result: Plugin config loaded after plugin discovered
```

### Environment Templating

```
Config File Loop:
  app.toml: host = "${DB_HOST}"
  
Environment Loop:
  ENV: DB_HOST=localhost
  Feedback: Substitute ${DB_HOST} with "localhost"
  
CLI Override Loop:
  CLI: --host production.example.com
  Feedback: Override resolved value
  
Result: host = "production.example.com"
```

## Loop Sequencing

### Bootstrap Phase

```
1. Invocation Fragment → Discovery Loop
   Feedback: Learn invocation_dir, invocation_args

2. Discovery Loop → Config File Loop
   Feedback: Add config files as sources

3. Config File Loop → Plugin Discovery
   Feedback: Register plugin ConfigParts

4. Plugin Discovery → Config File Loop (again)
   Feedback: Load plugin configs from files
```

### Full Load Phase

```
1. Config File Loop
   Load all config files with all ConfigParts

2. Environment Loop
   Override with environment variables

3. CLI Override Loop
   Final overrides from command line

4. Build final config instances
```

## Feedback Timing

### Immediate Feedback

Some loops provide immediate feedback:
- Discovery loop adds sources right away
- Plugin registration happens immediately
- These affect subsequent loading

### Deferred Feedback

Some loops defer feedback:
- CLI overrides applied at the end
- Validation happens after all sources loaded
- Observers notified after build complete

## Error Handling in Loops

### Loop Failure

If a loop fails:

```python
try:
    # Config File Loop
    for file in config_files:
        data = load_file(file)
except ConfigFileError as e:
    # Continue with partial config?
    # Or fail fast?
    handle_error(e)
```

### Partial Feedback

When discovery partially succeeds:

```python
# Some files found, some missing
discovered = discover_files()  # Returns [app.toml], missing ~/.config/app.toml
# Feedback: Add what we found
# Continue or warn about missing files?
```

## Design Questions

1. **Loop Order**: Is the precedence order correct?
2. **Failure Modes**: Continue or fail when a loop fails?
3. **Partial Config**: Support loading with incomplete config?
4. **Validation Timing**: Validate per-loop or at end?
5. **Observability**: How to debug loop interactions?

## Examples

### Complete Flow

```python
# Phase 1: Bootstrap
manager = ConfigManager()

# Discovery Loop
manager.add_fragment({
    "invocation_dir": Path("/project"),
    "invocation_args": ["--debug", "--config", "app.toml"],
})
# Feedback: Discover app.toml, add FileSource

# Phase 2: Full Load

# Config File Loop
# Load app.toml: debug = false, plugins = ["pytest"]
# Feedback: Register pytest.ConfigPart

# Config File Loop (again, with plugin parts)
# Load pytest config from app.toml

# Environment Loop
# ENV: APP_DEBUG=true
# Feedback: Override debug = true

# CLI Override Loop
# CLI: --debug (already true)
# Feedback: No change (already true from env)

# Result:
# debug = true (from env, confirmed by CLI)
# plugins = ["pytest"] (from file)
# pytest config loaded
```

### addopts Accumulation

```python
# File Loop:
# /etc/app/pytest.ini: addopts = --tb=short
# ~/.config/pytest.ini: addopts = -v
# ./pytest.ini: addopts = -x
# Accumulated: addopts = "--tb=short -v -x"

# CLI Loop:
# CLI: --debug --log-level=DEBUG
# Combined args: ["--tb=short", "-v", "-x", "--debug", "--log-level=DEBUG"]
```
