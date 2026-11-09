import os
import time
from datetime import datetime, timezone
import boto3
from mcstatus import JavaServer
from botocore.config import Config
from botocore.exceptions import ClientError

#Lambda environment variable, use1 default
REGION = os.environ.get("AWS_REGION", "us-east-1")
MC_PORT = 25565
PROJECT_TAG = {"Key": "Project", "Value": "mc-ec2"}
# Set by backend/jobs.py on a running server with no players.
IDLE_TAG = "IdleSince"
IDLE_TAG_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
# Set by backend/jobs.py when players are seen, and cleared once the world has been backed up.
NEEDS_BACKUP_TAG = "NeedsBackup"
# Marks a snapshot as a world backup. Other snapshots, such as manual ones, are never deleted here.
BACKUP_KIND_TAG = "Kind"
SESSION_BACKUP = "session"
PRE_RESTORE_BACKUP = "pre-restore"
# A restore in progress: the backup to restore, and the snapshot of the world it will replace.
RESTORE_TO_TAG = "RestoreTo"
RESTORE_SAFETY_TAG = "RestoreSafety"
# The AWS task replacing the root volume, once the job has created it.
RESTORE_TASK_TAG = "RestoreTask"
RESTORE_FAILED_TAG = "RestoreFailed"

# No client at import time: health and mock mode require no credentials.
ec2 = None

def get_client(region=None):
    return ec2 if ec2 is not None else boto3.client(
        "ec2", region_name=region or REGION,
        config=Config(connect_timeout=3, read_timeout=5,
                      retries={"total_max_attempts": 1}),
    )

#eg, start while stopping, stop while pending
class InvalidState(Exception):
        """The instance is in a state where the requested action can't run yet."""

#When the running instance became idle. A tag older than the last start is stale, so it doesn't count.
def idle_since(inst):
    tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
    try:
        since = datetime.strptime(tags[IDLE_TAG], IDLE_TAG_FORMAT).replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return None
    launched = inst.get("LaunchTime")
    return None if launched is not None and since < launched else since

def _tags(resource):
    return {t["Key"]: t["Value"] for t in resource.get("Tags", [])}

def _root_volume(inst):
    return next((d["Ebs"]["VolumeId"] for d in inst.get("BlockDeviceMappings", [])
                 if d["DeviceName"] == inst.get("RootDeviceName")), None)

#Return state and ip of instance
def describe(instance_id, region=None):
    resp = get_client(region).describe_instances(InstanceIds=[instance_id])
    inst = resp["Reservations"][0]["Instances"][0]
    tags = _tags(inst)
    return {"state": inst["State"]["Name"], "ip": inst.get("PublicIpAddress"), "idle_since": idle_since(inst),
            "restoring": RESTORE_TO_TAG in tags, "restore_failed": RESTORE_FAILED_TAG in tags,
            "volume_id": _root_volume(inst)}

#Use JavaServer library to get MC server info
def ping_minecraft(ip, timeout=3):
    if not ip:
        return None
    try:
        s = JavaServer(ip, MC_PORT, timeout=timeout).status(tries=1)
        return {"online": s.players.online, "max": s.players.max, "version": s.version.name}
    # Offline/booting/unreachable is normal status, not an API failure.
    except Exception:
        return None

#Wrap AWS instance + minecraft server info into one
def status(instance_id, region=None):
    info = describe(instance_id) if region is None else describe(instance_id, region=region)
    info["minecraft"] = ping_minecraft(info["ip"]) if info["state"] == "running" else None
    return info

#Attempt to start instance
def start(instance_id, region=None):
    state = (describe(instance_id) if region is None else describe(instance_id, region=region))["state"]
    if state in ("running", "pending"):
        return state
    if state == "stopping":
        raise InvalidState("instance is still stopping; try again shortly")
    resp = get_client(region).start_instances(InstanceIds=[instance_id])
    return resp["StartingInstances"][0]["CurrentState"]["Name"]

#Attempt to stop instance
def stop(instance_id, region=None):
    state = (describe(instance_id) if region is None else describe(instance_id, region=region))["state"]
    if state in ("stopped", "stopping"):
        return state
    if state == "pending":
        raise InvalidState("instance is still starting; try again shortly")
    resp = get_client(region).stop_instances(InstanceIds=[instance_id])
    return resp["StoppingInstances"][0]["CurrentState"]["Name"]

#Instances launched for a server that haven't been terminated, found by tag.
def find_instances(server_id, region=None):
    existing = get_client(region).describe_instances(Filters=[
        {"Name": "tag:ServerId", "Values": [server_id]},
        {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]}])
    return [inst for reservation in existing["Reservations"] for inst in reservation["Instances"]]

#Terminate an instance; one AWS no longer knows about is already gone.
def terminate(instance_id, region=None):
    try:
        get_client(region).terminate_instances(InstanceIds=[instance_id])
    except ClientError as exc:
        if not exc.response["Error"]["Code"].startswith("InvalidInstanceID"):
            raise

