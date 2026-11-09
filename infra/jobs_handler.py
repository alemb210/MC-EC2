# Lambda entry point for scheduled jobs. Separate from lambda_handler.py so the job doesn't load
# the API, and with it the database layer.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from config import Settings  # noqa: E402
import jobs  # noqa: E402


def handler(event, context):
    settings = Settings.from_env()
    stopped = jobs.auto_stop(settings.auto_stop_idle_minutes, region=settings.aws_region)
    restores = jobs.advance_restores(region=settings.aws_region)
    backed_up = jobs.back_up_worlds(region=settings.aws_region)
    pruned = jobs.prune_backups(region=settings.aws_region)
    return {"stopped": stopped, "restores": restores, "backed_up": backed_up, "pruned": pruned}
