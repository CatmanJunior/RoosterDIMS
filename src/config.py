import json
from pathlib import Path
from typing import Any, Dict


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def get_locations_config() -> Dict[str, Any]:
    return load_json("config/locations.json")


def get_data_sources_config() -> Dict[str, Any]:
    return load_json("config/data_sources.json")
