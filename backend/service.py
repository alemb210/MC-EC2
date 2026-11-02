from datetime import datetime, timedelta, timezone
from botocore.exceptions import BotoCoreError, ClientError
import cognito
import ec2
import player_access
from auth import Principal
from config import Settings
from db import DatabaseUnavailable, OwnedServer, ServerLimitReached, ServerRow
from models import (AccessSettings, AccessUpdated, ServerAction, ServerAdmin, ServerCreate, ServerCreated,
                    ServerStatus, ServerSummary, UserResponse)

class UnknownServer(Exception):
    pass

class UnknownUser(Exception):
    """No confirmed site user has this email."""

class UnknownAdmin(Exception):
    pass

class UnknownPlayers(Exception):
    """Mojang says these Minecraft names don't exist."""

    def __init__(self, names: list[str]):
        super().__init__(", ".join(names))

class AWSUnavailable(Exception):
    pass

class InvalidServerState(Exception):
    pass

class NotPermitted(Exception):
    """The caller is an admin of this server, and this action is for its owner."""

class CreationUnavailable(Exception):
    """Server creation is not configured (no launch template)."""

# Matches VERSION in infra/minecraft/user_data.sh, which every launched instance runs.
MINECRAFT_VERSION = "LATEST"
MAX_ADMINS_PER_SERVER = 5
AWS_ERROR = "Unable to reach AWS. Try again shortly."

MOCK_STATUSES = {
    "demo-server": ("running", True, "203.0.113.10:25565"),
    "demo-starting": ("running", False, "203.0.113.11:25565"),
    "demo-stopped": ("stopped", False, None),
    "demo-shared": ("running", True, "203.0.113.12:25565"),
}
MOCK_MINECRAFT = {
    "demo-server": {"online": 2, "max": 20, "version": "1.21.4"},
    "demo-shared": {"online": 0, "max": 20, "version": "1.21.4"},
}
MOCK_ROLES = {"demo-shared": "admin"}
MOCK_ACCESS = {"demo-server": {"mode": "whitelist", "players": ["Steve", "Alex"]}}
MOCK_ADMINS = {"demo-server": [ServerAdmin(user_id="00000000-0000-4000-8000-000000000001", email="friend@example.com")]}
MOCK_AUTO_STOP_MINUTES = {"demo-shared": 12}

def _mock_name(server_id: str) -> str:
    # demo-starting has no custom name, so it shows how an unnamed server looks.
    return server_id if server_id == "demo-starting" else server_id.replace("-", " ").capitalize()

