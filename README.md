# MC-EC2

One-Click Minecraft Server Hosting on AWS EC2, initial local backend.
Team: Alif (frontend/UI), Alem (Docker/AWS), Ryan (backend/integration).

## Implemented

- GET /health: API liveness and explicit mock_mode; never contacts AWS.
- GET /servers/{server_id}/status: validated EC2 state, Minecraft readiness, current address.

No database or proposed data-model implementation was present in this repository.
DEMO_SERVERS is a temporary application ID -> EC2 ID mapping, not persistence.
Existing EC2/Minecraft functions are reused. Legacy start/stop CLI functions remain
in ec2.py. The original /api status/start/stop routes and frontend at / are preserved alongside the new endpoints. Use /docs for the new backend demonstration.

## Installation and startup

Python 3.10+; run from the repository root in Windows PowerShell:

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app:app --app-dir backend --env-file .env --reload --host 127.0.0.1 --port 8000
~~~

The example contains placeholders and safe mock defaults, no credentials.
Uvicorn explicitly loads .env via --env-file. Imports do not automatically load it.
Existing environment variables take precedence. Restart after configuration changes.
On macOS/Linux use python3 and .venv/bin/python instead of the Windows paths.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| AWS_REGION | us-east-1 | EC2 region |
| MOCK_MODE | false | Explicit true/false; true makes no AWS/Minecraft calls |
| DEMO_SERVERS | {} | JSON object mapping application IDs to existing EC2 IDs; real mode only |

Without configuration, real mode has an empty mapping; health needs no credentials.
Mock mode has deterministic built-in examples independent of DEMO_SERVERS:

| ID | EC2 state | Minecraft ready | Address |
|---|---|---|---|
| demo-server | running | true | 203.0.113.10:25565 |
| demo-starting | running | false | 203.0.113.11:25565 |
| demo-stopped | stopped | false | null |

These documentation IPs are illustrative, not playable servers.
For real mode, edit .env locally:

~~~dotenv
AWS_REGION=us-east-1
MOCK_MODE=false
DEMO_SERVERS='{"demo-server":"i-REPLACE_WITH_EXISTING_INSTANCE_ID"}'
~~~

Use AWS's standard credential provider chain: AWS_PROFILE/shared credentials,
environment credentials, or IAM role. No credentials are accepted or returned by
API routes. Never commit credentials or .env. Real mode needs ec2:DescribeInstances.
The new health/status endpoints do not provision or mutate AWS resources. The preserved legacy start/stop routes can change the state of existing EC2 instances when called in real mode.

## Demonstrate

Open http://127.0.0.1:8000/docs. Expand GET /health, click Try it out, then Execute.
Confirm mock_mode=true. Execute the status route with demo-server, demo-starting,
demo-stopped, and unknown to show ready, starting, stopped, and HTTP 404.

In another PowerShell window:

~~~powershell
curl.exe http://127.0.0.1:8000/health
curl.exe http://127.0.0.1:8000/servers/demo-server/status
curl.exe http://127.0.0.1:8000/servers/demo-starting/status
curl.exe http://127.0.0.1:8000/servers/demo-stopped/status
curl.exe -i http://127.0.0.1:8000/servers/unknown/status
~~~

Use curl on macOS/Linux. Example ready response:

~~~json
{
  "server_id": "demo-server",
  "instance_state": "running",
  "minecraft_ready": true,
  "connection_address": "203.0.113.10:25565"
}
~~~

## Flow and failures

app.py defines synchronous routes and translates errors. service.py resolves the
application ID using config.py, then calls ec2.status. ec2.describe calls Boto3
DescribeInstances on every real request, refreshing state and PublicIpAddress.
Only running instances with public IPs get a JavaServer status probe on port 25565.
Successful Java protocol response means ready, even with zero players.
models.py validates API responses with Pydantic.

FastAPI runs synchronous routes in its worker thread pool, keeping blocking SDK
calls off the async event loop. AWS connect/read timeouts are 3/5 seconds with one
total request attempt; Minecraft timeout is 3 seconds with one probe attempt. These bound network
operations, not the complete request duration.

