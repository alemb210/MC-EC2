from botocore.exceptions import BotoCoreError, ClientError
import ec2
from auth import Principal
from config import Settings
from db import DatabaseUnavailable, OwnedServer, ServerLimitReached
from models import ServerAction, ServerCreated, ServerStatus, ServerSummary, UserResponse

class UnknownServer(Exception):
    pass

class AWSUnavailable(Exception):
    pass

class InvalidServerState(Exception):
    pass

class CreationUnavailable(Exception):
    """Server creation is not configured (no launch template)."""

# Matches VERSION in infra/minecraft/user_data.sh, which every launched instance runs.
MINECRAFT_VERSION = "LATEST"

MOCK_STATUSES = {
    "demo-server": ("running", True, "203.0.113.10:25565"),
    "demo-starting": ("running", False, "203.0.113.11:25565"),
    "demo-stopped": ("stopped", False, None),
}
MOCK_MINECRAFT = {"demo-server": {"online": 2, "max": 20, "version": "1.21.4"}}

class StatusService:
    def __init__(self, settings: Settings, repository=None):
        self.settings = settings
        self.repository = repository

    def _owned_instance(self, principal: Principal, server_id: str) -> OwnedServer:
        # Ownership is checked before any EC2 call; servers the caller doesn't own look unknown.
        if self.repository is None:
            raise DatabaseUnavailable
        server = self.repository.get_owned_server(principal.sub, server_id)
        if server is None:
            raise UnknownServer(server_id)
        if server.instance_id is None:
            raise InvalidServerState("server has no EC2 instance yet")
        return server

    def register(self, principal: Principal) -> UserResponse:
        if self.settings.mock_mode:
            return UserResponse(user_id="00000000-0000-4000-8000-000000000000", created=False)
        if self.repository is None:
            raise DatabaseUnavailable
        user_id, created = self.repository.ensure_user(principal.sub)
        return UserResponse(user_id=user_id, created=created)

    def list_servers(self, principal: Principal) -> list[ServerSummary]:
        if self.settings.mock_mode:
            return [ServerSummary(server_id=sid, region="us-east-1", minecraft_version=MINECRAFT_VERSION,
                                  instance_type="t4g.small", has_instance=True) for sid in MOCK_STATUSES]
        if self.repository is None:
            raise DatabaseUnavailable
        return [ServerSummary(server_id=r.id, region=r.region, minecraft_version=r.version,
                              instance_type=r.instance_type, has_instance=r.has_instance)
                for r in self.repository.list_owned_servers(principal.sub)]

    def create_server(self, principal: Principal) -> ServerCreated:
        if self.settings.mock_mode:
            raise ServerLimitReached  # The mock user already has its demo servers.
        if self.settings.launch_template_id is None:
            raise CreationUnavailable
        if self.repository is None:
            raise DatabaseUnavailable
        user_id, _ = self.repository.ensure_user(principal.sub)
        # The row is saved before the launch and reused on retry, so a failed or interrupted
        # launch never leaves an untracked instance or uses up the caller's limit.
        server = self.repository.reserve_server(
            user_id, self.settings.aws_region, MINECRAFT_VERSION,
            self.settings.max_servers_per_user, self.settings.max_servers_total)
        try:
            launched = ec2.launch(server.id, self.settings.launch_template_id, region=server.region)
        except (ClientError, BotoCoreError) as exc:
            raise AWSUnavailable from exc
        self.repository.attach_instance(server.id, launched["instance_id"], launched["instance_type"])
        return ServerCreated(server_id=server.id, instance_state=launched["state"], region=server.region,
                             minecraft_version=MINECRAFT_VERSION, instance_type=launched["instance_type"])

    def status(self, server_id: str, principal: Principal) -> ServerStatus:
        if self.settings.mock_mode:
            if server_id not in MOCK_STATUSES:
                raise UnknownServer(server_id)
            state, ready, address = MOCK_STATUSES[server_id]
            minecraft = MOCK_MINECRAFT.get(server_id)
        else:
            server = self._owned_instance(principal, server_id)
            try:
                info = ec2.status(server.instance_id, region=server.region)
            except (ClientError, BotoCoreError) as exc:
                # Never substitute mock data or expose AWS exception details.
                raise AWSUnavailable from exc
            state = info["state"]
            minecraft = info["minecraft"]
            ready = minecraft is not None
            ip = info["ip"] if state == "running" else None
            address = f"{ip}:{ec2.MC_PORT}" if ip else None
        return ServerStatus(server_id=server_id, instance_state=state,
                            minecraft_ready=ready, connection_address=address,
                            players_online=minecraft["online"] if minecraft else None,
                            players_max=minecraft["max"] if minecraft else None,
                            minecraft_version=minecraft["version"] if minecraft else None)

    def start(self, server_id: str, principal: Principal) -> ServerAction:
        return self._change_state(server_id, principal, ec2.start, mock_result={"stopped": "pending"})

    def stop(self, server_id: str, principal: Principal) -> ServerAction:
        return self._change_state(server_id, principal, ec2.stop, mock_result={"running": "stopping"})

    def _change_state(self, server_id, principal, action, mock_result) -> ServerAction:
        if self.settings.mock_mode:
            if server_id not in MOCK_STATUSES:
                raise UnknownServer(server_id)
            current = MOCK_STATUSES[server_id][0]
            return ServerAction(server_id=server_id, instance_state=mock_result.get(current, current))
        server = self._owned_instance(principal, server_id)
        try:
            state = action(server.instance_id, region=server.region)
        except ec2.InvalidState as exc:
            raise InvalidServerState(str(exc)) from exc
        except (ClientError, BotoCoreError) as exc:
            raise AWSUnavailable from exc
        return ServerAction(server_id=server_id, instance_state=state)
