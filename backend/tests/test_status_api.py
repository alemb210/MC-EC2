import json
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import jwt
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError, ReadTimeoutError
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
import cognito
import ec2
import player_access
import app as app_module
from app import create_app
from auth import CognitoVerifier
from config import Settings
from db import AdminLimitReached, DatabaseUnavailable, OwnedServer, ServerLimitReached, ServerRow

POOL_ID = "us-east-1_TestPool"
CLIENT_ID = "test-client-id"
ISSUER = f"https://cognito-idp.us-east-1.amazonaws.com/{POOL_ID}"
OWNER_SUB = "owner-sub"
SERVER_ID = "3f2a6c1e-0000-4000-8000-000000000001"
NEW_SERVER_ID = "3f2a6c1e-0000-4000-8000-000000000002"
TEMPLATE_ID = "lt-0123456789abcdef0"
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

    def get_server_for_user(self, sub, server_id):
        self.calls.append((sub, server_id))
        if self.error:
            raise self.error
        return self.servers.get((sub, server_id))

    def list_servers(self, sub):
        self.calls.append(("list", sub))
        if self.error:
            raise self.error
        return [ServerRow(s.id, s.region, "LATEST", "t4g.small", s.instance_id is not None, s.name or "Survival", s.role)
                for (owner, _), s in self.servers.items() if owner == sub]

    def rename_server(self, server_id, name):
        self.calls.append(("rename_server", server_id, name))
        self.servers = {key: replace(s, name=name) if s.id == server_id else s for key, s in self.servers.items()}

    def delete_server(self, server_id):
        self.calls.append(("delete_server", server_id))
        if self.delete_error:
            raise self.delete_error
        self.servers = {key: s for key, s in self.servers.items() if s.id != server_id}

    def server_exists(self, server_id):
        return not self.deleted_during_launch

    def list_admins(self, server_id):
        self.calls.append(("list_admins", server_id))
        return [{"user_id": user_id, "email": email} for user_id, email in self.admins.items()]

    def add_admin(self, server_id, user_id, email, max_admins):
        self.calls.append(("add_admin", server_id, user_id, email, max_admins))
        if self.admin_limit_reached:
            raise AdminLimitReached
        self.admins = {**self.admins, user_id: email}

    def remove_admin(self, server_id, user_id):
        self.calls.append(("remove_admin", server_id, user_id))
        existed = user_id in self.admins
        self.admins = {k: v for k, v in self.admins.items() if k != user_id}
        return existed

    # Registration and server creation, keyed by sub (user_id is "user-<sub>").
    registered = ()
    pending = None
    limit_reached = False
    attach_error = None
    delete_error = None
    deleted_during_launch = False
    admins = {}
    admin_limit_reached = False

    def ensure_user(self, sub):
        self.calls.append(("ensure_user", sub))
        if self.error:
            raise self.error
        created = sub not in self.registered
        self.registered = (*self.registered, sub)
        return f"user-{sub}", created

    def reserve_server(self, user_id, region, version, max_per_user, max_total, name="Minecraft server"):
        self.calls.append(("reserve_server", user_id, region, version, max_per_user, max_total))
        if self.limit_reached:
            raise ServerLimitReached
        self.pending = self.pending or OwnedServer(NEW_SERVER_ID, None, region, name)
        return self.pending

    def attach_instance(self, server_id, instance_id, instance_type):
        self.calls.append(("attach_instance", server_id, instance_id, instance_type))
        if self.attach_error:
            raise self.attach_error
        self.pending = None

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

def real_api(repository=None, **overrides):
    settings = Settings(cognito_user_pool_id=POOL_ID, cognito_client_id=CLIENT_ID,
                        db_cluster_arn="arn:cluster", db_secret_arn="arn:secret",
                        **{"launch_template_id": TEMPLATE_ID, **overrides})
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
            "/health", "/me", "/servers", "/servers/{server_id}", "/servers/{server_id}/status",
            "/servers/{server_id}/start", "/servers/{server_id}/stop", "/servers/{server_id}/access",
            "/servers/{server_id}/admins", "/servers/{server_id}/admins/{user_id}"}

