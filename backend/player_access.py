"""A server's access settings (public or whitelist), saved in SSM Parameter Store.

Parameter Store rather than Aurora, so a booting server can read its own settings without
database access: the mc-sync-access script in infra/minecraft/user_data.sh applies them."""
import json
import logging
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

MOJANG_PROFILE_URL = "https://api.mojang.com/users/profiles/minecraft/{}"
MOJANG_TIMEOUT = 2
MOJANG_TOTAL_TIMEOUT = 5

# No client at import time, matching ec2.py.
ssm = None

def get_client(region):
    return ssm if ssm is not None else boto3.client(
        "ssm", region_name=region,
        config=Config(connect_timeout=3, read_timeout=5, retries={"total_max_attempts": 1}))

def parameter_name(server_id):
    return f"/mc-ec2/servers/{server_id}/access"

#The saved settings; a server without any is public.
def load(server_id, region):
    try:
        value = get_client(region).get_parameter(Name=parameter_name(server_id))["Parameter"]["Value"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ParameterNotFound":
            return {"mode": "public", "players": []}
        raise
    return json.loads(value)

def save(server_id, mode, players, region):
    get_client(region).put_parameter(Name=parameter_name(server_id), Type="String", Overwrite=True,
                                     Value=json.dumps({"mode": mode, "players": players}))

def delete(server_id, region):
    try:
        get_client(region).delete_parameter(Name=parameter_name(server_id))
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ParameterNotFound":
            raise

#Ask a running server to apply its settings now. False if it can't be reached; it applies them at next boot.
def trigger_sync(instance_id, document, region):
    try:
        get_client(region).send_command(InstanceIds=[instance_id], DocumentName=document)
    except (ClientError, BotoCoreError) as exc:
        logger.info("Could not trigger access sync on %s: %s", instance_id, exc)
        return False
    return True

#Whether Mojang knows the name. Any other answer or failure counts as known: only a definite "no" rejects a name.
def _player_exists(name):
    try:
        with urllib.request.urlopen(MOJANG_PROFILE_URL.format(name), timeout=MOJANG_TIMEOUT) as response:
            return response.status != 204
    except urllib.error.HTTPError as exc:
        return exc.code != 404
    except OSError:
        return True

#The names Mojang says don't exist. Names still unchecked at the deadline are accepted, so Mojang can't block a save.
def unknown_players(names):
    if not names:
        return []
    executor = ThreadPoolExecutor(max_workers=8)
    checks = {executor.submit(_player_exists, name): name for name in names}
    done, _ = wait(checks, timeout=MOJANG_TOTAL_TIMEOUT)
    executor.shutdown(wait=False, cancel_futures=True)
    unknown = {checks[check] for check in done if not check.result()}
    return [name for name in names if name in unknown]
