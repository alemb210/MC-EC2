# Lambda entry point. Wraps the unmodified FastAPI app in backend/ with Mangum.
# The zip mirrors the repo layout (backend/, frontend/), so app.py's frontend path still resolves.
import sys
from pathlib import Path

# backend modules import each other as top-level modules (import ec2, from config import ...).
sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from mangum import Mangum  # noqa: E402
from app import app  # noqa: E402

handler = Mangum(app, lifespan="off")
