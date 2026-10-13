import json
import uuid
from dataclasses import dataclass
import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from config import Settings

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

    def query(self, sql: str, **params) -> list[dict]:
        try:
            resp = self._rds().execute_statement(
                **self.target, sql=sql, formatRecordsAs="JSON",
                parameters=[_param(k, v) for k, v in params.items()])
        except ClientError as exc:
            resuming = exc.response["Error"]["Code"] == "DatabaseResumingException"
            raise DatabaseUnavailable(retry_after=15 if resuming else None) from exc
        except BotoCoreError as exc:
            raise DatabaseUnavailable from exc
        return json.loads(resp.get("formattedRecords") or "[]")

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
