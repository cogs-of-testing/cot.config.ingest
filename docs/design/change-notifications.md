# Change Notifications and Dependencies

## Overview

Configuration parts can depend on each other, and changes to one part may need to trigger updates in dependent parts.

## Dependency Types

### 1. Config Part Dependencies

Application parts depend on configuration:

```python
class LoggingService:
    """Depends on LogConfig."""
    
    def __init__(self, config: LogConfig):
        self.config = config
        self._setup_logging()
    
    def on_config_change(self, new_config: LogConfig):
        """Called when LogConfig changes."""
        self.config = new_config
        self._setup_logging()
```

### 2. Cross-Part Dependencies

Config parts depend on other config parts:

```python
class ServerConfig(ConfigPart):
    """Server needs database connection string."""
    host: str = "localhost"
    port: int = 8000

class DatabaseConfig(ConfigPart):
    """Database config is independent."""
    host: str = "localhost"
    port: int = 5432

# ServerConfig might need to know database host for health checks
```

### 3. Bootstrap Dependencies

Later bootstrap stages depend on earlier ones:

```python
# Stage 2 depends on Stage 1
config_files = discover_files(invocation_dir)  # From Stage 1

# Stage 3 depends on Stage 2
addopts = load_from_file(config_files[0])  # From Stage 2
```

## Change Notification Patterns

### 1. Observer Pattern

```python
class ConfigObserver(Protocol):
    def on_config_change(self, config_part: ConfigPart) -> None:
        """Called when config part changes."""
        ...

class ConfigManager:
    def observe(
        self,
        config_part_name: str,
        observer: ConfigObserver,
    ) -> None:
        """Register an observer for config changes."""
        self.observers[config_part_name].append(observer)
    
    def notify_change(self, config_part_name: str, new_config: ConfigPart) -> None:
        """Notify observers of config change."""
        for observer in self.observers[config_part_name]:
            observer.on_config_change(new_config)
```

### 2. Callback Registration

```python
manager = ConfigManager()

def on_database_change(new_config: DatabaseConfig):
    print(f"Database config changed: {new_config.host}:{new_config.port}")

manager.on_change("DatabaseConfig", on_database_change)
```

### 3. Reactive Updates

```python
# When config reloads, dependent parts update automatically
manager.reload_config()  # Triggers notifications to all observers
```

## Use Cases

### Hot Reload

```python
# Application running, config file changes
manager.watch_config_files()  # Start watching

# File changes detected
manager.reload_config()

# Observers notified:
# - LoggingService reconfigures log level
# - DatabasePool resizes connection pool
# - ServerConfig updates worker count
```

### Plugin Loading

```python
# Bootstrap discovers plugins
plugins = discover_plugins_from_config()

# Register plugin config parts
for plugin in plugins:
    manager.register_part(plugin.ConfigPart)
    
    # Notify that new config is available
    manager.notify_new_part(plugin.ConfigPart.__name__)

# App components can observe new parts
@manager.on_new_part
def handle_new_config(part_name: str):
    print(f"New config part available: {part_name}")
```

### Validation Dependencies

```python
class ServerConfig(ConfigPart):
    def validate(self, context: ValidationContext):
        # Check if database is reachable
        db_config = context.get("DatabaseConfig")
        if not can_connect(db_config.host, db_config.port):
            raise ValidationError("Cannot reach database")
```

## Design Questions

1. **Notification Timing**: Sync or async notifications?
2. **Batch Updates**: Notify after all changes, or incrementally?
3. **Error Handling**: What if an observer raises an exception?
4. **Dependency Graph**: Should we track and validate dependencies?
5. **Circular Dependencies**: How to detect and handle?

## To Be Designed

- Full observer API
- Dependency declaration syntax
- Validation dependency handling
- Hot reload implementation
- Error recovery strategies
