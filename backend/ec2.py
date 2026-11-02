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

#Return state and ip of instance
def describe(instance_id, region=None):
    resp = get_client(region).describe_instances(InstanceIds=[instance_id])
    inst = resp["Reservations"][0]["Instances"][0]
    return {"state": inst["State"]["Name"], "ip": inst.get("PublicIpAddress"), "idle_since": idle_since(inst)}

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
             "has_idle_tag": any(t["Key"] == IDLE_TAG for t in inst.get("Tags", []))}
            for reservation in resp["Reservations"] for inst in reservation["Instances"]]

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
