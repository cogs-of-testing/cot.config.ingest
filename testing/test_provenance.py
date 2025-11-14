import json
from pathlib import Path

from cot.config import Config, field, sub_config
from cot.config.loader import ConfigLoader
from cot.config.source_info import SourceType


class DB(Config):
    host = field(default=None)
    port = field(default=None)


class AppConfig(Config):
    db = sub_config(DB)
    name = field(default=None)


def test_nested_provenance(tmp_path: Path) -> None:
    data = {"db": {"host": "filehost", "port": 123}, "name": "myapp"}
    json_file = tmp_path / "config.json"
    json_file.write_text(json.dumps(data))

    loader = ConfigLoader(AppConfig, debug=True)
    loader.load_file(json_file)

    # Environment override for nested field db.host -> DB_HOST
    environ = {"DB_HOST": "envhost"}
    loader.load_env(environ)

    cfg = loader.build()
    dbg = cfg._debug_info  # type: ignore[attr-defined]

    # Effective values
    assert cfg.db.host == "envhost"
    assert cfg.db.port == 123

    # Provenance
    host_val = dbg.get_value("db.host")
    port_val = dbg.get_value("db.port")

    assert host_val is not None and host_val.source.source_type == SourceType.ENV
    assert port_val is not None and port_val.source.source_type == SourceType.FILE
