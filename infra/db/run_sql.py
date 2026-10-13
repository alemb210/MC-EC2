#!/usr/bin/env python3
"""Runs SQL against Aurora through the RDS Data API, using the AWS CLI (standard library only).

  run_sql.py migrate          apply db/migrations/*.sql not yet recorded in schema_migrations
  run_sql.py apply FILE       run FILE once; :name parameters come from SQL_PARAM_<name> env vars

Each file runs in one transaction. Statements are separated by a semicolon at the end of a line.
Requires DB_CLUSTER_ARN, DB_SECRET_ARN and DB_NAME in the environment.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

CLUSTER = os.environ["DB_CLUSTER_ARN"]
SECRET = os.environ["DB_SECRET_ARN"]
DATABASE = os.environ["DB_NAME"]
REGION = os.environ.get("AWS_REGION", "us-east-1")
MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def rds_data(command, *args):
    cmd = ["aws", "rds-data", command, "--region", REGION, "--resource-arn", CLUSTER,
           "--secret-arn", SECRET, "--output", "json", *args]
    for _ in range(12):
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return json.loads(result.stdout or "{}")
        if "DatabaseResumingException" in result.stderr:
            print("Aurora is resuming from auto-pause; retrying in 10s...", flush=True)
            time.sleep(10)
            continue
        sys.exit(f"rds-data {command} failed:\n{result.stderr}")
    sys.exit("Aurora did not resume in time")


def execute(sql, params=None, transaction_id=None):
    args = ["--database", DATABASE, "--sql", sql, "--format-records-as", "JSON"]
    if params:
        args += ["--parameters", json.dumps(
            [{"name": k, "value": {"isNull": True} if v is None else {"stringValue": v}} for k, v in params.items()])]
    if transaction_id:
        args += ["--transaction-id", transaction_id]
    return json.loads(rds_data("execute-statement", *args).get("formattedRecords") or "[]")


def statements(path):
    text = "\n".join(line for line in path.read_text().splitlines() if not line.lstrip().startswith("--"))
    return [s.strip() for s in re.split(r";\s*$", text, flags=re.MULTILINE) if s.strip()]


def run_file(path, params=None, record_version=None):
    tx = rds_data("begin-transaction", "--database", DATABASE)["transactionId"]
    try:
        for sql in statements(path):
            names = set(re.findall(r"(?<!:):(\w+)", sql))
            execute(sql, {n: params[n] for n in names} if params else None, tx)
        if record_version:
            execute("INSERT INTO schema_migrations (version) VALUES (:version)", {"version": record_version}, tx)
        rds_data("commit-transaction", "--transaction-id", tx)
    except BaseException:
        rds_data("rollback-transaction", "--transaction-id", tx)
        raise


def migrate():
    execute("CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
    applied = {row["version"] for row in execute("SELECT version FROM schema_migrations")}
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name in applied:
            continue
        print(f"Applying {path.name}", flush=True)
        run_file(path, record_version=path.name)
    print("Migrations up to date.")


def apply(file):
    params = {k[len("SQL_PARAM_"):]: v for k, v in os.environ.items() if k.startswith("SQL_PARAM_")}
    print(f"Applying {file}", flush=True)
    run_file(Path(file), params=params)


if __name__ == "__main__":
    if sys.argv[1:] == ["migrate"]:
        migrate()
    elif len(sys.argv) == 3 and sys.argv[1] == "apply":
        apply(sys.argv[2])
    else:
        sys.exit(__doc__)
