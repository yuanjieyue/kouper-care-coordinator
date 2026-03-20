"""
Care Coordinator FastAPI server.

Endpoints:
    POST /chat   — send a message and get a reply
    GET  /health — liveness check
"""

import logging
import uuid
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

UI_INDEX = Path(__file__).parent.parent / "ui" / "index.html"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
for _noisy in ("httpx", "httpcore", "anthropic"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
logger = logging.getLogger("care_coordinator")

from agent.agent import MODEL, process_message

app = FastAPI(title="Kouper Health Care Coordinator", version="0.1.0")

# CORS — allow all origins during development so the UI can be opened directly
# from the filesystem (file://) or any localhost port.
# TODO: restrict allow_origins to the specific frontend URL before production deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# In-memory session store: { session_id: { "patient_id": int, "history": list } }
# Swap for Redis or a DB-backed store in production.
_sessions: dict[str, dict] = {}


# ── Request / response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    patient_id: int
    message: str
    session_id: Optional[str] = None   # omit to start a new conversation


class ChatResponse(BaseModel):
    reply: str
    session_id: str


# Static patient records — replace with a real DB/EHR lookup in production.
_PATIENTS: dict[int, dict] = {
    1: {
        "id": 1,
        "name": "John Doe",
        "dob": "01/01/1975",
        "pcp": "Dr. Meredith Grey",
        "ehrId": "1234abcd",
        "referred_providers": [
            {"provider": "House, Gregory MD", "specialty": "Orthopedics"},
            {"specialty": "Primary Care"},
        ],
        "appointments": [
            {"date": "3/05/18",  "time": "9:15am",  "provider": "Dr. Meredith Grey",  "status": "completed"},
            {"date": "8/12/24",  "time": "2:30pm",  "provider": "Dr. Gregory House",  "status": "completed"},
            {"date": "9/17/24",  "time": "10:00am", "provider": "Dr. Meredith Grey",  "status": "noshow"},
            {"date": "11/25/24", "time": "11:30am", "provider": "Dr. Meredith Grey",  "status": "cancelled"},
        ],
    },
}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/")
def serve_ui():
    return FileResponse(UI_INDEX)


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL}


@app.get("/patient/{patient_id}")
def get_patient(patient_id: int):
    patient = _PATIENTS.get(patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found.")
    return patient


@app.post("/chat", response_model=ChatResponse)
# Intentionally sync: FastAPI runs sync endpoints in a thread pool, so this
# won't block the event loop. Switching to async def would require replacing
# the requests library with httpx and the Anthropic client with AsyncAnthropic
# throughout the agent layer.
def chat(req: ChatRequest):
    # Resolve or create session
    if req.session_id:
        session = _sessions.get(req.session_id)
        if session is None:
            raise HTTPException(
                status_code=404,
                detail=f"Session '{req.session_id}' not found. Omit session_id to start a new conversation.",
            )
        if session["patient_id"] != req.patient_id:
            raise HTTPException(
                status_code=400,
                detail="patient_id does not match the existing session.",
            )
    else:
        session_id = str(uuid.uuid4())
        session = {"patient_id": req.patient_id, "history": []}
        _sessions[session_id] = session
        req = req.model_copy(update={"session_id": session_id})
        logger.info("New session created | session_id=%s patient_id=%s", session_id, req.patient_id)

    logger.debug(
        "Incoming request | session_id=%s patient_id=%s message_length=%d",
        req.session_id,
        req.patient_id,
        len(req.message),
    )

    # Run the agent
    try:
        reply, updated_history = process_message(
            patient_id=session["patient_id"],
            history=session["history"],
            user_message=req.message,
        )
    except Exception as e:
        logger.error(
            "Agent error | session_id=%s patient_id=%s error=%s",
            req.session_id,
            req.patient_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"Agent error: {e}")

    # Persist the updated history back to the session
    session["history"] = updated_history

    return ChatResponse(reply=reply, session_id=req.session_id)
