from datetime import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, Field, StringConstraints, field_validator

ServerName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32,
                                              pattern=r"^[^\x00-\x1f\x7f]+$")]
PlayerName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_]{3,16}$")]
Role = Literal["owner", "admin"]

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
    # When the auto-stop job will stop this server if it stays empty; null while players are online.
    auto_stop_at: datetime | None = None

class ServerAction(BaseModel):
    server_id: str
    instance_state: InstanceState

class UserResponse(BaseModel):
    user_id: str
    created: bool

class ServerSummary(BaseModel):
    server_id: str
    name: str
    # Whether the caller owns this server or was added to it as an admin.
    role: Role
    region: str
    minecraft_version: str | None
    instance_type: str | None
    # False while a launch hasn't finished; POST /servers again resumes it.
    has_instance: bool

class AccessSettings(BaseModel):
    mode: Literal["public", "whitelist"]
    # Kept while public, so switching back to whitelist doesn't lose the names.
    players: list[PlayerName] = Field(default_factory=list, max_length=100)

    @field_validator("players")
    @classmethod
    def unique_players(cls, players):
        unique = {}
        for player in players:
            unique.setdefault(player.lower(), player)
        return list(unique.values())

class AccessUpdated(AccessSettings):
    # Applied now on a running server; otherwise the server applies it when it next boots.
    applied: Literal["applying", "on_next_start"]

class ServerCreate(BaseModel):
    name: ServerName | None = None
    # Omitted: the server is public.
    access: AccessSettings | None = None

class ServerRename(BaseModel):
    name: ServerName

class AdminCreate(BaseModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=254,
                                            pattern=r'^[^@\s"\\]+@[^@\s"\\]+$')]

class ServerAdmin(BaseModel):
    user_id: str
    email: str

class ServerCreated(BaseModel):
    server_id: str
    name: str
    instance_state: InstanceState
    region: str
    minecraft_version: str
    instance_type: str | None