def test_environment_configuration(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("COGNITO_USER_POOL_ID", POOL_ID)
    monkeypatch.setenv("COGNITO_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("DB_CLUSTER_ARN", "arn:cluster")
    monkeypatch.setenv("DB_SECRET_ARN", "arn:secret")
    monkeypatch.delenv("DB_NAME", raising=False)
    monkeypatch.setenv("LAUNCH_TEMPLATE_ID", TEMPLATE_ID)
    monkeypatch.setenv("MAX_SERVERS_TOTAL", "5")
    monkeypatch.delenv("MAX_SERVERS_PER_USER", raising=False)
    settings = Settings.from_env()
    assert (settings.launch_template_id, settings.max_servers_per_user, settings.max_servers_total) == (TEMPLATE_ID, 1, 5)
    assert (settings.aws_region, settings.mock_mode) == ("us-west-2", False)
    assert (settings.cognito_user_pool_id, settings.cognito_client_id) == (POOL_ID, CLIENT_ID)
    assert (settings.db_cluster_arn, settings.db_secret_arn, settings.db_name) == ("arn:cluster", "arn:secret", "mcec2")

def test_invalid_mock_mode(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "maybe")
    with pytest.raises(ValueError):
        Settings.from_env()

def test_frontend_and_routes_coexist():
    api = TestClient(create_app(Settings(mock_mode=True)))
    assert "<title>" in api.get("/").text
    assert api.get("/health").status_code == 200
    assert api.get("/servers/demo-server/status").status_code == 200

def test_frontend_not_built_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "FRONTEND_DIR", tmp_path / "missing")
    response = TestClient(create_app(Settings(mock_mode=True))).get("/")
    assert response.status_code == 200
    assert "npm run build" in response.text

def test_frontend_built_is_served(monkeypatch, tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>built</title>")
    monkeypatch.setattr(app_module, "FRONTEND_DIR", tmp_path)
    assert "built" in TestClient(create_app(Settings(mock_mode=True))).get("/").text

# --- Mock mode (no Cognito, no database, no AWS) ---

NO_PLAYERS = {"players_online": None, "players_max": None, "minecraft_version": None, "auto_stop_at": None}

@pytest.mark.parametrize("server,state,ready,address,players", [
    ("demo-server", "running", True, "203.0.113.10:25565",
     {"players_online": 2, "players_max": 20, "minecraft_version": "1.21.4", "auto_stop_at": None}),
    ("demo-starting", "running", False, "203.0.113.11:25565", NO_PLAYERS),
    ("demo-stopped", "stopped", False, None, NO_PLAYERS)])
def test_mock_status(server, state, ready, address, players):
    api = TestClient(create_app(Settings(mock_mode=True)))
    assert api.get(f"/servers/{server}/status").json() == {
        "server_id": server, "instance_state": state, "minecraft_ready": ready,
        "provisioning_state": "instance_assigned",
        "connection_address": address, **players}

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
    auth(token(sub="")),
    auth(token(sub=" ")),
])
@pytest.mark.parametrize("method,path", [
    ("post", "/me"),
    ("get", f"/servers/{SERVER_ID}/status"),
    ("post", f"/servers/{SERVER_ID}/start"),
    ("post", f"/servers/{SERVER_ID}/stop"),
    ("get", "/servers"),
    ("post", "/servers"),
    ("patch", f"/servers/{SERVER_ID}"),
    ("delete", f"/servers/{SERVER_ID}"),
    ("get", f"/servers/{SERVER_ID}/access"),
    ("put", f"/servers/{SERVER_ID}/access"),
    ("get", f"/servers/{SERVER_ID}/admins"),
    ("post", f"/servers/{SERVER_ID}/admins"),
    ("delete", f"/servers/{SERVER_ID}/admins/me")])
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


def test_unfinished_launch_status_is_visible_only_to_owner_and_recovers(monkeypatch):
    repository = FakeRepository({(OWNER_SUB, SERVER_ID): OwnedServer(SERVER_ID, None, "us-east-1")})
    api = real_api(repository)
    response = api.get(f"/servers/{SERVER_ID}/status", headers=auth())
    assert response.status_code == 200
    assert response.json() == {
        "server_id": SERVER_ID, "provisioning_state": "awaiting_instance", "instance_state": None,
        "minecraft_ready": False, "connection_address": None, **NO_PLAYERS,
    }
    # No AWS call is possible under the autouse network guard above.
    assert api.get(f"/servers/{SERVER_ID}/status", headers=auth(token(sub="stranger"))).status_code == 404
    assert api.post(f"/servers/{SERVER_ID}/stop", headers=auth()).status_code == 409

    repository.servers[(OWNER_SUB, SERVER_ID)] = OwnedServer(SERVER_ID, "i-test", "us-east-1")
    aws_instance(monkeypatch, state="stopped", ip=None)
    assigned = api.get(f"/servers/{SERVER_ID}/status", headers=auth()).json()
    assert (assigned["provisioning_state"], assigned["instance_state"]) == ("instance_assigned", "stopped")

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
                               "provisioning_state": "instance_assigned",
                               "minecraft_ready": False, "connection_address": "203.0.113.10:25565",
                               **NO_PLAYERS}
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
    body = api.get(f"/servers/{SERVER_ID}/status", headers=auth()).json()
    assert body["minecraft_ready"] is True
    assert (body["players_online"], body["players_max"], body["minecraft_version"]) == (0, 20, "1.21")
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
    assert response.json()["players_online"] is None

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

# --- Registration (POST /me) and through listing ---

def test_listing_registers_user():
    repository = FakeRepository()
    api = real_api(repository)
    assert api.get("/servers", headers=auth()).status_code == 200
    assert api.get("/servers", headers=auth()).status_code == 200
    assert repository.registered == (OWNER_SUB, OWNER_SUB)
    assert repository.calls == [("ensure_user", OWNER_SUB), ("list", OWNER_SUB)] * 2


def test_register_creates_then_returns_user():
    repository = FakeRepository()
    api = real_api(repository)
    first = api.post("/me", headers=auth())
    assert (first.status_code, first.json()) == (201, {"user_id": f"user-{OWNER_SUB}", "created": True})
    second = api.post("/me", headers=auth())
    assert (second.status_code, second.json()) == (200, {"user_id": f"user-{OWNER_SUB}", "created": False})
    assert repository.calls == [("ensure_user", OWNER_SUB)] * 2


@pytest.mark.parametrize("retry_after,header", [(15, "15"), (None, None)])
def test_register_database_unavailable(retry_after, header):
    response = real_api(FakeRepository(error=DatabaseUnavailable(retry_after))).post("/me", headers=auth())
    assert response.status_code == 503
    assert response.headers.get("Retry-After") == header


def test_register_mock_mode():
    response = TestClient(create_app(Settings(mock_mode=True))).post("/me")
    assert response.status_code == 200
    assert response.json()["created"] is False

# --- Listing (GET /servers) ---