#Every running Minecraft instance, for the auto-stop job.
def list_running(region=None):
    resp = get_client(region).describe_instances(Filters=[
        {"Name": f"tag:{PROJECT_TAG['Key']}", "Values": [PROJECT_TAG["Value"]]},
        {"Name": "instance-state-name", "Values": ["running"]}])
    return [{"instance_id": inst["InstanceId"], "ip": inst.get("PublicIpAddress"), "idle_since": idle_since(inst),
             "has_idle_tag": any(t["Key"] == IDLE_TAG for t in inst.get("Tags", [])),
             "needs_backup": any(t["Key"] == NEEDS_BACKUP_TAG for t in inst.get("Tags", [])),
             "restoring": any(t["Key"] == RESTORE_TO_TAG for t in inst.get("Tags", []))}
            for reservation in resp["Reservations"] for inst in reservation["Instances"]]

#Stopped instances that have been played on since their last backup.
def list_needing_backup(region=None):
    resp = get_client(region).describe_instances(Filters=[
        {"Name": f"tag:{PROJECT_TAG['Key']}", "Values": [PROJECT_TAG["Value"]]},
        {"Name": "tag-key", "Values": [NEEDS_BACKUP_TAG]},
        {"Name": "instance-state-name", "Values": ["stopped"]}])
    return [{"instance_id": inst["InstanceId"],
             "server_id": next((t["Value"] for t in inst.get("Tags", []) if t["Key"] == "ServerId"), None),
             "volume_id": _root_volume(inst)}
            for reservation in resp["Reservations"] for inst in reservation["Instances"]]

def mark_needs_backup(instance_id, region=None):
    get_client(region).create_tags(Resources=[instance_id], Tags=[{"Key": NEEDS_BACKUP_TAG, "Value": "true"}])

def clear_needs_backup(instance_id, region=None):
    get_client(region).delete_tags(Resources=[instance_id], Tags=[{"Key": NEEDS_BACKUP_TAG}])

#Whether the instance is being terminated or is already gone.
def is_terminating(instance_id, region=None):
    try:
        resp = get_client(region).describe_instances(InstanceIds=[instance_id])
    except ClientError as exc:
        if exc.response["Error"]["Code"].startswith("InvalidInstanceID"):
            return True
        raise
    return resp["Reservations"][0]["Instances"][0]["State"]["Name"] in ("shutting-down", "terminated")

def create_backup(volume_id, server_id, region=None, kind=SESSION_BACKUP):
    tags = [PROJECT_TAG, {"Key": "ServerId", "Value": server_id},
            {"Key": BACKUP_KIND_TAG, "Value": kind},
            {"Key": "Name", "Value": f"mc-ec2-{server_id[:8]}-backup"}]
    resp = get_client(region).create_snapshot(
        VolumeId=volume_id, Description=f"World backup for server {server_id}",
        TagSpecifications=[{"ResourceType": "snapshot", "Tags": tags}])
    return resp["SnapshotId"]

#Every world backup, or only one server's. Follows pagination so a partial list can't look like the full set.
def list_backups(server_id=None, region=None):
    filters = [{"Name": f"tag:{PROJECT_TAG['Key']}", "Values": [PROJECT_TAG["Value"]]},
               {"Name": "tag-key", "Values": [BACKUP_KIND_TAG]}]
    if server_id:
        filters.append({"Name": "tag:ServerId", "Values": [server_id]})
    client = get_client(region)
    snapshots, kwargs = [], {}
    while True:
        resp = client.describe_snapshots(OwnerIds=["self"], Filters=filters, **kwargs)
        snapshots.extend(resp["Snapshots"])
        if not resp.get("NextToken"):
            break
        kwargs = {"NextToken": resp["NextToken"]}
    return [{"snapshot_id": s["SnapshotId"], "state": s["State"], "started_at": s["StartTime"],
             "server_id": next((t["Value"] for t in s.get("Tags", []) if t["Key"] == "ServerId"), None),
             "kind": next((t["Value"] for t in s.get("Tags", []) if t["Key"] == BACKUP_KIND_TAG), None)}
            for s in snapshots]

#A backup's state and start time, or None if AWS no longer has it.
def backup_info(snapshot_id, region=None):
    try:
        snapshot = get_client(region).describe_snapshots(SnapshotIds=[snapshot_id])["Snapshots"][0]
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "InvalidSnapshot.NotFound":
            raise
        return None
    return {"state": snapshot["State"], "started_at": snapshot["StartTime"]}

#Hand a restore to the scheduled job, which carries it out over its next few runs.
def begin_restore(instance_id, snapshot_id, safety_id, region=None):
    client = get_client(region)
    client.create_tags(Resources=[instance_id], Tags=[{"Key": RESTORE_TO_TAG, "Value": snapshot_id},
                                                      {"Key": RESTORE_SAFETY_TAG, "Value": safety_id}])
    # The world being replaced is already saved, and an earlier failure no longer applies.
    client.delete_tags(Resources=[instance_id], Tags=[{"Key": NEEDS_BACKUP_TAG}, {"Key": RESTORE_FAILED_TAG},
                                                      {"Key": RESTORE_TASK_TAG}])

