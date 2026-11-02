import io
import json
import time
import urllib.error
from unittest.mock import Mock
import pytest
from botocore.exceptions import ClientError
import player_access

SERVER_ID = "3f2a6c1e-0000-4000-8000-000000000001"

@pytest.fixture
def ssm(monkeypatch):
    client = Mock()
    monkeypatch.setattr(player_access, "ssm", client)
    return client

def not_found(operation):
    return ClientError({"Error": {"Code": "ParameterNotFound"}}, operation)

def test_load_saved(ssm):
    ssm.get_parameter.return_value = {"Parameter": {"Value": '{"mode": "whitelist", "players": ["Steve"]}'}}
    assert player_access.load(SERVER_ID, "us-east-1") == {"mode": "whitelist", "players": ["Steve"]}
    ssm.get_parameter.assert_called_once_with(Name=f"/mc-ec2/servers/{SERVER_ID}/access")

def test_load_missing_is_public(ssm):
    ssm.get_parameter.side_effect = not_found("GetParameter")
    assert player_access.load(SERVER_ID, "us-east-1") == {"mode": "public", "players": []}

def test_load_other_errors_propagate(ssm):
    ssm.get_parameter.side_effect = ClientError({"Error": {"Code": "AccessDeniedException"}}, "GetParameter")
    with pytest.raises(ClientError):
        player_access.load(SERVER_ID, "us-east-1")

def test_save_overwrites(ssm):
    player_access.save(SERVER_ID, "whitelist", ["Steve"], "us-east-1")
    kwargs = ssm.put_parameter.call_args.kwargs
    assert (kwargs["Type"], kwargs["Overwrite"]) == ("String", True)
    assert json.loads(kwargs["Value"]) == {"mode": "whitelist", "players": ["Steve"]}

def test_largest_allowed_list_fits_a_standard_parameter():
    value = json.dumps({"mode": "whitelist", "players": ["x" * 16] * 100})
    assert len(value) < 4096

def test_delete_missing_is_fine(ssm):
    ssm.delete_parameter.side_effect = not_found("DeleteParameter")
    player_access.delete(SERVER_ID, "us-east-1")

def test_delete_other_errors_propagate(ssm):
    ssm.delete_parameter.side_effect = ClientError({"Error": {"Code": "AccessDeniedException"}}, "DeleteParameter")
    with pytest.raises(ClientError):
        player_access.delete(SERVER_ID, "us-east-1")

def test_trigger_reports_unreachable(ssm):
    assert player_access.trigger_sync("i-test", "doc", "us-east-1") is True
    ssm.send_command.side_effect = ClientError({"Error": {"Code": "InvalidInstanceId"}}, "SendCommand")
    assert player_access.trigger_sync("i-test", "doc", "us-east-1") is False

# --- Mojang lookup ---

def response(status):
    r = io.BytesIO(b"{}")
    r.status = status
    return r

def http_error(code):
    return urllib.error.HTTPError("url", code, "error", {}, io.BytesIO())

@pytest.mark.parametrize("answer,exists", [
    (response(200), True),
    (response(204), False),
    (http_error(404), False),
    (http_error(429), True),       # rate limited: not a definite "no"
    (http_error(500), True),
    (urllib.error.URLError("down"), True),
    (TimeoutError(), True)])
def test_player_exists(monkeypatch, answer, exists):
    monkeypatch.setattr(player_access.urllib.request, "urlopen", Mock(side_effect=[answer]))
    assert player_access._player_exists("Steve") is exists

def test_unknown_players_keeps_order(monkeypatch):
    monkeypatch.setattr(player_access, "_player_exists", lambda name: name == "Steve")
    assert player_access.unknown_players(["Zed", "Steve", "Abe"]) == ["Zed", "Abe"]

def test_no_names_makes_no_requests(monkeypatch):
    monkeypatch.setattr(player_access, "_player_exists", Mock(side_effect=AssertionError))
    assert player_access.unknown_players([]) == []

def test_slow_mojang_cant_block_a_save(monkeypatch):
    monkeypatch.setattr(player_access, "MOJANG_TOTAL_TIMEOUT", 0.05)
    monkeypatch.setattr(player_access, "_player_exists", lambda name: time.sleep(0.3) or False)
    assert player_access.unknown_players(["Steve"]) == []