def test_list_returns_only_the_callers_servers():
    repository = FakeRepository({
        (OWNER_SUB, SERVER_ID): OwnedServer(SERVER_ID, "i-test", "us-east-1"),
        (OWNER_SUB, NEW_SERVER_ID): OwnedServer(NEW_SERVER_ID, None, "us-east-1"),
        ("stranger", "other"): OwnedServer("other", "i-other", "us-east-1")})
    response = real_api(repository).get("/servers", headers=auth())
    assert response.status_code == 200
    assert response.json() == [
        {"server_id": SERVER_ID, "name": "Survival", "role": "owner", "region": "us-east-1",
         "minecraft_version": "LATEST", "instance_type": "t4g.small", "has_instance": True},
        {"server_id": NEW_SERVER_ID, "name": "Survival", "role": "owner", "region": "us-east-1",
         "minecraft_version": "LATEST", "instance_type": "t4g.small", "has_instance": False}]
    assert "i-test" not in response.text  # EC2 instance IDs are never exposed
    assert repository.calls == [("ensure_user", OWNER_SUB), ("list", OWNER_SUB)]

def test_list_empty_for_new_user():
    response = real_api().get("/servers", headers=auth(token(sub="new-user")))
    assert (response.status_code, response.json()) == (200, [])

@pytest.mark.parametrize("retry_after,header", [(15, "15"), (None, None)])
def test_list_database_unavailable(retry_after, header):
    response = real_api(FakeRepository(error=DatabaseUnavailable(retry_after))).get("/servers", headers=auth())
    assert response.status_code == 503
    assert response.headers.get("Retry-After") == header

def test_list_mock_mode():
    response = TestClient(create_app(Settings(mock_mode=True))).get("/servers")
    assert [(s["server_id"], s["role"]) for s in response.json()] == [
        ("demo-server", "owner"), ("demo-starting", "owner"), ("demo-stopped", "owner"), ("demo-shared", "admin")]

# --- Server creation (POST /servers) ---

def launch_client(monkeypatch, existing=None):
    client = Mock()
    client.describe_instances.return_value = {"Reservations": [{"Instances": existing}] if existing else []}
    client.run_instances.return_value = {"Instances": [
        {"InstanceId": "i-new", "State": {"Name": "pending"}, "InstanceType": "t4g.small"}]}
    monkeypatch.setattr(ec2, "ec2", client)
    return client

def test_create_server_launches_from_template(monkeypatch):
    client = launch_client(monkeypatch)
    repository = FakeRepository()
    response = real_api(repository).post("/servers", headers=auth())
    assert response.status_code == 201
    assert response.json() == {"server_id": NEW_SERVER_ID, "name": "Minecraft server",
                               "instance_state": "pending", "region": "us-east-1",
                               "minecraft_version": "LATEST", "instance_type": "t4g.small"}
    kwargs = client.run_instances.call_args.kwargs
    assert kwargs["LaunchTemplate"] == {"LaunchTemplateId": TEMPLATE_ID, "Version": "$Default"}
    assert (kwargs["MinCount"], kwargs["MaxCount"], kwargs["ClientToken"]) == (1, 1, NEW_SERVER_ID)
    for spec in kwargs["TagSpecifications"]:
        tags = {t["Key"]: t["Value"] for t in spec["Tags"]}
        assert (tags["Project"], tags["ServerId"]) == ("mc-ec2", NEW_SERVER_ID)
    assert {s["ResourceType"] for s in kwargs["TagSpecifications"]} == {"instance", "volume"}
    assert repository.calls == [
        ("ensure_user", OWNER_SUB),
        ("reserve_server", f"user-{OWNER_SUB}", "us-east-1", "LATEST", 1, 3),
        ("attach_instance", NEW_SERVER_ID, "i-new", "t4g.small")]

def test_create_server_passes_configured_limits(monkeypatch):
    launch_client(monkeypatch)
    repository = FakeRepository()
    real_api(repository, max_servers_per_user=2, max_servers_total=10).post("/servers", headers=auth())
    assert repository.calls[1][-2:] == (2, 10)

def test_create_server_limit_reached_never_launches(monkeypatch):
    client = launch_client(monkeypatch)
    repository = FakeRepository()
    repository.limit_reached = True
    response = real_api(repository).post("/servers", headers=auth())
    assert response.status_code == 409
    client.run_instances.assert_not_called()
    client.describe_instances.assert_not_called()

def test_create_server_not_configured_touches_nothing():
    repository = FakeRepository()
    response = real_api(repository, launch_template_id=None).post("/servers", headers=auth())
    assert response.status_code == 503
    assert repository.calls == []

def test_create_server_mock_mode():
    assert TestClient(create_app(Settings(mock_mode=True))).post("/servers").status_code == 409

def test_failed_launch_is_retried_on_the_same_server(monkeypatch):
    client = launch_client(monkeypatch)
    client.run_instances.side_effect = [
        ClientError({"Error": {"Code": "InsufficientInstanceCapacity", "Message": "private detail"}}, "RunInstances"),
        client.run_instances.return_value]
    repository = FakeRepository()
    api = real_api(repository)
    failed = api.post("/servers", headers=auth())
    assert failed.status_code == 502
    assert "private detail" not in failed.text
    assert api.post("/servers", headers=auth()).json()["server_id"] == NEW_SERVER_ID
    assert [c.kwargs["ClientToken"] for c in client.run_instances.call_args_list] == [NEW_SERVER_ID] * 2

