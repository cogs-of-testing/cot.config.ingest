"""Test configuration file loaders."""

import json
import tempfile
from pathlib import Path

import pytest

from cot.config.loaders import load_file, load_json, load_toml, save_json


def test_load_json(tmp_path):
    """Test loading JSON files."""
    config_data = {
        "name": "test",
        "debug": True,
        "settings": {
            "level": 2,
            "items": ["a", "b", "c"],
        },
    }

    # Save test data
    json_file = tmp_path / "config.json"
    with json_file.open("w") as f:
        json.dump(config_data, f)

    # Load and verify
    loaded = load_json(json_file)
    assert loaded == config_data


def test_load_toml(tmp_path):
    """Test loading TOML files."""
    toml_content = """
    name = "test"
    debug = true

    [settings]
    level = 2
    items = ["a", "b", "c"]
    """

    toml_file = tmp_path / "config.toml"
    toml_file.write_text(toml_content)

    loaded = load_toml(toml_file)
    assert loaded["name"] == "test"
    assert loaded["debug"] is True
    assert loaded["settings"]["level"] == 2
    assert loaded["settings"]["items"] == ["a", "b", "c"]


def test_load_file_auto_detect(tmp_path):
    """Test automatic format detection."""
    # Test JSON
    json_data = {"type": "json", "value": 1}
    json_file = tmp_path / "config.json"
    with json_file.open("w") as f:
        json.dump(json_data, f)

    loaded = load_file(json_file)
    assert loaded == json_data

    # Test TOML
    toml_file = tmp_path / "config.toml"
    toml_file.write_text('type = "toml"\nvalue = 2')

    loaded = load_file(toml_file)
    assert loaded["type"] == "toml"
    assert loaded["value"] == 2


def test_load_file_unsupported():
    """Test unsupported file format."""
    with pytest.raises(ValueError, match="Unsupported file format"):
        load_file("config.ini")


def test_save_json(tmp_path):
    """Test saving JSON files."""
    data = {
        "name": "save_test",
        "nested": {"key": "value"},
    }

    json_file = tmp_path / "output.json"
    save_json(data, json_file)

    # Verify the file was saved correctly
    loaded = load_json(json_file)
    assert loaded == data


def test_load_yaml_not_installed(tmp_path, monkeypatch):
    """Test YAML loading when PyYAML is not installed."""
    # Mock import failure
    import builtins
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("No module named 'yaml'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    from cot.config.loaders import load_yaml

    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("test: value")

    with pytest.raises(ImportError, match="PyYAML is required"):
        load_yaml(yaml_file)