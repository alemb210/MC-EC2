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

@dataclass(frozen=True)
class ServerRow:
    id: str
    region: str
    version: str | None
    instance_type: str | None
    has_instance: bool

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
        except BaseException:
            try:
                self._call("rollback_transaction", resourceArn=self.target["resourceArn"],
                           secretArn=self.target["secretArn"], transactionId=tx)
            except DatabaseUnavailable:
                pass  # The Data API rolls back abandoned transactions after a timeout.
            raise
        self._call("commit_transaction", resourceArn=self.target["resourceArn"],
                   secretArn=self.target["secretArn"], transactionId=tx)

    def ensure_user(self, sub: str) -> tuple[str, bool]:
        """The user ID for a Cognito sub, creating the users and identities rows on first call.

        Returns (user_id, created)."""
        rows = self.query(
            "WITH existing AS ("
            "  SELECT user_id FROM identities WHERE provider = 'cognito' AND provider_id = :sub"
            "), new_user AS ("
            "  INSERT INTO users (name) SELECT NULL WHERE NOT EXISTS (SELECT 1 FROM existing) RETURNING id"
            "), new_identity AS ("
            "  INSERT INTO identities (user_id, provider, provider_id) SELECT id, 'cognito', :sub FROM new_user"
            "  ON CONFLICT (provider, provider_id) DO NOTHING RETURNING user_id"
            ") "
            "SELECT user_id::text AS user_id, false AS created FROM existing "
            "UNION ALL SELECT user_id::text, true FROM new_identity",
            sub=sub)
        if rows:
            return rows[0]["user_id"], rows[0]["created"]
        # A concurrent first login won the identity insert; its row is visible now. The losing
        # users row has no identity or servers and is harmless.
        rows = self.query("SELECT user_id::text AS user_id FROM identities "
                          "WHERE provider = 'cognito' AND provider_id = :sub", sub=sub)
        if not rows:
            raise DatabaseUnavailable
        return rows[0]["user_id"], False

    def reserve_server(self, user_id: str, region: str, version: str,
                       max_per_user: int, max_total: int) -> OwnedServer:
        """A server row for the user to launch an instance into.

        Reuses the user's server whose launch didn't finish (instance_id still NULL), otherwise
        inserts one if both limits allow it. Raises ServerLimitReached."""
        owner = uuid.UUID(user_id)
        with self.transaction() as tx:
            self.query("SELECT 1 AS locked FROM (SELECT pg_advisory_xact_lock(:key)) l",
                       transaction_id=tx, key=CREATE_SERVER_LOCK)
            pending = self.query(
                "SELECT id::text AS id, region FROM servers "
                "WHERE owner_id = :owner AND instance_id IS NULL ORDER BY created_at LIMIT 1",
                transaction_id=tx, owner=owner)
            if pending:
                return OwnedServer(id=pending[0]["id"], instance_id=None, region=pending[0]["region"])
            counts = self.query(
                "SELECT count(*) FILTER (WHERE owner_id = :owner) AS mine, count(*) AS total FROM servers",
                transaction_id=tx, owner=owner)[0]
            if counts["mine"] >= max_per_user or counts["total"] >= max_total:
                raise ServerLimitReached
            row = self.query(
                "INSERT INTO servers (owner_id, region, version) VALUES (:owner, :region, :version) "
                "RETURNING id::text AS id, region",
                transaction_id=tx, owner=owner, region=region, version=version)[0]
        return OwnedServer(id=row["id"], instance_id=None, region=row["region"])

    def attach_instance(self, server_id: str, instance_id: str, instance_type: str | None) -> None:
        self.query("UPDATE servers SET instance_id = :instance_id, instance_type = :instance_type "
                   "WHERE id = :server_id AND instance_id IS NULL",
                   server_id=uuid.UUID(server_id), instance_id=instance_id, instance_type=instance_type)

    def list_owned_servers(self, sub: str) -> list[ServerRow]:
        """The servers the Cognito user sub owns, oldest first."""
        rows = self.query(
            "SELECT s.id::text AS id, s.region, s.version, s.instance_type, "
            "s.instance_id IS NOT NULL AS has_instance "
            "FROM servers s JOIN identities i ON i.user_id = s.owner_id "
            "WHERE i.provider = 'cognito' AND i.provider_id = :sub ORDER BY s.created_at",
            sub=sub)
        return [ServerRow(id=r["id"], region=r["region"], version=r.get("version"),
                          instance_type=r.get("instance_type"), has_instance=r["has_instance"])
                for r in rows]

    def get_owned_server(self, sub: str, server_id: str) -> OwnedServer | None:
        """The server, only if the Cognito user sub owns it."""
        try:
            server_uuid = uuid.UUID(server_id)
        except ValueError:
            return None  # Not a server ID; avoids a cast error in SQL.
        rows = self.query(
            "SELECT s.id::text AS id, s.instance_id, s.region "
            "FROM servers s JOIN identities i ON i.user_id = s.owner_id "
            "WHERE i.provider = 'cognito' AND i.provider_id = :sub AND s.id = :server_id",
            sub=sub, server_id=server_uuid)
        if not rows:
            return None
        row = rows[0]
        return OwnedServer(id=row["id"], instance_id=row.get("instance_id"), region=row["region"])

def build_repository(settings: Settings) -> ServerRepository | None:
    if settings.mock_mode or not (settings.db_cluster_arn and settings.db_secret_arn):
        return None
    return ServerRepository(settings.db_cluster_arn, settings.db_secret_arn,
                            settings.db_name, settings.aws_region)