def test_launched_but_unrecorded_instance_is_reattached(monkeypatch):
    # The instance launched but saving its ID failed; the retry finds it by tag instead of launching again.
    client = launch_client(monkeypatch)
    repository = FakeRepository()
    repository.attach_error = DatabaseUnavailable(retry_after=15)
    api = real_api(repository)
    assert api.post("/servers", headers=auth()).status_code == 503
    repository.attach_error = None
    client.describe_instances.return_value = {"Reservations": [{"Instances": [
        {"InstanceId": "i-new", "State": {"Name": "running"}, "InstanceType": "t4g.small"}]}]}
    response = api.post("/servers", headers=auth())
    assert (response.status_code, response.json()["instance_state"]) == (201, "running")
    client.run_instances.assert_called_once()
    assert repository.calls[-1] == ("attach_instance", NEW_SERVER_ID, "i-new", "t4g.small")
    filters = client.describe_instances.call_args.kwargs["Filters"]
    assert {"Name": "tag:ServerId", "Values": [NEW_SERVER_ID]} in filters

# --- Permissions: every server route for owner, admin and stranger ---

ADMIN_SUB = "admin-sub"
OWNER_ONLY = "owner-only"

def role_repository():
    return FakeRepository({
        (OWNER_SUB, SERVER_ID): OwnedServer(SERVER_ID, "i-test", "us-east-1"),
        (ADMIN_SUB, SERVER_ID): OwnedServer(SERVER_ID, "i-test", "us-east-1", role="admin")})

ROUTES = [
    ("get", f"/servers/{SERVER_ID}/status", None, 200, 200),
    ("post", f"/servers/{SERVER_ID}/start", None, 202, 202),
    ("post", f"/servers/{SERVER_ID}/stop", None, 202, 202),
    ("patch", f"/servers/{SERVER_ID}", {"name": "New"}, 200, 200),
    ("get", f"/servers/{SERVER_ID}/access", None, 200, 200),
    ("put", f"/servers/{SERVER_ID}/access", {"mode": "public", "players": []}, 200, 200),
    ("delete", f"/servers/{SERVER_ID}", None, 204, 403),
    ("get", f"/servers/{SERVER_ID}/admins", None, 200, 403),
    ("post", f"/servers/{SERVER_ID}/admins", {"email": "friend@example.com"}, 201, 403),
    ("delete", f"/servers/{SERVER_ID}/admins/{NEW_SERVER_ID}", None, 204, 403),
]

@pytest.fixture
def stub_aws(monkeypatch):
    """AWS stand-ins for routes that reach it; returns the EC2 client."""
    client = aws_instance(monkeypatch, "running")
    client.describe_instances.side_effect = lambda **kw: (
        {"Reservations": []} if "Filters" in kw else
        {"Reservations": [{"Instances": [{"State": {"Name": "stopped"}, "PublicIpAddress": None}]}]})
    ssm = Mock()
    ssm.get_parameter.side_effect = ClientError({"Error": {"Code": "ParameterNotFound"}}, "GetParameter")
    monkeypatch.setattr(player_access, "ssm", ssm)
    monkeypatch.setattr(player_access, "unknown_players", lambda names: [])
    pool = Mock()
    pool.list_users.return_value = {"Users": [
        {"Enabled": True, "UserStatus": "CONFIRMED", "Attributes": [{"Name": "sub", "Value": "friend-sub"}]}]}
    monkeypatch.setattr(cognito, "client", pool)
    monkeypatch.setattr(ec2, "ping_minecraft", lambda ip: None)
    client.ssm = ssm
    return client

@pytest.mark.parametrize("method,path,body,owner_status,admin_status", ROUTES)
def test_permission_matrix(stub_aws, method, path, body, owner_status, admin_status):
    kwargs = {"json": body} if body else {}
    def call(sub, repo=None):
        repository = repo or role_repository()
        repository.admins = {NEW_SERVER_ID: "friend@example.com"}
        return getattr(real_api(repository), method)(path, headers=auth(token(sub=sub)), **kwargs).status_code

    assert call(OWNER_SUB) == owner_status
    assert call(ADMIN_SUB) == admin_status

    # A stranger, or an admin refused an owner-only action, makes no AWS change.
    stub_aws.reset_mock()
    assert call("stranger") == 404
    if admin_status == 403:
        assert call(ADMIN_SUB) == 403
    stub_aws.start_instances.assert_not_called()
    stub_aws.stop_instances.assert_not_called()
    stub_aws.terminate_instances.assert_not_called()
    stub_aws.ssm.put_parameter.assert_not_called()
    stub_aws.ssm.delete_parameter.assert_not_called()
    cognito.client.list_users.reset_mock()

def test_every_server_route_is_in_the_permission_matrix():
    paths = create_app(Settings(mock_mode=True)).openapi()["paths"]
    documented = {(method, path) for path, ops in paths.items() for method in ops if path.startswith("/servers/")}
    tested = {(m, p.replace(SERVER_ID, "{server_id}").replace(NEW_SERVER_ID, "{user_id}")) for m, p, *_ in ROUTES}
    assert documented == tested

# --- Names ---

def test_create_server_with_name(monkeypatch):
    launch_client(monkeypatch)
    response = real_api(FakeRepository()).post("/servers", headers=auth(), json={"name": "  Survival  "})
    assert response.status_code == 201
    assert response.json()["name"] == "Survival"

@pytest.mark.parametrize("name", ["", "   ", "x" * 33, "bad\nname", "bad\x7fname", None, 5])
def test_invalid_names_rejected_before_any_change(monkeypatch, name):
    client = launch_client(monkeypatch)
    repository = FakeRepository()
    api = real_api(repository)
    assert api.patch(f"/servers/{SERVER_ID}", headers=auth(), json={"name": name}).status_code == 422
    if name is not None:
        assert api.post("/servers", headers=auth(), json={"name": name}).status_code == 422
    client.run_instances.assert_not_called()
    assert repository.calls == []

