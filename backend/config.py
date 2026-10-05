import json
import os
from pydantic import BaseModel, Field

class Settings(BaseModel):
    aws_region: str = Field(default="us-east-1", min_length=1)
    mock_mode: bool = False
    servers: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_env(cls):
        # Temporary application ID -> EC2 ID mapping until persistence exists.
        servers = json.loads(os.environ.get("DEMO_SERVERS", "{}"))
        if not isinstance(servers, dict) or any(
            not isinstance(k, str) or not k or not isinstance(v, str) or not v
            for k, v in servers.items()
        ):
            raise ValueError("DEMO_SERVERS must map nonempty server IDs to instance IDs")
        mode = os.environ.get("MOCK_MODE", "false").lower()
        if mode not in {"true", "false"}:
            raise ValueError("MOCK_MODE must be true or false")
        return cls(aws_region=os.environ.get("AWS_REGION", "us-east-1"),
                   mock_mode=mode == "true", servers=servers)
