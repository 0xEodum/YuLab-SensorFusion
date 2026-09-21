import copy
import json
import math

import pytest
from jsonschema import Draft202012Validator

from app.contracts import CONTRACTS, SCHEMA, parse_json, validate_payload

FIXTURES = CONTRACTS / "fixtures"
CASES = json.loads((FIXTURES / "cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_shared_wire_cases(case):
    def run():
        value = parse_json(case.get("raw") or (FIXTURES / case["base"]).read_text())
        for patch in case.get("patches", []):
            target = value
            for key in patch["path"][:-1]:
                target = target[key]
            key = patch["path"][-1]
            if patch["op"] == "delete":
                del target[key]
            else:
                target[key] = copy.deepcopy(patch["value"])
        validate_payload(case["schema"], value)
    if case["valid"]:
        run()
    else:
        with pytest.raises(ValueError):
            run()


def test_schema_and_family_coverage():
    Draft202012Validator.check_schema(SCHEMA)
    names = {r["$ref"].split("/")[-1] for r in SCHEMA["oneOf"]}
    assert names == {c["schema"] for c in CASES if c["valid"]}


@pytest.mark.parametrize("number", [math.nan, math.inf, -math.inf])
def test_in_memory_non_finite(number):
    world = json.loads((FIXTURES / "WorldSpec.json").read_text())
    world["extent_m"][0] = number
    with pytest.raises(ValueError, match="Non-finite"):
        validate_payload("WorldSpec", world)


def test_generated_bindings_import():
    # Generated annotations must remain importable on the locked Python runtime.
    from app import generated
    assert set(generated.Health.__required_keys__) == {"schema_version", "kind", "status", "service", "service_version"}
