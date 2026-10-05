from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError, ReadTimeoutError
from fastapi.testclient import TestClient
import ec2
from app import create_app
from config import Settings

@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    monkeypatch.setattr(ec2.boto3, "client", Mock(side_effect=AssertionError("Unexpected AWS access")))
    monkeypatch.setattr(ec2, "JavaServer", Mock(side_effect=AssertionError("Unexpected Minecraft access")))

def real_api():
    return TestClient(create_app(Settings(servers={"demo-server": "i-test"})))

def aws_instance(monkeypatch, state="running", ip="203.0.113.10"):
    client = Mock()
    client.describe_instances.return_value = {
        "Reservations": [{"Instances": [{"State": {"Name": state}, "PublicIpAddress": ip}]}]}
    monkeypatch.setattr(ec2, "ec2", client)
    return client

@pytest.mark.parametrize("mode", [False, True])
def test_health_without_aws(mode):
    with TestClient(create_app(Settings(mock_mode=mode))) as api:
        assert api.get("/health").json() == {"status": "ok", "mock_mode": mode}

@pytest.mark.parametrize("mode", [False, True])
def test_unknown_server(mode):
    api = TestClient(create_app(Settings(mock_mode=mode)))
    assert api.get("/servers/unknown/status").status_code == 404

@pytest.mark.parametrize("server,state,ready,address", [
    ("demo-server", "running", True, "203.0.113.10:25565"),
    ("demo-starting", "running", False, "203.0.113.11:25565"),
    ("demo-stopped", "stopped", False, None)])
def test_mock_status(server, state, ready, address):
    api = TestClient(create_app(Settings(mock_mode=True)))
    expected = {"server_id": server, "instance_state": state,
                "minecraft_ready": ready, "connection_address": address}
    assert api.get(f"/servers/{server}/status").json() == expected
    assert api.get(f"/servers/{server}/status").json() == expected

@pytest.mark.parametrize("failure", [TimeoutError("timeout"), ConnectionRefusedError("starting"), EOFError()])
def test_running_minecraft_not_ready(monkeypatch, failure):
    client = aws_instance(monkeypatch)
    minecraft = Mock()
    minecraft.status.side_effect = failure
    factory = Mock(return_value=minecraft)
    monkeypatch.setattr(ec2, "JavaServer", factory)
    response = real_api().get("/servers/demo-server/status")
    assert response.status_code == 200
    assert response.json() == {"server_id": "demo-server", "instance_state": "running",
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
    assert api.get("/servers/demo-server/status").json()["minecraft_ready"] is True
    client.describe_instances.return_value["Reservations"][0]["Instances"][0]["PublicIpAddress"] = "203.0.113.20"
    assert api.get("/servers/demo-server/status").json()["connection_address"] == "203.0.113.20:25565"
    assert client.describe_instances.call_count == 2

@pytest.mark.parametrize("state,ip", [("running", None), ("stopped", None), ("pending", "203.0.113.10")])
def test_unavailable_address(monkeypatch, state, ip):
    aws_instance(monkeypatch, state, ip)
    response = real_api().get("/servers/demo-server/status")
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
    response = real_api().get("/servers/demo-server/status")
    assert response.status_code == 502
    assert "Unable to retrieve EC2 status" in response.json()["detail"]
    assert "private detail" not in response.text

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

def test_docs_and_scope():
    with TestClient(create_app(Settings(mock_mode=True))) as api:
        assert api.get("/docs").status_code == 200
        assert set(api.get("/openapi.json").json()["paths"]) == {
            "/health", "/servers/{server_id}/status", "/api/servers/{instance_id}",
            "/api/servers/{instance_id}/start", "/api/servers/{instance_id}/stop"}
        assert api.post("/api/servers/i-test/start").status_code == 503

def test_environment_configuration(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("DEMO_SERVERS", '{"demo-server":"i-test"}')
    settings = Settings.from_env()
    assert settings.servers == {"demo-server": "i-test"}
    assert settings.aws_region == "us-west-2"
    assert settings.mock_mode is False

@pytest.mark.parametrize("mapping", ['[]', '{"demo-server":42}', '{"":"i-test"}'])
def test_invalid_mapping(monkeypatch, mapping):
    monkeypatch.setenv("DEMO_SERVERS", mapping)
    with pytest.raises(ValueError):
        Settings.from_env()

def test_invalid_mock_mode(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "maybe")
    monkeypatch.setenv("DEMO_SERVERS", "{}")
    with pytest.raises(ValueError):
        Settings.from_env()

@pytest.mark.parametrize("method,path", [
    ("get", "/api/servers/i-test"),
    ("post", "/api/servers/i-test/start"),
    ("post", "/api/servers/i-test/stop")])
def test_legacy_routes_cannot_access_aws_in_mock_mode(method, path):
    api = TestClient(create_app(Settings(mock_mode=True)))
    response = getattr(api, method)(path)
    assert response.status_code == 503
    assert "MOCK_MODE=false" in response.json()["detail"]

def test_legacy_stop_while_pending(monkeypatch):
    aws_instance(monkeypatch, "pending", None)
    response = real_api().post("/api/servers/i-test/stop")
    assert response.status_code == 409

@pytest.mark.parametrize("error", [
    NoCredentialsError(),
    ClientError({"Error": {"Code": "UnauthorizedOperation"}}, "DescribeInstances")])
def test_legacy_aws_errors(monkeypatch, error):
    client = aws_instance(monkeypatch)
    client.describe_instances.side_effect = error
    assert real_api().get("/api/servers/i-test").status_code == 502

def test_frontend_and_new_routes_coexist():
    api = TestClient(create_app(Settings(mock_mode=True)))
    assert 'id="start"' in api.get("/").text
    assert api.get("/health").status_code == 200
    assert api.get("/servers/demo-server/status").status_code == 200
    assert api.get("/docs").status_code == 200
