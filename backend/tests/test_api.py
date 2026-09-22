import json

import pytest
from fastapi.testclient import TestClient

from app.contracts import CONTRACTS, validate_payload
from app.main import app

client = TestClient(app)


def test_real_health_and_capabilities_obey_contract(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "probe_capture_worker", lambda: {
        "browser": "Chromium fixture", "renderer": "WebGL fixture", "vendor": "device fixture",
    })
    for route, name in [("health", "Health"), ("capabilities", "Capabilities")]:
        response = client.get(f"/api/v1/{route}")
        assert response.status_code == 200
        validate_payload(name, response.json())
        assert response.headers["x-request-id"]
        assert response.headers["cache-control"] == "no-store"
    capabilities = client.get("/api/v1/capabilities").json()
    assert not capabilities["checkpoints"]
    assert capabilities["device"] == "device fixture"
    assert "Chromium fixture" in capabilities["capture_renderer"]
    assert capabilities["sensors"]["rgb"]["available"]
    assert not capabilities["sensors"]["ir"]["available"]
    assert capabilities["services"]["capture"]["available"]
    assert not capabilities["services"]["datasets"]["available"]


def test_capture_request_hashes_are_validated_before_acceptance(monkeypatch):
    from app import main
    payload = json.loads((CONTRACTS / "fixtures" / "CaptureRequest.json").read_text())
    for field, key in [
        ("world_sha256", "world"),
        ("rig_sha256", "rig"),
        ("environment_sha256", "environment"),
    ]:
        payload["plan"][field] = main.canonical_hash(payload[key])

    class Coordinator:
        def submit(self, request):
            assert request == payload
            return {
                "schema_version": "lab.v1", "kind": "CaptureJob",
                "job_id": "capture-job-api", "capture_id": "capture-fixture",
                "state": "queued", "progress": 0, "result": None, "error": None,
                "created_at": "2026-09-22T00:00:00Z",
                "updated_at": "2026-09-22T00:00:00Z",
            }
    monkeypatch.setattr(main, "capture_coordinator", Coordinator())
    response = client.post("/api/v1/captures", json=payload)
    assert response.status_code == 202
    validate_payload("CaptureJob", response.json())
    payload["plan"]["world_sha256"] = "0" * 64
    response = client.post("/api/v1/captures", json=payload)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_unknown_capture_job_and_artifact_are_explicit_404s():
    for path in [
        "/api/v1/jobs/unknown-job",
        "/api/v1/jobs/unknown-job/artifacts/rgb.png",
    ]:
        response = client.get(path)
        assert response.status_code == 404
        validate_payload("ApiError", response.json())
    response = client.post("/api/v1/jobs/unknown-job/cancel")
    assert response.status_code == 404
    validate_payload("ApiError", response.json())


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
