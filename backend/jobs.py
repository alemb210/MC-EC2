"""Scheduled jobs, run by the mc-ec2-jobs Lambda.

Never imports db.py: a query every 5 minutes would keep Aurora from auto-pausing. Idle time is
kept in an EC2 tag instead."""
import logging
from datetime import datetime, timedelta, timezone
from botocore.exceptions import BotoCoreError, ClientError
import ec2

logger = logging.getLogger(__name__)

def _check_instance(inst, idle_for, now, region):
    """Whether this instance was stopped."""
    minecraft = ec2.ping_minecraft(inst["ip"])
    if minecraft and minecraft["online"] > 0:
        if inst["has_idle_tag"]:
            ec2.clear_idle(inst["instance_id"], region=region)
        return False
    # A failed ping counts as idle: a crashed server or failed boot should stop costing money too.
    if inst["idle_since"] is None:
        ec2.mark_idle(inst["instance_id"], now, region=region)
        return False
    if now - inst["idle_since"] < idle_for:
        return False
    ec2.stop(inst["instance_id"], region=region)
    ec2.clear_idle(inst["instance_id"], region=region)
    return True

def auto_stop(idle_minutes, region=None, now=None):
    """Stops running servers that have had no players for idle_minutes. Returns the instances stopped."""
    if idle_minutes <= 0:
        return []
    now = now or datetime.now(timezone.utc)
    stopped = []
    for inst in ec2.list_running(region=region):
        # One failing server must not keep the others running.
        try:
            if _check_instance(inst, timedelta(minutes=idle_minutes), now, region):
                stopped.append(inst["instance_id"])
        except (ClientError, BotoCoreError, ec2.InvalidState):
            logger.exception("Auto-stop failed for %s", inst["instance_id"])
    return stopped
