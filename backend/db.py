import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from config import Settings

class ServerLimitReached(Exception):
    """The caller (or the whole deployment) already has the maximum number of servers."""

class AdminLimitReached(Exception):
    """The server already has the maximum number of admins."""

class DatabaseUnavailable(Exception):
    """The database could not answer. retry_after is set when Aurora is resuming from auto-pause."""

    def __init__(self, retry_after: int | None = None):
        super().__init__("database unavailable")
        self.retry_after = retry_after

@dataclass(frozen=True)
class OwnedServer:
    id: str
    instance_id: str | None
    region: str
    name: str | None = None
    role: str = "owner"

@dataclass(frozen=True)
class ServerRow:
    id: str
    region: str
    version: str | None
    instance_type: str | None
    has_instance: bool
    name: str | None = None
    role: str = "owner"

# The caller's relationship to a server; used by queries that join identities i to servers s.
ROLE_SQL = "CASE WHEN s.owner_id = i.user_id THEN 'owner' ELSE 'admin' END AS role"
CAN_ACCESS_SQL = ("(s.owner_id = i.user_id OR EXISTS (SELECT 1 FROM server_admins a "
                  "WHERE a.server_id = s.id AND a.user_id = i.user_id))")

# Advisory lock key that serializes server creation, so the server limits hold under concurrency.
CREATE_SERVER_LOCK = 7_320_001

def _param(name, value):
    if value is None:
        return {"name": name, "value": {"isNull": True}}
    if isinstance(value, bool):
        return {"name": name, "value": {"booleanValue": value}}
    if isinstance(value, int):
        return {"name": name, "value": {"longValue": value}}
    if isinstance(value, uuid.UUID):
        return {"name": name, "value": {"stringValue": str(value)}, "typeHint": "UUID"}
    return {"name": name, "value": {"stringValue": str(value)}}

