from pathlib import Path

from botocore.exceptions import ClientError
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

import ec2

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="MC-EC2")

#Map ec2.py errors onto HTTP status codes
def call(fn, instance_id):
    try:
        return fn(instance_id)
    except ec2.InvalidState as e:
        raise HTTPException(409, str(e))
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code.startswith("InvalidInstanceID"):
            raise HTTPException(404, f"instance {instance_id} not found")
        raise HTTPException(502, f"AWS error: {code}")

@app.get("/api/servers/{instance_id}")
def get_status(instance_id: str):
    return call(ec2.status, instance_id)

@app.post("/api/servers/{instance_id}/start")
def start(instance_id: str):
    return {"state": call(ec2.start, instance_id)}

@app.post("/api/servers/{instance_id}/stop")
def stop(instance_id: str):
    return {"state": call(ec2.stop, instance_id)}

#Serve the static frontend at / (mounted last so /api routes win)
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
