import time
from types import SimpleNamespace
from unittest.mock import Mock
import jwt
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError, ReadTimeoutError
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
import ec2
import app as app_module
from app import create_app
from auth import CognitoVerifier
from config import Settings
from db import DatabaseUnavailable, OwnedServer, ServerLimitReached, ServerRow

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

    def get_owned_server(self, sub, server_id):
        self.calls.append((sub, server_id))
        if self.error:
            raise self.error
        return self.servers.get((sub, server_id))

    def list_owned_servers(self, sub):
        self.calls.append(("list", sub))
        if self.error:
            raise self.error
        return [ServerRow(s.id, s.region, "LATEST", "t4g.small", s.instance_id is not None)
                for (owner, _), s in self.servers.items() if owner == sub]

    # Registration and server creation, keyed by sub (user_id is "user-<sub>").
    registered = ()
    pending = None
    limit_reached = False
    attach_error = None

    def ensure_user(self, sub):
        self.calls.append(("ensure_user", sub))
        if self.error:
            raise self.error
        created = sub not in self.registered
        self.registered = (*self.registered, sub)
        return f"user-{sub}", created

    def reserve_server(self, user_id, region, version, max_per_user, max_total):
        self.calls.append(("reserve_server", user_id, region, version, max_per_user, max_total))
        if self.limit_reached:
            raise ServerLimitReached
        self.pending = self.pending or OwnedServer(NEW_SERVER_ID, None, region)
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
            "/health", "/servers", "/servers/{server_id}/status",
            "/servers/{server_id}/start", "/servers/{server_id}/stop"}

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

NO_PLAYERS = {"players_online": None, "players_max": None, "minecraft_version": None}

@pytest.mark.parametrize("server,state,ready,address,players", [
    ("demo-server", "running", True, "203.0.113.10:25565",
     {"players_online": 2, "players_max": 20, "minecraft_version": "1.21.4"}),
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
    ("get", f"/servers/{SERVER_ID}/status"),
    ("post", f"/servers/{SERVER_ID}/start"),
    ("post", f"/servers/{SERVER_ID}/stop"),
    ("get", "/servers"),
    ("post", "/servers")])
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

# --- Registration through listing ---

def test_register_creates_then_returns_user():
    repository = FakeRepository()
    api = real_api(repository)
    assert api.get("/servers", headers=auth()).status_code == 200
    assert api.get("/servers", headers=auth()).status_code == 200
    assert repository.registered == (OWNER_SUB, OWNER_SUB)
    assert repository.calls == [("ensure_user", OWNER_SUB), ("list", OWNER_SUB)] * 2

# --- Listing (GET /servers) ---

def test_list_returns_only_the_callers_servers():
    repository = FakeRepository({
        (OWNER_SUB, SERVER_ID): OwnedServer(SERVER_ID, "i-test", "us-east-1"),
        (OWNER_SUB, NEW_SERVER_ID): OwnedServer(NEW_SERVER_ID, None, "us-east-1"),
        ("stranger", "other"): OwnedServer("other", "i-other", "us-east-1")})
    response = real_api(repository).get("/servers", headers=auth())
    assert response.status_code == 200
    assert response.json() == [
        {"server_id": SERVER_ID, "region": "us-east-1", "minecraft_version": "LATEST",
         "instance_type": "t4g.small", "has_instance": True},
        {"server_id": NEW_SERVER_ID, "region": "us-east-1", "minecraft_version": "LATEST",
         "instance_type": "t4g.small", "has_instance": False}]
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
    assert [s["server_id"] for s in response.json()] == ["demo-server", "demo-starting", "demo-stopped"]

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
    assert response.json() == {"server_id": NEW_SERVER_ID, "instance_state": "pending", "region": "us-east-1",
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
