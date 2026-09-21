"""Canonical JSON Schema validation. Never coerce wire values into validity."""
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
SCHEMA = json.loads((CONTRACTS / "lab.schema.json").read_text(encoding="utf-8"))


def _finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite number at payload boundary")
    if isinstance(value, dict):
        for item in value.values():
            _finite(item)
    elif isinstance(value, list):
        for item in value:
            _finite(item)


def parse_json(text: str) -> Any:
    def reject(token: str) -> None:
        raise ValueError(f"Invalid JSON constant: {token}")
    value = json.loads(text, parse_constant=reject)
    _finite(value)
    return value


@lru_cache
def _validator(name: str) -> Draft202012Validator:
    definition = SCHEMA["$defs"].get(name, {})
    if "kind" not in definition.get("properties", {}):
        raise ValueError(f"Unknown payload: {name}")
    schema = {**SCHEMA, "oneOf": [{"$ref": f"#/$defs/{name}"}]}
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_payload(name: str, value: Any) -> None:
    _finite(value)
    errors = list(_validator(name).iter_errors(value))
    if errors:
        leaves = errors[0].context or errors
        detail = "; ".join(f"{e.json_path}: {e.message}" for e in leaves[:10])
        raise ValueError(detail)
