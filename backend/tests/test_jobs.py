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
    fake.describe_instances.return_value = {"Reservations": []}
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

def test_players_mark_the_world_for_backup(client, monkeypatch):
    players(monkeypatch, 2)
    running(client, instance())
    jobs.auto_stop(30, now=NOW)
    client.delete_tags.assert_not_called()
    client.create_tags.assert_called_once_with(Resources=["i-1"], Tags=[{"Key": "NeedsBackup", "Value": "true"}])

def test_already_marked_world_isnt_tagged_again(client, monkeypatch):
    players(monkeypatch, 2)
    running(client, instance(tags=[{"Key": "NeedsBackup", "Value": "true"}]))
    jobs.auto_stop(30, now=NOW)
    client.create_tags.assert_not_called()

def test_empty_session_isnt_marked_for_backup(client, monkeypatch):
    players(monkeypatch, 0)
    running(client, instance(tags=[tag(5)]))
    jobs.auto_stop(30, now=NOW)
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
    client.stop_instances.assert_not_called()
    client.create_tags.assert_not_called()

def test_sessions_are_still_marked_with_auto_stop_off(client, monkeypatch):
    players(monkeypatch, 1)
    running(client, instance())
    assert jobs.auto_stop(0, now=NOW) == []
    client.create_tags.assert_called_once_with(Resources=["i-1"], Tags=[{"Key": "NeedsBackup", "Value": "true"}])

# --- Backups ---

def stopped(instance_id="i-1", server_id="server-abcdef", volume_id="vol-1"):
    tags = [{"Key": "NeedsBackup", "Value": "true"}] + ([{"Key": "ServerId", "Value": server_id}] if server_id else [])
    mappings = [{"DeviceName": "/dev/xvda", "Ebs": {"VolumeId": volume_id}}] if volume_id else []
    return {"InstanceId": instance_id, "State": {"Name": "stopped"}, "RootDeviceName": "/dev/xvda",
            "BlockDeviceMappings": mappings, "Tags": tags}

def backup_client(client, *instances, state_after="stopped"):
    listing = {"Reservations": [{"Instances": list(instances)}]} if instances else {"Reservations": []}
    def describe(**kwargs):
        if "InstanceIds" in kwargs:
            return {"Reservations": [{"Instances": [{"State": {"Name": state_after}}]}]}
        return listing
    client.describe_instances.side_effect = describe
    client.create_snapshot.side_effect = lambda **kw: {"SnapshotId": f"snap-{kw['VolumeId']}"}

def test_backup_snapshots_root_volume_and_clears_tag(client):
    backup_client(client, stopped())
    assert jobs.back_up_worlds() == ["snap-vol-1"]
    assert client.describe_instances.call_args_list[0].kwargs["Filters"] == [
        {"Name": "tag:Project", "Values": ["mc-ec2"]}, {"Name": "tag-key", "Values": ["NeedsBackup"]},
        {"Name": "instance-state-name", "Values": ["stopped"]}]
    kwargs = client.create_snapshot.call_args.kwargs
    assert kwargs["VolumeId"] == "vol-1"
    tags = {t["Key"]: t["Value"] for t in kwargs["TagSpecifications"][0]["Tags"]}
    assert (tags["Project"], tags["ServerId"], tags["Kind"]) == ("mc-ec2", "server-abcdef", "session")
    client.delete_tags.assert_called_once_with(Resources=["i-1"], Tags=[{"Key": "NeedsBackup"}])

def test_failed_backup_keeps_tag_for_retry_and_others_continue(client):
    backup_client(client, stopped("i-bad", volume_id="vol-bad"), stopped("i-good", volume_id="vol-good"))
    def create(**kw):
        if kw["VolumeId"] == "vol-bad":
            raise ClientError({"Error": {"Code": "SnapshotLimitExceeded"}}, "CreateSnapshot")
        return {"SnapshotId": "snap-good"}
    client.create_snapshot.side_effect = create
    assert jobs.back_up_worlds() == ["snap-good"]
    client.delete_tags.assert_called_once_with(Resources=["i-good"], Tags=[{"Key": "NeedsBackup"}])

def test_instance_without_server_id_or_volume_is_skipped(client):
    backup_client(client, stopped("i-a", server_id=None), stopped("i-b", volume_id=None))
    assert jobs.back_up_worlds() == []
    client.create_snapshot.assert_not_called()

def test_backup_of_server_deleted_meanwhile_is_removed(client):
    backup_client(client, stopped(), state_after="shutting-down")
    assert jobs.back_up_worlds() == []
    client.delete_snapshot.assert_called_once_with(SnapshotId="snap-vol-1")

def test_backup_when_instance_has_vanished_is_removed(client):
    backup_client(client, stopped())
    listing = client.describe_instances.side_effect
    def describe(**kwargs):
        if "InstanceIds" in kwargs:
            raise ClientError({"Error": {"Code": "InvalidInstanceID.NotFound"}}, "DescribeInstances")
        return listing(**kwargs)
    client.describe_instances.side_effect = describe
    assert jobs.back_up_worlds() == []
    client.delete_snapshot.assert_called_once_with(SnapshotId="snap-vol-1")