class ServerRepository:
    """Reads users/identities/servers through the RDS Data API (HTTPS; no VPC needed)."""

    def __init__(self, cluster_arn: str, secret_arn: str, database: str, region: str):
        self.target = {"resourceArn": cluster_arn, "secretArn": secret_arn, "database": database}
        self.region = region
        self.client = None

    def _rds(self):
        # No client at import time, matching ec2.py.
        if self.client is None:
            self.client = boto3.client("rds-data", region_name=self.region,
                                       config=Config(connect_timeout=3, read_timeout=10,
                                                     retries={"total_max_attempts": 1}))
        return self.client

    def _call(self, method, **kwargs):
        try:
            return getattr(self._rds(), method)(**kwargs)
        except ClientError as exc:
            resuming = exc.response["Error"]["Code"] == "DatabaseResumingException"
            raise DatabaseUnavailable(retry_after=15 if resuming else None) from exc
        except BotoCoreError as exc:
            raise DatabaseUnavailable from exc

    def query(self, sql: str, transaction_id: str | None = None, **params) -> list[dict]:
        extra = {"transactionId": transaction_id} if transaction_id else {}
        resp = self._call("execute_statement", **self.target, **extra, sql=sql, formatRecordsAs="JSON",
                          parameters=[_param(k, v) for k, v in params.items()])
        return json.loads(resp.get("formattedRecords") or "[]")

    @contextmanager
    def transaction(self):
        tx = self._call("begin_transaction", **self.target)["transactionId"]
        try:
            yield tx
            self._call("commit_transaction", resourceArn=self.target["resourceArn"],
                       secretArn=self.target["secretArn"], transactionId=tx)
        except BaseException:
            try:
                self._call("rollback_transaction", resourceArn=self.target["resourceArn"],
                           secretArn=self.target["secretArn"], transactionId=tx)
            except DatabaseUnavailable:
                pass  # The Data API rolls back abandoned transactions after a timeout.
            raise

    def _find_user(self, sub: str, transaction_id: str | None = None) -> str | None:
        rows = self.query("SELECT user_id::text AS user_id FROM identities "
                          "WHERE provider = 'cognito' AND provider_id = :sub",
                          sub=sub, transaction_id=transaction_id)
        return rows[0]["user_id"] if rows else None

    def ensure_user(self, sub: str) -> tuple[str, bool]:
        """The user ID for a Cognito sub, creating the users and identities rows on first call.

        Returns (user_id, created)."""
        existing = self._find_user(sub)
        if existing:
            return existing, False
        with self.transaction() as tx:
            # Serialize first logins for this subject without waiting inside Lambda.
            lock = self.query("SELECT pg_try_advisory_xact_lock(hashtextextended(:sub, 0)) AS acquired",
                              sub=sub, transaction_id=tx)
            if not lock[0]["acquired"]:
                raise DatabaseUnavailable(retry_after=1)
            existing = self._find_user(sub, tx)
            if existing:
                return existing, False
            user_id = uuid.uuid4()
            self.query("INSERT INTO users (id) VALUES (:user_id)", user_id=user_id, transaction_id=tx)
            self.query("INSERT INTO identities (user_id, provider, provider_id) "
                       "VALUES (:user_id, 'cognito', :sub)", user_id=user_id, sub=sub, transaction_id=tx)
        return str(user_id), True

    def reserve_server(self, user_id: str, region: str, version: str,
                       max_per_user: int, max_total: int, name: str | None = None) -> OwnedServer:
        """A server row for the user to launch an instance into.

        Reuses the user's server whose launch didn't finish (instance_id still NULL), otherwise
        inserts one if both limits allow it. Raises ServerLimitReached."""
        owner = uuid.UUID(user_id)
        with self.transaction() as tx:
            self.query("SELECT 1 AS locked FROM (SELECT pg_advisory_xact_lock(:key)) l",
                       transaction_id=tx, key=CREATE_SERVER_LOCK)
            pending = self.query(
                "SELECT id::text AS id, region, name FROM servers "
                "WHERE owner_id = :owner AND instance_id IS NULL ORDER BY created_at LIMIT 1",
                transaction_id=tx, owner=owner)
            if pending:
                return OwnedServer(id=pending[0]["id"], instance_id=None, region=pending[0]["region"],
                                   name=pending[0].get("name"))
            counts = self.query(
                "SELECT count(*) FILTER (WHERE owner_id = :owner) AS mine, count(*) AS total FROM servers",
                transaction_id=tx, owner=owner)[0]
            if counts["mine"] >= max_per_user or counts["total"] >= max_total:
                raise ServerLimitReached
            row = self.query(
                "INSERT INTO servers (owner_id, region, version, name) VALUES (:owner, :region, :version, :name) "
                "RETURNING id::text AS id, region, name",
                transaction_id=tx, owner=owner, region=region, version=version, name=name)[0]
        return OwnedServer(id=row["id"], instance_id=None, region=row["region"], name=row.get("name"))

    def attach_instance(self, server_id: str, instance_id: str, instance_type: str | None) -> None:
        self.query("UPDATE servers SET instance_id = :instance_id, instance_type = :instance_type "
                   "WHERE id = :server_id AND instance_id IS NULL",
                   server_id=uuid.UUID(server_id), instance_id=instance_id, instance_type=instance_type)

    def server_exists(self, server_id: str) -> bool:
        return bool(self.query("SELECT 1 AS found FROM servers WHERE id = :server_id",
                               server_id=uuid.UUID(server_id)))

    def rename_server(self, server_id: str, name: str) -> None:
        self.query("UPDATE servers SET name = :name WHERE id = :server_id",
                   server_id=uuid.UUID(server_id), name=name)

    def delete_server(self, server_id: str) -> None:
        """Deletes the row; its admins go with it (ON DELETE CASCADE)."""
        self.query("DELETE FROM servers WHERE id = :server_id", server_id=uuid.UUID(server_id))

    def list_admins(self, server_id: str) -> list[dict]:
        return self.query("SELECT user_id::text AS user_id, email FROM server_admins "
                          "WHERE server_id = :server_id ORDER BY created_at",
                          server_id=uuid.UUID(server_id))

    def add_admin(self, server_id: str, user_id: str, email: str, max_admins: int) -> None:
        """Adds an admin; adding an existing admin changes nothing. Raises AdminLimitReached."""
        server, user = uuid.UUID(server_id), uuid.UUID(user_id)
        with self.transaction() as tx:
            # Serializes additions to this server, so the limit holds under concurrency.
            self.query("SELECT 1 AS locked FROM (SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))) l",
                       transaction_id=tx, key=server_id)
            counts = self.query(
                "SELECT count(*) FILTER (WHERE user_id = :user_id) AS existing, count(*) AS total "
                "FROM server_admins WHERE server_id = :server_id",
                transaction_id=tx, server_id=server, user_id=user)[0]
            if counts["existing"]:
                return
            if counts["total"] >= max_admins:
                raise AdminLimitReached
            self.query("INSERT INTO server_admins (server_id, user_id, email) "
                       "VALUES (:server_id, :user_id, :email)",
                       transaction_id=tx, server_id=server, user_id=user, email=email)

    def remove_admin(self, server_id: str, user_id: str) -> bool:
        """Whether a row was removed."""
        try:
            user = uuid.UUID(user_id)
        except ValueError:
            return False  # Not a user ID; avoids a cast error in SQL.
        return bool(self.query(
            "DELETE FROM server_admins WHERE server_id = :server_id AND user_id = :user_id "
            "RETURNING user_id::text AS user_id", server_id=uuid.UUID(server_id), user_id=user))

    def list_servers(self, sub: str) -> list[ServerRow]:
        """The servers the Cognito user sub owns or administers, oldest first."""
        rows = self.query(
            f"SELECT s.id::text AS id, s.region, s.version, s.instance_type, s.name, {ROLE_SQL}, "
            "s.instance_id IS NOT NULL AS has_instance "
            f"FROM identities i JOIN servers s ON {CAN_ACCESS_SQL} "
            "WHERE i.provider = 'cognito' AND i.provider_id = :sub ORDER BY s.created_at",
            sub=sub)
        return [ServerRow(id=r["id"], region=r["region"], version=r.get("version"),
                          instance_type=r.get("instance_type"), has_instance=r["has_instance"],
                          name=r.get("name"), role=r.get("role", "owner"))
                for r in rows]

    def get_server_for_user(self, sub: str, server_id: str) -> OwnedServer | None:
        """The server with the caller's role, only if the Cognito user sub owns or administers it."""
        try:
            server_uuid = uuid.UUID(server_id)
        except ValueError:
            return None  # Not a server ID; avoids a cast error in SQL.
        rows = self.query(
            f"SELECT s.id::text AS id, s.instance_id, s.region, s.name, {ROLE_SQL} "
            f"FROM identities i JOIN servers s ON {CAN_ACCESS_SQL} "
            "WHERE i.provider = 'cognito' AND i.provider_id = :sub AND s.id = :server_id",
            sub=sub, server_id=server_uuid)
        if not rows:
            return None
        row = rows[0]
        return OwnedServer(id=row["id"], instance_id=row.get("instance_id"), region=row["region"],
                           name=row.get("name"), role=row.get("role", "owner"))

def build_repository(settings: Settings) -> ServerRepository | None:
    if settings.mock_mode or not (settings.db_cluster_arn and settings.db_secret_arn):
        return None
    return ServerRepository(settings.db_cluster_arn, settings.db_secret_arn,
                            settings.db_name, settings.aws_region)
