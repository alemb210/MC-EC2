from typing import Literal
from pydantic import BaseModel

class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    mock_mode: bool

class ServerStatus(BaseModel):
    server_id: str
    instance_state: Literal["pending", "running", "stopping", "stopped", "shutting-down", "terminated"]
    minecraft_ready: bool
    connection_address: str | None
