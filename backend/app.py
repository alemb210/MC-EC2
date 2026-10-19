from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from auth import Principal, build_verifier, current_user_dependency
from config import Settings
from db import DatabaseUnavailable, build_repository
from db import ServerLimitReached
from models import HealthResponse, ServerAction, ServerCreated, ServerStatus, ServerSummary, UserResponse
from service import AWSUnavailable, CreationUnavailable, InvalidServerState, StatusService, UnknownServer

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
NOT_BUILT_PAGE = ("<!doctype html><title>MC-EC2</title>"
                  "<p>Frontend not built: run <code>npm run build</code> in frontend/.</p>")

# Legacy routes (/api/servers/{instance_id}) are disabled: they took raw EC2 instance IDs
# and bypassed authentication and ownership checks. Replaced by the authenticated
# /servers/{server_id}/start and /stop routes below.
#
# from botocore.exceptions import BotoCoreError, ClientError
# import ec2
#
# def call(fn, instance_id):
#     try:
#         return fn(instance_id)
#     except ec2.InvalidState as e:
#         raise HTTPException(409, str(e)) from None
#     except ClientError as e:
#         code = e.response["Error"]["Code"]
#         if code.startswith("InvalidInstanceID"):
#             raise HTTPException(404, f"instance {instance_id} not found") from None
#         raise HTTPException(502, f"AWS error: {code}") from None
#     except BotoCoreError:
#         raise HTTPException(502, "Unable to contact AWS. Check credentials and connectivity.") from None

SERVER_ERRORS = {
    401: {"description": "Missing, invalid, or expired access token"},
    404: {"description": "Unknown server, or not owned by the caller"},
    502: {"description": "AWS could not be reached"},
    503: {"description": "Database or authentication temporarily unavailable"},
}


def create_app(settings: Settings | None = None, verifier=None, repository=None) -> FastAPI:
    settings = settings if settings is not None else Settings.from_env()
    verifier = verifier if verifier is not None else build_verifier(settings)
    repository = repository if repository is not None else build_repository(settings)
    service = StatusService(settings, repository)
    current_user = current_user_dependency(settings, verifier)
    app = FastAPI(
        title="MC-EC2",
        description="Minecraft server lifecycle API. Server routes require a Cognito access token "
                    "(Authorization: Bearer) and only act on servers the caller owns.",
    )

    @app.get("/health", response_model=HealthResponse)
    def health():
        return HealthResponse(mock_mode=settings.mock_mode)

    def run(fn, *args):
        try:
            return fn(*args)
        except UnknownServer:
            raise HTTPException(404, "Unknown server ID") from None
        except InvalidServerState as e:
            raise HTTPException(409, str(e)) from None
        except ServerLimitReached:
            raise HTTPException(409, "Server limit reached.") from None
        except CreationUnavailable:
            raise HTTPException(503, "Server creation is not configured.") from None
        except DatabaseUnavailable as e:
            headers = {"Retry-After": str(e.retry_after)} if e.retry_after else None
            raise HTTPException(503, "Database unavailable. Try again shortly.", headers=headers) from None
        except AWSUnavailable:
            raise HTTPException(502, "Unable to reach EC2. Check AWS credentials, region, permissions, and connectivity.") from None

    @app.post("/me", response_model=UserResponse,
              responses={201: {"description": "User registered"}, 401: SERVER_ERRORS[401], 503: SERVER_ERRORS[503]})
    def register(response: Response, principal: Principal = Depends(current_user)):
        """Registers the caller on first call; later calls return the same user."""
        user = run(service.register, principal)
        response.status_code = 201 if user.created else 200
        return user

    @app.get("/servers", response_model=list[ServerSummary],
             responses={401: SERVER_ERRORS[401], 503: SERVER_ERRORS[503]})
    def list_servers(principal: Principal = Depends(current_user)):
        """Registers the caller if needed, then lists their servers, oldest first."""
        return run(service.list_servers, principal)

    @app.post("/servers", response_model=ServerCreated, status_code=201,
              responses={401: SERVER_ERRORS[401], 409: {"description": "Server limit reached"},
                         502: SERVER_ERRORS[502], 503: {"description": "Database unavailable, or server creation not configured"}})
    def create_server(principal: Principal = Depends(current_user)):
        """Launches a Minecraft server for the caller, registering them first if needed.

        Retrying after a failed launch resumes the same server instead of creating another."""
        return run(service.create_server, principal)

    # Synchronous routes run in FastAPI's worker thread pool, keeping blocking
    # SDK and Minecraft calls off the async event loop.
    @app.get("/servers/{server_id}/status", response_model=ServerStatus, responses=SERVER_ERRORS)
    def status(server_id: str, principal: Principal = Depends(current_user)):
        return run(service.status, server_id, principal)

    @app.post("/servers/{server_id}/start", response_model=ServerAction, status_code=202,
              responses={**SERVER_ERRORS, 409: {"description": "Instance is still stopping"}})
    def start(server_id: str, principal: Principal = Depends(current_user)):
        return run(service.start, server_id, principal)

    @app.post("/servers/{server_id}/stop", response_model=ServerAction, status_code=202,
              responses={**SERVER_ERRORS, 409: {"description": "Instance is still starting"}})
    def stop(server_id: str, principal: Principal = Depends(current_user)):
        return run(service.stop, server_id, principal)

    # Legacy routes, disabled (see the note at the top of this file).
    #
    # @app.get("/api/servers/{instance_id}")
    # def get_status(instance_id: str):
    #     return call(ec2.status, instance_id)
    #
    # @app.post("/api/servers/{instance_id}/start")
    # def legacy_start(instance_id: str):
    #     return {"state": call(ec2.start, instance_id)}
    #
    # @app.post("/api/servers/{instance_id}/stop")
    # def legacy_stop(instance_id: str):
    #     return {"state": call(ec2.stop, instance_id)}

    # Mounted last so API routes and /docs take precedence over static files.
    if FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    else:
        @app.get("/", include_in_schema=False)
        def frontend_not_built():
            return HTMLResponse(NOT_BUILT_PAGE)
    return app


app = create_app()
