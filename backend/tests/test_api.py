import os
import runpy
import sys

os.environ.update(AWS_ACCESS_KEY_ID="test", AWS_SECRET_ACCESS_KEY="test", AWS_DEFAULT_REGION="us-east-1")

import boto3
import pytest
from fastapi.testclient import TestClient
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


def test_status_running(api, instance_id):
    r = api.get(f"/api/servers/{instance_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "running"
    assert body["ip"]
    assert body["minecraft"] == FAKE_MC


def test_stop_then_start(api, instance_id):
    assert api.post(f"/api/servers/{instance_id}/stop").json() == {"state": "stopping"}
    stopped = api.get(f"/api/servers/{instance_id}").json()
    assert stopped == {"state": "stopped", "ip": None, "minecraft": None}
    assert api.post(f"/api/servers/{instance_id}/start").json() == {"state": "pending"}


def test_start_while_stopping_conflicts(api, instance_id, monkeypatch):
    monkeypatch.setattr(ec2, "describe", lambda iid: {"state": "stopping", "ip": None})
    r = api.post(f"/api/servers/{instance_id}/start")
    assert r.status_code == 409


def test_unknown_instance(api, instance_id):
    r = api.get("/api/servers/i-00000000000000000")
    assert r.status_code == 404


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
