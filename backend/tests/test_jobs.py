import importlib.util
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock
import pytest
from botocore.exceptions import ClientError
import ec2
import jobs

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
STARTED = NOW - timedelta(hours=5)
INFRA = Path(__file__).resolve().parents[2] / "infra"
BACKEND = Path(__file__).resolve().parents[1]

def tag(minutes_ago):
    return {"Key": "IdleSince", "Value": (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")}

def instance(instance_id="i-1", tags=(), launched=STARTED, ip="203.0.113.10"):
    return {"InstanceId": instance_id, "State": {"Name": "running"}, "PublicIpAddress": ip,
            "LaunchTime": launched, "Tags": [{"Key": "Project", "Value": "mc-ec2"}, *tags]}

@pytest.fixture
def client(monkeypatch):
    fake = Mock()
    fake.stop_instances.return_value = {"StoppingInstances": [{"CurrentState": {"Name": "stopping"}}]}
    monkeypatch.setattr(ec2, "ec2", fake)
    monkeypatch.setattr(ec2.boto3, "client", Mock(side_effect=AssertionError("Unexpected AWS client")))
    return fake

def running(fake, *instances):
    fake.describe_instances.return_value = {"Reservations": [{"Instances": list(instances)}]} if instances else {"Reservations": []}

def players(monkeypatch, online):
    result = None if online is None else {"online": online, "max": 20, "version": "1.21"}
    ping = Mock(return_value=result)
    monkeypatch.setattr(ec2, "ping_minecraft", ping)
    return ping

def test_only_running_project_instances_are_checked(client, monkeypatch):
    players(monkeypatch, 1)
    running(client)
    jobs.auto_stop(30, now=NOW)
    assert client.describe_instances.call_args.kwargs["Filters"] == [
        {"Name": "tag:Project", "Values": ["mc-ec2"]}, {"Name": "instance-state-name", "Values": ["running"]}]

def test_nothing_running_does_nothing(client, monkeypatch):
    ping = players(monkeypatch, 0)
    running(client)
    assert jobs.auto_stop(30, now=NOW) == []
    ping.assert_not_called()
    client.create_tags.assert_not_called()

def test_first_idle_check_starts_the_timer(client, monkeypatch):
    players(monkeypatch, 0)
    running(client, instance())
    assert jobs.auto_stop(30, now=NOW) == []
    client.create_tags.assert_called_once_with(
        Resources=["i-1"], Tags=[{"Key": "IdleSince", "Value": "2026-11-01T12:00:00Z"}])
    client.stop_instances.assert_not_called()

def test_below_threshold_keeps_running(client, monkeypatch):
    players(monkeypatch, 0)
    running(client, instance(tags=[tag(29)]))
    assert jobs.auto_stop(30, now=NOW) == []
    client.stop_instances.assert_not_called()
    client.create_tags.assert_not_called()  # The timer keeps its original start.

def test_at_threshold_stops_and_clears_tag(client, monkeypatch):
    players(monkeypatch, 0)
    running(client, instance(tags=[tag(30)]))
    assert jobs.auto_stop(30, now=NOW) == ["i-1"]
    client.stop_instances.assert_called_once_with(InstanceIds=["i-1"])
    client.delete_tags.assert_called_once_with(Resources=["i-1"], Tags=[{"Key": "IdleSince"}])

def test_players_reset_the_timer(client, monkeypatch):
    players(monkeypatch, 2)
    running(client, instance(tags=[tag(60)]))
    assert jobs.auto_stop(30, now=NOW) == []
    client.stop_instances.assert_not_called()
    client.delete_tags.assert_called_once_with(Resources=["i-1"], Tags=[{"Key": "IdleSince"}])

def test_players_with_no_timer_change_nothing(client, monkeypatch):
    players(monkeypatch, 2)
    running(client, instance())
    jobs.auto_stop(30, now=NOW)
    client.delete_tags.assert_not_called()
    client.create_tags.assert_not_called()

def test_stale_tag_from_before_last_start_doesnt_stop_server(client, monkeypatch):
    # Stopped by hand while idle, then restarted: the old tag mustn't stop it straight away.
    players(monkeypatch, 0)
    running(client, instance(tags=[tag(600)], launched=NOW - timedelta(minutes=1)))
    assert jobs.auto_stop(30, now=NOW) == []
    client.stop_instances.assert_not_called()
    assert client.create_tags.call_args.kwargs["Tags"][0]["Value"] == "2026-11-01T12:00:00Z"

def test_failed_ping_counts_as_idle(client, monkeypatch):
    # A crashed server or failed first boot should stop costing money too.
    players(monkeypatch, None)
    running(client, instance(tags=[tag(30)]))
    assert jobs.auto_stop(30, now=NOW) == ["i-1"]

def test_malformed_tag_restarts_the_timer(client, monkeypatch):
    players(monkeypatch, 0)
    running(client, instance(tags=[{"Key": "IdleSince", "Value": "soon"}]))
    assert jobs.auto_stop(30, now=NOW) == []
    client.stop_instances.assert_not_called()
    client.create_tags.assert_called_once()

def test_one_failing_instance_doesnt_block_others(client, monkeypatch):
    players(monkeypatch, 0)
    running(client, instance("i-bad", tags=[tag(60)]), instance("i-good", tags=[tag(60)]))
    def stop(InstanceIds):
        if InstanceIds == ["i-bad"]:
            raise ClientError({"Error": {"Code": "UnauthorizedOperation"}}, "StopInstances")
        return {"StoppingInstances": [{"CurrentState": {"Name": "stopping"}}]}
    client.stop_instances.side_effect = stop
    assert jobs.auto_stop(30, now=NOW) == ["i-good"]

def test_zero_turns_auto_stop_off(client, monkeypatch):
    ping = players(monkeypatch, 0)
    running(client, instance(tags=[tag(600)]))
    assert jobs.auto_stop(0, now=NOW) == []
    client.describe_instances.assert_not_called()
    ping.assert_not_called()

def test_job_never_loads_the_database_layer():
    # A query every 5 minutes would keep Aurora from auto-pausing, at a real monthly cost.
    code = ("import sys; sys.path.insert(0, %r); sys.path.insert(0, %r); import jobs_handler; "
            "assert 'db' not in sys.modules and 'service' not in sys.modules and 'app' not in sys.modules"
            % (str(BACKEND), str(INFRA)))
    subprocess.run([sys.executable, "-c", code], check=True)

def test_handler_uses_configured_threshold(client, monkeypatch):
    players(monkeypatch, 0)
    now = datetime.now(timezone.utc)
    idle_since = (now - timedelta(minutes=11)).strftime("%Y-%m-%dT%H:%M:%SZ")
    running(client, instance(tags=[{"Key": "IdleSince", "Value": idle_since}], launched=now - timedelta(hours=1)))
    monkeypatch.setenv("AUTO_STOP_IDLE_MINUTES", "10")
    spec = importlib.util.spec_from_file_location("jobs_handler", INFRA / "jobs_handler.py")
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)
    assert handler.handler({}, None) == {"stopped": ["i-1"]}
