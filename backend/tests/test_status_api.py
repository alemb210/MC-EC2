import time
from types import SimpleNamespace
from unittest.mock import Mock
import jwt
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError, ReadTimeoutError
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
import ec2
from app import create_app
from auth import CognitoVerifier
from config import Settings
from db import DatabaseUnavailable, OwnedServer

POOL_ID = "us-east-1_TestPool"
CLIENT_ID = "test-client-id"
ISSUER = f"https://cognito-idp.us-east-1.amazonaws.com/{POOL_ID}"
OWNER_SUB = "owner-sub"
SERVER_ID = "3f2a6c1e-0000-4000-8000-000000000001"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)

@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    monkeypatch.setattr(ec2.boto3, "client", Mock(side_effect=AssertionError("Unexpected AWS access")))
    monkeypatch.setattr(ec2, "JavaServer", Mock(side_effect=AssertionError("Unexpected Minecraft access")))

class FakeRepository:
    """In-memory stand-in for db.ServerRepository: (sub, server_id) -> server."""

    def __init__(self, servers=None, error=None):
        self.servers = servers if servers is not None else {
            (OWNER_SUB, SERVER_ID): OwnedServer(id=SERVER_ID, instance_id="i-test", region="us-east-1")}
        self.error = error
        self.calls = []

    def get_owned_server(self, sub, server_id):
        self.calls.append((sub, server_id))
        if self.error:
            raise self.error
        return self.servers.get((sub, server_id))

def verifier():
    v = CognitoVerifier("us-east-1", POOL_ID, CLIENT_ID)
    v.jwks = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=KEY.public_key()))
    return v

def token(sub=OWNER_SUB, key=KEY, **overrides):
    claims = {"sub": sub, "iss": ISSUER, "client_id": CLIENT_ID, "token_use": "access",
              "exp": int(time.time()) + 3600, "iat": int(time.time())}
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})

def auth(tok=None):
    return {"Authorization": f"Bearer {tok or token()}"}

def real_api(repository=None):
    settings = Settings(cognito_user_pool_id=POOL_ID, cognito_client_id=CLIENT_ID,
                        db_cluster_arn="arn:cluster", db_secret_arn="arn:secret")
    return TestClient(create_app(settings, verifier=verifier(), repository=repository or FakeRepository()))

def aws_instance(monkeypatch, state="running", ip="203.0.113.10"):
    client = Mock()
    client.describe_instances.return_value = {
        "Reservations": [{"Instances": [{"State": {"Name": state}, "PublicIpAddress": ip}]}]}
    client.start_instances.return_value = {"StartingInstances": [{"CurrentState": {"Name": "pending"}}]}
    client.stop_instances.return_value = {"StoppingInstances": [{"CurrentState": {"Name": "stopping"}}]}
    monkeypatch.setattr(ec2, "ec2", client)
    return client

# --- Health, docs, configuration ---

@pytest.mark.parametrize("mode", [False, True])
def test_health_without_aws(mode):
    with TestClient(create_app(Settings(mock_mode=mode))) as api:
        assert api.get("/health").json() == {"status": "ok", "mock_mode": mode}

def test_docs_and_scope():
    with TestClient(create_app(Settings(mock_mode=True))) as api:
        assert api.get("/docs").status_code == 200
        assert set(api.get("/openapi.json").json()["paths"]) == {
            "/health", "/servers/{server_id}/status",
            "/servers/{server_id}/start", "/servers/{server_id}/stop"}

