# MC-EC2

One-Click Minecraft Server Hosting on AWS EC2.
Team: Alif (frontend/UI), Alem (Docker/AWS), Ryan (backend/integration).

Anyone can sign up, launch a named Minecraft server, choose who can join, share control with other users,
and start, check, stop, and delete it through an authenticated API. Idle servers stop themselves.
The backend runs on AWS Lambda behind API Gateway; all AWS resources are managed with Terraform in [`infra/`](infra/README.md).

## Implemented

| Method | Path | Auth | Response |
|---|---|---|---|
| GET | /health | none | API liveness and `mock_mode`; never contacts AWS |
| POST | /me | token | Registers the caller: 201 for a new application user, 200 for an existing user |
| GET | /servers | token | Registers the caller if needed, then lists servers they own or administer, oldest first (`[]` for a new user), with `name` and `role`; never includes EC2 instance IDs |
| POST | /servers | token | 201: launches a new server from the Minecraft launch template (registers the caller if needed). Optional body: `{name, access}` |
| PATCH | /servers/{server_id} | token + owner or admin | Renames the server |
| DELETE | /servers/{server_id} | token + owner | 204: terminates the instance and deletes the server, its world and its backups; safe to retry |
| GET | /servers/{server_id}/backups | token + owner or admin | World backups, newest first |
| POST | /servers/{server_id}/backups/{backup_id}/restore | token + owner | 202: saves the current world, then restores the backup over the next few job runs; the server must be stopped |
| GET | /servers/{server_id}/status | token + owner or admin | EC2 state, Minecraft readiness, current address, player count and version (null until ready), `auto_stop_at` |
| POST | /servers/{server_id}/start | token + owner or admin | 202, new state (`pending`, or the current state if already running) |
| POST | /servers/{server_id}/stop | token + owner or admin | 202, new state (`stopping`, or the current state if already stopped) |
| GET, PUT | /servers/{server_id}/access | token + owner or admin | Public or whitelist, and the player names; editable while stopped |
| GET, POST | /servers/{server_id}/admins | token + owner | Lists admins, or adds a site user by email (immediately) |
| DELETE | /servers/{server_id}/admins/{user_id} | token + owner, or `me` for an admin leaving | 204: removes an admin |
| GET | /docs | none | Swagger UI |
| GET | / | none | React dashboard (`frontend/dist`); a "not built" page if the frontend hasn't been built |

`server_id` is the UUID of a row in the `servers` table. Server routes require a Cognito
**access token** (`Authorization: Bearer <token>`) and only act on servers the caller owns or
administers. Admins can do everything an owner can except delete the server and manage admins.

The legacy `/api/servers/{instance_id}` routes are commented out in `backend/app.py`: they took raw
EC2 instance IDs and bypassed authentication and ownership. The React dashboard uses the
authenticated routes above instead.

## Architecture

```
Client ──Bearer token──► API Gateway ──► Lambda (FastAPI via Mangum)
   1. auth.py     verify the token with Cognito's public keys          → 401 if missing/invalid
   2. db.py       Data API query: does this user (sub) own server_id?  → 404 if not
   3. ec2.py      start / stop / describe the instance                 → 409 wrong state, 502 AWS error

POST /servers:
   1. auth.py     verify the token
   2. db.py       find or create the user; in one transaction, reuse their unlaunched server
                  or insert a row if the limits allow                   → 409 limit reached
   3. ec2.py      find the instance tagged ServerId=<id>, or RunInstances from the template
   4. db.py       save the instance ID on the row
```

| File | Role |
|---|---|
| `backend/app.py` | Routes, auth dependency, error mapping, serves `frontend/dist` |
| `backend/auth.py` | Cognito access-token verification (signature, issuer, expiry, `token_use`, `client_id`) |
| `backend/db.py` | Aurora access through the RDS Data API; ownership lookup |
| `backend/service.py` | Business rules: access checks before any EC2 call; mock data |
| `backend/ec2.py` | Boto3 + mcstatus wrappers; also a small CLI |
| `backend/jobs.py` | Auto-stop job, run every 5 minutes; deliberately has no database access |
| `backend/player_access.py` | Access settings in Parameter Store; Mojang name check |
| `backend/cognito.py` | Finds a site user by email, for adding admins |
| `backend/config.py` | Settings from environment variables |
| `backend/models.py` | Pydantic response models |
| `frontend/` | React + Vite dashboard with Cognito login |
| `infra/` | Terraform, Lambda packaging, database migrations ([infra/README.md](infra/README.md)) |

