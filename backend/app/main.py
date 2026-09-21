"""SF-01 foundation API. Future lab operations are deliberately absent."""
import json
import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .contracts import CONTRACTS, validate_payload
from .generated import Capabilities, Health

app = FastAPI(title="YuLab foundation API", version="0.1.0")
logger = logging.getLogger(__name__)


def canonical_openapi():
    return json.loads((CONTRACTS / "openapi.bundle.json").read_text(encoding="utf-8"))


app.openapi = canonical_openapi


def error_response(request: Request, status: int, code: str, message: str, headers=None):
    payload = {
        "schema_version": "lab.v1", "kind": "ApiError", "code": code,
        "message": message, "request_id": request.state.request_id,
        "job_id": None, "details": [],
    }
    validate_payload("ApiError", payload)
    return JSONResponse(payload, status_code=status, headers=headers)


@app.middleware("http")
async def request_boundary(request: Request, call_next):
    request.state.request_id = uuid4().hex
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Request failed: %s", request.state.request_id)
        response = error_response(request, 500, "internal_error", "The backend could not complete this request.")
    response.headers["x-request-id"] = request.state.request_id
    response.headers["cache-control"] = "no-store"
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    codes = {404: "not_found", 405: "method_not_allowed"}
    return error_response(request, exc.status_code, codes.get(exc.status_code, "validation_error"), str(exc.detail), exc.headers)


@app.get("/api/v1/health", response_model=None)
def health() -> Health:
    payload: Health = {
        "schema_version": "lab.v1", "kind": "Health", "status": "ok",
        "service": "yulab-backend", "service_version": "0.1.0",
    }
    validate_payload("Health", payload)
    return payload


@app.get("/api/v1/capabilities", response_model=None)
def capabilities() -> Capabilities:
    def unavailable():
        return {"available": False, "reason": "not_implemented"}
    payload: Capabilities = {
        "schema_version": "lab.v1", "kind": "Capabilities",
        "service_version": "0.1.0", "contracts_version": "lab.v1",
        "capture_renderer": None, "device": None,
        "sensors": {name: unavailable() for name in ("rgb", "ir", "lidar")},
        "services": {name: unavailable() for name in ("worlds", "capture", "datasets", "training", "inference")},
        "checkpoints": [],
    }
    validate_payload("Capabilities", payload)
    return payload