class StatusService:
    def __init__(self, settings: Settings, repository=None):
        self.settings = settings
        self.repository = repository

    def _accessible_server(self, principal: Principal, server_id: str) -> OwnedServer:
        # Access is checked before any EC2 call; servers the caller can't access look unknown.
        if self.repository is None:
            raise DatabaseUnavailable
        server = self.repository.get_server_for_user(principal.sub, server_id)
        if server is None:
            raise UnknownServer(server_id)
        return server

    def _owned_server(self, principal: Principal, server_id: str) -> OwnedServer:
        server = self._accessible_server(principal, server_id)
        if server.role != "owner":
            raise NotPermitted
        return server

    def _accessible_instance(self, principal: Principal, server_id: str) -> OwnedServer:
        server = self._accessible_server(principal, server_id)
        if server.instance_id is None:
            raise InvalidServerState("server has no EC2 instance yet")
        return server

    def _mock_server(self, server_id: str, owner_only: bool = False) -> None:
        if server_id not in MOCK_STATUSES:
            raise UnknownServer(server_id)
        if owner_only and MOCK_ROLES.get(server_id, "owner") != "owner":
            raise NotPermitted

    def register(self, principal: Principal) -> UserResponse:
        if self.settings.mock_mode:
            return UserResponse(user_id="00000000-0000-4000-8000-000000000000", created=False)
        if self.repository is None:
            raise DatabaseUnavailable
        user_id, created = self.repository.ensure_user(principal.sub)
        return UserResponse(user_id=user_id, created=created)

    @staticmethod
    def _summary(row: ServerRow) -> ServerSummary:
        # A server without a custom name goes by its ID.
        return ServerSummary(server_id=row.id, name=row.name or row.id, role=row.role,
                             region=row.region, minecraft_version=row.version,
                             instance_type=row.instance_type, has_instance=row.has_instance)

    def list_servers(self, principal: Principal) -> list[ServerSummary]:
        if self.settings.mock_mode:
            return [ServerSummary(server_id=sid, name=_mock_name(sid), role=MOCK_ROLES.get(sid, "owner"),
                                  region="us-east-1", minecraft_version=MINECRAFT_VERSION,
                                  instance_type="t4g.small", has_instance=True) for sid in MOCK_STATUSES]
        if self.repository is None:
            raise DatabaseUnavailable
        self.repository.ensure_user(principal.sub)
        return [self._summary(r) for r in self.repository.list_servers(principal.sub)]

    def _reject_unknown_players(self, names: list[str]) -> None:
        unknown = player_access.unknown_players(names)
        if unknown:
            raise UnknownPlayers(unknown)

    def create_server(self, principal: Principal, request: ServerCreate | None = None) -> ServerCreated:
        request = request or ServerCreate()
        if self.settings.mock_mode:
            raise ServerLimitReached  # The mock user already has its demo servers.
        if self.settings.launch_template_id is None:
            raise CreationUnavailable
        if self.repository is None:
            raise DatabaseUnavailable
        if request.access:
            self._reject_unknown_players(request.access.players)
        user_id, _ = self.repository.ensure_user(principal.sub)
        # The row is saved before the launch and reused on retry, so a failed or interrupted
        # launch never leaves an untracked instance or uses up the caller's limit.
        server = self.repository.reserve_server(
            user_id, self.settings.aws_region, MINECRAFT_VERSION,
            self.settings.max_servers_per_user, self.settings.max_servers_total,
            name=request.name)
        try:
            # Saved before the launch, so the server's first boot applies it.
            if request.access:
                player_access.save(server.id, request.access.mode, request.access.players, server.region)
            launched = ec2.launch(server.id, self.settings.launch_template_id, region=server.region)
        except (ClientError, BotoCoreError) as exc:
            raise AWSUnavailable from exc
        self.repository.attach_instance(server.id, launched["instance_id"], launched["instance_type"])
        # The owner deleted the server during the launch: don't leave the new instance running untracked.
        if not self.repository.server_exists(server.id):
            try:
                ec2.terminate(launched["instance_id"], region=server.region)
            except (ClientError, BotoCoreError) as exc:
                raise AWSUnavailable from exc
            raise UnknownServer(server.id)
        return ServerCreated(server_id=server.id, name=server.name or server.id,
                             instance_state=launched["state"], region=server.region,
                             minecraft_version=MINECRAFT_VERSION, instance_type=launched["instance_type"])

    def rename_server(self, server_id: str, name: str, principal: Principal) -> ServerSummary:
        if self.settings.mock_mode:
            self._mock_server(server_id)
            return ServerSummary(server_id=server_id, name=name, role=MOCK_ROLES.get(server_id, "owner"),
                                 region="us-east-1", minecraft_version=MINECRAFT_VERSION,
                                 instance_type="t4g.small", has_instance=True)
        server = self._accessible_server(principal, server_id)
        self.repository.rename_server(server.id, name)
        rows = self.repository.list_servers(principal.sub)
        row = next((r for r in rows if r.id == server.id), None)
        if row is None:
            raise UnknownServer(server_id)
        return self._summary(row)

    def delete_server(self, server_id: str, principal: Principal) -> None:
        if self.settings.mock_mode:
            self._mock_server(server_id, owner_only=True)
            return
        server = self._owned_server(principal, server_id)
        if server.id in self.settings.protected_server_ids:
            raise InvalidServerState("This server is protected and can't be deleted.")
        # AWS first: if a step fails the row remains, so retrying finishes the job. The other
        # order could leave an instance running and billing with nothing tracking it.
        try:
            # By tag too, because a launch can succeed before its instance ID is recorded.
            instance_ids = {i["InstanceId"] for i in ec2.find_instances(server.id, region=server.region)}
            if server.instance_id:
                instance_ids.add(server.instance_id)
            for instance_id in sorted(instance_ids):
                ec2.terminate(instance_id, region=server.region)
            player_access.delete(server.id, server.region)
        except (ClientError, BotoCoreError) as exc:
            raise AWSUnavailable from exc
        self.repository.delete_server(server.id)

    def get_access(self, server_id: str, principal: Principal) -> AccessSettings:
        if self.settings.mock_mode:
            self._mock_server(server_id)
            return AccessSettings(**MOCK_ACCESS.get(server_id, {"mode": "public", "players": []}))
        server = self._accessible_server(principal, server_id)
        try:
            return AccessSettings(**player_access.load(server.id, server.region))
        except (ClientError, BotoCoreError) as exc:
            raise AWSUnavailable(AWS_ERROR) from exc

    def update_access(self, server_id: str, settings: AccessSettings, principal: Principal) -> AccessUpdated:
        if self.settings.mock_mode:
            self._mock_server(server_id)
            return AccessUpdated(mode=settings.mode, players=settings.players, applied="applying")
        server = self._accessible_server(principal, server_id)
        try:
            saved = {p.lower() for p in player_access.load(server.id, server.region)["players"]}
            # Only new names: a saved name that Mojang fails to confirm later shouldn't block an edit.
            self._reject_unknown_players([p for p in settings.players if p.lower() not in saved])
            player_access.save(server.id, settings.mode, settings.players, server.region)
        except (ClientError, BotoCoreError) as exc:
            raise AWSUnavailable(AWS_ERROR) from exc
        document = self.settings.sync_access_document
        applying = bool(server.instance_id and document and
                        player_access.trigger_sync(server.instance_id, document, server.region))
        return AccessUpdated(mode=settings.mode, players=settings.players,
                             applied="applying" if applying else "on_next_start")

    def list_admins(self, server_id: str, principal: Principal) -> list[ServerAdmin]:
        if self.settings.mock_mode:
            self._mock_server(server_id, owner_only=True)
            return MOCK_ADMINS.get(server_id, [])
        server = self._owned_server(principal, server_id)
        return [ServerAdmin(**row) for row in self.repository.list_admins(server.id)]

    def add_admin(self, server_id: str, email: str, principal: Principal) -> ServerAdmin:
        if self.settings.mock_mode:
            self._mock_server(server_id, owner_only=True)
            return ServerAdmin(user_id="00000000-0000-4000-8000-000000000002", email=email)
        server = self._owned_server(principal, server_id)
        try:
            sub = cognito.find_user_sub(email, self.settings.cognito_user_pool_id, self.settings.aws_region)
        except (ClientError, BotoCoreError) as exc:
            raise AWSUnavailable(AWS_ERROR) from exc
        if sub is None:
            raise UnknownUser(email)
        if sub == principal.sub:
            raise InvalidServerState("You already own this server.")
        # They may not have opened the site since confirming, so this can create their user row.
        user_id, _ = self.repository.ensure_user(sub)
        self.repository.add_admin(server.id, user_id, email, MAX_ADMINS_PER_SERVER)
        return ServerAdmin(user_id=user_id, email=email)

    def remove_admin(self, server_id: str, target: str, principal: Principal) -> None:
        """target is an admin's user ID, or "me" for an admin leaving the server."""
        if self.settings.mock_mode:
            self._mock_server(server_id, owner_only=target != "me")
            return
        server = self._accessible_server(principal, server_id)
        caller_id, _ = self.repository.ensure_user(principal.sub)
        user_id = caller_id if target == "me" else target
        if server.role != "owner" and user_id != caller_id:
            raise NotPermitted
        if not self.repository.remove_admin(server.id, user_id):
            raise UnknownAdmin(user_id)

    def status(self, server_id: str, principal: Principal) -> ServerStatus:
        auto_stop_at = None
        if self.settings.mock_mode:
            if server_id not in MOCK_STATUSES:
                raise UnknownServer(server_id)
            state, ready, address = MOCK_STATUSES[server_id]
            minecraft = MOCK_MINECRAFT.get(server_id)
            if server_id in MOCK_AUTO_STOP_MINUTES:
                auto_stop_at = datetime.now(timezone.utc) + timedelta(minutes=MOCK_AUTO_STOP_MINUTES[server_id])
        else:
            server = self._accessible_server(principal, server_id)
            if server.instance_id is None:
                return ServerStatus(server_id=server_id, instance_state=None,
                                    provisioning_state="awaiting_instance",
                                    minecraft_ready=False, connection_address=None)
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
            idle_minutes = self.settings.auto_stop_idle_minutes
            if state == "running" and idle_minutes > 0 and info.get("idle_since"):
                auto_stop_at = info["idle_since"] + timedelta(minutes=idle_minutes)
        return ServerStatus(server_id=server_id, instance_state=state,
                            minecraft_ready=ready, connection_address=address,
                            players_online=minecraft["online"] if minecraft else None,
                            players_max=minecraft["max"] if minecraft else None,
                            minecraft_version=minecraft["version"] if minecraft else None,
                            auto_stop_at=auto_stop_at)

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
        server = self._accessible_instance(principal, server_id)
        try:
            state = action(server.instance_id, region=server.region)
        except ec2.InvalidState as exc:
            raise InvalidServerState(str(exc)) from exc
        except (ClientError, BotoCoreError) as exc:
            raise AWSUnavailable from exc
        return ServerAction(server_id=server_id, instance_state=state)