Database tables (proposal §IV-F): `users`, `identities` (Cognito `sub` → user), `servers`
(owner → EC2 instance), and `server_admins`. See `infra/db/migrations/`.

**Auto-stop:** the job stops servers with no players for `auto_stop_idle_minutes` (default 30; 0 turns it
off). A failed Minecraft ping counts as idle, so a crashed server stops costing money too. Idle time is
kept in an `IdleSince` EC2 tag because querying the database every 5 minutes would keep Aurora from auto-pausing.

**Player access:** settings live in a Parameter Store parameter per server, so a booting server can read
them without database access. The `mc-sync-access` script (in `infra/minecraft/user_data.sh`) applies them
on every boot, and the API triggers it through a fixed SSM document when a running server's settings change.
The API sends no names or commands to the instance. A server with no saved settings is public.

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

## Frontend

The dashboard in `frontend/` (React, Vite, TypeScript) lists the servers a user owns or administers
from `GET /servers`. The Create server button opens a form for an optional name and a public or whitelist
choice; a server with no custom name goes by its ID. Each card
shows state, Minecraft readiness, address, players and version, an auto-stop countdown when the server is
empty, and Start, Stop, Refresh and Copy address. Owners and admins can rename a server and edit who can
join, even while it's stopped. Owners can also manage admins and delete the server; admins can leave.
A card disappears if its server is deleted or the user is removed from it.