def test_rename_returns_updated_summary():
    repository = FakeRepository()
    response = real_api(repository).patch(f"/servers/{SERVER_ID}", headers=auth(), json={"name": "New name"})
    assert response.status_code == 200
    assert (response.json()["server_id"], response.json()["name"]) == (SERVER_ID, "New name")
    assert ("rename_server", SERVER_ID, "New name") in repository.calls

def test_mock_rename():
    response = TestClient(create_app(Settings(mock_mode=True))).patch("/servers/demo-server", json={"name": "New"})
    assert (response.status_code, response.json()["name"]) == (200, "New")

# --- Deletion ---

def delete_client(monkeypatch, tagged=()):
    client = Mock()
    client.describe_instances.return_value = {
        "Reservations": [{"Instances": [{"InstanceId": i} for i in tagged]}] if tagged else []}
    monkeypatch.setattr(ec2, "ec2", client)
    ssm = Mock()
    monkeypatch.setattr(player_access, "ssm", ssm)
    client.ssm = ssm
    return client

def test_delete_terminates_then_removes_row(monkeypatch):
    client = delete_client(monkeypatch)
    repository = FakeRepository()
    response = real_api(repository).delete(f"/servers/{SERVER_ID}", headers=auth())
    assert (response.status_code, response.content) == (204, b"")
    client.terminate_instances.assert_called_once_with(InstanceIds=["i-test"])
    client.ssm.delete_parameter.assert_called_once_with(Name=f"/mc-ec2/servers/{SERVER_ID}/access")
    assert repository.calls[-1] == ("delete_server", SERVER_ID)
    assert repository.servers == {}

def test_delete_row_without_instance_finds_unrecorded_launch(monkeypatch):
    client = delete_client(monkeypatch, tagged=["i-unrecorded"])
    repository = FakeRepository({(OWNER_SUB, SERVER_ID): OwnedServer(SERVER_ID, None, "us-east-1")})
    assert real_api(repository).delete(f"/servers/{SERVER_ID}", headers=auth()).status_code == 204
    client.terminate_instances.assert_called_once_with(InstanceIds=["i-unrecorded"])

def test_delete_row_with_nothing_launched(monkeypatch):
    client = delete_client(monkeypatch)
    repository = FakeRepository({(OWNER_SUB, SERVER_ID): OwnedServer(SERVER_ID, None, "us-east-1")})
    assert real_api(repository).delete(f"/servers/{SERVER_ID}", headers=auth()).status_code == 204
    client.terminate_instances.assert_not_called()
    assert repository.servers == {}

def test_delete_instance_already_gone(monkeypatch):
    client = delete_client(monkeypatch)
    client.terminate_instances.side_effect = ClientError({"Error": {"Code": "InvalidInstanceID.NotFound"}}, "TerminateInstances")
    repository = FakeRepository()
    assert real_api(repository).delete(f"/servers/{SERVER_ID}", headers=auth()).status_code == 204
    assert repository.servers == {}

def test_delete_termination_failure_keeps_row(monkeypatch):
    client = delete_client(monkeypatch)
    client.terminate_instances.side_effect = ClientError(
        {"Error": {"Code": "UnauthorizedOperation", "Message": "private detail"}}, "TerminateInstances")
    repository = FakeRepository()
    response = real_api(repository).delete(f"/servers/{SERVER_ID}", headers=auth())
    assert response.status_code == 502
    assert "private detail" not in response.text
    assert repository.servers != {}

def test_delete_retries_after_database_failure(monkeypatch):
    client = delete_client(monkeypatch)
    repository = FakeRepository()
    repository.delete_error = DatabaseUnavailable(retry_after=15)
    api = real_api(repository)
    assert api.delete(f"/servers/{SERVER_ID}", headers=auth()).status_code == 503
    repository.delete_error = None
    assert api.delete(f"/servers/{SERVER_ID}", headers=auth()).status_code == 204
    assert api.delete(f"/servers/{SERVER_ID}", headers=auth()).status_code == 404
    assert client.terminate_instances.call_count == 2

def test_delete_protected_server_touches_nothing(monkeypatch):
    client = delete_client(monkeypatch)
    repository = FakeRepository()
    api = real_api(repository, protected_server_ids=frozenset([SERVER_ID]))
    assert api.delete(f"/servers/{SERVER_ID}", headers=auth()).status_code == 409
    client.terminate_instances.assert_not_called()
    client.describe_instances.assert_not_called()
    assert repository.servers != {}

def test_protected_servers_from_environment(monkeypatch):
    monkeypatch.setenv("PROTECTED_SERVER_IDS", f"{SERVER_ID},{NEW_SERVER_ID}")
    assert Settings.from_env().protected_server_ids == {SERVER_ID, NEW_SERVER_ID}
    monkeypatch.delenv("PROTECTED_SERVER_IDS")
    assert Settings.from_env().protected_server_ids == frozenset()

def test_server_deleted_during_launch_terminates_new_instance(monkeypatch):
    client = launch_client(monkeypatch)
    repository = FakeRepository()
    repository.deleted_during_launch = True
    assert real_api(repository).post("/servers", headers=auth()).status_code == 404
    client.terminate_instances.assert_called_once_with(InstanceIds=["i-new"])

def test_mock_delete():
    api = TestClient(create_app(Settings(mock_mode=True)))
    assert api.delete("/servers/demo-server").status_code == 204
    assert api.delete("/servers/demo-shared").status_code == 403
    assert api.delete("/servers/unknown").status_code == 404

# --- Auto-stop countdown in /status ---

