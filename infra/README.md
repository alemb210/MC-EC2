# Infrastructure (Terraform)

Terraform for every MC-EC2 AWS resource in `us-east-1`. The original resources were built in the
AWS console and then imported, so the configuration matches what was already running.
Change infrastructure here, not in the console.

| File | Resources |
|---|---|
| `minecraft.tf` | Minecraft instance (tagged `Project = mc-ec2`), launch template (`minecraft/user_data.sh`), security group, instance role/profile |
| `database.tf` | Aurora Serverless v2 (PostgreSQL 17), 0–2 ACU, auto-pause after 5 minutes, RDS Data API enabled |
| `database_schema.tf`, `db/` | Table migrations and the admin seed, applied through the Data API |
| `cognito.tf` | User pool, web app client, login domain, admin user |
| `iam.tf` | `mc-ec2-api` Lambda role: logs, EC2 describe, start/stop only for `Project = mc-ec2`, Data API |
| `lambda.tf` | `mc-ec2-api` Lambda function and log group |
| `api.tf` | `mc-ec2` HTTP API: all routes go to the Lambda; throttling; CORS |
| `budget.tf` | Monthly cost budget and alert emails |
| `imports.tf` | One-time import blocks from the console resources; safe to delete |

## First-time setup

1. Create `terraform.tfvars` (gitignored; holds values that shouldn't be public):
   ```hcl
   budget_alert_emails = ["you@example.com"]
   admin_email         = "you@example.com"
   ```
2. `terraform init`
3. You need the AWS CLI logged in (`aws login` or `aws sso login`) and `python3` on your PATH
   (standard library only; used by the database scripts).

## Deploying

```bash
./build_lambda.sh          # rebuild after any backend/ or frontend/ change
terraform plan             # review: a code change shows as a new source_code_hash
terraform apply
curl "$(terraform output -raw api_url)/health"
```

`terraform output` prints the API URL, Cognito IDs, issuer and login URL, database ARNs, and the
admin's server ID.

## Lambda packaging

The FastAPI app in `backend/` is deployed unmodified:

- `lambda_handler.py` wraps it with [Mangum](https://mangum.fastapiexpert.com/), which turns
  API Gateway events into ordinary HTTP requests. The Lambda handler is `lambda_handler.handler`.
- `build_lambda.sh` builds `build/api.zip` with the repo layout (`backend/`, `frontend/dist/`) and Linux
  arm64 / Python 3.12 wheels, so compiled packages (`pydantic_core`, `cryptography`) load on Lambda.
- The script also builds the React app (`npm ci && npm run build`), so the deploy machine needs
  Node `^20.19.0 || >=22.12.0` and an initialised Terraform directory. It bakes the public Cognito
  values from `terraform output` into the bundle and ships `frontend/dist` only. The API URL is
  an allowed Cognito callback and logout URL (`cognito.tf`), so the dashboard works there.
- Dependencies: `requirements-lambda.txt` = `backend/requirements.txt` + `mangum`.

## Database

Lambda reaches Aurora over HTTPS through the RDS Data API, so it stays outside the VPC: no NAT
gateway, and no direct `psql` access. Inspect data with the RDS Query Editor in the console
(Secrets Manager secret, database `mcec2`) or `aws rds-data execute-statement`.

- **Schema changes:** add a new numbered file in `db/migrations/` (e.g. `002_add_state.sql`) and
  run `terraform apply`. `db/run_sql.py migrate` applies files not yet recorded in
  `schema_migrations`, each in one transaction. Never edit a migration that has already run.
  Statements are separated by a semicolon at the end of a line.
- **Admin seed:** `db/seed_admin.sql` inserts the admin user, their Cognito identity
  (`provider_id` = the Cognito `sub`), and the Minecraft server row. It is idempotent and reruns
  when the admin, the instance, or the file changes.
- **Auto-pause:** the first query after about 5 idle minutes waits ~15 s while Aurora resumes.
  The scripts retry; the API returns 503 with `Retry-After: 15`. For demos, set `min_capacity = 0.5`.

## Cognito

- Sign-in by email (case-insensitive); passwords need 12+ characters with upper, lower and a digit.
- Self-signup is off (`allow_admin_create_user_only = true`) until the API registers users.
- The web client has no secret and uses authorization code + PKCE. `ALLOW_USER_PASSWORD_AUTH` is
  enabled so tokens can be fetched from the CLI for testing.
- The admin user gets a temporary password by email. Set a permanent one outside Terraform, so it
  never lands in state:
  ```bash
  aws cognito-idp admin-set-user-password --user-pool-id <pool id> \
    --username <admin email> --password '<password>' --permanent
  ```

## State

State is **local only** (`terraform.tfstate`, gitignored). The repo is public, and state stores
resource attributes in plain text.

- Only the infrastructure owner runs Terraform, from one machine.
- Back up `terraform.tfstate`. If it's lost, re-import resources with `import` blocks.
- To share later, move state to S3: add a `backend "s3"` block with `use_lockfile = true`, then
  `terraform init -migrate-state`.

## Safety

- `prevent_destroy` on the Aurora cluster and instance, the Cognito user pool, and the Minecraft
  instance (its root volume holds the world).
- The Minecraft instance ignores changes to `ami` and `user_data`; changing either would replace it.
- Starting and stopping instances is the API's job; Terraform doesn't track running/stopped state.

## Rollback

```bash
aws lambda update-function-code --function-name mc-ec2-api --zip-file fileb://build/<previous>.zip
```
Then fix the code and `terraform apply` again so Terraform and AWS agree.
