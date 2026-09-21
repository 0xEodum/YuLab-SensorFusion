import json

import pytest
from fastapi.testclient import TestClient

from app.contracts import CONTRACTS, validate_payload
from app.main import app

client = TestClient(app)


def test_real_health_and_capabilities_obey_contract():
    for route, name in [("health", "Health"), ("capabilities", "Capabilities")]:
        response = client.get(f"/api/v1/{route}")
        assert response.status_code == 200
        validate_payload(name, response.json())
        assert response.headers["x-request-id"]
        assert response.headers["cache-control"] == "no-store"
    capabilities = client.get("/api/v1/capabilities").json()
    assert not capabilities["checkpoints"]
    assert capabilities["device"] is None
    assert capabilities["capture_renderer"] is None
    assert all(not c["available"] for c in capabilities["sensors"].values())
    assert all(not c["available"] for c in capabilities["services"].values())


@pytest.mark.parametrize("method,path,status,code", [
    ("GET", "/api/v1/missing", 404, "not_found"),
    ("POST", "/api/v1/health", 405, "method_not_allowed"),
    ("POST", "/api/v1/inference", 404, "not_found"),
])
def test_errors(method, path, status, code):
    response = client.request(method, path)
    assert response.status_code == status
    validate_payload("ApiError", response.json())
    assert response.json()["code"] == code
    assert response.json()["request_id"] == response.headers["x-request-id"]
    if status == 405:
        assert response.headers["allow"] == "GET"


def test_openapi_is_exactly_the_reviewed_contract():
    expected = json.loads((CONTRACTS / "openapi.bundle.json").read_text())
    assert client.get("/openapi.json").json() == expected
    routes = {(r.path, method) for r in app.routes for method in (r.methods or []) if r.path.startswith('/api/')}
    declared = {(p, m.upper()) for p, ops in expected['paths'].items() for m in ops}
    assert routes == declared


def test_no_remote_reference_resolution():
    document = json.dumps(client.get('/openapi.json').json())
    assert './lab.schema.json' not in document
    assert '#/$defs/' not in document


def test_internal_errors_are_sanitized_and_contract_valid(monkeypatch):
    from app import main
    original = main.validate_payload
    def broken(name, value):
        if name == 'Health':
            raise RuntimeError('private diagnostic that must not reach the client')
        original(name, value)
    monkeypatch.setattr(main, 'validate_payload', broken)
    response = client.get('/api/v1/health')
    assert response.status_code == 500
    validate_payload('ApiError', response.json())
    assert response.json()['code'] == 'internal_error'
    assert 'private diagnostic' not in response.text
    assert response.json()['request_id'] == response.headers['x-request-id']