Minecraft timeout, refused connection, or incomplete/invalid protocol response
returns HTTP 200 with minecraft_ready=false. This can mean booting, offline, or
unreachable; the probe cannot distinguish the cause. Running instances retain the
current address even when not ready. Non-running instances or those without a
public IP return connection_address=null.

Unknown application IDs return 404 before external calls. AWS credential,
permission, connectivity, timeout, and missing configured-instance errors return
502 with a safe diagnostic message. A configured but missing EC2 instance is an
upstream/configuration failure, distinct from an unknown application ID.
Real AWS failures never fall back to mock data.

## Verification

~~~powershell
.\.venv\Scripts\python.exe -m pytest -c backend/pytest.ini
~~~

External calls are mocked; unexpected AWS/Minecraft calls fail tests.
Coverage: health without AWS, unknown IDs, deterministic mocks, running but not
ready, refreshed addresses, absent addresses, AWS errors, SDK timeouts, environment
validation, and /docs/OpenAPI scope, plus preserved frontend and legacy API/CLI behavior. Verified locally: 41 tests passed, including restored original route/frontend/CLI tests and added CLI start/stop regression tests. Uvicorn startup, frontend, /health, /docs, and OpenAPI passed in mock and real modes without AWS access. Dependency consistency checks passed. No live AWS verification is performed.

## Limitations and next steps

Local development prototype only. Legacy /api routes accept raw EC2 instance IDs and do not use the new application-ID mapping. Authentication and server ownership checks are
required before public deployment. There is no database persistence, user model,
billing, Cognito, Discord integration, or API create/delete. Legacy API start/stop operations are retained; application-ID lifecycle integration remains future work.
Next: persistent user/server mapping, authenticated ownership enforcement, and
lifecycle integration with Alem's infrastructure and Alif's frontend.

## Weekly progress

Implemented read-only FastAPI health and status endpoints with Pydantic responses,
temporary environment-based mapping, and explicit mock mode. Reused Boto3/mcstatus,
refreshed public IPs per real request, separated EC2 running from Minecraft
readiness, bounded network timeouts, and handled AWS failures. Added offline tests
and /docs/curl demonstration instructions. Authentication, persistence, and application-ID lifecycle integration remain.

Implementation references: [FastAPI synchronous routes](https://fastapi.tiangolo.com/async/)
and [Botocore timeout/retry configuration](https://docs.aws.amazon.com/botocore/latest/reference/config.html).

## Preserved frontend and legacy API

The original frontend is served at http://127.0.0.1:8000/ and retains its
instance-ID lookup, start, stop, and refresh UI. Its API contracts are preserved:

| Method | Path | Response |
|---|---|---|
| GET | /api/servers/{instance_id} | state, ip, minecraft |
| POST | /api/servers/{instance_id}/start | state; 409 while stopping |
| POST | /api/servers/{instance_id}/stop | state; 409 while pending |

Unknown EC2 IDs return 404; other AWS failures return 502.
In MOCK_MODE=true these legacy routes return 503 without making AWS calls.
Set MOCK_MODE=false with standard AWS credentials to use the original frontend.
The legacy routes bypass DEMO_SERVERS, as they did before. Authentication and
ownership enforcement are still required for all real-resource routes.

The existing CLI commands remain available (these always use real AWS):

~~~powershell
.\.venv\Scripts\python.exe backend/ec2.py status i-REPLACE_WITH_INSTANCE_ID
.\.venv\Scripts\python.exe backend/ec2.py start i-REPLACE_WITH_INSTANCE_ID
.\.venv\Scripts\python.exe backend/ec2.py stop i-REPLACE_WITH_INSTANCE_ID
~~~

The original tests remain in backend/tests/test_api.py; new endpoint and
compatibility tests are in backend/tests/test_status_api.py. moto is retained
as a development dependency. Automated lifecycle checks use mocked AWS only.