def test_environment_configuration(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("COGNITO_USER_POOL_ID", POOL_ID)
    monkeypatch.setenv("COGNITO_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("DB_CLUSTER_ARN", "arn:cluster")
    monkeypatch.setenv("DB_SECRET_ARN", "arn:secret")
    monkeypatch.delenv("DB_NAME", raising=False)
    settings = Settings.from_env()
    assert (settings.aws_region, settings.mock_mode) == ("us-west-2", False)
    assert (settings.cognito_user_pool_id, settings.cognito_client_id) == (POOL_ID, CLIENT_ID)
    assert (settings.db_cluster_arn, settings.db_secret_arn, settings.db_name) == ("arn:cluster", "arn:secret", "mcec2")

def test_invalid_mock_mode(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "maybe")
    with pytest.raises(ValueError):
        Settings.from_env()

def test_frontend_and_routes_coexist():
    api = TestClient(create_app(Settings(mock_mode=True)))
    assert 'id="start"' in api.get("/").text
    assert api.get("/health").status_code == 200
    assert api.get("/servers/demo-server/status").status_code == 200

# --- Mock mode (no Cognito, no database, no AWS) ---

@pytest.mark.parametrize("server,state,ready,address", [
    ("demo-server", "running", True, "203.0.113.10:25565"),
    ("demo-starting", "running", False, "203.0.113.11:25565"),
    ("demo-stopped", "stopped", False, None)])
def test_mock_status(server, state, ready, address):
    api = TestClient(create_app(Settings(mock_mode=True)))
    assert api.get(f"/servers/{server}/status").json() == {
        "server_id": server, "instance_state": state, "minecraft_ready": ready, "connection_address": address}

@pytest.mark.parametrize("action,server,expected", [
    ("start", "demo-stopped", "pending"), ("start", "demo-server", "running"),
    ("stop", "demo-server", "stopping"), ("stop", "demo-stopped", "stopped")])
def test_mock_start_stop(action, server, expected):
    response = TestClient(create_app(Settings(mock_mode=True))).post(f"/servers/{server}/{action}")
    assert response.status_code == 202
    assert response.json() == {"server_id": server, "instance_state": expected}

@pytest.mark.parametrize("method,path", [("get", "/servers/unknown/status"), ("post", "/servers/unknown/start")])
def test_mock_unknown_server(method, path):
    assert getattr(TestClient(create_app(Settings(mock_mode=True))), method)(path).status_code == 404

# --- Authentication ---

@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": "Basic dXNlcjpwYXNz"},
    {"Authorization": "Bearer not-a-jwt"},
    auth(token(exp=int(time.time()) - 60)),                     # expired
    auth(token(key=OTHER_KEY)),                                 # wrong signing key
    auth(token(iss="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Other")),
    auth(token(client_id="other-client")),
    auth(token(token_use="id")),                                # ID token instead of access token
    auth(token(client_id=None)),                                # required claim missing
])
@pytest.mark.parametrize("method,path", [
    ("get", f"/servers/{SERVER_ID}/status"),
    ("post", f"/servers/{SERVER_ID}/start"),
    ("post", f"/servers/{SERVER_ID}/stop")])
