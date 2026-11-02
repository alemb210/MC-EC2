import os
from pydantic import BaseModel, Field

class Settings(BaseModel):
    aws_region: str = Field(default="us-east-1", min_length=1)
    mock_mode: bool = False
    # Cognito user pool that issues the access tokens the API accepts.
    cognito_user_pool_id: str | None = None
    cognito_client_id: str | None = None
    # Aurora cluster reached through the RDS Data API.
    db_cluster_arn: str | None = None
    db_secret_arn: str | None = None
    db_name: str = "mcec2"
    # Launch template for new servers; server creation returns 503 without it.
    launch_template_id: str | None = None
    # Caps on POST /servers. Self-signup is open, so these bound what strangers can launch.
    max_servers_per_user: int = Field(default=1, ge=0)
    max_servers_total: int = Field(default=3, ge=0)
    # Idle minutes before the auto-stop job stops a server; 0 turns auto-stop off.
    auto_stop_idle_minutes: int = Field(default=30, ge=0)
    # Servers the API must not delete (Terraform manages the admin's instance).
    protected_server_ids: frozenset[str] = frozenset()
    # SSM document that makes a running server apply its saved access settings.
    sync_access_document: str | None = None

    @classmethod
    def from_env(cls):
        mode = os.environ.get("MOCK_MODE", "false").lower()
        if mode not in {"true", "false"}:
            raise ValueError("MOCK_MODE must be true or false")
        # Missing Cognito/DB settings are not an error here: protected routes fail
        # closed with 503 at request time, so health and docs still work.
        return cls(aws_region=os.environ.get("AWS_REGION", "us-east-1"),
                   mock_mode=mode == "true",
                   cognito_user_pool_id=os.environ.get("COGNITO_USER_POOL_ID") or None,
                   cognito_client_id=os.environ.get("COGNITO_CLIENT_ID") or None,
                   db_cluster_arn=os.environ.get("DB_CLUSTER_ARN") or None,
                   db_secret_arn=os.environ.get("DB_SECRET_ARN") or None,
                   db_name=os.environ.get("DB_NAME") or "mcec2",
                   launch_template_id=os.environ.get("LAUNCH_TEMPLATE_ID") or None,
                   max_servers_per_user=int(os.environ.get("MAX_SERVERS_PER_USER") or 1),
                   max_servers_total=int(os.environ.get("MAX_SERVERS_TOTAL") or 3),
                   auto_stop_idle_minutes=int(os.environ.get("AUTO_STOP_IDLE_MINUTES") or 30),
                   protected_server_ids=frozenset(
                       s for s in os.environ.get("PROTECTED_SERVER_IDS", "").split(",") if s),
                   sync_access_document=os.environ.get("SYNC_ACCESS_DOCUMENT") or None)