def snapshot(snapshot_id, hours_ago, server_id="s1", state="completed", kind="session"):
    tags = ([{"Key": "ServerId", "Value": server_id}] if server_id else []) + ([{"Key": "Kind", "Value": kind}] if kind else [])
    return {"SnapshotId": snapshot_id, "State": state, "StartTime": NOW - timedelta(hours=hours_ago), "Tags": tags}

def snapshots(client, *items):
    client.describe_snapshots.return_value = {"Snapshots": list(items)}

def test_prune_keeps_newest_per_server(client):
    snapshots(client, *[snapshot(f"snap-{h}", h) for h in range(9)], snapshot("other", 500, server_id="s2"))
    assert sorted(jobs.prune_backups(keep=7)) == ["snap-7", "snap-8"]

def test_prune_only_lists_this_accounts_tagged_backups(client):
    snapshots(client)
    jobs.prune_backups()
    kwargs = client.describe_snapshots.call_args.kwargs
    assert kwargs["OwnerIds"] == ["self"]
    assert {"Name": "tag-key", "Values": ["Kind"]} in kwargs["Filters"]

def test_pending_backups_dont_push_out_completed_ones(client):
    snapshots(client, *[snapshot(f"new-{h}", h, state="pending") for h in range(3)],
              *[snapshot(f"snap-{h}", h + 10) for h in range(7)])
    assert jobs.prune_backups(keep=7) == []

def test_prune_removes_failed_backups(client):
    snapshots(client, snapshot("bad", 1, state="error"))
    assert jobs.prune_backups() == ["bad"]

def test_prune_ignores_other_kinds_and_unowned_backups(client):
    snapshots(client, *[snapshot(f"pre-{h}", h, kind="pre-restore") for h in range(9)],
              *[snapshot(f"none-{h}", h, server_id=None) for h in range(9)])
    assert jobs.prune_backups(keep=1) == []
    client.delete_snapshot.assert_not_called()

def test_prune_follows_pagination(client):
    client.describe_snapshots.side_effect = [
        {"Snapshots": [snapshot("a", 1), snapshot("b", 2)], "NextToken": "more"}, {"Snapshots": [snapshot("c", 3)]}]
    assert jobs.prune_backups(keep=2) == ["c"]
    assert client.describe_snapshots.call_args.kwargs["NextToken"] == "more"

def test_prune_failure_doesnt_block_others(client):
    snapshots(client, snapshot("keep", 0), snapshot("stuck", 1), snapshot("gone", 2))
    def delete(SnapshotId):
        if SnapshotId == "stuck":
            raise ClientError({"Error": {"Code": "InvalidSnapshot.InUse"}}, "DeleteSnapshot")
    client.delete_snapshot.side_effect = delete
    assert jobs.prune_backups(keep=1) == ["gone"]

def test_servers_without_their_instance_keep_their_backups(client):
    # Only deleting a server removes its backups; an instance lost some other way needs them most.
    backup_client(client)
    snapshots(client, snapshot("only-copy", 1))
    jobs.back_up_worlds()
    assert jobs.prune_backups() == []
    client.delete_snapshot.assert_not_called()

# --- Restores ---

def restoring(client, state="stopped", task=None, safety="snap-safety", started=None):
    tags = [{"Key": "RestoreTo", "Value": "snap-target"}] + ([{"Key": "RestoreSafety", "Value": safety}] if safety else [])
    if task:
        tags.append({"Key": "RestoreTask", "Value": task})
    client.describe_instances.return_value = {"Reservations": [{"Instances": [
        {"InstanceId": "i-1", "State": {"Name": state}, "Tags": tags}]}]}
    client.start_instances.return_value = {"StartingInstances": [{"CurrentState": {"Name": "pending"}}]}
    client.create_replace_root_volume_task.return_value = {"ReplaceRootVolumeTask": {"ReplaceRootVolumeTaskId": "task-1"}}

def safety_snapshot(client, state="completed", age=timedelta(minutes=10)):
    client.describe_snapshots.return_value = {"Snapshots": [{"State": state, "StartTime": NOW - age}]}

def task_state(client, state):
    client.describe_replace_root_volume_tasks.return_value = {"ReplaceRootVolumeTasks": [{"TaskState": state}]}

def assert_failed(client):
    assert {"Key": "RestoreFailed", "Value": "2026-11-01T12:00:00Z"} in client.create_tags.call_args.kwargs["Tags"]
    assert {"Key": "RestoreTo"} in client.delete_tags.call_args.kwargs["Tags"]

def test_restore_waits_for_the_safety_snapshot(client):
    restoring(client)
    safety_snapshot(client, "pending")
    jobs.advance_restores(now=NOW)
    client.start_instances.assert_not_called()
    client.create_replace_root_volume_task.assert_not_called()

