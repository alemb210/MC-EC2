from botocore.exceptions import BotoCoreError, ClientError
import ec2
from config import Settings
from models import ServerStatus

class UnknownServer(Exception):
    pass

class AWSUnavailable(Exception):
    pass

MOCK_STATUSES = {
    "demo-server": ("running", True, "203.0.113.10:25565"),
    "demo-starting": ("running", False, "203.0.113.11:25565"),
    "demo-stopped": ("stopped", False, None),
}

class StatusService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def status(self, server_id: str) -> ServerStatus:
        if self.settings.mock_mode:
            if server_id not in MOCK_STATUSES:
                raise UnknownServer(server_id)
            state, ready, address = MOCK_STATUSES[server_id]
        else:
            instance_id = self.settings.servers.get(server_id)
            if instance_id is None:
                raise UnknownServer(server_id)
            try:
                info = ec2.status(instance_id, region=self.settings.aws_region)
            except (ClientError, BotoCoreError) as exc:
                # Never substitute mock data or expose AWS exception details.
                raise AWSUnavailable from exc
            state = info["state"]
            ready = info["minecraft"] is not None
            ip = info["ip"] if state == "running" else None
            address = f"{ip}:{ec2.MC_PORT}" if ip else None
        return ServerStatus(server_id=server_id, instance_state=state,
                            minecraft_ready=ready, connection_address=address)
