# MC-EC2

One-Click Minecraft Server Hosting on AWS EC2.
Team: Alif (frontend/UI), Alem (Docker/AWS), Ryan (backend/integration).

A logged-in user can start, check, and stop their Minecraft server through an authenticated API.
The backend runs on AWS Lambda behind API Gateway; all AWS resources are managed with Terraform in [`infra/`](infra/README.md).

## Implemented

| Method | Path | Auth | Response |
|---|---|---|---|
| GET | /health | none | API liveness and `mock_mode`; never contacts AWS |
| GET | /servers/{server_id}/status | token + owner | EC2 state, Minecraft readiness, current address |
| POST | /servers/{server_id}/start | token + owner | 202, new state (`pending`, or the current state if already running) |
| POST | /servers/{server_id}/stop | token + owner | 202, new state (`stopping`, or the current state if already stopped) |
| GET | /docs | none | Swagger UI |
| GET | / | none | Static frontend page |

`server_id` is the UUID of a row in the `servers` table. Server routes require a Cognito
**access token** (`Authorization: Bearer <token>`) and only act on servers the caller owns.

The legacy `/api/servers/{instance_id}` routes are commented out in `backend/app.py`: they took raw
EC2 instance IDs and bypassed authentication and ownership. The static page's start/stop buttons
used them, so they no longer work until the frontend logs in and calls the new routes.

## Architecture

```
Client ──Bearer token──► API Gateway ──► Lambda (FastAPI via Mangum)
   1. auth.py     verify the token with Cognito's public keys          → 401 if missing/invalid
   2. db.py       Data API query: does this user (sub) own server_id?  → 404 if not
   3. ec2.py      start / stop / describe the instance                 → 409 wrong state, 502 AWS error
```

| File | Role |
|---|---|
| `backend/app.py` | Routes, auth dependency, error mapping, static frontend mount |
| `backend/auth.py` | Cognito access-token verification (signature, issuer, expiry, `token_use`, `client_id`) |
| `backend/db.py` | Aurora access through the RDS Data API; ownership lookup |
| `backend/service.py` | Business rules: ownership before any EC2 call; mock data |
| `backend/ec2.py` | Boto3 + mcstatus wrappers; also a small CLI |
| `backend/config.py` | Settings from environment variables |
| `backend/models.py` | Pydantic response models |
| `infra/` | Terraform, Lambda packaging, database migrations ([infra/README.md](infra/README.md)) |

Database tables (proposal §IV-F): `users`, `identities` (Cognito `sub` → user), and `servers`
(owner → EC2 instance). See `infra/db/migrations/`.

## Run locally

Python 3.10+. From the repository root:

~~~bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
cp .env.example .env
.venv/bin/uvicorn app:app --app-dir backend --env-file .env --reload --host 127.0.0.1 --port 8000
~~~

On Windows PowerShell use `python`, `.\.venv\Scripts\python.exe -m pip ...`, `Copy-Item`, and
`.\.venv\Scripts\python.exe -m uvicorn ...`.

Uvicorn loads `.env` via `--env-file`; existing environment variables take precedence.
Restart after configuration changes.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| AWS_REGION | us-east-1 | AWS region (set automatically on Lambda) |
| MOCK_MODE | false | `true`: no Cognito, database, or AWS calls; fixed demo data |
| COGNITO_USER_POOL_ID | — | User pool that issues accepted tokens |
| COGNITO_CLIENT_ID | — | App client the tokens must be issued to |
| DB_CLUSTER_ARN | — | Aurora cluster for the Data API |
| DB_SECRET_ARN | — | Secrets Manager secret with the database credentials |
| DB_NAME | mcec2 | Database name |

Real values come from `terraform output` in `infra/`. If the Cognito or database settings are
missing in real mode, server routes fail closed with 503; `/health` and `/docs` still work.

AWS credentials use the standard provider chain (profile, environment, or IAM role) and are
never accepted or returned by the API. Never commit credentials or `.env`.

## Demonstrate

### Mock mode (no AWS)

