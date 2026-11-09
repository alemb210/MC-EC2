"""Scheduled jobs, run by the mc-ec2-jobs Lambda.

Never imports db.py: a query every 5 minutes would keep Aurora from auto-pausing. Idle time and
backup state are kept in EC2 tags instead."""
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from botocore.exceptions import BotoCoreError, ClientError
import ec2

logger = logging.getLogger(__name__)

# Counted rather than aged, so a world nobody has played for months keeps its history.
BACKUPS_KEPT = 7
# How long the snapshot taken just before a restore is kept, so the restore can be undone.
PRE_RESTORE_KEPT = timedelta(days=30)
# Auto-stop skips a server being restored, so a stuck restore must give up or it would run forever.
RESTORE_TIMEOUT = timedelta(hours=2)

def _check_instance(inst, idle_for, now, region):
    """Whether this instance was stopped."""
    minecraft = ec2.ping_minecraft(inst["ip"])
    if minecraft and minecraft["online"] > 0:
        if not inst["needs_backup"]:
            ec2.mark_needs_backup(inst["instance_id"], region=region)
        if inst["has_idle_tag"]:
            ec2.clear_idle(inst["instance_id"], region=region)
        return False
    if idle_for is None:
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
    """Records played sessions, and stops running servers that have had no players for idle_minutes
    (never, if idle_minutes is 0). Returns the instances stopped."""
    now = now or datetime.now(timezone.utc)
    idle_for = timedelta(minutes=idle_minutes) if idle_minutes > 0 else None
    stopped = []
    for inst in ec2.list_running(region=region):
        # A restore replaces this world, and its reboot would look like a crashed server.
        if inst["restoring"]:
            continue
        # One failing server must not keep the others running.
        try:
            if _check_instance(inst, idle_for, now, region):
                stopped.append(inst["instance_id"])
        except (ClientError, BotoCoreError, ec2.InvalidState):
            logger.exception("Auto-stop failed for %s", inst["instance_id"])
    return stopped

def _back_up(inst, region):
    """The new snapshot's ID, or None if the server was deleted while it was being taken."""
    snapshot_id = ec2.create_backup(inst["volume_id"], inst["server_id"], region=region)
    # Deleting a server terminates it and then deletes its backups, so a backup started after that
    # list was taken would be left behind and billed forever. Only an instance that is actually
    # terminating counts: backups must outlive a server that merely can't be found.
    if ec2.is_terminating(inst["instance_id"], region=region):
        ec2.delete_backup(snapshot_id, region=region)
        return None
    ec2.clear_needs_backup(inst["instance_id"], region=region)
    return snapshot_id

def back_up_worlds(region=None):
    """Backs up servers that stopped after being played on. Returns the new snapshots."""
    created = []
    for inst in ec2.list_needing_backup(region=region):
        if not inst["server_id"] or not inst["volume_id"]:
            logger.error("Can't back up %s: missing server ID or root volume", inst["instance_id"])
            continue
        # One failing server must not block the others. Its tag stays, so the next run retries.
        try:
            snapshot_id = _back_up(inst, region)
            if snapshot_id:
                created.append(snapshot_id)
        except (ClientError, BotoCoreError):
            logger.exception("Backup failed for %s", inst["instance_id"])
    return created

def _fail_restore(inst, reason, now, region):
    logger.error("Restore failed for %s: %s", inst["instance_id"], reason)
    ec2.finish_restore(inst["instance_id"], failed_at=now, region=region)

def _advance_restore(inst, now, region):
    """Moves one restore on by a step: wait for the safety snapshot, start the server, replace its disk."""
    task_state = ec2.restore_task_state(inst["task_id"], region=region) if inst["task_id"] else None
    if task_state == "succeeded":
        ec2.finish_restore(inst["instance_id"], region=region)
        return
    if task_state in ("failed", "failed-detached"):
        _fail_restore(inst, f"root volume task {task_state}", now, region)
        return
    safety = ec2.backup_info(inst["safety_id"], region=region) if inst["safety_id"] else None
    if safety is None or safety["state"] == "error":
        _fail_restore(inst, "the snapshot of the current world failed", now, region)
    elif now - safety["started_at"] >= RESTORE_TIMEOUT:
        _fail_restore(inst, "timed out", now, region)
    # The replaced volume is deleted, so nothing touches it until its snapshot is finished.
    elif task_state is None and safety["state"] == "completed":
        if inst["state"] == "stopped":
            ec2.start(inst["instance_id"], region=region)  # AWS can only replace the disk of a running instance.
        elif inst["state"] == "running":
            ec2.create_restore_task(inst["instance_id"], inst["snapshot_id"], inst["safety_id"], region=region)

def advance_restores(region=None, now=None):
    """Moves every restore in progress on by a step. Returns the instances handled."""
    now = now or datetime.now(timezone.utc)
    handled = []
    for inst in ec2.list_restoring(region=region):
        # One failing server must not block the others. Its tags stay, so the next run retries.
        try:
            _advance_restore(inst, now, region)
            handled.append(inst["instance_id"])
        except (ClientError, BotoCoreError, ec2.InvalidState):
            logger.exception("Restore step failed for %s", inst["instance_id"])
    return handled

def prune_backups(keep=BACKUPS_KEPT, region=None, now=None):
    """Deletes failed backups, expired pre-restore ones, and all but the newest completed session
    backups. Returns those deleted."""
    now = now or datetime.now(timezone.utc)
    in_use = {i for inst in ec2.list_restoring(region=region) for i in (inst["snapshot_id"], inst["safety_id"])}
    by_server = defaultdict(list)
    doomed = []
    for backup in ec2.list_backups(region=region):
        if backup["kind"] not in (ec2.SESSION_BACKUP, ec2.PRE_RESTORE_BACKUP) or not backup["server_id"] \
                or backup["snapshot_id"] in in_use:
            continue
        if backup["kind"] == ec2.PRE_RESTORE_BACKUP:
            if backup["state"] == "error" or now - backup["started_at"] >= PRE_RESTORE_KEPT:
                doomed.append(backup)
            continue
        # Only completed backups count, so an older one is never removed for a replacement that fails.
        if backup["state"] == "completed":
            by_server[backup["server_id"]].append(backup)
        elif backup["state"] == "error":
            doomed.append(backup)
    for backups in by_server.values():
        backups.sort(key=lambda b: b["started_at"], reverse=True)
        doomed.extend(backups[keep:])
    deleted = []
    for backup in doomed:
        try:
            ec2.delete_backup(backup["snapshot_id"], region=region)
            deleted.append(backup["snapshot_id"])
        except (ClientError, BotoCoreError):
            logger.exception("Couldn't delete backup %s", backup["snapshot_id"])
    return deleted