def test_status_reports_auto_stop_time(monkeypatch):
    client = aws_instance(monkeypatch)
    monkeypatch.setattr(ec2, "ping_minecraft", lambda ip: {"online": 0, "max": 20, "version": "1.21"})
    client.describe_instances.return_value["Reservations"][0]["Instances"][0].update(
        LaunchTime=datetime(2026, 11, 1, 11, 0, tzinfo=timezone.utc),
        Tags=[{"Key": "IdleSince", "Value": "2026-11-01T12:00:00Z"}])
    body = real_api(auto_stop_idle_minutes=30).get(f"/servers/{SERVER_ID}/status", headers=auth()).json()
    assert datetime.fromisoformat(body["auto_stop_at"].replace("Z", "+00:00")) == datetime(2026, 11, 1, 12, 30, tzinfo=timezone.utc)

@pytest.mark.parametrize("instance,minutes", [
    ({}, 30),                                                                    # no tag
    ({"Tags": [{"Key": "IdleSince", "Value": "not a time"}]}, 30),               # bad tag
    ({"LaunchTime": datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc),           # tag from before the last start
      "Tags": [{"Key": "IdleSince", "Value": "2026-11-01T12:00:00Z"}]}, 30),
    ({"Tags": [{"Key": "IdleSince", "Value": "2026-11-01T12:00:00Z"}]}, 0)])     # auto-stop off
def test_status_without_auto_stop_time(monkeypatch, instance, minutes):
    client = aws_instance(monkeypatch)
    monkeypatch.setattr(ec2, "ping_minecraft", lambda ip: None)
    client.describe_instances.return_value["Reservations"][0]["Instances"][0].update(instance)
    body = real_api(auto_stop_idle_minutes=minutes).get(f"/servers/{SERVER_ID}/status", headers=auth()).json()
    assert body["auto_stop_at"] is None

def test_mock_status_has_auto_stop_example():
    body = TestClient(create_app(Settings(mock_mode=True))).get("/servers/demo-shared/status").json()
    assert datetime.fromisoformat(body["auto_stop_at"].replace("Z", "+00:00")) > datetime.now(timezone.utc) + timedelta(minutes=5)

# --- Access settings ---

def access_ssm(monkeypatch, saved=None):
    ssm = Mock()
    if saved is None:
        ssm.get_parameter.side_effect = ClientError({"Error": {"Code": "ParameterNotFound"}}, "GetParameter")
    else:
        ssm.get_parameter.return_value = {"Parameter": {"Value": json.dumps(saved)}}
    monkeypatch.setattr(player_access, "ssm", ssm)
    monkeypatch.setattr(player_access, "unknown_players", Mock(return_value=[]))
    return ssm

def saved_value(ssm):
    return json.loads(ssm.put_parameter.call_args.kwargs["Value"])

def test_create_saves_access_before_launch(monkeypatch):
    client = launch_client(monkeypatch)
    ssm = access_ssm(monkeypatch)
    order = Mock()
    order.attach_mock(ssm.put_parameter, "save")
    order.attach_mock(client.run_instances, "launch")
    body = {"name": "Friends", "access": {"mode": "whitelist", "players": ["Steve", "Alex"]}}
    assert real_api().post("/servers", headers=auth(), json=body).status_code == 201
    assert [c[0] for c in order.mock_calls] == ["save", "launch"]
    assert ssm.put_parameter.call_args.kwargs["Name"] == f"/mc-ec2/servers/{NEW_SERVER_ID}/access"
    assert saved_value(ssm) == {"mode": "whitelist", "players": ["Steve", "Alex"]}

def test_create_without_access_is_public_with_no_parameter(monkeypatch):
    launch_client(monkeypatch)
    ssm = access_ssm(monkeypatch)
    assert real_api().post("/servers", headers=auth()).status_code == 201
    ssm.put_parameter.assert_not_called()

def test_failed_access_save_never_launches(monkeypatch):
    client = launch_client(monkeypatch)
    ssm = access_ssm(monkeypatch)
    ssm.put_parameter.side_effect = ClientError({"Error": {"Code": "ThrottlingException"}}, "PutParameter")
    body = {"access": {"mode": "whitelist", "players": []}}
    assert real_api().post("/servers", headers=auth(), json=body).status_code == 502
    client.run_instances.assert_not_called()

def test_create_rejects_unknown_players_before_any_change(monkeypatch):
    client = launch_client(monkeypatch)
    ssm = access_ssm(monkeypatch)
    player_access.unknown_players.return_value = ["Notch2"]
    repository = FakeRepository()
    body = {"access": {"mode": "whitelist", "players": ["Notch2"]}}
    response = real_api(repository).post("/servers", headers=auth(), json=body)
    assert response.status_code == 422
    assert "Notch2" in response.json()["detail"]
    ssm.put_parameter.assert_not_called()
    client.run_instances.assert_not_called()
    assert repository.calls == []

def test_get_access_defaults_to_public(monkeypatch):
    access_ssm(monkeypatch)
    response = real_api().get(f"/servers/{SERVER_ID}/access", headers=auth())
    assert response.json() == {"mode": "public", "players": []}

def test_get_access_returns_saved(monkeypatch):
    access_ssm(monkeypatch, {"mode": "whitelist", "players": ["Steve"]})
    response = real_api().get(f"/servers/{SERVER_ID}/access", headers=auth())
    assert response.json() == {"mode": "whitelist", "players": ["Steve"]}

