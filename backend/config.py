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
                   db_name=os.environ.get("DB_NAME") or "mcec2")