def test_restore_starts_a_stopped_server_once_the_world_is_saved(client):
    restoring(client)
    safety_snapshot(client)
    jobs.advance_restores(now=NOW)
    client.start_instances.assert_called_once_with(InstanceIds=["i-1"])
    client.create_replace_root_volume_task.assert_not_called()

def test_restore_waits_for_a_booting_server(client):
    restoring(client, state="pending")
    safety_snapshot(client)
    jobs.advance_restores(now=NOW)
    client.create_replace_root_volume_task.assert_not_called()

def test_restore_replaces_the_disk_of_a_running_server(client):
    restoring(client, state="running")
    safety_snapshot(client)
    assert jobs.advance_restores(now=NOW) == ["i-1"]
    client.create_replace_root_volume_task.assert_called_once_with(
        InstanceId="i-1", SnapshotId="snap-target", ClientToken="snap-safety", DeleteReplacedRootVolume=True)
    client.create_tags.assert_called_once_with(Resources=["i-1"], Tags=[{"Key": "RestoreTask", "Value": "task-1"}])

def test_restore_task_in_progress_is_left_alone(client):
    restoring(client, state="running", task="task-1")
    safety_snapshot(client)
    task_state(client, "in-progress")
    jobs.advance_restores(now=NOW)
    client.create_replace_root_volume_task.assert_not_called()
    client.delete_tags.assert_not_called()

def test_finished_restore_clears_its_tags(client):
    restoring(client, state="running", task="task-1")
    task_state(client, "succeeded")
    jobs.advance_restores(now=NOW)
    client.delete_tags.assert_called_once_with(Resources=["i-1"], Tags=[
        {"Key": "RestoreTo"}, {"Key": "RestoreSafety"}, {"Key": "RestoreTask"}])
    client.create_tags.assert_not_called()

@pytest.mark.parametrize("state", ["failed", "failed-detached"])
def test_failed_task_is_recorded(client, state):
    restoring(client, state="running", task="task-1")
    task_state(client, state)
    jobs.advance_restores(now=NOW)
    assert_failed(client)

def test_failed_safety_snapshot_abandons_restore_before_touching_the_disk(client):
    restoring(client, state="running")
    safety_snapshot(client, "error")
    jobs.advance_restores(now=NOW)
    client.create_replace_root_volume_task.assert_not_called()
    assert_failed(client)

def test_missing_safety_snapshot_abandons_restore(client):
    restoring(client, state="running")
    client.describe_snapshots.side_effect = ClientError({"Error": {"Code": "InvalidSnapshot.NotFound"}}, "DescribeSnapshots")
    jobs.advance_restores(now=NOW)
    client.create_replace_root_volume_task.assert_not_called()
    assert_failed(client)

def test_stuck_restore_gives_up_so_auto_stop_resumes(client):
    restoring(client, state="running")
    safety_snapshot(client, age=timedelta(hours=2))
    client.create_replace_root_volume_task.side_effect = AssertionError("should have given up")
    jobs.advance_restores(now=NOW)
    assert_failed(client)

def test_restore_error_keeps_tags_for_retry_and_others_continue(client):
    restoring(client, state="running")
    safety_snapshot(client)
    client.create_replace_root_volume_task.side_effect = ClientError({"Error": {"Code": "IncorrectState"}}, "CreateReplaceRootVolumeTask")
    assert jobs.advance_restores(now=NOW) == []
    client.delete_tags.assert_not_called()

def test_auto_stop_leaves_a_restoring_server_alone(client, monkeypatch):
    ping = players(monkeypatch, 3)
    running(client, instance(tags=[tag(600), {"Key": "RestoreTo", "Value": "snap-1"}]))
    assert jobs.auto_stop(30, now=NOW) == []
    ping.assert_not_called()
    client.create_tags.assert_not_called()

def test_pre_restore_backups_expire_after_30_days(client):
    snapshots(client, snapshot("old", 24 * 30, kind="pre-restore"), snapshot("recent", 24 * 29, kind="pre-restore"))
    assert jobs.prune_backups(now=NOW) == ["old"]

def test_backups_in_use_by_a_restore_arent_pruned(client):
    restoring(client, state="running")
    snapshots(client, snapshot("newest", 0), snapshot("snap-target", 5), snapshot("snap-safety", 24 * 40, kind="pre-restore"))
    assert jobs.prune_backups(keep=1, now=NOW) == []

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
    client.describe_snapshots.return_value = {"Snapshots": []}
    assert handler.handler({}, None)["stopped"] == ["i-1"]

def test_handler_reports_backups_and_pruning(client, monkeypatch):
    players(monkeypatch, 0)
    monkeypatch.setenv("AUTO_STOP_IDLE_MINUTES", "10")
    running(client)
    client.describe_snapshots.return_value = {"Snapshots": []}
    spec = importlib.util.spec_from_file_location("jobs_handler", INFRA / "jobs_handler.py")
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)
    assert handler.handler({}, None) == {"stopped": [], "restores": [], "backed_up": [], "pruned": []}