def test_update_access_on_reachable_server_applies_now(monkeypatch):
    ssm = access_ssm(monkeypatch)
    response = real_api(sync_access_document="mc-ec2-sync-access").put(
        f"/servers/{SERVER_ID}/access", headers=auth(), json={"mode": "whitelist", "players": ["Steve"]})
    assert response.json() == {"mode": "whitelist", "players": ["Steve"], "applied": "applying"}
    # The command carries only the fixed document: no names or shell reach the instance this way.
    ssm.send_command.assert_called_once_with(InstanceIds=["i-test"], DocumentName="mc-ec2-sync-access")

def test_update_access_saved_when_server_unreachable(monkeypatch):
    ssm = access_ssm(monkeypatch)
    ssm.send_command.side_effect = ClientError({"Error": {"Code": "InvalidInstanceId"}}, "SendCommand")
    response = real_api(sync_access_document="mc-ec2-sync-access").put(
        f"/servers/{SERVER_ID}/access", headers=auth(), json={"mode": "public", "players": []})
    assert response.status_code == 200
    assert response.json()["applied"] == "on_next_start"
    ssm.put_parameter.assert_called_once()

def test_update_access_before_instance_exists(monkeypatch):
    ssm = access_ssm(monkeypatch)
    repository = FakeRepository({(OWNER_SUB, SERVER_ID): OwnedServer(SERVER_ID, None, "us-east-1")})
    response = real_api(repository, sync_access_document="doc").put(
        f"/servers/{SERVER_ID}/access", headers=auth(), json={"mode": "public", "players": []})
    assert response.json()["applied"] == "on_next_start"
    ssm.send_command.assert_not_called()

def test_switching_to_public_keeps_names(monkeypatch):
    ssm = access_ssm(monkeypatch, {"mode": "whitelist", "players": ["Steve"]})
    real_api().put(f"/servers/{SERVER_ID}/access", headers=auth(), json={"mode": "public", "players": ["Steve"]})
    assert saved_value(ssm) == {"mode": "public", "players": ["Steve"]}

def test_only_new_names_are_checked_with_mojang(monkeypatch):
    access_ssm(monkeypatch, {"mode": "whitelist", "players": ["Steve"]})
    real_api().put(f"/servers/{SERVER_ID}/access", headers=auth(),
                   json={"mode": "whitelist", "players": ["steve", "Alex"]})
    player_access.unknown_players.assert_called_once_with(["Alex"])

def test_update_access_unknown_player_saves_nothing(monkeypatch):
    ssm = access_ssm(monkeypatch)
    player_access.unknown_players.return_value = ["Nobody"]
    response = real_api().put(f"/servers/{SERVER_ID}/access", headers=auth(),
                              json={"mode": "whitelist", "players": ["Nobody"]})
    assert response.status_code == 422
    ssm.put_parameter.assert_not_called()

@pytest.mark.parametrize("players", [
    ["a;rm -rf /"], ["$(reboot)"], ["two words"], ["ab"], ["x" * 17], ["name\n"], ["../x"], [5],
    [f"player{i}" for i in range(101)]])
def test_invalid_players_rejected_before_any_aws_call(monkeypatch, players):
    ssm = access_ssm(monkeypatch)
    response = real_api().put(f"/servers/{SERVER_ID}/access", headers=auth(),
                              json={"mode": "whitelist", "players": players})
    assert response.status_code == 422
    ssm.get_parameter.assert_not_called()
    ssm.put_parameter.assert_not_called()
    ssm.send_command.assert_not_called()

def test_invalid_mode_rejected(monkeypatch):
    ssm = access_ssm(monkeypatch)
    response = real_api().put(f"/servers/{SERVER_ID}/access", headers=auth(), json={"mode": "open", "players": []})
    assert response.status_code == 422
    ssm.put_parameter.assert_not_called()

def test_duplicate_players_collapse_case_insensitively(monkeypatch):
    ssm = access_ssm(monkeypatch)
    real_api().put(f"/servers/{SERVER_ID}/access", headers=auth(),
                   json={"mode": "whitelist", "players": ["Steve", "Alex", "STEVE"]})
    assert saved_value(ssm)["players"] == ["Steve", "Alex"]

def test_access_aws_failure_hides_details(monkeypatch):
    ssm = access_ssm(monkeypatch)
    ssm.get_parameter.side_effect = ClientError({"Error": {"Code": "AccessDenied", "Message": "private detail"}}, "GetParameter")
    response = real_api().get(f"/servers/{SERVER_ID}/access", headers=auth())
    assert response.status_code == 502
    assert "private detail" not in response.text

def test_mock_access():
    api = TestClient(create_app(Settings(mock_mode=True)))
    assert api.get("/servers/demo-server/access").json() == {"mode": "whitelist", "players": ["Steve", "Alex"]}
    assert api.get("/servers/demo-stopped/access").json() == {"mode": "public", "players": []}
    updated = api.put("/servers/demo-stopped/access", json={"mode": "whitelist", "players": ["Steve"]}).json()
    assert updated == {"mode": "whitelist", "players": ["Steve"], "applied": "applying"}

# --- Admins ---

FRIEND = {"Enabled": True, "UserStatus": "CONFIRMED", "Attributes": [{"Name": "sub", "Value": "friend-sub"}]}

def user_pool(monkeypatch, users=(FRIEND,)):
    pool = Mock()
    pool.list_users.return_value = {"Users": list(users)}
    monkeypatch.setattr(cognito, "client", pool)
    return pool

