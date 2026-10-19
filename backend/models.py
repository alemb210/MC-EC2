from typing import Literal
from pydantic import BaseModel

InstanceState = Literal["pending", "running", "stopping", "stopped", "shutting-down", "terminated"]

class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    mock_mode: bool

class ServerStatus(BaseModel):
    server_id: str
    # No EC2 state exists until the launch has been recorded in the database.
    instance_state: InstanceState | None
    provisioning_state: Literal["awaiting_instance", "instance_assigned"] = "instance_assigned"
    minecraft_ready: bool
    connection_address: str | None
    # From the Minecraft status ping; null unless minecraft_ready.
    players_online: int | None = None
    players_max: int | None = None
    minecraft_version: str | None = None

class ServerAction(BaseModel):
    server_id: str
    instance_state: InstanceState

class ServerSummary(BaseModel):
    server_id: str
    region: str
    minecraft_version: str | None
    instance_type: str | None
    # False while a launch hasn't finished; POST /servers again resumes it.
    has_instance: bool

class ServerCreated(BaseModel):
    server_id: str
    instance_state: InstanceState
    region: str
    minecraft_version: str
    instance_type: str | None
