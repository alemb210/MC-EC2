from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

import ec2
from config import Settings
from models import HealthResponse, ServerStatus
from service import AWSUnavailable, StatusService, UnknownServer

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


# Preserve the original helper and legacy error/response contracts.
def call(fn, instance_id):
    try:
        return fn(instance_id)
    except ec2.InvalidState as e:
        raise HTTPException(409, str(e)) from None
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code.startswith("InvalidInstanceID"):
            raise HTTPException(404, f"instance {instance_id} not found") from None
        raise HTTPException(502, f"AWS error: {code}") from None
    except BotoCoreError:
        raise HTTPException(502, "Unable to contact AWS. Check credentials and connectivity.") from None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings.from_env()
    service = StatusService(settings)
    app = FastAPI(
        title="MC-EC2",
        description="Local prototype with health/status and existing frontend/EC2 lifecycle routes. Authentication and ownership checks are required before public deployment.",
    )

    @app.get("/health", response_model=HealthResponse)
    def health():
        return HealthResponse(mock_mode=settings.mock_mode)

    # Synchronous routes run in FastAPI's worker thread pool, keeping blocking
    # SDK and Minecraft calls off the async event loop.
    @app.get("/servers/{server_id}/status", response_model=ServerStatus,
             responses={404: {"description": "Unknown application server ID"},
                        502: {"description": "AWS status could not be retrieved"}})
    def status(server_id: str):
        try:
            return service.status(server_id)
        except UnknownServer:
            raise HTTPException(404, "Unknown server ID") from None
        except AWSUnavailable:
            raise HTTPException(502, "Unable to retrieve EC2 status. Check AWS credentials, region, permissions, and connectivity.") from None

    def legacy_call(fn, instance_id):
        # Legacy routes use real instance IDs, not application IDs. They have no
        # mock implementation; block them in mock mode to prevent AWS access.
        if settings.mock_mode:
            raise HTTPException(503, "Legacy EC2 routes require MOCK_MODE=false.")
        return call(fn, instance_id)

    @app.get("/api/servers/{instance_id}")
    def get_status(instance_id: str):
        return legacy_call(ec2.status, instance_id)

    @app.post("/api/servers/{instance_id}/start")
    def start(instance_id: str):
        return {"state": legacy_call(ec2.start, instance_id)}

    @app.post("/api/servers/{instance_id}/stop")
    def stop(instance_id: str):
        return {"state": legacy_call(ec2.stop, instance_id)}

    # Mounted last so API routes and /docs take precedence over static files.
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app


app = create_app()