def test_owner_adds_admin_by_email(monkeypatch):
    pool = user_pool(monkeypatch)
    repository = FakeRepository()
    response = real_api(repository).post(f"/servers/{SERVER_ID}/admins", headers=auth(), json={"email": "friend@example.com"})
    assert response.status_code == 201
    assert response.json() == {"user_id": "user-friend-sub", "email": "friend@example.com"}
    assert pool.list_users.call_args.kwargs == {"UserPoolId": POOL_ID, "Filter": 'email = "friend@example.com"', "Limit": 1}
    assert ("ensure_user", "friend-sub") in repository.calls
    assert ("add_admin", SERVER_ID, "user-friend-sub", "friend@example.com", 5) in repository.calls

def test_add_admin_tries_lowercase_email(monkeypatch):
    pool = user_pool(monkeypatch)
    pool.list_users.side_effect = [{"Users": []}, {"Users": [FRIEND]}]
    response = real_api().post(f"/servers/{SERVER_ID}/admins", headers=auth(), json={"email": "Friend@Example.com"})
    assert response.status_code == 201
    assert [c.kwargs["Filter"] for c in pool.list_users.call_args_list] == [
        'email = "Friend@Example.com"', 'email = "friend@example.com"']

@pytest.mark.parametrize("users", [
    [],
    [{**FRIEND, "UserStatus": "UNCONFIRMED"}],   # hasn't proved they own the email
    [{**FRIEND, "Enabled": False}]])
def test_add_unknown_user(monkeypatch, users):
    user_pool(monkeypatch, users)
    repository = FakeRepository()
    response = real_api(repository).post(f"/servers/{SERVER_ID}/admins", headers=auth(), json={"email": "x@example.com"})
    assert response.status_code == 404
    assert "email" in response.json()["detail"]
    assert not any(c[0] in ("add_admin", "ensure_user") for c in repository.calls)

@pytest.mark.parametrize("email", ["not-an-email", 'a"b@example.com', "a b@example.com", "a\\b@example.com", "x@y@z", ""])
def test_invalid_emails_never_reach_cognito(monkeypatch, email):
    pool = user_pool(monkeypatch)
    response = real_api().post(f"/servers/{SERVER_ID}/admins", headers=auth(), json={"email": email})
    assert response.status_code == 422
    pool.list_users.assert_not_called()

def test_owner_cannot_add_themselves(monkeypatch):
    user_pool(monkeypatch, [{**FRIEND, "Attributes": [{"Name": "sub", "Value": OWNER_SUB}]}])
    repository = FakeRepository()
    response = real_api(repository).post(f"/servers/{SERVER_ID}/admins", headers=auth(), json={"email": "me@example.com"})
    assert response.status_code == 409
    assert not any(c[0] == "add_admin" for c in repository.calls)

def test_admin_limit(monkeypatch):
    user_pool(monkeypatch)
    repository = FakeRepository()
    repository.admin_limit_reached = True
    response = real_api(repository).post(f"/servers/{SERVER_ID}/admins", headers=auth(), json={"email": "friend@example.com"})
    assert response.status_code == 409

def test_cognito_failure_hides_details(monkeypatch):
    pool = user_pool(monkeypatch)
    pool.list_users.side_effect = ClientError({"Error": {"Code": "AccessDenied", "Message": "private detail"}}, "ListUsers")
    response = real_api().post(f"/servers/{SERVER_ID}/admins", headers=auth(), json={"email": "friend@example.com"})
    assert response.status_code == 502
    assert "private detail" not in response.text
    assert "EC2" not in response.text

def test_owner_lists_and_removes_admins():
    repository = FakeRepository()
    repository.admins = {"friend-id": "friend@example.com"}
    api = real_api(repository)
    assert api.get(f"/servers/{SERVER_ID}/admins", headers=auth()).json() == [
        {"user_id": "friend-id", "email": "friend@example.com"}]
    assert api.delete(f"/servers/{SERVER_ID}/admins/friend-id", headers=auth()).status_code == 204
    assert api.delete(f"/servers/{SERVER_ID}/admins/friend-id", headers=auth()).status_code == 404

def test_admin_can_leave_but_not_remove_others():
    repository = role_repository()
    repository.admins = {f"user-{ADMIN_SUB}": "me@example.com", "other": "other@example.com"}
    api = real_api(repository)
    headers = auth(token(sub=ADMIN_SUB))
    assert api.delete(f"/servers/{SERVER_ID}/admins/other", headers=headers).status_code == 403
    assert api.delete(f"/servers/{SERVER_ID}/admins/me", headers=headers).status_code == 204
    assert repository.admins == {"other": "other@example.com"}

def test_owner_cannot_leave_their_own_server():
    assert real_api().delete(f"/servers/{SERVER_ID}/admins/me", headers=auth()).status_code == 404

def test_admin_sees_shared_server_in_list():
    repository = role_repository()
    response = real_api(repository).get("/servers", headers=auth(token(sub=ADMIN_SUB)))
    assert [(s["server_id"], s["role"]) for s in response.json()] == [(SERVER_ID, "admin")]

def test_admin_starts_and_stops_server(monkeypatch):
    client = aws_instance(monkeypatch, "stopped", None)
    api = real_api(role_repository())
    assert api.post(f"/servers/{SERVER_ID}/start", headers=auth(token(sub=ADMIN_SUB))).status_code == 202
    client.start_instances.assert_called_once_with(InstanceIds=["i-test"])

def test_mock_admins():
    api = TestClient(create_app(Settings(mock_mode=True)))
    assert api.get("/servers/demo-server/admins").json()[0]["email"] == "friend@example.com"
    assert api.post("/servers/demo-server/admins", json={"email": "new@example.com"}).status_code == 201
    assert api.get("/servers/demo-shared/admins").status_code == 403
    assert api.delete("/servers/demo-shared/admins/me").status_code == 204
