import os
import time
import boto3
from mcstatus import JavaServer
from botocore.config import Config

#Lambda environment variable, use1 default
REGION = os.environ.get("AWS_REGION", "us-east-1")
MC_PORT = 25565

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

#Return state and ip of instance
def describe(instance_id, region=None):
    resp = get_client(region).describe_instances(InstanceIds=[instance_id])
    inst = resp["Reservations"][0]["Instances"][0]
    return {"state": inst["State"]["Name"], "ip": inst.get("PublicIpAddress")}

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
