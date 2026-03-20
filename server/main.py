"""
Care Coordinator FastAPI server.

Endpoints:
    POST /chat   — send a message and get a reply
    GET  /health — liveness check
"""

import logging
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("care_coordinator")

from agent.agent import MODEL, process_message

app = FastAPI(title="Kouper Health Care Coordinator", version="0.1.0")

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


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL}


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