Set `MOCK_MODE=true`, open http://127.0.0.1:8000/docs, and try the server routes with:

| ID | EC2 state | Minecraft ready | Address |
|---|---|---|---|
| demo-server | running | true | 203.0.113.10:25565 |
| demo-starting | running | false | 203.0.113.11:25565 |
| demo-stopped | stopped | false | null |

No token is needed in mock mode. Start/stop return the state the server would move to.

### Live API

~~~bash
API=https://k19j61rb5c.execute-api.us-east-1.amazonaws.com
SERVER=$(cd infra && terraform output -raw admin_server_id)   # or ask Alem
TOKEN=$(aws cognito-idp initiate-auth --client-id "$(cd infra && terraform output -raw cognito_client_id)" \
  --auth-flow USER_PASSWORD_AUTH --auth-parameters USERNAME='<email>',PASSWORD='<password>' \
  --query AuthenticationResult.AccessToken --output text)

curl -X POST -H "Authorization: Bearer $TOKEN" "$API/servers/$SERVER/start"
curl -H "Authorization: Bearer $TOKEN" "$API/servers/$SERVER/status"   # until minecraft_ready is true
curl -X POST -H "Authorization: Bearer $TOKEN" "$API/servers/$SERVER/stop"
~~~

A running server costs money; stop it when finished. Example ready response:

~~~json
{
  "server_id": "dc9984dd-a660-636e-f9d1-3c6b20bef576",
  "instance_state": "running",
  "minecraft_ready": true,
  "connection_address": "3.91.56.173:25565"
}
~~~

## Flow and failures

| Status | When |
|---|---|
| 401 | Missing, malformed, or expired token; wrong issuer or app client; an ID token instead of an access token |
| 404 | Unknown server ID, or a server the caller doesn't own (deliberately indistinguishable) |
| 409 | Start while stopping, stop while starting, or a server row with no instance yet |
| 502 | EC2 call failed; AWS error details are never returned |
| 503 | Database resuming from auto-pause (`Retry-After: 15`), or Cognito/database not configured |

Ownership is checked before any EC2 call, so an unauthorized request makes no AWS change.
EC2 state and the public IP are read from AWS on every status call; the IP changes after each
stop/start. Only running instances with a public IP get a Minecraft status probe on port 25565;
a timeout or refused connection returns 200 with `minecraft_ready: false`.

Timeouts: EC2 3 s connect / 5 s read, one attempt; Data API 3 s / 10 s, one attempt;
Minecraft probe 3 s; Cognito key fetch 3 s (keys are cached in a warm Lambda).
Synchronous routes run in FastAPI's worker thread pool, keeping blocking calls off the event loop.

The CLI still works against real AWS: `python backend/ec2.py status|start|stop <instance-id>`.

## Verification

~~~bash
.venv/bin/python -m pytest -c backend/pytest.ini
~~~

92 tests, all offline: external calls are mocked and unexpected AWS or Minecraft calls fail the test.
Coverage includes every token rejection case, cross-user access (404 with no AWS call), database
errors and auto-pause, start/stop transitions and conflicts, region handling, and EC2 lifecycle
behavior against moto.

## Deployment

See [infra/README.md](infra/README.md). In short: `cd infra && ./build_lambda.sh && terraform apply`.

## Limitations and next steps

- Self-signup is off; there is one admin account. Next: register users on first login, `GET /servers`.
- No server creation or deletion through the API yet (`POST /servers`, `DELETE /servers/{id}`).
- `/stop` calls `StopInstances` directly; a graceful world save before stopping is still to do.
- No operation locks, runtime history, or cost reporting yet.
- The static frontend has no login yet.

## Progress log

- **Oct 5:** read-only FastAPI health and status endpoints with Pydantic responses, mock mode,
  bounded timeouts, AWS error handling, and offline tests.
- **Oct 13:** deployed to Lambda + API Gateway; imported all AWS resources into Terraform; added
  Cognito, the users/identities/servers tables, token verification, ownership checks, and
  authenticated start/stop; disabled the unauthenticated legacy routes.