#Instances with a restore in progress.
def list_restoring(region=None):
    resp = get_client(region).describe_instances(Filters=[
        {"Name": f"tag:{PROJECT_TAG['Key']}", "Values": [PROJECT_TAG["Value"]]},
        {"Name": "tag-key", "Values": [RESTORE_TO_TAG]},
        {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]}])
    restoring = []
    for reservation in resp["Reservations"]:
        for inst in reservation["Instances"]:
            tags = _tags(inst)
            if RESTORE_TO_TAG in tags:
                restoring.append({"instance_id": inst["InstanceId"], "state": inst["State"]["Name"],
                                  "snapshot_id": tags[RESTORE_TO_TAG], "safety_id": tags.get(RESTORE_SAFETY_TAG),
                                  "task_id": tags.get(RESTORE_TASK_TAG)})
    return restoring

#Replaces the root volume of a running instance. The token makes a retried request start only one task.
def create_restore_task(instance_id, snapshot_id, token, region=None):
    client = get_client(region)
    resp = client.create_replace_root_volume_task(InstanceId=instance_id, SnapshotId=snapshot_id, ClientToken=token,
                                                  DeleteReplacedRootVolume=True)
    task_id = resp["ReplaceRootVolumeTask"]["ReplaceRootVolumeTaskId"]
    client.create_tags(Resources=[instance_id], Tags=[{"Key": RESTORE_TASK_TAG, "Value": task_id}])
    return task_id

def restore_task_state(task_id, region=None):
    resp = get_client(region).describe_replace_root_volume_tasks(ReplaceRootVolumeTaskIds=[task_id])
    return resp["ReplaceRootVolumeTasks"][0]["TaskState"]

def finish_restore(instance_id, failed_at=None, region=None):
    client = get_client(region)
    client.delete_tags(Resources=[instance_id], Tags=[{"Key": RESTORE_TO_TAG}, {"Key": RESTORE_SAFETY_TAG},
                                                      {"Key": RESTORE_TASK_TAG}])
    if failed_at is not None:
        client.create_tags(Resources=[instance_id], Tags=[{"Key": RESTORE_FAILED_TAG,
                                                           "Value": failed_at.strftime(IDLE_TAG_FORMAT)}])

#Delete a backup; one AWS no longer knows about is already gone.
def delete_backup(snapshot_id, region=None):
    try:
        get_client(region).delete_snapshot(SnapshotId=snapshot_id)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "InvalidSnapshot.NotFound":
            raise

def mark_idle(instance_id, since, region=None):
    get_client(region).create_tags(Resources=[instance_id],
                                   Tags=[{"Key": IDLE_TAG, "Value": since.strftime(IDLE_TAG_FORMAT)}])

def clear_idle(instance_id, region=None):
    get_client(region).delete_tags(Resources=[instance_id], Tags=[{"Key": IDLE_TAG}])

#Launch the instance for a server from the launch template, or return the one already launched for it.
#Instances carry Project=mc-ec2 (required by the start/stop and launch IAM policies) and ServerId.
def launch(server_id, launch_template_id, region=None):
    client = get_client(region)
    for inst in find_instances(server_id, region=region):
        return {"instance_id": inst["InstanceId"], "state": inst["State"]["Name"],
                "instance_type": inst.get("InstanceType")}
    tags = [PROJECT_TAG, {"Key": "ServerId", "Value": server_id},
            {"Key": "Name", "Value": f"mc-ec2-{server_id[:8]}"}]
    resp = client.run_instances(
        LaunchTemplate={"LaunchTemplateId": launch_template_id, "Version": "$Default"},
        MinCount=1, MaxCount=1,
        ClientToken=server_id,  # a retried request can't launch a second instance
        TagSpecifications=[{"ResourceType": "instance", "Tags": tags},
                           {"ResourceType": "volume", "Tags": tags}])
    inst = resp["Instances"][0]
    return {"instance_id": inst["InstanceId"], "state": inst["State"]["Name"],
            "instance_type": inst.get("InstanceType")}

#Poll AWS until instance returns stopped.
def wait_until_stopped(instance_id):
    get_client().get_waiter("instance_stopped").wait(InstanceIds=[instance_id])

#Block until instance is running & MC returns a ping, returning final status or TimeoutError
def wait_until_ready(instance_id, timeout=180, interval=5):
    get_client().get_waiter("instance_running").wait(InstanceIds=[instance_id])
    deadline = time.time() + timeout
    while time.time() < deadline:
        info = status(instance_id)
        if info["minecraft"]:
            return info
        time.sleep(interval)
    raise TimeoutError(f"instance is running but Minecraft didn't answer within {timeout}s")

#Route calls and take parameters
if __name__ == "__main__":
    import sys
    action, instance_id = sys.argv[1], sys.argv[2]
    if action == "status":
        print(status(instance_id))
    elif action == "start":
        print(start(instance_id))
    elif action == "stop":
        print(stop(instance_id))
