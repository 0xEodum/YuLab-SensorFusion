"""SF-01 foundation API. Future lab operations are deliberately absent."""
import json
import logging
import hashlib
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException

from .contracts import CONTRACTS, parse_json, validate_payload
from .generated import Capabilities, Health
from .capture_worker import ARTIFACT_ROOT, probe_capture_worker, run_capture_worker
from .jobs import CaptureCoordinator, CaptureJobStore

app = FastAPI(title="YuLab foundation API", version="0.1.0")
logger = logging.getLogger(__name__)
job_store = CaptureJobStore(ARTIFACT_ROOT / "jobs.sqlite3")
job_store.fail_interrupted()
capture_coordinator = CaptureCoordinator(job_store, run_capture_worker)


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
    try:
        worker = probe_capture_worker()
        capture = {"available": True, "reason": None}
        renderer = f"{worker['browser']} / {worker['renderer']}"
        device = worker["vendor"]
    except Exception:
        capture = {"available": False, "reason": "device_unavailable"}
        renderer = None
        device = None
    payload: Capabilities = {
        "schema_version": "lab.v1", "kind": "Capabilities",
        "service_version": "0.1.0", "contracts_version": "lab.v1",
        "capture_renderer": renderer, "device": device,
        "sensors": {"rgb": capture, "ir": capture, "lidar": unavailable()},
        "services": {
            "worlds": unavailable(), "capture": capture, "datasets": unavailable(),
            "training": unavailable(), "inference": unavailable(),
        },
        "checkpoints": [],
    }
    validate_payload("Capabilities", payload)
    return payload


def canonical_hash(value) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def public_job(job):
    validate_payload("CaptureJob", job)
    return job


@app.post("/api/v1/captures", response_model=None, status_code=202)
async def create_capture(request: Request):
    try:
        payload = parse_json((await request.body()).decode("utf-8"))
        validate_payload("CaptureRequest", payload)
        plan = payload["plan"]
        for field, key in [
            ("world_sha256", "world"),
            ("rig_sha256", "rig"),
            ("environment_sha256", "environment"),
        ]:
            if plan[field] != canonical_hash(payload[key]):
                raise ValueError(f"{field} does not match the submitted {key}")
        if plan["simulation_time_s"] != payload["environment"]["simulation_time_s"]:
            raise ValueError("capture and environment simulation ticks differ")
        job = capture_coordinator.submit(payload)
        return JSONResponse(public_job(job), status_code=202)
    except (UnicodeDecodeError, ValueError) as exc:
        return error_response(request, 422, "validation_error", str(exc))


@app.get("/api/v1/jobs/{job_id}", response_model=None)
def get_capture_job(request: Request, job_id: str):
    try:
        return public_job(job_store.get(job_id))
    except KeyError:
        return error_response(request, 404, "not_found", "Capture job not found.")


@app.post("/api/v1/jobs/{job_id}/cancel", response_model=None)
def cancel_capture_job(request: Request, job_id: str):
    try:
        return public_job(capture_coordinator.cancel(job_id))
    except KeyError:
        return error_response(request, 404, "not_found", "Capture job not found.")


@app.get("/api/v1/jobs/{job_id}/artifacts/{artifact_id}", response_model=None)
def get_capture_artifact(request: Request, job_id: str, artifact_id: str):
    try:
        job = job_store.get(job_id)
    except KeyError:
        return error_response(request, 404, "not_found", "Capture job not found.")
    if job["state"] != "succeeded" or not job["result"]:
        return error_response(request, 404, "not_found", "Capture artifact is not published.")
    artifacts = job["result"]["artifacts"]
    artifact = next((value for value in artifacts.values() if value["id"] == artifact_id), None)
    if artifact is None:
        return error_response(request, 404, "not_found", "Capture artifact not found.")
    path = (ARTIFACT_ROOT / job_id / artifact_id).resolve()
    if path.parent != (ARTIFACT_ROOT / job_id).resolve() or not path.is_file():
        return error_response(request, 404, "not_found", "Capture artifact not found.")
    return FileResponse(path, media_type=artifact["media_type"], filename=artifact_id)