Cards poll every 5 s while a server is changing state, and every 60 s while it's running in a visible
tab, so a background tab doesn't keep the database awake. `/health` decides the mode: in mock mode
there is no login and the demo servers appear (changes aren't saved, and the create form needs a login,
so it's hidden); in live mode the user logs in through
Cognito's hosted page (authorization code + PKCE) and the app sends the access token on every
`/servers/...` call. A 401 renews the token once, then falls back to the login screen. A 503 with
`Retry-After` (the database waking up) is retried up to 3 times.

Requires Node `^20.19.0 || >=22.12.0`.

~~~bash
cd frontend
npm ci
npm run dev        # http://localhost:3000, proxies API calls to uvicorn on :8000 (mock or live backend)
npm run dev:live   # same UI, proxies to the deployed API; needs frontend/.env.local
npm run build      # type-checks, then writes frontend/dist/
npm test           # Vitest
~~~

The dev port is fixed at 3000 because Cognito only allows `http://localhost:3000/` and the
API URL as callback and logout URLs. FastAPI serves `frontend/dist` at `/`, so in production the
hosted URL is the API URL and there is no CORS. After frontend changes run `npm run build`.

Live mode needs the public Cognito settings. Copy `frontend/.env.example` to
`frontend/.env.local` and fill in values from `terraform output` (the Lambda build does this
automatically):

| Variable | terraform output |
|---|---|
| VITE_COGNITO_AUTHORITY | cognito_issuer |
| VITE_COGNITO_CLIENT_ID | cognito_client_id |
| VITE_COGNITO_DOMAIN | cognito_login_url |

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
| AUTO_STOP_IDLE_MINUTES | 30 | Idle minutes before auto-stop; 0 turns it off |
| PROTECTED_SERVER_IDS | — | Comma-separated servers the API won't delete |
| SYNC_ACCESS_DOCUMENT | — | SSM document that applies access settings on a running server |

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

Sign up (or use the hosted login page's "Sign up" link), confirm with the emailed code, then
register and launch a server:

~~~bash
CLIENT=$(cd infra && terraform output -raw cognito_client_id)
aws cognito-idp sign-up --client-id "$CLIENT" --username '<email>' --password '<password>'
aws cognito-idp confirm-sign-up --client-id "$CLIENT" --username '<email>' --confirmation-code '<code>'
~~~

With `$API` and `$TOKEN` set as below:

~~~bash
curl -X POST -H "Authorization: Bearer $TOKEN" "$API/me"    # explicit application registration
curl -H "Authorization: Bearer $TOKEN" "$API/servers"        # also registers the caller if needed
curl -X POST -H "Authorization: Bearer $TOKEN" "$API/servers"   # returns server_id; the instance boots running
~~~

The new instance installs Docker and Minecraft on first boot, so it takes a few minutes before
`minecraft_ready` is true. Each user can create `max_servers_per_user` servers (default 1), and at
most `max_servers_total` servers exist in total (default 3, including the admin's); both are
Terraform variables. If a launch fails, retrying `POST /servers` resumes the same server rather
than creating another.

If a server row exists but its EC2 instance has not been recorded, `/status` returns 200
with `provisioning_state: "awaiting_instance"` and `instance_state: null`. This is separate
from EC2's `pending` state. The dashboard labels it **Awaiting instance** and offers
**Resume creation**, which retries `POST /servers` for the unfinished row. Status polling
only observes progress; it does not resume a launch automatically. Start/stop still return
409 until an instance is attached. Assigned servers return `provisioning_state: "instance_assigned"`.

Start, check, and stop a server:

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
  "connection_address": "3.91.56.173:25565",
  "players_online": 2,
  "players_max": 20,
  "minecraft_version": "1.21.4"
}
~~~

## Flow and failures

| Status | When |
|---|---|
| 401 | Missing, malformed, or expired token; wrong issuer or app client; an ID token instead of an access token |
| 403 | An admin attempting something only the owner can do |
| 404 | Unknown server ID, or a server the caller can't access (deliberately indistinguishable); no user with that email; not an admin |
| 409 | Start while stopping, stop while starting, a server row with no instance yet, `POST /servers` over the server limit, deleting a protected server, or the admin limit |
| 422 | Invalid name, email or player name; a Minecraft player Mojang says doesn't exist |
| 502 | EC2 call failed; AWS error details are never returned |
| 503 | Database resuming from auto-pause (`Retry-After: 15`), or Cognito, database, or launch template not configured |

Access is checked before any EC2 call, so an unauthorized request makes no AWS change.
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

Tests run offline: external calls are mocked and unexpected AWS or Minecraft calls fail the test.
Coverage includes every token rejection case, cross-user access (404 with no AWS call), database
errors and auto-pause, start/stop transitions and conflicts, region handling, registration, server
limits, launch retries, and EC2 lifecycle and launching against moto. It also covers the permissions of every
server route for owner, admin and stranger, auto-stop (including that it never loads the database layer), and
`user_data.sh` with its sync script run against stub `docker` and `aws` commands. The frontend has Vitest tests
for the API client, token renewal and retry logic, plus DOM tests that drive the components through corner cases such as double submits, failed
loads, and servers that disappear mid-action: `cd frontend && npm test`.

## Deployment

See [infra/README.md](infra/README.md). In short: `cd infra && ./build_lambda.sh && terraform apply`.

## Limitations and next steps

- Self-signup is open; `max_servers_total` and the AWS budget are what limit cost. Cognito's default
  email sender allows about 50 confirmation emails a day.
- Deleting a server is permanent and also deletes its backups.
- Backups can't be downloaded, and a very long session isn't backed up until the server stops.
- `VERSION=LATEST` can upgrade a world whenever its container restarts; versions aren't pinned yet.
- Any signed-in user with a server can test whether an email has an account by adding it as an admin.
- No operation locks, runtime history, or cost reporting yet.

## Progress log

- **Oct 5:** read-only FastAPI health and status endpoints with Pydantic responses, mock mode,
  bounded timeouts, AWS error handling, and offline tests.
- **Oct 13:** deployed to Lambda + API Gateway; imported all AWS resources into Terraform; added
  Cognito, the users/identities/servers tables, token verification, ownership checks, and
  authenticated start/stop; disabled the unauthenticated legacy routes.
- **Oct 13:** React dashboard with Cognito login (hosted UI), served by Lambda from `frontend/dist`.
