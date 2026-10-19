import os
import runpy
import sys

os.environ.update(AWS_ACCESS_KEY_ID="test", AWS_SECRET_ACCESS_KEY="test", AWS_DEFAULT_REGION="us-east-1")

import boto3
import pytest
from fastapi.testclient import TestClient
from botocore.exceptions import ClientError
from moto import mock_aws

import app as app_module
import ec2

FAKE_MC = {"online": 2, "max": 20, "version": "1.21.1"}


@pytest.fixture
def instance_id(monkeypatch):
    with mock_aws():
        client = boto3.client("ec2", region_name="us-east-1")
        monkeypatch.setattr(ec2, "ec2", client)
        # Mocked instances have fake IPs; don't wait on a real Minecraft ping
        monkeypatch.setattr(ec2, "ping_minecraft", lambda ip, timeout=3: FAKE_MC)
        resp = client.run_instances(ImageId="ami-12c6146b", MinCount=1, MaxCount=1)
        yield resp["Instances"][0]["InstanceId"]


@pytest.fixture
def api():
    return TestClient(app_module.app)


# The legacy /api/servers/{instance_id} routes are disabled (see app.py); the same
# EC2 lifecycle behavior is covered here at the ec2.py level against moto.

def test_status_running(instance_id):
    info = ec2.status(instance_id)
    assert info["state"] == "running"
    assert info["ip"]
    assert info["minecraft"] == FAKE_MC


def test_stop_then_start(instance_id):
    assert ec2.stop(instance_id) == "stopping"
    assert ec2.status(instance_id) == {"state": "stopped", "ip": None, "minecraft": None}
    assert ec2.start(instance_id) == "pending"


def test_start_while_stopping_conflicts(instance_id, monkeypatch):
    monkeypatch.setattr(ec2, "describe", lambda iid: {"state": "stopping", "ip": None})
    with pytest.raises(ec2.InvalidState):
        ec2.start(instance_id)


def test_unknown_instance(instance_id):
    with pytest.raises(ClientError) as exc:
        ec2.status("i-00000000000000000")
    assert exc.value.response["Error"]["Code"].startswith("InvalidInstanceID")


def test_legacy_routes_removed(api):
    assert api.get("/api/servers/i-test").status_code in (404, 405)
    assert api.post("/api/servers/i-test/start").status_code in (404, 405)


def test_frontend_served(api):
    r = api.get("/")
    assert r.status_code == 200
    assert "<title>" in r.text


def test_cli_status(instance_id, capsys, monkeypatch):
    # Same as: python ec2.py status <id>
    def no_network(*args, **kwargs):
        raise OSError("no network in tests")
    monkeypatch.setattr("mcstatus.JavaServer", no_network)
    monkeypatch.setattr(sys, "argv", ["ec2.py", "status", instance_id])
    runpy.run_path(ec2.__file__, run_name="__main__")
    assert "'state': 'running'" in capsys.readouterr().out

@pytest.mark.parametrize("action,expected", [("stop", "stopping"), ("start", "pending")])
def test_cli_lifecycle(instance_id, capsys, monkeypatch, action, expected):
    if action == "start":
        ec2.stop(instance_id)
        assert ec2.describe(instance_id)["state"] == "stopped"
    monkeypatch.setattr(sys, "argv", ["ec2.py", action, instance_id])
    runpy.run_path(ec2.__file__, run_name="__main__")
    assert expected in capsys.readouterr().out


def test_launch_from_template_against_moto(monkeypatch):
    with mock_aws():
        client = boto3.client("ec2", region_name="us-east-1")
        monkeypatch.setattr(ec2, "ec2", client)
        template = client.create_launch_template(
            LaunchTemplateName="mc-ec2", LaunchTemplateData={"ImageId": "ami-12c6146b", "InstanceType": "t4g.small"})
        template_id = template["LaunchTemplate"]["LaunchTemplateId"]
        server_id = "3f2a6c1e-0000-4000-8000-000000000002"
        first = ec2.launch(server_id, template_id)
        assert first["instance_type"] == "t4g.small"
        # Launching the same server again returns the existing instance.
        assert ec2.launch(server_id, template_id)["instance_id"] == first["instance_id"]
        inst = client.describe_instances(InstanceIds=[first["instance_id"]])["Reservations"][0]["Instances"][0]
        assert {"Key": "Project", "Value": "mc-ec2"} in inst["Tags"]
        assert len(client.describe_instances()["Reservations"]) == 1
