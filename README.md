# MC-EC2

One-click Minecraft server hosting on AWS EC2.

```
backend/    Python: ec2.py (EC2 + Minecraft control, also a CLI) and app.py (HTTP API)
frontend/   Static web page served by the backend at /
```

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
```

AWS credentials come from the usual boto3 sources (`aws configure`, env vars, etc.).
Region defaults to `us-east-1`; override with `AWS_REGION`.

## CLI

```sh
.venv/bin/python backend/ec2.py status i-0123456789abcdef0
.venv/bin/python backend/ec2.py start  i-0123456789abcdef0
.venv/bin/python backend/ec2.py stop   i-0123456789abcdef0
```

## Web app

```sh
cd backend
../.venv/bin/uvicorn app:app --reload
```

Open http://127.0.0.1:8000, enter an instance ID, and start/stop the server.
Interactive API docs are at http://127.0.0.1:8000/docs.

| Method | Path                            | Returns                                   |
|--------|---------------------------------|-------------------------------------------|
| GET    | `/api/servers/{instance_id}`       | `{state, ip, minecraft}`                  |
| POST   | `/api/servers/{instance_id}/start` | `{state}`; 409 if the instance is still stopping |
| POST   | `/api/servers/{instance_id}/stop`  | `{state}`; 409 if the instance is still starting |

Unknown instance IDs return 404.

## Tests

Tests run against mocked AWS (moto), so no credentials or real instances are needed:

```sh
cd backend
../.venv/bin/pytest
```
