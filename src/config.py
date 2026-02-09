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


def get_locations_config(path: str | None = None) -> Dict[str, Any]:
    return load_json(path or "config/locations.json")


def get_data_sources_config(path: str | None = None) -> Dict[str, Any]:
    return load_json(path or "config/data_sources.json")


def get_departments_config() -> Dict[str, Any]:
    try:
        return load_json("config/departments.json")
    except FileNotFoundError:
        return {"departments": {}}


def get_department_defaults(department: str | None) -> Dict[str, Any]:
    conf = get_departments_config()
    if not department:
        department = conf.get("default_department")
    return conf.get("departments", {}).get(department, {})


def get_weights_config(path: str | None = None) -> Dict[str, Any]:
    """Load weights configuration from a JSON file.

    If path is None, loads from default "config/weights.json".
    """
    return load_json(path or "config/weights.json")
