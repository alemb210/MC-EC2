from botocore.exceptions import BotoCoreError, ClientError
import ec2
from auth import Principal
from config import Settings
from db import DatabaseUnavailable, OwnedServer
from models import ServerAction, ServerStatus

class UnknownServer(Exception):
    pass

class AWSUnavailable(Exception):
    pass

class InvalidServerState(Exception):
    pass

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