def test_rejects_bad_tokens_before_db_or_aws(method, path, headers):
    repository = FakeRepository()
    response = getattr(real_api(repository), method)(path, headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert repository.calls == []

def test_fails_closed_without_cognito_config():
    api = TestClient(create_app(Settings(), repository=FakeRepository()))
    assert api.get(f"/servers/{SERVER_ID}/status", headers=auth()).status_code == 503

# --- Ownership ---

@pytest.mark.parametrize("method,path", [
    ("get", f"/servers/{SERVER_ID}/status"),
    ("post", f"/servers/{SERVER_ID}/start"),
    ("post", f"/servers/{SERVER_ID}/stop")])
def test_valid_token_without_ownership_never_reaches_aws(method, path):
    # Valid Cognito user with no matching identity/server rows: 404, and forbid_network proves no AWS call.
    repository = FakeRepository()
    response = getattr(real_api(repository), method)(path, headers=auth(token(sub="stranger")))
    assert response.status_code == 404
    assert repository.calls == [("stranger", SERVER_ID)]

def test_server_without_instance_conflicts():
    repository = FakeRepository({(OWNER_SUB, SERVER_ID): OwnedServer(SERVER_ID, None, "us-east-1")})
    assert real_api(repository).post(f"/servers/{SERVER_ID}/start", headers=auth()).status_code == 409

@pytest.mark.parametrize("retry_after,header", [(15, "15"), (None, None)])
def test_database_unavailable(retry_after, header):
    repository = FakeRepository(error=DatabaseUnavailable(retry_after=retry_after))
    response = real_api(repository).get(f"/servers/{SERVER_ID}/status", headers=auth())
    assert response.status_code == 503
    assert response.headers.get("Retry-After") == header

def test_database_not_configured():
    settings = Settings(cognito_user_pool_id=POOL_ID, cognito_client_id=CLIENT_ID)
    api = TestClient(create_app(settings, verifier=verifier()))
    assert api.get(f"/servers/{SERVER_ID}/status", headers=auth()).status_code == 503

# --- Status (owner) ---

@pytest.mark.parametrize("failure", [TimeoutError("timeout"), ConnectionRefusedError("starting"), EOFError()])
def test_running_minecraft_not_ready(monkeypatch, failure):
    client = aws_instance(monkeypatch)
    minecraft = Mock()
    minecraft.status.side_effect = failure
    factory = Mock(return_value=minecraft)
    monkeypatch.setattr(ec2, "JavaServer", factory)
    response = real_api().get(f"/servers/{SERVER_ID}/status", headers=auth())
    assert response.status_code == 200
    assert response.json() == {"server_id": SERVER_ID, "instance_state": "running",
                               "minecraft_ready": False, "connection_address": "203.0.113.10:25565"}
    client.describe_instances.assert_called_once_with(InstanceIds=["i-test"])
    factory.assert_called_once_with("203.0.113.10", 25565, timeout=3)
    minecraft.status.assert_called_once_with(tries=1)

def test_ready_and_address_refresh(monkeypatch):
    client = aws_instance(monkeypatch)
    minecraft = Mock()
    minecraft.status.return_value = SimpleNamespace(
        players=SimpleNamespace(online=0, max=20), version=SimpleNamespace(name="1.21"))
    monkeypatch.setattr(ec2, "JavaServer", Mock(return_value=minecraft))
    api = real_api()
    assert api.get(f"/servers/{SERVER_ID}/status", headers=auth()).json()["minecraft_ready"] is True
    client.describe_instances.return_value["Reservations"][0]["Instances"][0]["PublicIpAddress"] = "203.0.113.20"
    assert api.get(f"/servers/{SERVER_ID}/status", headers=auth()).json()["connection_address"] == "203.0.113.20:25565"
    assert client.describe_instances.call_count == 2

@pytest.mark.parametrize("state,ip", [("running", None), ("stopped", None), ("pending", "203.0.113.10")])
def test_unavailable_address(monkeypatch, state, ip):
    aws_instance(monkeypatch, state, ip)
    response = real_api().get(f"/servers/{SERVER_ID}/status", headers=auth())
    assert response.status_code == 200
    assert response.json()["connection_address"] is None
    assert response.json()["minecraft_ready"] is False

@pytest.mark.parametrize("error", [
    NoCredentialsError(), EndpointConnectionError(endpoint_url="https://ec2.example"),
    ReadTimeoutError(endpoint_url="https://ec2.example"),
    ClientError({"Error": {"Code": "UnauthorizedOperation", "Message": "private detail"}}, "DescribeInstances"),
    ClientError({"Error": {"Code": "InvalidInstanceID.NotFound"}}, "DescribeInstances")])
def test_aws_failures(monkeypatch, error):
    client = aws_instance(monkeypatch)
    client.describe_instances.side_effect = error
    response = real_api().get(f"/servers/{SERVER_ID}/status", headers=auth())
    assert response.status_code == 502
    assert "Unable to reach EC2" in response.json()["detail"]
    assert "private detail" not in response.text

# --- Start / stop (owner) ---

def test_owner_starts_stopped_server(monkeypatch):
    client = aws_instance(monkeypatch, "stopped", None)
    response = real_api().post(f"/servers/{SERVER_ID}/start", headers=auth())
    assert response.status_code == 202
    assert response.json() == {"server_id": SERVER_ID, "instance_state": "pending"}
    client.start_instances.assert_called_once_with(InstanceIds=["i-test"])

def test_owner_stops_running_server(monkeypatch):
    client = aws_instance(monkeypatch, "running")
    response = real_api().post(f"/servers/{SERVER_ID}/stop", headers=auth())
    assert response.status_code == 202
    assert response.json()["instance_state"] == "stopping"
    client.stop_instances.assert_called_once_with(InstanceIds=["i-test"])

@pytest.mark.parametrize("action,state", [("start", "running"), ("start", "pending"), ("stop", "stopped"), ("stop", "stopping")])
def test_repeated_requests_are_noops(monkeypatch, action, state):
    client = aws_instance(monkeypatch, state)
    response = real_api().post(f"/servers/{SERVER_ID}/{action}", headers=auth())
    assert response.status_code == 202
    assert response.json()["instance_state"] == state
    client.start_instances.assert_not_called()
    client.stop_instances.assert_not_called()

@pytest.mark.parametrize("action,state", [("start", "stopping"), ("stop", "pending")])
def test_conflicting_transitions(monkeypatch, action, state):
    aws_instance(monkeypatch, state)
    response = real_api().post(f"/servers/{SERVER_ID}/{action}", headers=auth())
    assert response.status_code == 409

def test_start_aws_failure(monkeypatch):
    client = aws_instance(monkeypatch, "stopped", None)
    client.start_instances.side_effect = ClientError({"Error": {"Code": "UnauthorizedOperation"}}, "StartInstances")
    assert real_api().post(f"/servers/{SERVER_ID}/start", headers=auth()).status_code == 502

def test_start_uses_server_region(monkeypatch):
    monkeypatch.setattr(ec2, "ec2", None)
    factory = Mock()
    factory.return_value.describe_instances.return_value = {
        "Reservations": [{"Instances": [{"State": {"Name": "stopped"}}]}]}
    factory.return_value.start_instances.return_value = {"StartingInstances": [{"CurrentState": {"Name": "pending"}}]}
    monkeypatch.setattr(ec2.boto3, "client", factory)
    repository = FakeRepository({(OWNER_SUB, SERVER_ID): OwnedServer(SERVER_ID, "i-test", "us-west-2")})
    assert real_api(repository).post(f"/servers/{SERVER_ID}/start", headers=auth()).status_code == 202
    assert {c.kwargs["region_name"] for c in factory.call_args_list} == {"us-west-2"}

def test_client_region_and_bounded_timeouts(monkeypatch):
    monkeypatch.setattr(ec2, "ec2", None)
    factory = Mock()
    monkeypatch.setattr(ec2.boto3, "client", factory)
    ec2.get_client("us-west-2")
    kwargs = factory.call_args.kwargs
    assert kwargs["region_name"] == "us-west-2"
    assert kwargs["config"].connect_timeout == 3
    assert kwargs["config"].read_timeout == 5
    assert kwargs["config"].retries == {"total_max_attempts": 1}
    assert "aws_access_key_id" not in kwargs
