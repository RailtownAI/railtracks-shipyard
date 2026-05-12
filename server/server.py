"""
Switchyard Competition Leaderboard Server
==========================================

Run from the repo root:
    uvicorn competition.server:app --host 0.0.0.0 --port 8000 --reload

Endpoints:
    POST /api/submit        — accept a score from an agent run
    GET  /api/leaderboard   — return current standings as JSON
    GET  /                  — serve the leaderboard web UI
    GET  /qr.png            — serve QR code image (drop qr.png into competition/)

TODO before production:
  - Add SUBMIT_TOKEN check in submit_score() to prevent fake submissions
  - Add SQLite persistence if scores need to survive a server restart
  - Restrict CORS allow_origins to your deployment domain
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

_HERE = Path(__file__).parent
_COMPETITIVE_SEED = 42

app = FastAPI(title="Switchyard Leaderboard", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: lock down in production
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ── Data model ────────────────────────────────────────────────────────────────

class ScoreSubmission(BaseModel):
    team_name: str = Field(..., min_length=1, max_length=64)
    seed: int
    track: Literal["prompt", "code"]
    cash: float
    item_worth: float
    bonus_points: float
    total_score: float
    time_consumed: int
    time_budget: int = 300


# ── In-memory store ───────────────────────────────────────────────────────────

_lock = threading.Lock()
_store: dict[str, list[dict]] = {"prompt": [], "code": []}


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.post("/api/submit")
def submit_score(payload: ScoreSubmission) -> dict:
    entry = {
        "team_name": payload.team_name,
        "seed": payload.seed,
        "total_score": round(payload.total_score, 2),
        "time_consumed": payload.time_consumed,
        "time_budget": payload.time_budget,
        "competitive": payload.seed == _COMPETITIVE_SEED,
        "submitted_at": time.time(),
    }
    with _lock:
        track = _store[payload.track]
        
        track.append(entry)
    return {"ok": True, "action": "added"}


@app.get("/api/leaderboard")
def get_leaderboard() -> dict:
    with _lock:
        return {
            "prompt": sorted(_store["prompt"], key=lambda e: e["total_score"], reverse=True),
            "code":   sorted(_store["code"],   key=lambda e: e["total_score"], reverse=True),
        }


@app.get("/qr.png")
def serve_qr() -> Response:
    p = _HERE / "qr.png"
    return FileResponse(p) if p.exists() else Response(status_code=404)


@app.get("/")
def serve_ui() -> FileResponse:
    return FileResponse(_HERE / "index.html")
